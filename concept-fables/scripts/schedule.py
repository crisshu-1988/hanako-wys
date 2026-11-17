#!/usr/bin/env python3
"""Install and inspect the macOS 20:30 Concept Fables schedule."""

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
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
LOG_DIR = CODEX_HOME / "concept-fables" / "logs"
LABEL = "com.shujianda.concept-fables"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")


def launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def plist_data() -> dict:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node is required for Feishu card callbacks and audio")
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
        "StartCalendarInterval": {"Hour": 20, "Minute": 30},
        "RunAtLoad": False,
        "ProcessType": "Background",
        "StandardOutPath": str(LOG_DIR / "launchd.out.log"),
        "StandardErrorPath": str(LOG_DIR / "launchd.err.log"),
    }


def install() -> int:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_data(), handle)
    domain = "gui/{}".format(os.getuid())
    service = "{}/{}".format(domain, LABEL)
    launchctl("bootout", service)
    result = None
    for attempt in range(3):
        result = launchctl("bootstrap", domain, str(PLIST_PATH))
        if result.returncode == 0:
            break
        if attempt < 2:
            time.sleep(1)
    if result is None or result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return result.returncode if result else 1
    launchctl("enable", service)
    print("已安装概念寓言任务：{}".format(PLIST_PATH))
    print("计划：每天 20:30")
    print("日志：{}".format(LOG_DIR))
    return 0


def status() -> int:
    if not PLIST_PATH.exists():
        print("未安装：{}".format(PLIST_PATH))
        return 1
    result = launchctl("print", "gui/{}/{}".format(os.getuid(), LABEL))
    if result.returncode != 0:
        print("{}：已写入 plist，但服务未加载。".format(LABEL))
        return result.returncode
    print(LABEL)
    for line in result.stdout.splitlines():
        if any(key in line for key in ("state =", "last exit code", "runs =")):
            print("  " + line.strip())
    print("日志：{}".format(LOG_DIR))
    return 0


def uninstall() -> int:
    launchctl("bootout", "gui/{}/{}".format(os.getuid(), LABEL))
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print("已卸载概念寓言定时任务。")
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
