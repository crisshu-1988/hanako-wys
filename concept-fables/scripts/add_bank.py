#!/usr/bin/env python3
"""Validate and merge a generated concept-fable batch into the private bank."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
USER_BANK = CODEX_HOME / "concept-fables" / "bank.json"
SEED_BANK = SKILL_ROOT / "data" / "seed_bank.json"
DOMAINS = {"ai_agent", "household_economics", "child_development"}
REQUIRED = {
    "id", "domain", "domain_label", "concept", "title", "story", "question",
    "options", "definition", "mapping", "application", "talk_track", "source",
}


class BankError(RuntimeError):
    pass


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_item(item: dict, known_ids: set[str]) -> None:
    missing = REQUIRED.difference(item)
    if missing:
        raise BankError("{} 缺少字段：{}".format(item.get("id", "未命名条目"), sorted(missing)))
    if item["id"] in known_ids:
        raise BankError("重复 id：{}".format(item["id"]))
    if item["domain"] not in DOMAINS:
        raise BankError("{} 的领域无效".format(item["id"]))
    if not 700 <= len(item["story"]) <= 1200:
        raise BankError("{} 的故事长度为 {}，应在 700-1200 字".format(item["id"], len(item["story"])))
    if item["concept"].lower() in item["story"].lower() or item["concept"].lower() in item["title"].lower():
        raise BankError("{} 在故事或标题中泄露了概念名".format(item["id"]))
    options = item["options"]
    if len(options) != 4:
        raise BankError("{} 必须有四个选项".format(item["id"]))
    if sum(1 for option in options if option.get("correct")) != 1:
        raise BankError("{} 必须且只能有一个正确选项".format(item["id"]))
    if len({option.get("id") for option in options}) != 4:
        raise BankError("{} 的选项 id 必须唯一".format(item["id"]))
    if not isinstance(item["mapping"], list) or not item["mapping"]:
        raise BankError("{} 缺少故事映射".format(item["id"]))
    for field in ("definition", "application", "talk_track", "source"):
        if not str(item.get(field, "")).strip():
            raise BankError("{} 的 {} 不能为空".format(item["id"], field))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="JSON file containing an items array")
    args = parser.parse_args()
    try:
        incoming = read_json(Path(args.file).expanduser())
        additions = incoming.get("items", []) if isinstance(incoming, dict) else []
        if not additions:
            raise BankError("待合并文件中没有 items")
        if not USER_BANK.exists():
            USER_BANK.parent.mkdir(parents=True, exist_ok=True)
            USER_BANK.write_bytes(SEED_BANK.read_bytes())
        bank = read_json(USER_BANK)
        known_ids = {item["id"] for item in bank.get("items", [])}
        for item in additions:
            validate_item(item, known_ids)
            known_ids.add(item["id"])
            bank.setdefault("items", []).append(item)
        write_json(USER_BANK, bank)
        print("已合并 {} 篇，内容库共 {} 篇。".format(len(additions), len(bank["items"])))
        return 0
    except (OSError, json.JSONDecodeError, BankError) as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
