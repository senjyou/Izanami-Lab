from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class ModuleConfig:
    """模块配置"""
    module_id: int          # 模块ID
    tier: int               # Tier (1-8)
    level: int              # 等级 (1-45)
    gear_effects: List[Dict] = field(default_factory=list)  # 词条效果列表，每项为 {'effect_type': int, 'value': float}

@dataclass
class CharacterConfig:
    """角色个体配置"""
    character_id: int
    level: int = 1
    rarity: int = 1
    affection_level: int = 1
    skill_levels: Dict[int, int] = field(default_factory=dict)  # 技能ID -> 等级
    modules: List[ModuleConfig] = field(default_factory=list)   # 模块配置
    equipment_ids: List[int] = field(default_factory=list)      # 装备ID列表
