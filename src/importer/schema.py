# -*- coding: utf-8 -*-
"""实体行 → 具名字段（只声明本功能用到的表）。

``/api/data/user`` 的每个实体行是 ``[typeId, [字段...]]``（位置数组，没有字段名）。
这里按抓包实测 + ``MuvLuvGirlsGardenX/MasterMap.py`` 的 ``MASTER_SCHEMA_BY_ID``
补一份最小字段表：

* 只列**本功能会读**的类型，未知类型原样忽略（快照里仍然保留，供以后扩展）。
* 行字段**多于**声明 → 忽略多余字段（游戏加字段不会破坏导入）。
* 行字段**少于**声明 → 缺失位补 ``None`` 并记一条告警（schema 漂移可观察）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["SCHEMAS", "NamedEntities", "name_rows", "table"]


# typeId -> (表名, 字段名)
SCHEMAS: Dict[int, Tuple[str, Tuple[str, ...]]] = {
    0: ("User", (
        "Id", "Name", "Comment", "PlayerRank", "RankPoint", "VipRank",
        "FriendMemoryMasterId", "TrophyMasterId", "Code", "IsTutorialCompleted",
        "TotalCombatPower", "IsReceiveCircleInvitation", "WorldMasterId",
    )),
    # 33 在 MasterMap 里没有名字（用户侧 Actuator 表），字段由抓包实测确认：Id, ActuatorMasterId, Level
    33: ("Actuator", ("Id", "ActuatorMasterId", "Level")),
    38: ("Memory", ("Id", "MMemoryId", "ReceivedAt")),
    40: ("Character", (
        "Id", "CharacterMasterId", "CharacterRarity", "Level", "AffectionLevel",
        "AffectionLevelPoint", "OperatingSystemLevel", "CombatPower",
        "ViewExSkillCharacterMasterId", "ViewCockpitCharacterMasterId",
    )),
    55: ("CharacterSkill", ("Id", "CharacterMasterId", "CharacterSkillMasterId", "Level")),
    60: ("LevelLink", ("Id", "MaxSlot", "MaxLevel", "UpperLevel", "IsLock")),
    62: ("LevelLinkSlot", ("Id", "LevelLinkId", "CharacterMasterId", "FinishCoolTime", "Position")),
    68: ("Party", ("Id", "Type", "Order", "Name")),
    69: ("PartyCharacter", ("Id", "PartyId", "Position", "Reserved", "CharacterId", "TrialPartyCharacterMasterId")),
    70: ("PartyMemory", ("Id", "PartyId", "Position", "MemoryId")),
    140: ("LevelLinkSyncLevel", ("Id", "CharacterMasterId", "Level")),
    196: ("TypeEquipment", ("Id", "TypeEquipmentMasterId", "Level", "Progress", "Hp", "Attack", "Defense")),
    225: ("Module", ("Id", "CharacterId", "ModuleMasterId", "Tier", "Level")),
    226: ("ModuleGear", ("Id", "ModuleId", "Order", "IsLocked", "ModuleGearEffectMasterId", "ModuleGearItemMasterId")),
}

_NAME_BY_ID = {tid: name for tid, (name, _) in SCHEMAS.items()}


@dataclass
class NamedEntities:
    """按表名分组的具名实体行 + 解析告警。"""

    by_name: Dict[str, List[dict]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def get(self, name: str) -> List[dict]:
        return self.by_name.get(name, [])

    def first(self, name: str) -> Optional[dict]:
        rows = self.by_name.get(name) or []
        return rows[0] if rows else None


def name_rows(rows: Iterable[Tuple[int, Sequence]]) -> NamedEntities:
    """实体行 ``[(typeId, fields), ...]`` → 具名实体。

    未知 typeId 直接忽略（不计告警：游戏新增实体表是正常演化）；
    已知 typeId 但字段不足时才告警。
    """
    out = NamedEntities()
    short: Dict[int, int] = {}

    for type_id, fields in rows:
        schema = SCHEMAS.get(type_id)
        if schema is None:
            continue
        name, names = schema
        bucket = out.by_name.setdefault(name, [])
        if len(fields) < len(names):
            short[type_id] = short.get(type_id, 0) + 1
            padded = list(fields) + [None] * (len(names) - len(fields))
            bucket.append(dict(zip(names, padded)))
        else:
            bucket.append(dict(zip(names, fields)))

    for type_id, count in sorted(short.items()):
        name, names = SCHEMAS[type_id]
        out.warnings.append(f"{name}(type {type_id}) 有 {count} 行字段不足 {len(names)} 个，缺失位按 None 处理")
    return out


def table(type_id: int) -> Tuple[str, Tuple[str, ...]]:
    """取 (表名, 字段名)；未声明的 typeId 抛 KeyError。"""
    return SCHEMAS[type_id]
