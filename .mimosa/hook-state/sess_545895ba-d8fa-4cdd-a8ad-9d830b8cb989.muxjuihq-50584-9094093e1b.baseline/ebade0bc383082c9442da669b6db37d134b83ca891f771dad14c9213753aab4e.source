#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
回忆卡实体
src/entities/memory_card.py

回忆卡（Memory Card）是编队时可单独设置的装备物品。
每套编成最多6张，每张回忆卡定义了对特定角色的效果规则。
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class MemoryHighlight:
    """回忆卡效果条件"""
    character_attribute: Optional[int] = None
    character_base_master_id: Optional[int] = None
    character_master_id: Optional[int] = None
    character_role: Optional[int] = None
    character_team_master_id: Optional[int] = None
    character_type: Optional[int] = None
    is_targeting_friendly_party: bool = True
    party_position: Optional[int] = None
    skill_master_id: Optional[int] = None


@dataclass
class MemoryCard:
    """回忆卡"""
    card_id: int
    name: str
    description: str
    rarity: int
    highlights: List[MemoryHighlight] = field(default_factory=list)

    @property
    def skill_ids(self) -> List[int]:
        return [h.skill_master_id for h in self.highlights if h.skill_master_id]