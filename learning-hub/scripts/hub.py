#!/usr/bin/env python3
"""Shared learning-center card for English and concept-fable streams."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
HUB_DIR = CODEX_HOME / "learning-hub"
STATE_PATH = HUB_DIR / "state.json"
CONFIG_PATH = CODEX_HOME / "family-english-cards" / "config.json"
ENGLISH_SESSION_DIR = CODEX_HOME / "family-english-cards" / "sessions"
CONCEPT_SESSION_DIR = CODEX_HOME / "concept-fables" / "sessions"
sys.path.insert(0, str(SCRIPT_DIR))
import feishu  # noqa: E402


class HubError(RuntimeError):
    pass


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def english_status(today: date) -> str:
    path = ENGLISH_SESSION_DIR / "{}.json".format(today.isoformat())
    session = read_json(path, {})
    if not session:
        return "今日尚未开始"
    runtime = session.get("runtime", {})
    if runtime.get("completed"):
        return "今日已完成"
    if runtime.get("expired"):
        return "今日未完成"
    total = len(runtime.get("queue", []))
    current = min(int(runtime.get("current_index", 0)) + 1, total) if total else 0
    return "进行中 {}/{}".format(current, total) if total else "等待发送"


def concept_status(today: date) -> str:
    path = CONCEPT_SESSION_DIR / "{}.json".format(today.isoformat())
    session = read_json(path, {})
    if not session:
        return "今日尚未开始"
    page = session.get("page")
    if page == "result":
        correct = session.get("answer", {}).get("correct")
        return "已完成 · 答对" if correct else "已完成 · 已看解析"
    if page == "quiz":
        return "答题中"
    return "故事已发送"


def button(text: str, button_type: str, value: dict) -> dict:
    return {
        "tag": "button",
        "type": button_type,
        "width": "fill",
        "text": {"tag": "plain_text", "content": text},
        "behaviors": [{"type": "callback", "value": value}],
    }


def build_card(today: date) -> dict:
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "enable_forward": False},
        "header": {
            "template": "indigo",
            "title": {"tag": "plain_text", "content": "今日学习中心 · {}".format(today.isoformat())},
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": "## 概念寓言\n{}\n\n[进入或继续]".format(concept_status(today))},
                button("进入概念寓言", "primary", {"module": "hub", "action": "open", "target": "concept_fable"}),
                {"tag": "hr"},
                {"tag": "markdown", "content": "## 英语学习\n{}\n\n[进入或继续]".format(english_status(today))},
                button("进入英语学习", "primary", {"module": "hub", "action": "open", "target": "english"}),
                {"tag": "markdown", "content": "<font color='grey'>把这张卡片固定在群顶部，可随时切换，不会打断另一项进度。</font>"},
            ]
        },
    }


def send_or_update(refresh: bool = True) -> str:
    config = read_json(CONFIG_PATH, {})
    if config.get("mode") != "feishu_app":
        raise HubError("feishu_app configuration is required")
    token = feishu.get_tenant_access_token(config["app_id"], config["app_secret"])
    state = read_json(STATE_PATH, {})
    today = date.today()
    card = build_card(today)
    message_id = state.get("message_id")
    if refresh and message_id:
        feishu.patch_card(token, message_id, card)
        state["last_updated"] = date.today().isoformat()
        write_json(STATE_PATH, state)
        return message_id
    if refresh:
        return ""
    key = "learning-hub:{}:{}".format(today.isoformat(), uuid.uuid4().hex[:12])
    result = feishu.send_via_app(
        token,
        config.get("receive_id_type", "chat_id"),
        config["receive_id"],
        card,
        idempotency_uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
    )
    message_id = result.get("data", {}).get("message_id", "")
    write_json(STATE_PATH, {"message_id": message_id, "created_on": today.isoformat(), "last_updated": today.isoformat()})
    return message_id


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"send", "refresh"}:
        print("usage: hub.py send|refresh", file=sys.stderr)
        return 2
    try:
        message_id = send_or_update(refresh=sys.argv[1] == "refresh")
        print(message_id)
        return 0
    except (HubError, feishu.FeishuError) as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
