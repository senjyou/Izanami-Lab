# -*- coding: utf-8 -*-
"""把导入载荷合并进账号配置：合并策略、备份、原子写、审计。

设计约束（与 GUI 现有保存路径一致）：

* ``char_config.json`` 的键是角色 id（JSON 里是字符串，内存里是 int），
  值形如 ``{"override": True, "level": ..., "mod_tier_hp": ..., "gear": [...]}``。
* ``global_config.json`` 只改 ``school_levels`` / ``equipment``，其余键原样保留。
* 写入必须原子（复用 ``account_manager.atomic_write_bytes``），并在写入前备份。

本模块只依赖路径与 JSON，不 import tkinter，CLI 可直接用。
"""
from __future__ import annotations

import copy
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..utils.account_manager import atomic_write_bytes
from .map_user import ImportPayload

__all__ = [
    "ApplyOptions",
    "ApplyReport",
    "apply_payload",
    "merge_char_config",
    "merge_global_config",
    "load_current_configs",
    "read_audit",
    "CHAR_CONFIG_FILE",
    "GLOBAL_CONFIG_FILE",
    "AUDIT_FILE",
    "BACKUP_DIR",
]

CHAR_CONFIG_FILE = "char_config.json"
GLOBAL_CONFIG_FILE = "global_config.json"
AUDIT_FILE = "game_import.json"
BACKUP_DIR = "backups"
MAX_BACKUPS = 10


@dataclass
class ApplyOptions:
    school: bool = True
    equipment: bool = True
    characters: bool = True
    modules: bool = True
    gears: bool = True
    overwrite_locked: bool = False
    backup: bool = True


@dataclass
class ApplyReport:
    char_config: dict
    global_config: dict
    changed: bool = False
    stats: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    backup_dir: Optional[Path] = None


# ─────────────────────────────── 读取 ───────────────────────────────


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 损坏时退回默认模板，不要阻断导入流程
        return None
    return data if isinstance(data, dict) else None


def _default_config(data_dir: Optional[Path], name: str) -> dict:
    if data_dir:
        payload = _read_json(Path(data_dir) / f"{name}.default.json")
        if payload is not None:
            return payload
    return {}


def load_current_configs(account_dir: Path, data_dir: Optional[Path] = None) -> Tuple[dict, dict]:
    """读取账号当前配置；缺失时退回 ``data/*.default.json``。"""
    account_dir = Path(account_dir)
    char_config = _read_json(account_dir / CHAR_CONFIG_FILE)
    global_config = _read_json(account_dir / GLOBAL_CONFIG_FILE)
    if char_config is None:
        char_config = _default_config(data_dir, "char_config")
    if global_config is None:
        global_config = _default_config(data_dir, "global_config")
    return char_config, global_config


def read_audit(account_dir: Path) -> dict:
    return _read_json(Path(account_dir) / AUDIT_FILE) or {}


# ─────────────────────────────── 合并 ───────────────────────────────


def merge_global_config(
    current: dict,
    payload: ImportPayload,
    options: ApplyOptions,
) -> Tuple[dict, Dict[str, int]]:
    """覆盖学园等级、装备数值，以及「角色等级」= 游戏链接等级；其余键保持用户当前值。"""
    merged = copy.deepcopy(current)
    stats = {"school_levels": 0, "equipment": 0, "character_level": 0}

    if options.school and payload.school_levels:
        levels = dict(merged.get("school_levels") or {})
        levels.update(payload.school_levels)
        merged["school_levels"] = levels
        stats["school_levels"] = len(payload.school_levels)

    if options.equipment and payload.equipment:
        merged["equipment"] = {
            str(ct): {k: int(v) for k, v in bonuses.items()}
            for ct, bonuses in payload.equipment.items()
        }
        stats["equipment"] = len(payload.equipment)

    # 全局「角色等级」= 游戏链接等级（链接角色共享它；改全局等级时角色会跟着联动）
    if options.characters and payload.link_level:
        merged["character_level"] = int(payload.link_level)
        stats["character_level"] = int(payload.link_level)

    return merged, stats


def _find_key(config: dict, cid: int):
    if cid in config:
        return cid
    if str(cid) in config:
        return str(cid)
    return None


def _build_char_entry(
    existing: dict,
    payload_char,
    options: ApplyOptions,
) -> dict:
    entry = copy.deepcopy(existing) if existing else {"override": False}
    entry["override"] = True
    entry["level"] = payload_char.level
    entry["rarity"] = payload_char.rarity
    entry["affection"] = payload_char.affection
    entry["skill_levels"] = {str(sid): int(lv) for sid, lv in payload_char.skill_levels.items()}
    entry["skill_level"] = payload_char.skill_level
    if options.modules:
        entry["mod_tier_hp"], entry["mod_tier_atk"], entry["mod_tier_def"] = payload_char.mod_tiers
        entry["mod_level_hp"], entry["mod_level_atk"], entry["mod_level_def"] = payload_char.mod_levels
    if options.gears:
        entry["gear"] = copy.deepcopy(payload_char.gear)
    return entry


def merge_char_config(
    current: dict,
    payload: ImportPayload,
    options: ApplyOptions,
) -> Tuple[dict, Dict[str, int], List[str]]:
    """把导入结果合并进 char_config。

    未拥有角色不在 payload 里，天然不动；``locked`` 角色默认跳过。
    """
    merged = copy.deepcopy(current)
    warnings: List[str] = []
    stats = {
        "characters_updated": 0,
        "characters_locked_skipped": 0,
        "modules_updated": 0,
        "gears_updated": 0,
    }

    if not options.characters:
        return merged, stats, warnings

    for cid, payload_char in payload.characters.items():
        key = _find_key(merged, cid)
        existing = merged[key] if key is not None else {}
        if existing.get("locked") and not options.overwrite_locked:
            stats["characters_locked_skipped"] += 1
            warnings.append(f"角色 {cid} 已锁定，跳过（可在选项里允许覆盖）")
            continue
        entry = _build_char_entry(existing, payload_char, options)
        merged[cid if key is None else key] = entry
        stats["characters_updated"] += 1
        if options.modules:
            stats["modules_updated"] += 1
        if options.gears:
            stats["gears_updated"] += len(payload_char.gear)

    return merged, stats, warnings


# ─────────────────────────────── 备份 / 写入 ───────────────────────────────


def _backup(account_dir: Path) -> Optional[Path]:
    sources = [account_dir / CHAR_CONFIG_FILE, account_dir / GLOBAL_CONFIG_FILE]
    if not any(p.exists() for p in sources):
        return None
    target = account_dir / BACKUP_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    target.mkdir(parents=True, exist_ok=True)
    for path in sources:
        if path.exists():
            shutil.copy2(path, target / path.name)
    _prune_backups(account_dir / BACKUP_DIR)
    return target


def _prune_backups(backup_root: Path) -> None:
    if not backup_root.is_dir():
        return
    dirs = sorted((p for p in backup_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    for old in dirs[:-MAX_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)


def _write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    atomic_write_bytes(path, text.encode("utf-8"))


def _write_audit(
    account_dir: Path,
    payload: ImportPayload,
    options: ApplyOptions,
    report: ApplyReport,
    source_name: Optional[str],
    source_sha256: Optional[str],
) -> None:
    audit = read_audit(account_dir)
    audit["last_import"] = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "file": source_name,
        "sha256": source_sha256,
        "captured_at": payload.captured_at,
        "client_version": payload.client_version,
        "source_url": payload.source_url,
        "account": payload.account,
        "stats": report.stats,
        "options": asdict(options),
        "backup_dir": report.backup_dir.name if report.backup_dir else None,
    }
    _write_json(account_dir / AUDIT_FILE, audit)


# ─────────────────────────────── 入口 ───────────────────────────────


def apply_payload(
    account_dir: Path,
    payload: ImportPayload,
    options: Optional[ApplyOptions] = None,
    *,
    source_name: Optional[str] = None,
    source_sha256: Optional[str] = None,
    dry_run: bool = False,
    data_dir: Optional[Path] = None,
) -> ApplyReport:
    """合并 + （可选）备份并写盘。``dry_run=True`` 时只返回结果不落盘。"""
    options = options or ApplyOptions()
    account_dir = Path(account_dir)

    current_char, current_global = load_current_configs(account_dir, data_dir)
    new_char, char_stats, char_warnings = merge_char_config(current_char, payload, options)
    new_global, global_stats = merge_global_config(current_global, payload, options)

    stats = {**char_stats, **global_stats, **payload.stats}
    warnings = list(payload.warnings) + char_warnings

    char_changed = new_char != current_char
    global_changed = new_global != current_global
    report = ApplyReport(
        char_config=new_char,
        global_config=new_global,
        changed=char_changed or global_changed,
        stats=stats,
        warnings=warnings,
    )

    if dry_run or not report.changed:
        return report

    account_dir.mkdir(parents=True, exist_ok=True)
    if options.backup:
        report.backup_dir = _backup(account_dir)

    if char_changed:
        _write_json(account_dir / CHAR_CONFIG_FILE, new_char)
    if global_changed:
        _write_json(account_dir / GLOBAL_CONFIG_FILE, new_global)
    _write_audit(account_dir, payload, options, report, source_name, source_sha256)

    return report
