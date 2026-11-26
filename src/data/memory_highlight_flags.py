# -*- coding: utf-8 -*-
"""回忆卡 highlight 的条件位掩码 → 模拟器枚举 转换。

原始 `MemoryMaster.Highlights[].CharacterAttribute / CharacterRole / CharacterType`
都是**位掩码**，而 `memories.json` 与 `UnitState` 使用的是连续枚举：

| 字段 | 原始（位掩码） | 模拟器（枚举） |
|---|---|---|
| CharacterAttribute | Aggressive=1, Smart=2, Shy=4, Cute=8, Comical=16, Clever=32 | element 1..6（Aggressive=1, Smart=2, Shy=3, Cute=4, Comical=5, Clever=6） |
| CharacterRole | PhysicalAttacker=1, EnAttacker=2, Tank=4, Support=8, Control=16 | role_type 1..5 |
| CharacterType | Physical=1, Energy=2, Agility=4 | character_type 1..3（PHYSICAL=1, ENERGY=2, AGILITY=3） |

**为什么必须转换**：`BattleFlowController._match_memory_card_unit` 直接比较
`unit.role_type` / `unit.character_type` / `unit.element`。存位掩码会导致
「永不匹配」（如敏捷存 4，而角色类型只有 1/2/3）或「误命中」（如 Shy 存 4 命中 Cute 角色）。

组合掩码按位拆分成多个 highlight（与既有卡 30035 的拆分惯例一致）。

本模块**无导入副作用**，可被测试直接引用（`scripts/import_memory.py` 在模块级
调用 `setup_console_encoding()`，直接导入会替换 `sys.stdout` 破坏 pytest 捕获）。
"""
from typing import List, Optional


# 属性：位 → element
FLAG_TO_ELEMENT = {1: 1, 2: 2, 4: 3, 8: 4, 16: 5, 32: 6}

# 职能：位 → role_type
ROLE_FLAG_TO_TYPE = {1: 1, 2: 2, 4: 3, 8: 4, 16: 5}

# 类型：位 → character_type（注意 4 是敏捷的掩码位，枚举值是 3）
TYPE_FLAG_TO_TYPE = {1: 1, 2: 2, 4: 3}


def _convert(value: Optional[int], table: dict) -> List[Optional[int]]:
    """位掩码 → 枚举列表；0/None（无过滤）返回 [None]"""
    if not value:
        return [None]
    ids = [enum for bit, enum in sorted(table.items()) if value & bit]
    return ids or [None]


def convert_attribute_flags(value: Optional[int]) -> List[Optional[int]]:
    """CharacterAttribute 位掩码 → element 列表；0/None（无过滤）返回 [None]"""
    return _convert(value, FLAG_TO_ELEMENT)


def convert_role_flags(value: Optional[int]) -> List[Optional[int]]:
    """CharacterRole 位掩码 → role_type 列表；0/None（无过滤）返回 [None]"""
    return _convert(value, ROLE_FLAG_TO_TYPE)


def convert_type_flags(value: Optional[int]) -> List[Optional[int]]:
    """CharacterType 位掩码 → character_type 列表；0/None（无过滤）返回 [None]"""
    return _convert(value, TYPE_FLAG_TO_TYPE)
