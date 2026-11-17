#!/usr/bin/env python3
"""Feishu delivery helpers for Family English Cards."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple


FEISHU_API = "https://open.feishu.cn/open-apis"


class FeishuError(RuntimeError):
    pass


def _post_json(url: str, payload: dict, headers: Optional[dict] = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise FeishuError("Feishu HTTP {}: {}".format(exc.code, raw)) from exc
    except urllib.error.URLError as exc:
        raise FeishuError("Feishu network error: {}".format(exc)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeishuError("Feishu returned invalid JSON: {}".format(raw[:500])) from exc
    if data.get("code", 0) != 0:
        raise FeishuError("Feishu API error {}: {}".format(data.get("code"), data.get("msg")))
    return data


def _webhook_signature(secret: str) -> Tuple[str, str]:
    timestamp = str(int(time.time()))
    string_to_sign = "{}\n{}".format(timestamp, secret).encode("utf-8")
    digest = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(digest).decode("utf-8")
    return timestamp, sign


def _get_json(url: str, headers: Optional[dict] = None) -> dict:
    request_headers = {}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise FeishuError("Feishu HTTP {}: {}".format(exc.code, raw)) from exc
    except urllib.error.URLError as exc:
        raise FeishuError("Feishu network error: {}".format(exc)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeishuError("Feishu returned invalid JSON: {}".format(raw[:500])) from exc
    if data.get("code", 0) != 0:
        raise FeishuError("Feishu API error {}: {}".format(data.get("code"), data.get("msg")))
    return data


def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    data = _post_json(
        FEISHU_API + "/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
    )
    token = data.get("tenant_access_token")
    if not token:
        raise FeishuError("Feishu did not return tenant_access_token")
    return token


def list_chats(token: str, page_size: int = 100) -> List[dict]:
    url = "{}/im/v1/chats?page_size={}".format(FEISHU_API, page_size)
    data = _get_json(url, {"Authorization": "Bearer {}".format(token)})
    return data.get("data", {}).get("items", [])


def upload_opus(token: str, audio_path: Path, duration_ms: int) -> str:
    if not audio_path.is_file():
        raise FeishuError("Audio file does not exist: {}".format(audio_path))
    boundary = "----family-english-{}".format(os.urandom(12).hex())
    audio_bytes = audio_path.read_bytes()

    def field(name: str, value: str) -> bytes:
        return (
            "--{}\r\nContent-Disposition: form-data; name=\"{}\"\r\n\r\n{}\r\n".format(
                boundary, name, value
            )
        ).encode("utf-8")

    body = b"".join(
        [
            field("file_type", "opus"),
            field("file_name", audio_path.name),
            field("duration", str(duration_ms)),
            (
                "--{}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{}\"" 
                "\r\nContent-Type: application/octet-stream\r\n\r\n"
            ).format(boundary, audio_path.name).encode("utf-8"),
            audio_bytes,
            "\r\n--{}--\r\n".format(boundary).encode("utf-8"),
        ]
    )
    request = urllib.request.Request(
        FEISHU_API + "/im/v1/files",
        data=body,
        headers={
            "Authorization": "Bearer {}".format(token),
            "Content-Type": "multipart/form-data; boundary={}".format(boundary),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise FeishuError("Audio upload HTTP {}: {}".format(exc.code, raw)) from exc
    except urllib.error.URLError as exc:
        raise FeishuError("Audio upload network error: {}".format(exc)) from exc
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeishuError("Audio upload returned invalid JSON: {}".format(raw[:500])) from exc
    if result.get("code", 0) != 0:
        raise FeishuError(
            "Audio upload API error {}: {}".format(result.get("code"), result.get("msg"))
        )
    file_key = result.get("data", {}).get("file_key")
    if not file_key:
        raise FeishuError("Feishu did not return an audio file_key")
    return file_key


def send_via_app(
    token: str,
    receive_id_type: str,
    receive_id: str,
    card: dict,
    idempotency_uuid: Optional[str] = None,
) -> dict:
    url = "{}/im/v1/messages?receive_id_type={}".format(FEISHU_API, receive_id_type)
    payload = {
        "receive_id": receive_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False, separators=(",", ":")),
    }
    if idempotency_uuid:
        payload["uuid"] = idempotency_uuid[:50]
    return _post_json(url, payload, {"Authorization": "Bearer {}".format(token)})


def send_via_webhook(webhook_url: str, secret: str, card: dict) -> dict:
    payload = {"msg_type": "interactive", "card": card}
    if secret:
        timestamp, sign = _webhook_signature(secret)
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    return _post_json(webhook_url, payload)


def send_card(config: dict, card: dict, uploaded_keys: Optional[Dict[str, str]] = None) -> dict:
    mode = config.get("mode", "feishu_app")
    if mode == "feishu_webhook":
        return send_via_webhook(
            config["webhook_url"], config.get("webhook_secret", ""), card
        )
    if mode != "feishu_app":
        raise FeishuError("Unsupported Feishu mode: {}".format(mode))

    token = get_tenant_access_token(config["app_id"], config["app_secret"])
    receive_id_type = config.get("receive_id_type", "chat_id")
    return send_via_app(token, receive_id_type, config["receive_id"], card)
