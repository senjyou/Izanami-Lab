# -*- coding: utf-8 -*-
"""实体行 → 导入载荷（纯函数，无 IO、无 tkinter，可直接单测）。

输入是 ``/api/data/user`` 解码出的实体行，输出是"要写进
char_config.json / global_config.json 的值"加一份告警清单。
真正的落盘（备份、合并、原子写）在 apply.py。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from . import schema
from .lut import DataIndex

__all__ = [
    "CharacterImport",
    "ImportPayload",
    "build_payload",
    "SIM_MAX_MODULE_TIER",
    "SIM_MAX_MODULE_LEVEL",
    "SIM_MAX_AFFECTION",
    "SIM_MAX_LEVEL",
]

# 模拟器 GUI 的输入上限（gui/tabs/char_params.py 的 Spinbox 范围）
SIM_MAX_MODULE_TIER = 10
SIM_MAX_MODULE_LEVEL = 55
SIM_MAX_AFFECTION = 40
SIM_MAX_LEVEL = 999


@dataclass
class CharacterImport:
    """单个角色的导入结果（字段名对齐 char_config.json）。"""

    character_id: int
    level: int
    rarity: int
    affection: int
    skill_levels: Dict[int, int] = field(default_factory=dict)
    mod_tiers: Tuple[int, int, int] = (1, 1, 1)
    mod_levels: Tuple[int, int, int] = (1, 1, 1)
    gear: List[dict] = field(default_factory=list)

    @property
    def skill_level(self) -> int:
        return max(self.skill_levels.values()) if self.skill_levels else 1


@dataclass
class ImportPayload:
    """一次导入的全部结果。"""

    account: Dict[str, object] = field(default_factory=dict)
    captured_at: Optional[str] = None
    client_version: Optional[str] = None
    source_url: Optional[str] = None
    school_levels: Optional[Dict[str, int]] = None
    equipment: Optional[Dict[int, Dict[str, int]]] = None
    characters: Dict[int, CharacterImport] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    link_level: Optional[int] = None
    linked_characters: int = 0

    def warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


def _as_int(value, default: Optional[int] = None) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: int, low: int, high: int) -> Tuple[int, bool]:
    if value < low:
        return low, True
    if value > high:
        return high, True
    return value, False


def _build_account(payload: ImportPayload, user_rows: List[dict]) -> None:
    if not user_rows:
        payload.warning("快照里没有 User(type 0) 行，无法校验账号身份")
        return
    user = user_rows[0]
    payload.account = {
        "user_id": _as_int(user.get("Id")),
        "name": user.get("Name"),
        "code": user.get("Code"),
        "world_master_id": _as_int(user.get("WorldMasterId")),
        "player_rank": _as_int(user.get("PlayerRank")),
        "vip_rank": _as_int(user.get("VipRank")),
    }


def _build_school(payload: ImportPayload, index: DataIndex, rows: List[dict]) -> None:
    if not rows:
        payload.warning("快照里没有 Actuator(type 33) 行，跳过学园等级")
        return
    levels = index.school_levels_from_rows(rows)
    expected = {
        "physical_level", "en_level", "agility_level",
        "fire_level", "water_level", "wind_level",
        "earth_level", "light_level", "dark_level",
    }
    missing = expected - set(levels)
    if missing:
        payload.warning(f"学园等级缺少 {len(missing)} 项（{', '.join(sorted(missing))}），仅导入已有项")
    if not levels:
        payload.warning("学园等级一行都没解析出来，跳过")
        return
    payload.school_levels = levels


def _build_equipment(payload: ImportPayload, index: DataIndex, rows: List[dict]) -> None:
    if not rows:
        payload.warning("快照里没有 TypeEquipment(type 196) 行，跳过装备数值")
        return
    totals = index.equipment_totals(rows)
    if not any(any(v.values()) for v in totals.values()):
        payload.warning("装备数值全为 0（可能未解析到），仍按 0 导入")
    payload.equipment = totals


def _level_link(payload: ImportPayload, named) -> Tuple[set, Optional[int], Dict[int, int]]:
    """解析「链接等级」结构。

    - ``LevelLink.MaxLevel`` = 当前链接等级（真机确认：キョウ号 409、パンダ号 267）；
    - ``LevelLinkSlot`` 列出被链接角色（``CharacterMasterId``），它们共享链接等级；
    - ``LevelLinkSyncLevel`` 列出「标准角色」（不在槽位里，但同样按链接等级计算），
      5 条记录恰好就是 Character.Level=200 的那 5 个标准角色；
    - 既不在槽位也不在 SyncLevel 里的角色，等级独立，取 ``Character.Level``。
    """
    linked = set()
    for slot in named.get("LevelLinkSlot"):
        cid = _as_int(slot.get("CharacterMasterId"))
        if cid is not None:
            linked.add(cid)

    link_level = None
    link_rows = named.get("LevelLink")
    if link_rows:
        link_level = _as_int(link_rows[0].get("MaxLevel"))
        if link_level is not None and link_level < 1:
            link_level = None

    sync_levels: Dict[int, int] = {}
    for row in named.get("LevelLinkSyncLevel"):
        cid = _as_int(row.get("CharacterMasterId"))
        level = _as_int(row.get("Level"))
        if cid is not None and level is not None:
            sync_levels[cid] = level

    if link_level is None and (linked or sync_levels):
        payload.warning("快照里有链接结构但没有 LevelLink.MaxLevel，链接角色按各自 Character.Level 处理")
        linked = set()
        sync_levels = {}
    return linked, link_level, sync_levels


def build_payload(
    rows: Sequence[Tuple[int, Sequence]],
    index: DataIndex,
    *,
    captured_at: Optional[str] = None,
    client_version: Optional[str] = None,
    source_url: Optional[str] = None,
) -> ImportPayload:
    """把实体行转换成导入载荷。

    参数
    ----
    rows
        ``wire.extract_rows`` 的结果：``[(typeId, [字段...]), ...]``。
    index
        ``lut.DataIndex``（提供 master 数据与 LUT）。
    """
    payload = ImportPayload(
        captured_at=captured_at, client_version=client_version, source_url=source_url
    )
    named = schema.name_rows(rows)
    payload.warnings.extend(named.warnings)

    _build_account(payload, named.get("User"))
    _build_school(payload, index, named.get("Actuator"))
    _build_equipment(payload, index, named.get("TypeEquipment"))

    char_rows = named.get("Character")
    module_rows = named.get("Module")
    gear_rows = named.get("ModuleGear")
    skill_rows = named.get("CharacterSkill")

    instance_to_cid: Dict[int, int] = {}
    chars_by_cid: Dict[int, dict] = {}
    for row in char_rows:
        cid = _as_int(row.get("CharacterMasterId"))
        instance_id = _as_int(row.get("Id"))
        if cid is None or instance_id is None:
            continue
        instance_to_cid[instance_id] = cid
        chars_by_cid[cid] = row

    modules_by_cid: Dict[int, List[dict]] = {}
    for row in module_rows:
        cid = instance_to_cid.get(_as_int(row.get("CharacterId"), -1))
        if cid is None:
            continue
        modules_by_cid.setdefault(cid, []).append(row)

    gears_by_module: Dict[int, List[dict]] = {}
    for row in gear_rows:
        module_id = _as_int(row.get("ModuleId"))
        if module_id is None:
            continue
        gears_by_module.setdefault(module_id, []).append(row)

    skills_by_cid: Dict[int, Dict[int, int]] = {}
    for row in skill_rows:
        cid = _as_int(row.get("CharacterMasterId"))
        master_id = _as_int(row.get("CharacterSkillMasterId"))
        level = _as_int(row.get("Level"))
        if cid is None or master_id is None or level is None:
            continue
        skill_id = index.skill_master.get(master_id)
        if skill_id is None:
            payload.warning(f"技能映射缺失：CharacterSkillMasterId={master_id}（角色 {cid}），该技能按 1 级处理")
            continue
        skills_by_cid.setdefault(cid, {})[skill_id] = level

    linked_cids, link_level, sync_levels = _level_link(payload, named)
    payload.link_level = link_level
    # 共享链接等级的角色 = 槽位内（被链接）+ SyncLevel 名单（标准角色）
    payload.linked_characters = len(set(linked_cids) | set(sync_levels))

    unknown_characters: List[int] = []
    for cid, char in chars_by_cid.items():
        sim_char = index.characters.get(cid)
        if sim_char is None:
            unknown_characters.append(cid)
            continue

        if link_level and (cid in linked_cids or cid in sync_levels):
            raw_level = link_level
        else:
            raw_level = _as_int(char.get("Level"), 1) or 1
        level, clamped = _clamp(raw_level, 1, SIM_MAX_LEVEL)
        if clamped:
            payload.warning(f"角色 {cid} 等级 {raw_level} 超出 1..{SIM_MAX_LEVEL}，已夹取为 {level}")

        rarity = _as_int(char.get("CharacterRarity"), 1) or 1
        rarity_cap = index.max_rarity_for(cid)
        rarity, clamped = _clamp(rarity, 1, rarity_cap)
        if clamped:
            payload.warning(f"角色 {cid} 稀有度 {char.get('CharacterRarity')} 超出上限 {rarity_cap}，已夹取为 {rarity}")

        affection = _as_int(char.get("AffectionLevel"), 1) or 1
        affection, clamped = _clamp(affection, 1, SIM_MAX_AFFECTION)
        if clamped:
            payload.warning(f"角色 {cid} 好感度 {char.get('AffectionLevel')} 超出 1..{SIM_MAX_AFFECTION}，已夹取为 {affection}")

        # 模块：ModuleMasterId = 角色类型 * 10 + 1/2/3（HP/ATK/DEF）
        char_type = int(sim_char.get("character_type") or 1)
        wanted = {char_type * 10 + 1: 0, char_type * 10 + 2: 1, char_type * 10 + 3: 2}
        tiers = [1, 1, 1]
        levels = [1, 1, 1]
        found_modules = set()
        for module in modules_by_cid.get(cid, []):
            master_id = _as_int(module.get("ModuleMasterId"))
            group = wanted.get(master_id)
            if group is None:
                payload.warning(f"角色 {cid} 出现未知模块 ModuleMasterId={master_id}")
                continue
            found_modules.add(master_id)

            tier = _as_int(module.get("Tier"), 1) or 1
            tier, clamped = _clamp(tier, 1, SIM_MAX_MODULE_TIER)
            if clamped:
                payload.warning(f"角色 {cid} 模块 {master_id} 的 Tier {module.get('Tier')} 超出 1..{SIM_MAX_MODULE_TIER}，已夹取")
            module_level = _as_int(module.get("Level"), 1) or 1
            module_level, clamped = _clamp(module_level, 1, SIM_MAX_MODULE_LEVEL)
            if clamped:
                payload.warning(f"角色 {cid} 模块 {master_id} 的等级 {module.get('Level')} 超出 1..{SIM_MAX_MODULE_LEVEL}，已夹取")
            tiers[group] = tier
            levels[group] = module_level

        missing_modules = [mid for mid in wanted if mid not in found_modules]
        if missing_modules:
            payload.warning(f"角色 {cid} 缺少模块 {missing_modules}，按 Tier1/等级1 处理")

        # 词条：每个模块最多 3 条（Order 0..2），同组同类型只能有一个
        gear: List[dict] = []
        seen_group_types = set()
        for master_id, group in sorted(wanted.items(), key=lambda kv: kv[1]):
            module = next(
                (m for m in modules_by_cid.get(cid, []) if _as_int(m.get("ModuleMasterId")) == master_id),
                None,
            )
            if module is None:
                continue
            module_id = _as_int(module.get("Id"))
            entries = sorted(
                gears_by_module.get(module_id, []),
                key=lambda r: (_as_int(r.get("Order"), 0) or 0),
            )
            for entry in entries:
                effect_master_id = _as_int(entry.get("ModuleGearEffectMasterId"))
                if effect_master_id is None:
                    continue
                item_master_id = _as_int(entry.get("ModuleGearItemMasterId"))
                if item_master_id is not None and item_master_id not in index.gear_items:
                    payload.warning(
                        f"角色 {cid} 的词条道具 ModuleGearItemMasterId={item_master_id} 不在 LUT 中，按无损耗处理"
                    )
                mapped = index.gear_sim_effect(effect_master_id, item_master_id)
                if mapped is None:
                    payload.warning(
                        f"角色 {cid} 的词条 ModuleGearEffectMasterId={effect_master_id} 不在 LUT 中，已跳过"
                    )
                    continue
                effect_type, value = mapped
                if effect_type == 0:  # 効果なし
                    continue
                slot = _as_int(entry.get("Order"), 0) or 0
                if (group, effect_type) in seen_group_types:
                    payload.warning(
                        f"角色 {cid} 模块组 {group} 出现重复词条类型 {effect_type}，保留第一条"
                    )
                    continue
                seen_group_types.add((group, effect_type))
                gear.append({
                    "effect_type": effect_type,
                    "value": value,
                    "group": group,
                    "slot": slot,
                })

        skill_levels = index.skill_ids_for(cid)
        got = skills_by_cid.get(cid, {})
        payload.characters[cid] = CharacterImport(
            character_id=cid,
            level=level,
            rarity=rarity,
            affection=affection,
            skill_levels={sid: got.get(sid, 1) for sid in skill_levels},
            mod_tiers=(tiers[0], tiers[1], tiers[2]),
            mod_levels=(levels[0], levels[1], levels[2]),
            gear=gear,
        )

    if unknown_characters:
        shown = "、".join(str(c) for c in sorted(unknown_characters)[:10])
        more = "…" if len(unknown_characters) > 10 else ""
        payload.warning(
            f"{len(unknown_characters)} 个角色不在模拟器数据中（{shown}{more}），已跳过——请更新模拟器 master 数据"
        )

    payload.stats = {
        "entity_rows": len(rows),
        "characters_owned": len(chars_by_cid),
        "characters_imported": len(payload.characters),
        "characters_skipped": len(unknown_characters),
        "skill_rows": len(skill_rows),
        "module_rows": len(module_rows),
        "gear_rows": len(gear_rows),
        "gear_effective": sum(len(c.gear) for c in payload.characters.values()),
        "link_level": int(link_level or 0),
        "linked_characters": len(linked_cids),
        "warnings": len(payload.warnings),
    }
    return payload
