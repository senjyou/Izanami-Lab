from dataclasses import dataclass, field
from typing import Dict

@dataclass
class SchoolLevels:
    """学园等级配置"""
    # Group 1: Character Type
    physical_level: int = 1
    en_level: int = 1
    agility_level: int = 1
    
    # Group 2: Character Attribute
    fire_level: int = 1
    water_level: int = 1
    earth_level: int = 1
    wind_level: int = 1
    light_level: int = 1
    dark_level: int = 1
    
    def get_level_by_type(self, char_type: int) -> int:
        """根据角色类型获取等级"""
        mapping = {
            1: self.physical_level,
            2: self.en_level,
            3: self.agility_level
        }
        return mapping.get(char_type, 1)
        
    def get_level_by_attribute(self, attribute: int) -> int:
        """根据属性获取等级"""
        mapping = {
            1: self.fire_level,
            2: self.water_level,
            3: self.wind_level,
            4: self.earth_level,
            5: self.light_level,
            6: self.dark_level
        }
        return mapping.get(attribute, 1)

@dataclass
class PlayerConfig:
    """玩家全局配置"""
    school_level: int = 1               # 总学园等级（旧字段，保留兼容）
    school_levels: SchoolLevels = field(default_factory=SchoolLevels) # 详细学园等级
    equipment_enabled: bool = True      # 是否启用装备系统
    equipment_bonuses: Dict[int, Dict[str, int]] = field(default_factory=dict)
    # equipment_bonuses[char_type] = {"hp": int, "attack": int, "defense": int}
