# -*- coding: utf-8 -*-
"""命令行入口：把抓包快照导入当前（或指定）账号。

只读演示（默认不落盘）::

    python -m src.importer.cli MGG_user_20261018_175327.mggraw.json

真正写入::

    python -m src.importer.cli <file> --apply
    python -m src.importer.cli <file> --apply --account パンダ

退出码：0 成功；1 运行期错误（账号/数据问题）；2 快照文件问题。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from ..utils.account_manager import AccountError, AccountRegistry
from . import snapshot as snapshot_mod
from .apply import ApplyOptions, apply_payload
from .lut import DEFAULT_DATA_DIR, DataIndex, LutError
from .map_user import build_payload

__all__ = ["main"]

_SCHOOL_LABELS = [
    ("physical_level", "物理"), ("en_level", "EN"), ("agility_level", "敏捷"),
    ("fire_level", "火"), ("water_level", "水"), ("wind_level", "风"),
    ("earth_level", "土"), ("light_level", "光"), ("dark_level", "暗"),
]
_CT_LABELS = {1: "物理", 2: "EN", 3: "敏捷"}


def _resolve_account_dir(registry: AccountRegistry, name: Optional[str]) -> Path:
    if name:
        return registry.get_account_dir(name)
    return registry.get_active_dir()


def _print_human(snapshot, payload, report, dry_run: bool, account_dir: Path) -> None:
    account = payload.account or {}
    print(f"快照   {snapshot.source_name}（{snapshot.raw_bytes:,} B，sha256 {snapshot.sha256[:12]}…）")
    if account:
        print(
            f"账号   {account.get('name')} / code {account.get('code')} / "
            f"world {account.get('world_master_id')} / 玩家等级 {account.get('player_rank')}"
        )
    else:
        print("账号   未知（快照里没有 User 行）")
    captured = payload.captured_at or snapshot.captured_at or "未知"
    version = payload.client_version or snapshot.client_version or "未知"
    print(f"捕获   {captured}（客户端版本 {version}）")
    print(f"实体   {payload.stats.get('entity_rows', 0):,} 行")
    print(f"目标   {account_dir}")

    school = payload.school_levels or {}
    if school:
        parts = [f"{label}{school.get(key, '-')}" for key, label in _SCHOOL_LABELS if key in school]
        print("学园   " + " ".join(parts))
    equipment = payload.equipment or {}
    if equipment:
        parts = [
            f"{_CT_LABELS.get(ct, ct)} HP{v['hp']}/ATK{v['attack']}/DEF{v['defense']}"
            for ct, v in sorted(equipment.items())
        ]
        print("装备   " + "；".join(parts))

    print(
        "角色   "
        f"导入 {payload.stats.get('characters_imported', len(payload.characters))} / "
        f"拥有 {payload.stats.get('characters_owned', 0)} / "
        f"未知跳过 {payload.stats.get('characters_skipped', 0)}；"
        f"模块行 {payload.stats.get('module_rows', 0)}，"
        f"词条有效 {payload.stats.get('gear_effective', 0)}（含道具损耗）"
    )
    if payload.link_level:
        print(
            f"链接   等级 {payload.link_level}（{payload.linked_characters} 个角色共享，"
            f"含标准角色）；全局角色等级同步为该值"
        )

    if report.warnings:
        print(f"警告   {len(report.warnings)} 条")
        for warning in report.warnings[:20]:
            print(f"  - {warning}")
        if len(report.warnings) > 20:
            print(f"  … 其余 {len(report.warnings) - 20} 条省略")

    if dry_run:
        print("\n[DRY-RUN] 未写入任何文件；确认无误后加 --apply 落盘。")
    elif report.changed:
        print(f"\n[完成] 已写入 {account_dir.name}；备份目录：{report.backup_dir or '（未备份）'}")
    else:
        print("\n[完成] 解析成功，但配置没有变化（幂等：重复导入同一快照不会改动）。")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.importer.cli",
        description="把 /api/data/user 抓包快照导入 Izanami Lab 账号配置",
    )
    parser.add_argument("file", help="快照文件（mgg-http-capture / mgg-user-snapshot / .har）")
    parser.add_argument("--account", help="目标账号名（默认当前账号）")
    parser.add_argument("--apply", action="store_true", help="真正写盘（默认只预览）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--no-backup", action="store_true", help="写入前不备份")
    parser.add_argument("--overwrite-locked", action="store_true", help="连已锁定的角色也覆盖")
    parser.add_argument("--no-school", action="store_true", help="不导入学园等级")
    parser.add_argument("--no-equipment", action="store_true", help="不导入装备数值")
    parser.add_argument("--no-characters", action="store_true", help="不导入角色基础属性/技能")
    parser.add_argument("--no-modules", action="store_true", help="不导入模块 Tier/等级")
    parser.add_argument("--no-gears", action="store_true", help="不导入模块词条")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="模拟器 data/ 目录")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    registry = AccountRegistry()

    try:
        loaded = snapshot_mod.load(Path(args.file))
    except snapshot_mod.SnapshotError as exc:
        print(f"[快照错误] {exc}", file=sys.stderr)
        return 2

    try:
        index = DataIndex.load(data_dir)
    except LutError as exc:
        print(f"[数据错误] {exc}", file=sys.stderr)
        return 1

    payload = build_payload(
        loaded.rows,
        index,
        captured_at=loaded.captured_at,
        client_version=loaded.client_version,
        source_url=loaded.source_url,
    )

    options = ApplyOptions(
        school=not args.no_school,
        equipment=not args.no_equipment,
        characters=not args.no_characters,
        modules=not args.no_modules,
        gears=not args.no_gears,
        overwrite_locked=args.overwrite_locked,
        backup=not args.no_backup,
    )

    try:
        account_dir = _resolve_account_dir(registry, args.account)
    except AccountError as exc:
        print(f"[账号错误] {exc}", file=sys.stderr)
        return 1

    dry_run = not args.apply
    try:
        report = apply_payload(
            account_dir,
            payload,
            options,
            source_name=loaded.source_name,
            source_sha256=loaded.sha256,
            dry_run=dry_run,
            data_dir=data_dir,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 需要把任何落盘失败变成可读信息
        print(f"[写入失败] {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(
            {
                "dry_run": dry_run,
                "account_dir": str(account_dir),
                "account": payload.account,
                "captured_at": payload.captured_at,
                "client_version": payload.client_version,
                "stats": report.stats,
                "warnings": report.warnings,
                "changed": report.changed,
                "backup_dir": str(report.backup_dir) if report.backup_dir else None,
                "school_levels": payload.school_levels,
                "equipment": payload.equipment,
                "characters": {
                    str(cid): {
                        "level": c.level,
                        "rarity": c.rarity,
                        "affection": c.affection,
                        "skill_level": c.skill_level,
                        "gear": len(c.gear),
                        "mod_tiers": list(c.mod_tiers),
                        "mod_levels": list(c.mod_levels),
                    }
                    for cid, c in payload.characters.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ))
    else:
        _print_human(loaded, payload, report, dry_run, account_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
