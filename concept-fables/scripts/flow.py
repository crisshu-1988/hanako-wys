#!/usr/bin/env python3
"""Daily concept-fable story, quiz, and explanation flow."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
USER_DATA_DIR = CODEX_HOME / "concept-fables"
STATE_PATH = USER_DATA_DIR / "state.json"
BANK_PATH = USER_DATA_DIR / "bank.json"
SESSION_DIR = USER_DATA_DIR / "sessions"
LOG_DIR = USER_DATA_DIR / "logs"
SEED_BANK_PATH = SKILL_ROOT / "data" / "seed_bank.json"
CONFIG_PATH = CODEX_HOME / "family-english-cards" / "config.json"
HUB_SCRIPT = CODEX_HOME / "learning-hub" / "hub.py"

sys.path.insert(0, str(SCRIPT_DIR))
import feishu  # noqa: E402

DOMAIN_ORDER = ["household_economics", "child_development", "ai_agent"]
DOMAIN_LABELS = {
    "ai_agent": "AI Personal Agent",
    "household_economics": "家庭理财中的经济学",
    "child_development": "儿童成长教育",
}
CORRECT_I18N = {
    "zh_cn": "太棒了，答对啦！",
    "en_us": "Nice one—you nailed it!",
    "ja_jp": "すごい！大正解！",
    "ko_kr": "멋져요! 정답이에요!",
    "fr_fr": "Bravo, c’est exact !",
    "de_de": "Stark! Genau richtig!",
    "es_es": "¡Genial! ¡Respuesta correcta!",
    "ru_ru": "Отлично! Всё верно!",
}
WRONG_I18N = {
    "zh_cn": "差一点，再想一步！",
    "en_us": "Not quite—keep going!",
    "ja_jp": "おしい！次はいけるよ！",
    "ko_kr": "아깝다! 한 번 더!",
    "fr_fr": "Presque ! Continue !",
    "de_de": "Fast! Weiter so!",
    "es_es": "¡Casi! Sigue así.",
    "ru_ru": "Почти! Продолжай!",
}


class FlowError(RuntimeError):
    pass


def ensure_dirs() -> None:
    for path in (USER_DATA_DIR, SESSION_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
    if not BANK_PATH.exists():
        BANK_PATH.write_bytes(SEED_BANK_PATH.read_bytes())


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_bank() -> Dict[str, dict]:
    ensure_dirs()
    data = load_json(BANK_PATH, {"items": []})
    result = {}
    for item in data.get("items", []):
        required = {"id", "domain", "domain_label", "concept", "title", "story", "question", "options", "definition", "mapping", "application", "talk_track", "source"}
        missing = required.difference(item)
        if missing:
            raise FlowError("{} is missing {}".format(item.get("id", "item"), sorted(missing)))
        if item["id"] in result:
            raise FlowError("Duplicate story id: {}".format(item["id"]))
        if sum(1 for option in item["options"] if option.get("correct")) != 1:
            raise FlowError("{} must have exactly one correct option".format(item["id"]))
        result[item["id"]] = item
    return result


def default_state() -> dict:
    return {"version": 1, "seen": {}, "answers": []}


def session_path(target_date: date) -> Path:
    return SESSION_DIR / "{}.json".format(target_date.isoformat())


def load_session(target_date: date) -> Optional[dict]:
    path = session_path(target_date)
    return load_json(path, {}) if path.exists() else None


def save_session(session: dict) -> None:
    write_json(session_path(date.fromisoformat(session["date"])), session)


def domain_for_date(target_date: date) -> str:
    return DOMAIN_ORDER[target_date.toordinal() % len(DOMAIN_ORDER)]


def choose_story(target_date: date) -> dict:
    bank = load_bank()
    state = load_json(STATE_PATH, default_state())
    seen = state.setdefault("seen", {})
    domain = domain_for_date(target_date)
    candidates = [item for item in bank.values() if item["domain"] == domain and item["id"] not in seen]
    if candidates:
        return candidates[0]
    old_candidates = [item for item in bank.values() if item["domain"] == domain]
    if not old_candidates:
        raise FlowError("No stories available for domain: {}".format(domain))
    return min(old_candidates, key=lambda item: seen.get(item["id"], {}).get("sent_on", ""))


def create_session(target_date: date) -> dict:
    existing = load_session(target_date)
    if existing:
        return existing
    story = choose_story(target_date)
    session = {
        "version": 1,
        "date": target_date.isoformat(),
        "story_id": story["id"],
        "domain": story["domain"],
        "domain_label": DOMAIN_LABELS[story["domain"]],
        "page": "story",
        "view_id": 1,
        "message_id": None,
        "sent_at": None,
        "answer": None,
        "completed": False,
    }
    state = load_json(STATE_PATH, default_state())
    state.setdefault("seen", {})[story["id"]] = {
        "sent_on": target_date.isoformat(),
        "status": "story_sent",
    }
    write_json(STATE_PATH, state)
    save_session(session)
    return session


def button(text: str, button_type: str, value: dict, width: str = "fill") -> dict:
    return {
        "tag": "button",
        "type": button_type,
        "width": width,
        "text": {"tag": "plain_text", "content": text},
        "behaviors": [{"type": "callback", "value": value}],
    }


def card_shell(title: str, template: str, elements: List[dict]) -> dict:
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "enable_forward": False},
        "header": {"template": template, "title": {"tag": "plain_text", "content": title}},
        "body": {"elements": elements},
    }


def switch_button(source: str) -> dict:
    return button(
        "切换至英语",
        "default",
        {"module": "hub", "action": "switch", "source": source, "target": "english"},
    )


def base_action(session: dict, action: str) -> dict:
    return {
        "module": "concept_fable",
        "action": action,
        "date": session["date"],
        "story_id": session["story_id"],
        "view_id": session["view_id"],
    }


def story_card(session: dict, story: dict) -> dict:
    return card_shell(
        "概念寓言 · {}".format(session["domain_label"]),
        "violet",
        [
            {"tag": "markdown", "content": "# {}\n\n{}".format(story["title"], story["story"])},
            {"tag": "hr"},
            {"tag": "markdown", "content": "**故事读完了吗？**"},
            button("开始答题", "primary", base_action(session, "start_quiz")),
            switch_button("concept_fable"),
        ],
    )


def quiz_card(session: dict, story: dict) -> dict:
    elements = [
        {"tag": "markdown", "content": "# 答题时间\n\n{}".format(story["question"])},
        {"tag": "hr"},
    ]
    for option in story["options"]:
        value = base_action(session, "answer")
        value["choice"] = option["id"]
        elements.append(button("{}　{}".format(option["id"], option["text"]), "default", value))
    elements.append(switch_button("concept_fable"))
    return card_shell("概念寓言 · 猜概念", "blue", elements)


def result_card(session: dict, story: dict) -> dict:
    selected = session.get("answer", {}).get("choice")
    correct = session.get("answer", {}).get("correct", False)
    correct_option = next(option for option in story["options"] if option["correct"])
    status = "回答正确" if correct else "回答错误"
    mapping = "\n".join("- {}".format(line) for line in story["mapping"])
    return card_shell(
        "概念寓言 · 解析",
        "green" if correct else "orange",
        [
            {"tag": "markdown", "content": "# {}\n\n你的选择：**{}**　正确答案：**{} {}**".format(status, selected, correct_option["id"], correct_option["text"])},
            {"tag": "markdown", "content": "## 概念\n**{}**\n\n{}".format(story["concept"], story["definition"])},
            {"tag": "markdown", "content": "## 故事里的映射\n{}".format(mapping)},
            {"tag": "markdown", "content": "## 现实应用\n{}".format(story["application"])},
            {"tag": "markdown", "content": "## 一句可复用谈资\n{}".format(story["talk_track"])},
            {"tag": "markdown", "content": "## 来源\n{}".format(story["source"])},
            switch_button("concept_fable"),
        ],
    )


def page_card(session: dict) -> dict:
    story = load_bank()[session["story_id"]]
    if session["page"] == "story":
        return story_card(session, story)
    if session["page"] == "quiz":
        return quiz_card(session, story)
    return result_card(session, story)


def send_card(session: dict, card: dict) -> str:
    config = load_json(CONFIG_PATH, {})
    if config.get("mode") != "feishu_app":
        raise FlowError("feishu_app configuration is required")
    token = feishu.get_tenant_access_token(config["app_id"], config["app_secret"])
    key = "concept-fable:{}:{}:{}:{}".format(session["date"], session["story_id"], session["view_id"], session["page"])
    message_id = feishu.send_via_app(
        token,
        config.get("receive_id_type", "chat_id"),
        config["receive_id"],
        card,
        idempotency_uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
    ).get("data", {}).get("message_id", "")
    session["message_id"] = message_id
    session["sent_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_session(session)
    refresh_hub_async()
    return message_id


def refresh_hub_async() -> None:
    if not HUB_SCRIPT.exists():
        return
    try:
        with open(LOG_DIR / "hub-refresh.log", "a", encoding="utf-8") as log:
            subprocess.Popen(
                [sys.executable, str(HUB_SCRIPT), "refresh"],
                stdout=log,
                stderr=log,
                start_new_session=True,
                close_fds=True,
                env={**os.environ, "CODEX_HOME": str(CODEX_HOME)},
            )
    except Exception as exc:
        print("hub refresh failed: {}".format(exc), file=sys.stderr)


def run(target_date: date) -> int:
    ensure_dirs()
    session = load_session(target_date)
    if not session:
        session = create_session(target_date)
    if session.get("message_id") and session.get("page") != "result":
        print("今日故事已发送：{}".format(session["message_id"]))
        return 0
    if session.get("page") == "result":
        print("今日概念寓言已完成")
        return 0
    message_id = send_card(session, page_card(session))
    print("已发送故事：{}".format(message_id))
    return 0


def open_session(target_date: date) -> int:
    ensure_dirs()
    session = load_session(target_date) or create_session(target_date)
    session["view_id"] = int(session.get("view_id", 1)) + 1
    save_session(session)
    message_id = send_card(session, page_card(session))
    print(message_id)
    return 0


def invalidate(target_date: date) -> int:
    session = load_session(target_date)
    if not session:
        return 0
    session["view_id"] = int(session.get("view_id", 1)) + 1
    save_session(session)
    print("invalidated")
    return 0


def callback_card(session: dict, story_id: str, action: str, view_id: int, choice: str = "") -> dict:
    if session["story_id"] != story_id:
        raise FlowError("Story does not match the active card")
    if int(session.get("view_id", 1)) != int(view_id):
        raise FlowError("这张卡片已经过期，请从学习中心重新打开。")
    story = load_bank()[story_id]
    if action == "start_quiz":
        if session["page"] == "story":
            session["page"] = "quiz"
            save_session(session)
        return {"toast": {"type": "info", "content": "开始作答"}, "card": page_card(session), "schedule_next": False}
    if action != "answer":
        raise FlowError("Unsupported action")
    if session["page"] == "result":
        return {"toast": {"type": "info", "content": "本题已经提交"}, "card": page_card(session), "schedule_next": False}
    option = next((item for item in story["options"] if item["id"] == choice), None)
    if not option:
        raise FlowError("Unknown choice")
    correct = bool(option["correct"])
    session["page"] = "result"
    session["completed"] = True
    session["answer"] = {
        "choice": choice,
        "correct": correct,
        "answered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    save_session(session)
    state = load_json(STATE_PATH, default_state())
    state.setdefault("answers", []).append({
        "date": session["date"],
        "story_id": story_id,
        "concept": story["concept"],
        "choice": choice,
        "correct": correct,
    })
    state.setdefault("seen", {}).setdefault(story_id, {})["status"] = "answered"
    write_json(STATE_PATH, state)
    refresh_hub_async()
    i18n = CORRECT_I18N if correct else WRONG_I18N
    content = i18n["zh_cn"]
    return {
        "toast": {"type": "success" if correct else "warning", "content": content, "i18n": i18n},
        "card": page_card(session),
        "schedule_next": False,
    }


def status() -> int:
    ensure_dirs()
    state = load_json(STATE_PATH, default_state())
    today = date.today()
    session = load_session(today)
    print("内容库：{} 篇".format(len(load_bank())))
    print("已出题：{} 篇".format(len(state.get("seen", {}))))
    print("已回答：{} 次".format(len(state.get("answers", []))))
    print("今日：{}".format(session["story_id"] if session else "尚未创建"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "open", "invalidate"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--date")
    callback = subparsers.add_parser("callback")
    callback.add_argument("--date", required=True)
    callback.add_argument("--story-id", required=True)
    callback.add_argument("--action", required=True, choices=["start_quiz", "answer"])
    callback.add_argument("--view-id", required=True, type=int)
    callback.add_argument("--choice", default="")
    subparsers.add_parser("status")
    args = parser.parse_args()

    try:
        if args.command == "status":
            return status()
        target_date = date.fromisoformat(args.date) if getattr(args, "date", None) else date.today()
        if args.command == "run":
            return run(target_date)
        if args.command == "open":
            return open_session(target_date)
        if args.command == "invalidate":
            return invalidate(target_date)
        session = load_session(target_date)
        if not session:
            raise FlowError("No concept session for {}".format(target_date))
        result = callback_card(
            session,
            args.story_id,
            args.action,
            args.view_id,
            args.choice,
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (FlowError, feishu.FeishuError) as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
