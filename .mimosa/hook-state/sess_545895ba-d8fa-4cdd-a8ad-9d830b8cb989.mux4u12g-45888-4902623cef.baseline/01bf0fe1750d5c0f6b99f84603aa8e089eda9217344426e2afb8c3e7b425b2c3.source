from dataclasses import dataclass, field
from typing import Dict, List
from ..combat.position import Position
from .character_config import CharacterConfig

@dataclass
class TeamConfig:
    """队伍编成配置"""
    # 位置 -> 角色配置
    units: Dict[Position, CharacterConfig] = field(default_factory=dict)
    # 回忆卡列表 (最多6张)
    memory_cards: List[int] = field(default_factory=list)
