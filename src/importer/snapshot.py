# -*- coding: utf-8 -*-
"""快照文件读取：把用户从浏览器拿到的文件变成实体行。

支持三种输入（按内容自动识别）：

1. ``mgg-http-capture``（油猴脚本下载，**主路径**）::

       {"format": "mgg-http-capture", "version": 1, "captured_at": ...,
        "request": {"method": "GET", "url": ".../api/data/user", "status": 200},
        "headers": {"x-client-version": "77", ...},
        "body_b64": "<原始响应字节>"}

2. ``mgg-user-snapshot``（已解码的实体行，便于调试/回归）::

       {"format": "mgg-user-snapshot", "version": 1, "entities": {"40": [[...], ...]}}

3. DevTools 导出的 ``.har``（兜底）：取 ``/api/data/user`` 条目的
   ``response.content.text``（HAR 对二进制强制 base64）。

裸二进制响应也可以直接丢进来（按 msgpack 流尝试解码）。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import wire

__all__ = [
    "SnapshotError",
    "LoadedSnapshot",
    "load",
    "FORMAT_HTTP",
    "FORMAT_SNAPSHOT",
    "SUPPORTED_VERSIONS",
]

FORMAT_HTTP = "mgg-http-capture"
FORMAT_SNAPSHOT = "mgg-user-snapshot"
SUPPORTED_VERSIONS = {1}
TARGET_PATH = "/api/data/user"


class SnapshotError(ValueError):
    """快照文件损坏、格式未知或版本过高。"""


@dataclass
class LoadedSnapshot:
    rows: List[Tuple[int, Sequence]]
    source_name: str
    sha256: str
    captured_at: Optional[str] = None
    client_version: Optional[str] = None
    source_url: Optional[str] = None
    raw_bytes: int = 0
    extra: Dict[str, object] = field(default_factory=dict)


def _header(headers: dict, name: str) -> Optional[str]:
    if not isinstance(headers, dict):
        return None
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return value if isinstance(value, str) else None
    return None


def _check_version(doc: dict, fmt: str) -> None:
    version = doc.get("version", 1)
    if not isinstance(version, int) or version not in SUPPORTED_VERSIONS:
        raise SnapshotError(f"不支持的快照版本 {version!r}（{fmt}），请升级模拟器")


def _rows_from_http_capture(doc: dict, result: LoadedSnapshot) -> List[Tuple[int, Sequence]]:
    _check_version(doc, FORMAT_HTTP)
    body = doc.get("body_b64")
    if not isinstance(body, str) or not body:
        raise SnapshotError("快照缺少 body_b64（响应体为空）")
    try:
        raw = base64.b64decode(body, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise SnapshotError(f"body_b64 不是合法 base64：{exc}") from exc
    if not raw:
        raise SnapshotError("body_b64 解码后为空")

    request = doc.get("request") or {}
    result.source_url = request.get("url")
    result.captured_at = doc.get("captured_at")
    result.client_version = _header(doc.get("headers") or {}, "x-client-version")
    result.extra["wire_bytes"] = len(raw)
    try:
        return wire.extract_rows(raw)
    except wire.WireError as exc:
        raise SnapshotError(f"响应体不是合法的 msgpack/KMS 数据：{exc}") from exc


def _rows_from_snapshot(doc: dict, result: LoadedSnapshot) -> List[Tuple[int, Sequence]]:
    _check_version(doc, FORMAT_SNAPSHOT)
    entities = doc.get("entities")
    if not isinstance(entities, dict) or not entities:
        raise SnapshotError("快照缺少 entities")
    rows: List[Tuple[int, Sequence]] = []
    for key, values in entities.items():
        try:
            type_id = int(key)
        except (TypeError, ValueError) as exc:
            raise SnapshotError(f"entities 的键不是 typeId：{key!r}") from exc
        if not isinstance(values, list):
            raise SnapshotError(f"entities[{key}] 不是数组")
        for fields in values:
            if isinstance(fields, list):
                rows.append((type_id, fields))
    if not rows:
        raise SnapshotError("快照里没有实体行")
    result.captured_at = doc.get("captured_at")
    result.client_version = doc.get("client_version")
    result.source_url = doc.get("source_url")
    return rows


def _rows_from_har(doc: dict, result: LoadedSnapshot) -> List[Tuple[int, Sequence]]:
    entries = ((doc.get("log") or {}).get("entries")) or []
    candidates = [
        entry for entry in entries
        if TARGET_PATH in str((entry.get("request") or {}).get("url") or "")
    ]
    if not candidates:
        raise SnapshotError(f"HAR 里没有 {TARGET_PATH} 请求（请确认导出时勾选了 content）")
    entry = candidates[-1]
    content = (entry.get("response") or {}).get("content") or {}
    text = content.get("text")
    if not text:
        raise SnapshotError("HAR 条目没有响应体（导出时未包含 content）")
    if content.get("encoding") == "base64":
        try:
            raw = base64.b64decode(text, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise SnapshotError(f"HAR 响应体 base64 解码失败：{exc}") from exc
    else:
        raise SnapshotError("HAR 响应体不是 base64 编码，无法还原二进制（请用浏览器导出含 content 的 HAR）")

    result.source_url = (entry.get("request") or {}).get("url")
    result.captured_at = entry.get("startedDateTime")
    result.client_version = _header(
        {h.get("name"): h.get("value") for h in ((entry.get("request") or {}).get("headers") or [])
         if isinstance(h, dict)},
        "x-client-version",
    )
    result.extra["wire_bytes"] = len(raw)
    try:
        return wire.extract_rows(raw)
    except wire.WireError as exc:
        raise SnapshotError(f"HAR 响应体不是合法的 msgpack/KMS 数据：{exc}") from exc


def load(path) -> LoadedSnapshot:
    """读取快照文件（自动识别格式），返回实体行与元信息。"""
    path = Path(path)
    if not path.is_file():
        raise SnapshotError(f"文件不存在：{path}")
    raw = path.read_bytes()
    if not raw:
        raise SnapshotError(f"文件为空：{path.name}")

    result = LoadedSnapshot(
        rows=[],
        source_name=path.name,
        sha256=hashlib.sha256(raw).hexdigest(),
        raw_bytes=len(raw),
    )

    doc = None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        doc = None

    if isinstance(doc, dict) and doc.get("format") == FORMAT_HTTP:
        result.rows = _rows_from_http_capture(doc, result)
    elif isinstance(doc, dict) and doc.get("format") == FORMAT_SNAPSHOT:
        result.rows = _rows_from_snapshot(doc, result)
    elif isinstance(doc, dict) and isinstance(doc.get("log"), dict):
        result.rows = _rows_from_har(doc, result)
    elif doc is None:
        # 裸二进制：直接当 msgpack/KMS 响应解
        try:
            result.rows = wire.extract_rows(raw)
        except wire.WireError as exc:
            raise SnapshotError(
                "无法识别的文件：既不是 JSON 快照，也不是合法的 msgpack 响应"
            ) from exc
        result.extra["wire_bytes"] = len(raw)
    else:
        raise SnapshotError(
            "无法识别的 JSON：缺少 format 字段（期望 mgg-http-capture / mgg-user-snapshot / HAR）"
        )

    if not result.rows:
        raise SnapshotError("解析成功但没有实体行（快照可能不完整）")
    return result
