#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const Lark = require('../vendor/node_modules/@larksuiteoapi/node-sdk');

const codexHome = process.env.CODEX_HOME || path.join(process.env.HOME, '.codex');
const skillRoot = path.resolve(__dirname, '..');
const configPath = path.join(codexHome, 'family-english-cards', 'config.json');
const englishScript = path.join(skillRoot, 'scripts', 'flow.py');
const conceptScript = path.join(codexHome, 'skills', 'concept-fables', 'scripts', 'flow.py');
const python = process.env.PYTHON || '/usr/bin/python3';

if (!fs.existsSync(configPath)) {
  console.error(`Config not found: ${configPath}`);
  process.exit(1);
}

const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
if (config.mode !== 'feishu_app' || !config.app_id || !config.app_secret) {
  console.error('Interactive mode requires feishu_app configuration.');
  process.exit(1);
}

const childEnv = { ...process.env, CODEX_HOME: codexHome };

function runScript(script, args, timeout = 5000) {
  return execFileSync(python, [script, ...args], {
    cwd: path.dirname(path.dirname(script)),
    encoding: 'utf8',
    timeout,
    env: childEnv,
  }).trim();
}

function scheduleNext(sessionDate, delayMs) {
  setTimeout(async () => {
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        runScript(englishScript, ['send-next', '--date', sessionDate], 60000);
        console.log(`[${new Date().toISOString()}] next English card sent for ${sessionDate}`);
        return;
      } catch (error) {
        console.error(
          `[${new Date().toISOString()}] failed to send next English card (attempt ${attempt}/3)`,
          error.message
        );
        if (attempt === 3) return;
        await new Promise((resolve) => setTimeout(resolve, attempt * 2000));
      }
    }
  }, Math.max(600, Number(delayMs) || 1100));
}

let recoveryRunning = false;
setInterval(() => {
  if (recoveryRunning) return;
  recoveryRunning = true;
  try {
    const result = runScript(englishScript, ['resume-pending'], 60000);
    if (result && result !== 'waiting_for_answer' && result !== 'no active session') {
      console.log(`[${new Date().toISOString()}] recovered pending English send: ${result}`);
    }
  } catch (error) {
    console.error(`[${new Date().toISOString()}] English pending recovery failed`, error.message);
  } finally {
    recoveryRunning = false;
  }
}, 60000);

function englishCallback(value) {
  const args = [
    'callback',
    '--date', String(value.date),
    '--item-id', String(value.item_id),
    '--action', String(value.action),
    '--turn', String(value.turn),
  ];
  if (value.rating) args.push('--rating', String(value.rating));
  if (value.view_id !== undefined && value.view_id !== null) {
    args.push('--view-id', String(value.view_id));
  }
  const result = JSON.parse(runScript(englishScript, args, 5000));
  if (result.schedule_next) scheduleNext(String(value.date), result.delay_ms);
  return result;
}

function conceptCallback(value) {
  const args = [
    'callback',
    '--date', String(value.date),
    '--story-id', String(value.story_id),
    '--action', String(value.action),
    '--view-id', String(value.view_id),
  ];
  if (value.choice) args.push('--choice', String(value.choice));
  return JSON.parse(runScript(conceptScript, args, 5000));
}

function todayShanghai() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

function hubCallback(value) {
  const target = String(value.target || '');
  if (!['english', 'concept_fable'].includes(target)) {
    throw new Error('学习中心目标无效');
  }
  const script = target === 'english' ? englishScript : conceptScript;
  runScript(script, ['open', '--date', todayShanghai()], 20000);

  const source = String(value.source || '');
  if (value.action === 'switch' && source && source !== target) {
    const sourceScript = source === 'english' ? englishScript : conceptScript;
    runScript(sourceScript, ['invalidate', '--date', todayShanghai()], 5000);
  }
  return {
    toast: {
      type: 'success',
      content: target === 'english' ? '已切换至英语学习' : '已切换至概念寓言',
    },
    schedule_next: false,
  };
}

const eventDispatcher = new Lark.EventDispatcher({}).register({
  'card.action.trigger': async (data) => {
    const action = data.action || {};
    const value = action.value || {};
    const moduleName = value.module || (value.story_id ? 'concept_fable' : value.item_id ? 'english' : '');

    try {
      let result;
      if (moduleName === 'english') {
        if (!value.action || !value.date || !value.item_id || !value.turn) {
          throw new Error('英语卡片数据无效，请重新发送今日学习。');
        }
        result = englishCallback(value);
      } else if (moduleName === 'concept_fable') {
        if (!value.action || !value.date || !value.story_id || !value.view_id) {
          throw new Error('概念卡片数据无效，请重新发送今日故事。');
        }
        result = conceptCallback(value);
      } else if (moduleName === 'hub') {
        if (!['open', 'switch'].includes(value.action)) {
          throw new Error('学习中心操作无效');
        }
        result = hubCallback(value);
      } else {
        throw new Error('未知卡片，请从学习中心重新进入。');
      }

      const response = {
        toast: result.toast || { type: 'info', content: '已处理' },
      };
      if (result.card) response.card = { type: 'raw', data: result.card };
      return response;
    } catch (error) {
      console.error(`[${new Date().toISOString()}] callback failed`, error.message);
      const message = error.stdout ? String(error.stdout).trim() : error.message || '处理失败，请重试。';
      return { toast: { type: 'error', content: message.slice(0, 160) } };
    }
  },
});

const wsClient = new Lark.WSClient({
  appId: config.app_id,
  appSecret: config.app_secret,
  loggerLevel: Lark.LoggerLevel.info,
  onReady: () => console.log(`[${new Date().toISOString()}] connected to Feishu WebSocket`),
  onError: (error) => console.error(`[${new Date().toISOString()}] WebSocket error`, error),
  onReconnecting: () => console.log(`[${new Date().toISOString()}] reconnecting`),
  onReconnected: () => console.log(`[${new Date().toISOString()}] reconnected`),
});

process.on('SIGTERM', () => {
  try {
    wsClient.close();
  } finally {
    process.exit(0);
  }
});
process.on('SIGINT', () => process.exit(0));

console.log(`[${new Date().toISOString()}] starting shared learning callback listener`);
wsClient.start({ eventDispatcher }).catch((error) => {
  console.error(`[${new Date().toISOString()}] failed to start`, error);
  process.exit(1);
});
