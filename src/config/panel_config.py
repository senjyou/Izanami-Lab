from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .character_config import CharacterConfig, ModuleConfig
from .player_config import PlayerConfig, SchoolLevels


@dataclass
class PanelConfig:
    """用户面板配置框架

    全局配置（对所有角色生效）:
    - character_level: 角色等级 (默认200)
    - school_levels: 学园各属性/类型等级
    - equipment_ids: 装备ID列表（按角色类型自动匹配过滤）
    - equipment_enabled: 是否启用装备系统

    角色个体配置（针对每个角色单独设置，未设置则使用角色默认值）:
    - rarities: {character_id: rarity}
    - affection_levels: {character_id: affection_level}
    - modules: {character_id: [ModuleConfig]}
    - skill_levels: {character_id: {skill_id: level}}
    """

    character_level: int = 200
    school_levels: SchoolLevels = field(default_factory=SchoolLevels)
    equipment_ids: List[int] = field(default_factory=list)
    equipment_enabled: bool = True
    equipment_bonuses: Dict[int, Dict[str, int]] = field(default_factory=dict)

    rarities: Dict[int, int] = field(default_factory=dict)
    affection_levels: Dict[int, int] = field(default_factory=dict)
    modules: Dict[int, List[ModuleConfig]] = field(default_factory=dict)
    skill_levels: Dict[int, Dict[int, int]] = field(default_factory=dict)

    def get_player_config(self) -> PlayerConfig:
        return PlayerConfig(
            school_levels=self.school_levels,
            equipment_enabled=self.equipment_enabled,
            equipment_bonuses=self.equipment_bonuses,
        )

    @staticmethod
    def _get_max_rarity(default_rarity: int) -> int:
        """根据默认稀有度计算最大稀有度上限"""
        if default_rarity <= 1:
            return 5
        elif default_rarity <= 3:
            return 7
        else:
            return 14

    def get_character_config(self, char_id: int, default_rarity: int = 1) -> CharacterConfig:
        rarity = self.rarities.get(char_id, default_rarity)
        # 校验稀有度上限
        max_rarity = self._get_max_rarity(default_rarity)
        if rarity > max_rarity:
            rarity = max_rarity
        return CharacterConfig(
            character_id=char_id,
            level=self.character_level,
            rarity=rarity,
            affection_level=self.affection_levels.get(char_id, 1),
            skill_levels=self.skill_levels.get(char_id, {}),
            modules=self.modules.get(char_id, []),
            equipment_ids=self.equipment_ids,
        )