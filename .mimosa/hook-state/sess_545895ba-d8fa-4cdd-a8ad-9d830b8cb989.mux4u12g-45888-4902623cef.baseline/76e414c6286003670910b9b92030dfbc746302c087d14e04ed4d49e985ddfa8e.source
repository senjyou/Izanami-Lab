from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class EffectData:
    """单个技能效果数据"""
    effect_type: str
    target_type: str
    target_identifier: Optional[str] = None
    value: Optional[float] = None
    value_tag: Optional[str] = None
    value_source: Optional[str] = None
    duration: Optional[int] = None
    duration_type: Optional[str] = None
    duration_tag: Optional[str] = None
    hit_count: Optional[int] = None
    hit_count_tag: Optional[str] = None
    condition: Optional[Dict[str, Any]] = None
    flags: Dict[str, Any] = field(default_factory=dict)
    ignore_defense: int = 0
    ignore_shield: int = 0

@dataclass
class EffectBlock:
    """效果块 (Effect Block)"""
    block_id: int
    effects: List[EffectData] = field(default_factory=list)
    condition: Optional[Dict[str, Any]] = None

@dataclass
class SkillData:
    """技能元数据"""
    skill_id: int
    name: str
    skill_type: int
    resource_cost: int
    effect_blocks: List[EffectBlock] = field(default_factory=list)
    cooldown: int = 0
    display_target_type: Optional[int] = None
    display_target_range: Optional[int] = None
    display_target_priority: Optional[int] = None
    features: int = 0
