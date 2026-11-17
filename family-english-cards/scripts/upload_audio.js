#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const configPath = path.join(
  process.env.CODEX_HOME || path.join(process.env.HOME, '.codex'),
  'family-english-cards',
  'config.json'
);
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const args = process.argv.slice(2);

async function getToken() {
  const response = await fetch('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ app_id: config.app_id, app_secret: config.app_secret }),
    signal: AbortSignal.timeout(15000),
  });
  const data = await response.json();
  if (!response.ok || data.code !== 0 || !data.tenant_access_token) {
    throw new Error(`token request failed: ${JSON.stringify(data)}`);
  }
  return data.tenant_access_token;
}

async function uploadOne(token, item) {
  const audioPath = item.path;
  if (!fs.existsSync(audioPath)) throw new Error(`missing audio: ${audioPath}`);
  const form = new FormData();
  form.append('file_type', 'opus');
  form.append('file_name', path.basename(audioPath));
  form.append('duration', String(item.duration_ms || 3000));
  form.append('file', new Blob([fs.readFileSync(audioPath)]), path.basename(audioPath));
  const response = await fetch('https://open.feishu.cn/open-apis/im/v1/files', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
    signal: AbortSignal.timeout(30000),
  });
  const data = await response.json();
  if (!response.ok || data.code !== 0 || !data.data || !data.data.file_key) {
    throw new Error(`upload failed for ${item.id}: ${JSON.stringify(data)}`);
  }
  return data.data.file_key;
}

(async () => {
  const token = await getToken();
  if (args[0] === '--one' && args.length >= 4) {
    const fileKey = await uploadOne(token, {
      id: args[1],
      path: args[2],
      duration_ms: Number(args[3]),
    });
    process.stdout.write(JSON.stringify({ file_key: fileKey }));
    return;
  }
  if (args[0] === '--batch' && args[1]) {
    const manifest = JSON.parse(fs.readFileSync(args[1], 'utf8'));
    const result = {};
    for (const item of manifest.items || []) {
      result[item.id] = await uploadOne(token, item);
    }
    process.stdout.write(JSON.stringify({ file_keys: result }));
    return;
  }
  throw new Error('usage: upload_audio.js --one <id> <path> <duration_ms> | --batch <manifest>');
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
