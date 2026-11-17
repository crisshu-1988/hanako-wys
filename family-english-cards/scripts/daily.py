#!/usr/bin/env python3
"""Build, review, and deliver the Family English Cards daily session."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
import feishu  # noqa: E402

BANK_PATH = SKILL_ROOT / "data" / "family_core.json"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
USER_DATA_DIR = CODEX_HOME / "family-english-cards"
CONFIG_PATH = USER_DATA_DIR / "config.json"
STATE_PATH = USER_DATA_DIR / "state.json"
SESSION_DIR = USER_DATA_DIR / "sessions"
AUDIO_DIR = USER_DATA_DIR / "audio"
LOG_DIR = USER_DATA_DIR / "logs"
DEFAULT_OFFSETS = [1, 3, 7, 14, 30]


class DailyError(RuntimeError):
    pass


def ensure_dirs() -> None:
    for path in (USER_DATA_DIR, SESSION_DIR, AUDIO_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Optional[dict] = None) -> dict:
    if not path.exists():
        return default if default is not None else {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def load_config(required: bool = False) -> dict:
    config = load_json(CONFIG_PATH, {})
    if config:
        return config
    if required:
        raise DailyError(
            "Feishu is not configured. Run: python3 {} configure".format(Path(__file__).name)
        )
    return {
        "mode": "feishu_app",
        "voice": "Samantha",
        "rate": 165,
        "new_items_per_day": 10,
        "review_offsets_days": DEFAULT_OFFSETS,
    }


def parse_date(value: Optional[str]) -> date:
    if not value:
        return date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise DailyError("Date must use YYYY-MM-DD") from exc


def load_bank() -> Dict[str, dict]:
    bank = load_json(BANK_PATH)
    items = bank.get("items", [])
    required = {
        "id",
        "phrase",
        "ipa",
        "zh",
        "example",
        "example_zh",
        "scene",
        "level",
        "tags",
    }
    result: Dict[str, dict] = {}
    for item in items:
        missing = required.difference(item)
        if missing:
            raise DailyError("{} is missing: {}".format(item.get("id", "item"), sorted(missing)))
        if item["id"] in result:
            raise DailyError("Duplicate bank id: {}".format(item["id"]))
        result[item["id"]] = item
    return result


def default_state() -> dict:
    return {"version": 1, "items": {}}


def due_tokens(item_state: dict, offsets: Iterable[int], today: date) -> List[str]:
    introduced = item_state.get("introduced_on")
    if not introduced:
        return []
    introduced_date = parse_date(introduced)
    delivered = set(item_state.get("delivered_tokens", []))
    tokens: List[str] = []
    for offset in offsets:
        token = "base:{}".format(offset)
        due_date = introduced_date + timedelta(days=offset)
        if due_date <= today and token not in delivered:
            tokens.append(token)
    for extra in item_state.get("extra_reviews", []):
        token = "extra:{}".format(extra)
        if parse_date(extra) <= today and token not in delivered:
            tokens.append(token)
    return tokens


def next_due_date(item_state: dict, offsets: Iterable[int]) -> Optional[str]:
    introduced = item_state.get("introduced_on")
    if not introduced:
        return None
    introduced_date = parse_date(introduced)
    delivered = set(item_state.get("delivered_tokens", []))
    candidates: List[date] = []
    for offset in offsets:
        if "base:{}".format(offset) not in delivered:
            candidates.append(introduced_date + timedelta(days=offset))
    for extra in item_state.get("extra_reviews", []):
        if "extra:{}".format(extra) not in delivered:
            candidates.append(parse_date(extra))
    return min(candidates).isoformat() if candidates else None


def build_session(target_date: date) -> dict:
    ensure_dirs()
    config = load_config()
    bank = load_bank()
    state = load_json(STATE_PATH, default_state())
    state.setdefault("items", {})
    offsets = [int(value) for value in config.get("review_offsets_days", DEFAULT_OFFSETS)]
    new_count = int(config.get("new_items_per_day", 10))
    session_path = SESSION_DIR / "{}.json".format(target_date.isoformat())

    if session_path.exists():
        return load_json(session_path)

    due_items: List[Tuple[str, dict, List[str]]] = []
    for item_id, item in bank.items():
        item_state = state["items"].get(item_id)
        if not item_state:
            continue
        tokens = due_tokens(item_state, offsets, target_date)
        if tokens:
            due_items.append((item_id, item, tokens))
    due_items.sort(key=lambda entry: entry[0])

    new_items: List[dict] = []
    for item_id, item in bank.items():
        if item_id in state["items"]:
            continue
        new_items.append(item)
        if len(new_items) >= new_count:
            break

    session_items: List[dict] = []
    for item_id, item, tokens in due_items:
        session_items.append(
            {
                "id": item_id,
                "kind": "review",
                "review_tokens": tokens,
                "phrase": item["phrase"],
                "ipa": item["ipa"],
                "zh": item["zh"],
                "example": item["example"],
                "example_zh": item["example_zh"],
                "scene": item["scene"],
                "level": item["level"],
                "tags": item["tags"],
            }
        )
        state["items"][item_id].setdefault("delivered_tokens", []).extend(tokens)
        state["items"][item_id]["last_delivered_on"] = target_date.isoformat()

    for item in new_items:
        session_items.append(
            {
                "id": item["id"],
                "kind": "new",
                "review_tokens": [],
                "phrase": item["phrase"],
                "ipa": item["ipa"],
                "zh": item["zh"],
                "example": item["example"],
                "example_zh": item["example_zh"],
                "scene": item["scene"],
                "level": item["level"],
                "tags": item["tags"],
            }
        )
        state["items"][item["id"]] = {
            "introduced_on": target_date.isoformat(),
            "delivered_tokens": [],
            "extra_reviews": [],
            "ratings": [],
            "last_delivered_on": target_date.isoformat(),
        }

    if not session_items:
        raise DailyError("No new or due items are available")

    session = {
        "version": 1,
        "date": target_date.isoformat(),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_count": len(due_items),
        "new_count": len(new_items),
        "items": session_items,
        "audio": {},
        "delivery": {"status": "not_sent"},
    }

    if not config.get("skip_audio", False):
        audio_map = generate_session_audio(session, config)
        session["audio"] = audio_map

    write_json(session_path, session)
    write_session_markdown(session)
    write_json(STATE_PATH, state)
    return session


def find_ffmpeg() -> Optional[str]:
    candidates = [
        SKILL_ROOT / "vendor" / "evermeet" / "ffmpeg",
        SKILL_ROOT / "vendor" / "node_modules" / "ffmpeg-static" / "ffmpeg",
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("ffmpeg")


def audio_duration_ms(aiff_path: Path) -> int:
    afinfo = shutil.which("afinfo")
    if afinfo:
        result = subprocess.run([afinfo, str(aiff_path)], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if "estimated duration:" in line:
                value = line.split("estimated duration:", 1)[1].strip().split()[0]
                try:
                    return max(1, int(float(value) * 1000))
                except ValueError:
                    pass
    fallback = max(1, int(aiff_path.stat().st_size / 32))
    return fallback


def generate_session_audio(session: dict, config: dict) -> Dict[str, dict]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise DailyError(
            "ffmpeg is required for OPUS audio. Run npm install in the skill vendor directory."
        )
    voice = config.get("voice", "Samantha")
    rate = str(config.get("rate", 165))
    day_audio_dir = AUDIO_DIR / session["date"]
    day_audio_dir.mkdir(parents=True, exist_ok=True)
    audio_map: Dict[str, dict] = {}
    for index, item in enumerate(session["items"], start=1):
        item_id = item["id"]
        opus_path = day_audio_dir / "{:02d}-{}.opus".format(index, item_id)
        if not opus_path.exists():
            aiff_path = day_audio_dir / "{:02d}-{}.aiff".format(index, item_id)
            spoken = "{} ... {}".format(item["phrase"], item["example"])
            say = shutil.which("say")
            if not say:
                raise DailyError("macOS say command is required for audio generation")
            subprocess.run(
                [say, "-v", voice, "-r", rate, "-o", str(aiff_path), spoken],
                check=True,
            )
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(aiff_path),
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "32k",
                    "-ar",
                    "48000",
                    "-ac",
                    "1",
                    str(opus_path),
                ],
                check=True,
            )
            try:
                aiff_path.unlink()
            except FileNotFoundError:
                pass
        audio_map[item_id] = {
            "path": str(opus_path),
            "duration_ms": audio_duration_ms(opus_path)
            if opus_path.suffix == ".aiff"
            else ffmpeg_duration_ms(ffmpeg, opus_path),
        }
    return audio_map


def ffmpeg_duration_ms(ffmpeg: str, audio_path: Path) -> int:
    result = subprocess.run(
        [ffmpeg, "-i", str(audio_path)], capture_output=True, text=True
    )
    for line in result.stderr.splitlines():
        marker = "Duration: "
        if marker not in line:
            continue
        value = line.split(marker, 1)[1].split(",", 1)[0].strip()
        try:
            parts = value.split(":")
            seconds = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            return max(1, int(seconds * 1000))
        except (ValueError, IndexError):
            pass
    return max(1, int(audio_path.stat().st_size / 4))


def render_markdown(session: dict) -> str:
    lines = [
        "# Family English Cards · {}".format(session["date"]),
        "",
        "先看中文，试着开口说出英文；然后展开答案核对。",
        "",
        "> 今日新词：{}　到期复习：{}".format(session["new_count"], session["review_count"]),
        "",
    ]
    for index, item in enumerate(session["items"], start=1):
        label = "新词" if item["kind"] == "new" else "复习"
        lines.extend(
            [
                "## {}. [{}] {}".format(index, label, item["zh"]),
                "",
                "- **英文：** {}".format(item["phrase"]),
                "- **音标：** {}".format(item["ipa"]),
                "- **例句：** {}".format(item["example"]),
                "- **翻译：** {}".format(item["example_zh"]),
            ]
        )
        audio = session.get("audio", {}).get(item["id"])
        if audio:
            lines.append("- **音频：** `{}`".format(audio["path"]))
        lines.append("")
    lines.extend(
        [
            "## 今天的主动使用任务",
            "",
            "从今天的表达中选 3 句，在真实亲子沟通中使用一次。",
            "",
        ]
    )
    return "\n".join(lines)


def write_session_markdown(session: dict) -> Path:
    path = SESSION_DIR / "{}.md".format(session["date"])
    path.write_text(render_markdown(session), encoding="utf-8")
    return path


def build_feishu_card(session: dict, audio_keys: Dict[str, str]) -> dict:
    panels = []
    for index, item in enumerate(session["items"], start=1):
        label = "新词" if item["kind"] == "new" else "复习"
        panels.append(
            {
                "tag": "collapsible_panel",
                "expanded": False,
                "header": {
                    "title": {
                        "tag": "markdown",
                        "content": "**{}. [{}] {}**".format(index, label, item["zh"]),
                    }
                },
                "border": {"color": "grey", "corner_radius": "6px"},
                "padding": "8px 8px 8px 8px",
                "vertical_spacing": "6px",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": "**{}**  \n{}".format(item["phrase"], item["ipa"]),
                    },
                    {
                        "tag": "markdown",
                        "content": "_{}_  \n{}".format(item["example"], item["example_zh"]),
                    },
                ],
            }
        )
        audio_key = audio_keys.get(item["id"])
        if audio_key:
            panels[-1]["elements"].append(
                {
                    "tag": "audio",
                    "file_key": audio_key,
                    "audio_id": item["id"],
                    "show_progress_bar": True,
                    "show_time": True,
                    "time_display": "default",
                    "time_position": "end",
                    "style": "flat",
                    "width": "fill",
                }
            )
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "enable_forward": False},
        "header": {
            "template": "blue",
            "title": {
                "tag": "plain_text",
                "content": "亲子英语 · {}".format(session["date"]),
            },
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": "先看中文，自己说出英文，再展开核对。今天新词 **{}** 个，到期复习 **{}** 个。".format(
                        session["new_count"], session["review_count"]
                    ),
                }
            ]
            + panels
            + [
                {
                    "tag": "markdown",
                    "content": "**主动使用：** 选 3 句，今天和孩子真实说一遍。",
                }
            ]
        },
    }


def push_session(session: dict, allow_text_only: bool = False) -> dict:
    config = load_config(required=True)
    mode = config.get("mode", "feishu_app")
    uploaded: Dict[str, str] = {}
    audio_map = session.get("audio", {})

    if mode == "feishu_app":
        missing = [item["id"] for item in session["items"] if item["id"] not in audio_map]
        if missing and not allow_text_only:
            raise DailyError("Missing audio for: {}".format(", ".join(missing)))
        token = feishu.get_tenant_access_token(config["app_id"], config["app_secret"])
        for item in session["items"]:
            metadata = audio_map.get(item["id"])
            if not metadata:
                continue
            uploaded[item["id"]] = feishu.upload_opus(
                token,
                Path(metadata["path"]),
                int(metadata["duration_ms"]),
            )
        card = build_feishu_card(session, uploaded)
        result = feishu.send_via_app(
            token,
            config.get("receive_id_type", "chat_id"),
            config["receive_id"],
            card,
        )
    else:
        card = build_feishu_card(session, {})
        result = feishu.send_card(config, card, uploaded)

    session_path = SESSION_DIR / "{}.json".format(session["date"])
    session = load_json(session_path)
    session["delivery"] = {
        "status": "sent",
        "mode": mode,
        "sent_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "message_id": result.get("data", {}).get("message_id", ""),
        "audio_count": len(uploaded),
    }
    write_json(session_path, session)
    return result


def record_review(item_id: str, rating: str, target_date: date) -> None:
    allowed = {"认识", "模糊", "不认识"}
    if rating not in allowed:
        raise DailyError("Rating must be one of: {}".format(", ".join(sorted(allowed))))
    state = load_json(STATE_PATH, default_state())
    item_state = state.get("items", {}).get(item_id)
    if not item_state:
        raise DailyError("Unknown or not-yet-introduced item: {}".format(item_id))
    item_state.setdefault("ratings", []).append(
        {"date": target_date.isoformat(), "rating": rating}
    )
    if rating == "模糊":
        extra = target_date + timedelta(days=1)
        item_state.setdefault("extra_reviews", []).append(extra.isoformat())
    elif rating == "不认识":
        for days in (1, 3):
            extra = target_date + timedelta(days=days)
            item_state.setdefault("extra_reviews", []).append(extra.isoformat())
    write_json(STATE_PATH, state)


def configure() -> None:
    ensure_dirs()
    print("推荐使用飞书自建应用机器人，这样才能在卡片中播放音频。")
    print("请先在飞书开放平台创建应用并启用机器人，详见 references/feishu-setup.md。")
    mode_input = input("配置类型 [1=自建应用, 2=群Webhook纯文字] (默认 1): ").strip() or "1"
    if mode_input == "2":
        webhook_url = input("飞书群机器人 Webhook: ").strip()
        webhook_secret = getpass.getpass("签名密钥（没有直接回车）: ").strip()
        config = {
            "mode": "feishu_webhook",
            "webhook_url": webhook_url,
            "webhook_secret": webhook_secret,
            "voice": "Samantha",
            "rate": 165,
            "new_items_per_day": 10,
            "review_offsets_days": DEFAULT_OFFSETS,
        }
    else:
        app_id = input("App ID: ").strip()
        app_secret = getpass.getpass("App Secret（不会显示）: ").strip()
        receive_id = ""
        try:
            token = feishu.get_tenant_access_token(app_id, app_secret)
            chats = feishu.list_chats(token)
            if chats:
                print("机器人所在群聊：")
                for index, chat in enumerate(chats, start=1):
                    print("  {}. {}  {}".format(index, chat.get("name", "未命名"), chat.get("chat_id", "")))
                choice = input("选择群聊序号，或直接粘贴 chat_id: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(chats):
                    receive_id = chats[int(choice) - 1]["chat_id"]
                elif choice:
                    receive_id = choice
        except feishu.FeishuError as exc:
            print("无法自动读取群聊，可稍后手动填写 chat_id。原因：{}".format(exc))
        if not receive_id:
            receive_id = input("接收群 chat_id（必须以 oc_ 开头）: ").strip()
        config = {
            "mode": "feishu_app",
            "app_id": app_id,
            "app_secret": app_secret,
            "receive_id_type": "chat_id",
            "receive_id": receive_id,
            "voice": "Samantha",
            "rate": 165,
            "new_items_per_day": 10,
            "review_offsets_days": DEFAULT_OFFSETS,
        }
    write_json(CONFIG_PATH, config)
    os.chmod(CONFIG_PATH, 0o600)
    print("配置已保存到 {}".format(CONFIG_PATH))


def show_status() -> None:
    state = load_json(STATE_PATH, default_state())
    config = load_config()
    offsets = config.get("review_offsets_days", DEFAULT_OFFSETS)
    introduced = state.get("items", {})
    due = 0
    for item_state in introduced.values():
        if due_tokens(item_state, offsets, date.today()):
            due += 1
    remaining = len(load_bank()) - len(introduced)
    latest_session = sorted(SESSION_DIR.glob("*.json"))[-1] if SESSION_DIR.exists() else None
    print("已学习条目：{}".format(len(introduced)))
    print("当前到期：{}".format(due))
    print("语料库剩余：{}".format(remaining))
    print("配置：{}".format(config.get("mode", "未配置")))
    print("最近会话：{}".format(latest_session if latest_session else "无"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "run"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--date", help="Session date in YYYY-MM-DD")
        subparser.add_argument("--no-audio", action="store_true")
        if command == "run":
            subparser.add_argument("--allow-text-only", action="store_true")
            subparser.add_argument("--force", action="store_true")
    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("item_id")
    review_parser.add_argument("rating", choices=["认识", "模糊", "不认识"])
    review_parser.add_argument("--date", help="Review date in YYYY-MM-DD")
    subparsers.add_parser("configure")
    subparsers.add_parser("status")
    args = parser.parse_args()

    try:
        if args.command == "configure":
            configure()
            return 0
        if args.command == "status":
            show_status()
            return 0
        if args.command == "review":
            record_review(args.item_id, args.rating, parse_date(args.date))
            print("已记录：{} {}".format(args.item_id, args.rating))
            return 0

        config = load_config()
        if args.no_audio:
            config["skip_audio"] = True
        session = build_session(parse_date(args.date))
        print("会话：{}".format(SESSION_DIR / "{}.json".format(session["date"])))
        print("Markdown：{}".format(SESSION_DIR / "{}.md".format(session["date"])))
        print("新词 {}，复习 {}".format(session["new_count"], session["review_count"]))
        if args.command == "run":
            if session.get("delivery", {}).get("status") == "sent" and not args.force:
                print("今日卡片已经发送，跳过重复推送。")
                return 0
            result = push_session(session, allow_text_only=args.allow_text_only)
            print("飞书已发送：{}".format(result.get("data", {}).get("message_id", "success")))
        return 0
    except (DailyError, feishu.FeishuError, subprocess.CalledProcessError) as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
