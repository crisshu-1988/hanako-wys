#!/usr/bin/env python3
"""Interactive one-card-at-a-time flow for Family English Cards."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import daily  # noqa: E402
import feishu  # noqa: E402

INTERVALS = [3, 7, 14, 30, 60, 90]
RATINGS = {"会", "模糊", "不会"}
HUB_SCRIPT = daily.CODEX_HOME / "learning-hub" / "hub.py"


class FlowError(RuntimeError):
    pass


def load_state() -> dict:
    state = daily.load_json(daily.STATE_PATH, {"version": 2, "items": {}})
    state.setdefault("items", {})
    state["version"] = 2
    changed = False
    today = date.today()
    for item_id, item_state in state["items"].items():
        if "introduced_on" not in item_state:
            item_state["introduced_on"] = today.isoformat()
            changed = True
        if "stage" not in item_state:
            item_state["stage"] = 0
            changed = True
        if "due_on" not in item_state:
            introduced = daily.parse_date(item_state["introduced_on"])
            item_state["due_on"] = (introduced + timedelta(days=1)).isoformat()
            changed = True
        item_state.setdefault("rating_history", [])
        item_state.setdefault("last_rating", None)
        item_state.setdefault("last_delivered_on", None)
    if changed:
        daily.write_json(daily.STATE_PATH, state)
    return state


def session_path(target_date: date) -> Path:
    return daily.SESSION_DIR / "{}.json".format(target_date.isoformat())


def load_session(target_date: date) -> dict:
    path = session_path(target_date)
    if not path.exists():
        raise FlowError("Session does not exist: {}".format(path))
    session = daily.load_json(path)
    if "view_id" not in session or session.get("view_id") is None:
        session["view_id"] = 1
        daily.write_json(path, session)
    return session


def find_resumable_session(target_date: Optional[date] = None) -> Optional[dict]:
    if not daily.SESSION_DIR.exists():
        return None
    paths = [session_path(target_date)] if target_date else sorted(
        daily.SESSION_DIR.glob("*.json"), reverse=True
    )
    for path in paths:
        if not path.exists():
            continue
        session = daily.load_json(path)
        runtime = session.get("runtime", {})
        if (
            session.get("schema") == 2
            and not runtime.get("completed", False)
            and not runtime.get("expired", False)
        ):
            return session
    return None


def expire_previous_sessions(target_date: date) -> int:
    expired_count = 0
    if not daily.SESSION_DIR.exists():
        return expired_count
    for path in sorted(daily.SESSION_DIR.glob("*.json")):
        session = daily.load_json(path)
        if session.get("schema") != 2:
            continue
        runtime = session.get("runtime", {})
        session_date = daily.parse_date(session.get("date", ""))
        if (
            session_date < target_date
            and not runtime.get("completed", False)
            and not runtime.get("expired", False)
        ):
            runtime["expired"] = True
            runtime["expired_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            runtime["next_ready"] = True
            session["delivery"] = {
                **session.get("delivery", {}),
                "status": "expired",
                "expired_at": runtime["expired_at"],
            }
            daily.write_json(path, session)
            expired_count += 1
    return expired_count


def migrate_state() -> dict:
    return load_state()


def migrate_legacy_session(session: dict) -> dict:
    queue = []
    for item in session.get("items", []):
        queue.append(
            {
                "id": item["id"],
                "kind": item.get("kind", "new"),
                "attempt": 1,
                "is_retry": False,
            }
        )
    session["schema"] = 2
    session["version"] = 2
    session["queue"] = queue
    session["runtime"] = {
        "queue": queue,
        "current_index": 0,
        "current_item_id": None,
        "current_message_id": None,
        "next_ready": True,
        "completed": False,
        "processed_actions": [],
        "rating_counts": {"会": 0, "模糊": 0, "不会": 0},
    }
    session["audio_keys"] = {}
    session["delivery"] = {"status": "migrated"}
    daily.write_json(session_path(daily.parse_date(session["date"])), session)
    return session


def build_session(target_date: date) -> dict:
    daily.ensure_dirs()
    existing = find_resumable_session(target_date)
    if existing:
        return existing

    path = session_path(target_date)
    if path.exists():
        session = load_session(target_date)
        if session.get("schema") == 2:
            return session
        return migrate_legacy_session(session)

    state = migrate_state()
    bank = daily.load_bank()
    config = daily.load_config()
    offsets = [int(value) for value in config.get("review_offsets_days", daily.DEFAULT_OFFSETS)]
    del offsets  # v2 uses feedback-driven due dates.

    due_entries: List[dict] = []
    for item_id, item_state in state["items"].items():
        due_on = item_state.get("due_on")
        if due_on and daily.parse_date(due_on) <= target_date and item_id in bank:
            due_entries.append({"id": item_id, "kind": "review", "attempt": 1, "is_retry": False})
    due_entries.sort(
        key=lambda entry: (
            state["items"][entry["id"]].get("last_delivered_on") or "",
            state["items"][entry["id"]]["due_on"],
            entry["id"],
        )
    )
    review_limit = int(config.get("max_reviews_per_day", 10))
    due_entries = due_entries[:review_limit]

    new_entries: List[dict] = []
    new_limit = int(config.get("new_items_per_day", 10))
    for item_id in bank:
        if item_id in state["items"]:
            continue
        state["items"][item_id] = {
            "introduced_on": target_date.isoformat(),
            "stage": 0,
            "due_on": (target_date + timedelta(days=1)).isoformat(),
            "last_rating": None,
            "rating_history": [],
            "last_delivered_on": None,
        }
        new_entries.append({"id": item_id, "kind": "new", "attempt": 1, "is_retry": False})
        if len(new_entries) >= new_limit:
            break

    queue = due_entries + new_entries
    if not queue:
        raise FlowError("No new or due items are available")

    session = {
        "version": 2,
        "schema": 2,
        "date": target_date.isoformat(),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "new_count": len(new_entries),
        "review_count": len(due_entries),
        "queue": queue,
        "runtime": {
            "queue": queue,
            "current_index": 0,
            "current_item_id": None,
            "current_message_id": None,
            "next_ready": True,
            "completed": False,
            "processed_actions": [],
            "rating_counts": {"会": 0, "模糊": 0, "不会": 0},
        },
        "audio": {},
        "audio_keys": {},
        "delivery": {"status": "not_started"},
    }
    session["items"] = [bank[entry["id"]] for entry in queue]
    session["audio"] = daily.generate_session_audio(session, config)
    daily.write_json(daily.STATE_PATH, state)
    daily.write_json(path, session)
    return session


def save_session(session: dict) -> None:
    session["view_id"] = int(session.get("view_id", 1))
    daily.write_json(session_path(daily.parse_date(session["date"])), session)


def get_item(bank: dict, item_id: str) -> dict:
    if item_id not in bank:
        raise FlowError("Unknown item: {}".format(item_id))
    return bank[item_id]


def button(text: str, button_type: str, value: dict) -> dict:
    return {
        "tag": "button",
        "type": button_type,
        "width": "fill",
        "text": {"tag": "plain_text", "content": text},
        "behaviors": [{"type": "callback", "value": value}],
    }


def button_row(buttons: List[dict]) -> dict:
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "horizontal_spacing": "8px",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "vertical_align": "center",
                "elements": [item],
            }
            for item in buttons
        ],
    }


def switch_button() -> dict:
    return button(
        "切换至概念寓言",
        "default",
        {"module": "hub", "action": "switch", "source": "english", "target": "concept_fable"},
    )


def card_action(session: dict, action: str, **extra: str) -> dict:
    value = {
        "module": "english",
        "action": action,
        "date": session["date"],
        "view_id": int(session.get("view_id", 1)),
    }
    value.update(extra)
    return value


def card_shell(title: str, template: str, elements: List[dict]) -> dict:
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "enable_forward": False},
        "header": {"template": template, "title": {"tag": "plain_text", "content": title}},
        "body": {"elements": elements},
    }


def progress_text(session: dict) -> str:
    runtime = session["runtime"]
    current = min(runtime["current_index"] + 1, len(runtime["queue"]))
    total = len(runtime["queue"])
    entry = runtime["queue"][runtime["current_index"]]
    label = "新词" if entry["kind"] == "new" else "复习"
    if entry.get("is_retry"):
        label = "再练一次"
    return "第 **{} / {}** 题 · {}".format(current, total, label)


def turn_id(session: dict) -> str:
    runtime = session["runtime"]
    entry = runtime["queue"][runtime["current_index"]]
    return "{}:{}:{}".format(session["date"], runtime["current_index"], entry["attempt"])


def build_question_card(session: dict) -> dict:
    runtime = session["runtime"]
    bank = daily.load_bank()
    entry = runtime["queue"][runtime["current_index"]]
    item = get_item(bank, entry["id"])
    value = card_action(session, "reveal", item_id=entry["id"], turn=turn_id(session))
    return card_shell(
        "亲子英语 · 专注练习",
        "blue",
        [
            {"tag": "markdown", "content": progress_text(session)},
            {"tag": "hr"},
            {"tag": "markdown", "content": "**场景：{}**".format(scene_label(item["scene"]))},
            {"tag": "markdown", "content": "# {}\n\n先自己说出英文，再看答案。".format(item["zh"])},
            button("显示答案", "primary", value),
            switch_button(),
        ],
    )


def build_answer_card(session: dict) -> dict:
    runtime = session["runtime"]
    bank = daily.load_bank()
    entry = runtime["queue"][runtime["current_index"]]
    item = get_item(bank, entry["id"])
    base = card_action(session, "rate", item_id=entry["id"], turn=turn_id(session))
    elements: List[dict] = [
        {"tag": "markdown", "content": progress_text(session)},
        {"tag": "hr"},
        {"tag": "markdown", "content": "**{}**  \n{}".format(item["phrase"], item["ipa"])},
    ]
    audio_key = session.get("audio_keys", {}).get(entry["id"])
    if audio_key:
        elements.append(
            {
                "tag": "audio",
                "file_key": audio_key,
                "audio_id": "{}-{}".format(entry["id"], runtime["current_index"]),
                "show_progress_bar": True,
                "show_time": True,
                "time_position": "end",
                "style": "flat",
                "width": "fill",
            }
        )
    elements.extend(
        [
            {
                "tag": "markdown",
                "content": "_{}_  \n{}".format(item["example"], item["example_zh"]),
            },
            {"tag": "hr"},
            {"tag": "markdown", "content": "**刚才想出来了吗？**"},
            button_row(
                [
                    button("不会", "danger", dict(base, action="rate", rating="不会")),
                    button("模糊", "default", dict(base, action="rate", rating="模糊")),
                    button("会", "primary", dict(base, action="rate", rating="会")),
                ]
            ),
            switch_button(),
        ]
    )
    return card_shell("亲子英语 · 核对答案", "turquoise", elements)


def apply_rating(session: dict, entry: dict, rating: str, target_date: date) -> str:
    state = migrate_state()
    item_state = state["items"][entry["id"]]
    stage = int(item_state.get("stage", 0))
    item_state.setdefault("rating_history", []).append(
        {
            "date": target_date.isoformat(),
            "rating": rating,
            "retry": bool(entry.get("is_retry")),
        }
    )
    item_state["last_rating"] = rating
    if entry.get("is_retry"):
        item_state["due_on"] = (target_date + timedelta(days=1)).isoformat()
    elif rating == "会":
        stage += 1
        item_state["stage"] = stage
        interval = INTERVALS[min(stage - 1, len(INTERVALS) - 1)]
        item_state["due_on"] = (target_date + timedelta(days=interval)).isoformat()
    elif rating == "模糊":
        item_state["due_on"] = (target_date + timedelta(days=1)).isoformat()
    else:
        item_state["due_on"] = (target_date + timedelta(days=1)).isoformat()
    daily.write_json(daily.STATE_PATH, state)
    return item_state["due_on"]


def feedback_card(session: dict, item: dict, rating: str, due_on: str) -> dict:
    if rating == "会":
        heading = "已掌握"
        detail = "下次复习：**{}**".format(due_on)
        template = "green"
        toast = "已记录：会"
    elif rating == "模糊":
        heading = "还需要巩固"
        detail = "明天会优先再练一次。"
        template = "orange"
        toast = "已记录：模糊"
    else:
        heading = "本轮结束前再练一次"
        detail = "今天稍后会重新出现，明天也会继续复习。"
        template = "red"
        toast = "已记录：不会"
    return card_shell(
        "亲子英语 · 已记录",
        template,
        [
            {"tag": "markdown", "content": "# {}".format(heading)},
            {"tag": "markdown", "content": "**{}**  {}".format(item["phrase"], item["ipa"])},
            {"tag": "markdown", "content": detail},
            {"tag": "markdown", "content": "<font color='grey'>下一题将在约 1 秒后自动发送。</font>"},
        ],
    )


def summary_card(session: dict) -> dict:
    runtime = session["runtime"]
    counts = runtime.get("rating_counts", {})
    return card_shell(
        "亲子英语 · 今日完成",
        "purple",
        [
            {"tag": "markdown", "content": "# 本轮完成"},
            {
                "tag": "markdown",
                "content": "完成题目：**{}**  \n会：**{}**　模糊：**{}**　不会：**{}**".format(
                    len(runtime["queue"]),
                    counts.get("会", 0),
                    counts.get("模糊", 0),
                    counts.get("不会", 0),
                ),
            },
            {"tag": "hr"},
            {"tag": "markdown", "content": "**主动使用：** 选 3 句，今天和孩子真实说一遍。"},
            switch_button(),
        ],
    )


def send_card(session: dict, card: dict) -> str:
    config = daily.load_config(required=True)
    if config.get("mode") != "feishu_app":
        raise FlowError("Interactive flow requires feishu_app mode")
    token = feishu.get_tenant_access_token(config["app_id"], config["app_secret"])
    runtime = session["runtime"]
    entry = runtime["queue"][runtime["current_index"]] if runtime["current_index"] < len(runtime["queue"]) else None
    turn = "{}:{}:{}:{}".format(
        session["date"],
        runtime["current_index"],
        entry.get("attempt", 0) if entry else 0,
        "question" if entry else "summary",
    )
    idempotency_uuid = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        "family-english:{}:{}".format(session.get("view_id", 1), turn),
    ))
    result = feishu.send_via_app(
        token,
        config.get("receive_id_type", "chat_id"),
        config["receive_id"],
        card,
        idempotency_uuid=idempotency_uuid,
    )
    return result.get("data", {}).get("message_id", "")


def refresh_hub_async() -> None:
    if not HUB_SCRIPT.exists():
        return
    try:
        with open(daily.LOG_DIR / "hub-refresh.log", "a", encoding="utf-8") as log:
            subprocess.Popen(
                [sys.executable, str(HUB_SCRIPT), "refresh"],
                stdout=log,
                stderr=log,
                start_new_session=True,
                close_fds=True,
                env={**os.environ, "CODEX_HOME": str(daily.CODEX_HOME)},
            )
    except Exception as exc:
        print("学习中心刷新失败：{}".format(exc), file=sys.stderr)


def find_node() -> Optional[str]:
    config = daily.load_config()
    candidates = [
        config.get("node_binary"),
        os.environ.get("NODE_BINARY"),
        shutil.which("node"),
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
    ]
    nvm_root = Path.home() / ".nvm" / "versions" / "node"
    if nvm_root.exists():
        candidates.extend(str(path) for path in sorted(nvm_root.glob("*/bin/node"), reverse=True))
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def ensure_audio_keys(session: dict, only_item_id: Optional[str] = None) -> None:
    keys = session.setdefault("audio_keys", {})
    missing = []
    for item in session.get("items", []):
        item_id = item["id"]
        if only_item_id and item_id != only_item_id:
            continue
        metadata = session.get("audio", {}).get(item_id)
        if metadata and item_id not in keys:
            missing.append(
                {
                    "id": item_id,
                    "path": metadata["path"],
                    "duration_ms": int(metadata["duration_ms"]),
                }
            )
    if not missing:
        return

    node = find_node()
    if not node:
        raise FlowError("Node.js is required for reliable Feishu audio uploads")
    uploader = SCRIPT_DIR / "upload_audio.js"
    manifest_path = None
    try:
        if only_item_id:
            item = missing[0]
            command = [node, str(uploader), "--one", item["id"], item["path"], str(item["duration_ms"])]
        else:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                prefix="family-audio-",
                dir=str(daily.LOG_DIR),
                delete=False,
            ) as handle:
                json.dump({"items": missing}, handle, ensure_ascii=False)
                manifest_path = handle.name
            command = [node, str(uploader), "--batch", manifest_path]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise FlowError(result.stderr.strip() or result.stdout.strip() or "audio upload failed")
        payload = json.loads(result.stdout)
        if only_item_id:
            keys[only_item_id] = payload["file_key"]
        else:
            keys.update(payload.get("file_keys", {}))
        save_session(session)
    finally:
        if manifest_path:
            try:
                Path(manifest_path).unlink()
            except FileNotFoundError:
                pass


def start_audio_preload(session: dict) -> None:
    try:
        daily.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(daily.LOG_DIR / "audio-preload.log", "a", encoding="utf-8") as log:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "preload-audio", "--date", session["date"]],
                cwd=str(SCRIPT_DIR.parent),
                stdout=log,
                stderr=log,
                start_new_session=True,
                close_fds=True,
                env={**os.environ, "CODEX_HOME": str(daily.CODEX_HOME)},
            )
    except Exception as exc:
        print("音频预上传启动失败：{}".format(exc), file=sys.stderr)


def send_next(session: dict, force: bool = False) -> str:
    runtime = session["runtime"]
    if runtime.get("completed"):
        return "completed"
    if runtime.get("current_message_id") and not runtime.get("next_ready", False) and not force:
        return "waiting_for_answer"
    if runtime["current_index"] >= len(runtime["queue"]):
        message_id = send_card(session, summary_card(session))
        runtime["completed"] = True
        runtime["next_ready"] = False
        runtime["page"] = "summary"
        runtime["summary_message_id"] = message_id
        save_session(session)
        refresh_hub_async()
        return message_id

    entry = runtime["queue"][runtime["current_index"]]
    try:
        ensure_audio_keys(session, only_item_id=entry["id"])
    except FlowError as exc:
        print("当前题音频上传暂未成功，先发送文字卡片：{}".format(exc), file=sys.stderr)
    card = build_question_card(session)
    message_id = send_card(session, card)
    entry = runtime["queue"][runtime["current_index"]]
    runtime["current_item_id"] = entry["id"]
    runtime["current_message_id"] = message_id
    runtime["next_ready"] = False
    runtime["page"] = "question"
    session["delivery"] = {
        "status": "in_progress",
        "message_id": message_id,
        "sent_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    state = migrate_state()
    state["items"][entry["id"]]["last_delivered_on"] = session["date"]
    daily.write_json(daily.STATE_PATH, state)
    save_session(session)
    start_audio_preload(session)
    refresh_hub_async()
    return message_id


def callback_card(
    session: dict,
    item_id: str,
    action: str,
    turn: str,
    rating: str = "",
    view_id: Optional[int] = None,
) -> dict:
    runtime = session["runtime"]
    if view_id is not None and int(session.get("view_id", 1)) != int(view_id):
        raise FlowError("这张卡片已经过期，请从学习中心重新打开。")
    if runtime.get("expired"):
        raise FlowError("这张卡片已过期，请使用今天新发送的卡片。")
    if runtime.get("completed"):
        raise FlowError("Session is already complete")
    if runtime["current_index"] >= len(runtime["queue"]):
        raise FlowError("No current item")
    expected_turn = turn_id(session)
    if turn != expected_turn:
        raise FlowError("This card is no longer active")
    entry = runtime["queue"][runtime["current_index"]]
    if entry["id"] != item_id:
        raise FlowError("Card item does not match current item")
    bank = daily.load_bank()
    item = get_item(bank, item_id)

    if action == "reveal":
        try:
            ensure_audio_keys(session, only_item_id=item_id)
        except FlowError as exc:
            print("答案音频上传暂未成功：{}".format(exc), file=sys.stderr)
        runtime["page"] = "answer"
        save_session(session)
        return {
            "toast": {"type": "info", "content": "答案已显示"},
            "card": build_answer_card(session),
            "schedule_next": False,
        }

    if action != "rate" or rating not in RATINGS:
        raise FlowError("Unsupported callback action")

    action_key = "{}:{}".format(turn, rating)
    if action_key in runtime.get("processed_actions", []):
        return {
            "toast": {"type": "info", "content": "这条反馈已经记录过了"},
            "schedule_next": False,
        }

    target_date = daily.parse_date(session["date"])
    due_on = apply_rating(session, entry, rating, target_date)
    runtime.setdefault("rating_counts", {"会": 0, "模糊": 0, "不会": 0})
    runtime["rating_counts"][rating] = runtime["rating_counts"].get(rating, 0) + 1
    runtime.setdefault("processed_actions", []).append(action_key)

    if rating == "不会" and not entry.get("is_retry"):
        retry_entry = dict(entry)
        retry_entry["attempt"] = int(entry.get("attempt", 1)) + 1
        retry_entry["is_retry"] = True
        runtime["queue"].append(retry_entry)

    runtime["current_index"] = int(runtime["current_index"]) + 1
    runtime["next_ready"] = True
    runtime["page"] = "feedback"
    save_session(session)
    refresh_hub_async()
    return {
        "toast": {"type": "success", "content": "已记录：{}".format(rating)},
        "card": feedback_card(session, item, rating, due_on),
        "schedule_next": True,
        "delay_ms": 1100,
    }


def scene_label(scene: str) -> str:
    return {
        "morning": "早晨",
        "meals": "吃饭",
        "learning": "学习",
        "chores": "家务",
        "safety": "安全",
        "emotions": "情绪沟通",
        "outdoors": "外出",
        "bedtime": "睡前",
        "family": "家庭沟通",
    }.get(scene, scene)


def run(target_date: date) -> int:
    expired = expire_previous_sessions(target_date)
    if expired:
        print("已过期旧会话：{} 个".format(expired))
    session = find_resumable_session(target_date) or build_session(target_date)
    result = send_next(session, force=False)
    if result == "waiting_for_answer":
        print("当前题目等待作答，未重复发送。")
    elif result == "completed":
        print("今日学习已经完成。")
    else:
        print("已发送卡片：{}".format(result))
    return 0


def resume_pending(target_date: Optional[date] = None) -> int:
    session = find_resumable_session(target_date or date.today())
    if not session:
        print("no active session")
        return 0
    runtime = session["runtime"]
    if not runtime.get("next_ready", False):
        print("waiting_for_answer")
        return 0
    result = send_next(session, force=False)
    print(result)
    return 0


def open_session(target_date: date) -> int:
    """Open or resume the current English card as a fresh message."""
    session = find_resumable_session(target_date) or build_session(target_date)
    session["view_id"] = int(session.get("view_id", 1)) + 1
    runtime = session["runtime"]

    if runtime.get("completed") or runtime["current_index"] >= len(runtime["queue"]):
        runtime["completed"] = True
        runtime["page"] = "summary"
        message_id = send_card(session, summary_card(session))
        runtime["summary_message_id"] = message_id
        save_session(session)
        refresh_hub_async()
        print(message_id)
        return 0

    entry = runtime["queue"][runtime["current_index"]]
    if runtime.get("page") == "answer" and runtime.get("current_item_id") == entry["id"]:
        message_id = send_card(session, build_answer_card(session))
        runtime["current_message_id"] = message_id
        runtime["next_ready"] = False
        save_session(session)
        refresh_hub_async()
        print(message_id)
        return 0

    try:
        ensure_audio_keys(session, only_item_id=entry["id"])
    except FlowError as exc:
        print("当前题音频上传暂未成功，先发送文字卡片：{}".format(exc), file=sys.stderr)
    message_id = send_card(session, build_question_card(session))
    runtime["current_item_id"] = entry["id"]
    runtime["current_message_id"] = message_id
    runtime["next_ready"] = False
    runtime["page"] = "question"
    session["delivery"] = {
        "status": "in_progress",
        "message_id": message_id,
        "sent_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    state = migrate_state()
    state["items"][entry["id"]]["last_delivered_on"] = session["date"]
    daily.write_json(daily.STATE_PATH, state)
    save_session(session)
    start_audio_preload(session)
    refresh_hub_async()
    print(message_id)
    return 0


def invalidate_session(target_date: date) -> int:
    path = session_path(target_date)
    if not path.exists():
        print("no active session")
        return 0
    session = load_session(target_date)
    session["view_id"] = int(session.get("view_id", 1)) + 1
    save_session(session)
    print("invalidated")
    return 0


def status() -> int:
    state = migrate_state()
    today = date.today()
    due = 0
    scheduled = 0
    for item_state in state["items"].values():
        due_on = item_state.get("due_on")
        if not due_on:
            continue
        due_date = daily.parse_date(due_on)
        if due_date <= today:
            due += 1
        else:
            scheduled += 1
    active = find_resumable_session(today)
    print("已学习条目：{}".format(len(state["items"])))
    print("当前到期：{}".format(due))
    print("未来已排期：{}".format(scheduled))
    print("语料库剩余：{}".format(len(daily.load_bank()) - len(state["items"])))
    print("进行中会话：{}".format(active["date"] if active else "无"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "send-next", "preload-audio", "resume-pending", "open", "invalidate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--date", help="Session date in YYYY-MM-DD")
    callback = subparsers.add_parser("callback")
    callback.add_argument("--date", required=True)
    callback.add_argument("--item-id", required=True)
    callback.add_argument("--action", required=True, choices=["reveal", "rate"])
    callback.add_argument("--turn", required=True)
    callback.add_argument("--rating", default="")
    callback.add_argument("--view-id", type=int)
    subparsers.add_parser("status")
    args = parser.parse_args()

    try:
        if args.command == "status":
            return status()
        if args.command == "run":
            return run(daily.parse_date(args.date))
        if args.command == "send-next":
            session = load_session(daily.parse_date(args.date))
            result = send_next(session, force=False)
            print(result)
            return 0
        if args.command == "preload-audio":
            session = load_session(daily.parse_date(args.date))
            ensure_audio_keys(session)
            print("audio preload complete")
            return 0
        if args.command == "resume-pending":
            target = daily.parse_date(args.date) if args.date else date.today()
            return resume_pending(target)
        if args.command == "open":
            return open_session(daily.parse_date(args.date))
        if args.command == "invalidate":
            return invalidate_session(daily.parse_date(args.date))
        session = load_session(daily.parse_date(args.date))
        result = callback_card(
            session,
            args.item_id,
            args.action,
            args.turn,
            args.rating,
            args.view_id,
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (FlowError, daily.DailyError, feishu.FeishuError) as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
