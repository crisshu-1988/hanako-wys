#!/usr/bin/env python3
"""Install and inspect the macOS 22:00 Family English Cards schedule."""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DAILY_SCRIPT = SCRIPT_DIR / "flow.py"
LISTENER_SCRIPT = SCRIPT_DIR / "interactive_bot.js"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
LOG_DIR = CODEX_HOME / "family-english-cards" / "logs"
LABEL = "com.shujianda.family-english-cards"
LISTENER_LABEL = "com.shujianda.family-english-cards-listener"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")
LISTENER_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / (LISTENER_LABEL + ".plist")


def launchctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=check)


def plist_data() -> dict:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node is required for Feishu audio uploads")
    node_path = "{}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin".format(
        str(Path(node).parent)
    )
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(DAILY_SCRIPT), "run"],
        "WorkingDirectory": str(SKILL_ROOT),
        "EnvironmentVariables": {
            "CODEX_HOME": str(CODEX_HOME),
            "NODE_BINARY": node,
            "PATH": node_path,
        },
        "StartCalendarInterval": {"Hour": 22, "Minute": 0},
        "RunAtLoad": False,
        "ProcessType": "Background",
        "StandardOutPath": str(LOG_DIR / "launchd.out.log"),
        "StandardErrorPath": str(LOG_DIR / "launchd.err.log"),
    }


def listener_plist_data() -> dict:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node is required for the Feishu callback listener")
    node_path = "{}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin".format(
        str(Path(node).parent)
    )
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LISTENER_LABEL,
        "ProgramArguments": [node, str(LISTENER_SCRIPT)],
        "WorkingDirectory": str(SKILL_ROOT),
        "EnvironmentVariables": {
            "CODEX_HOME": str(CODEX_HOME),
            "NODE_BINARY": node,
            "PATH": node_path,
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(LOG_DIR / "listener.out.log"),
        "StandardErrorPath": str(LOG_DIR / "listener.err.log"),
    }


def _install_one(plist_path: Path, data: dict, label: str) -> int:
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as handle:
        plistlib.dump(data, handle)
    domain = "gui/{}".format(os.getuid())
    service = "{}/{}".format(domain, label)
    launchctl("bootout", service)
    result = None
    for attempt in range(3):
        result = launchctl("bootstrap", domain, str(plist_path))
        if result.returncode == 0:
            break
        if attempt < 2:
            time.sleep(1)
    if result is None or result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return result.returncode if result else 1
    launchctl("enable", service)
    return 0


def install() -> int:
    daily_result = _install_one(PLIST_PATH, plist_data(), LABEL)
    if daily_result:
        return daily_result
    listener_result = _install_one(
        LISTENER_PLIST_PATH, listener_plist_data(), LISTENER_LABEL
    )
    if listener_result:
        return listener_result
    print("已安装每日任务：{}".format(PLIST_PATH))
    print("计划：每天 22:00")
    print("已安装反馈监听：{}".format(LISTENER_PLIST_PATH))
    print("日志：{}".format(LOG_DIR))
    return 0


def _status_one(plist_path: Path, label: str) -> int:
    if not plist_path.exists():
        print("未安装：{}".format(plist_path))
        return 1
    result = launchctl("print", "gui/{}/{}".format(os.getuid(), label))
    if result.returncode != 0:
        print("{}：已写入 plist，但服务未加载。".format(label))
        return result.returncode
    print(label)
    for line in result.stdout.splitlines():
        if any(key in line for key in ("state =", "last exit code", "runs =")):
            print("  " + line.strip())
    return 0


def status() -> int:
    daily_result = _status_one(PLIST_PATH, LABEL)
    listener_result = _status_one(LISTENER_PLIST_PATH, LISTENER_LABEL)
    print("日志：{}".format(LOG_DIR))
    return daily_result or listener_result


def uninstall() -> int:
    domain = "gui/{}".format(os.getuid())
    for label, plist_path in (
        (LABEL, PLIST_PATH),
        (LISTENER_LABEL, LISTENER_PLIST_PATH),
    ):
        launchctl("bootout", "{}/{}".format(domain, label))
        if plist_path.exists():
            plist_path.unlink()
    print("已卸载定时任务和反馈监听。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "status", "uninstall"])
    args = parser.parse_args()
    if args.command == "install":
        return install()
    if args.command == "status":
        return status()
    return uninstall()


if __name__ == "__main__":
    raise SystemExit(main())
