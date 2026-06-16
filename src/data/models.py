"""
数据模型定义

定义角色数据、技能数据等数据模型类
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class BaseStats:
    """基础属性"""
    level: int
    hp: int
    attack: int
    defense: int
    speed: int
    crit_rate: float


@dataclass
class BonusStats:
    """每级加成属性 (201级起)"""
    hp: int
    attack: int
    defense: int
    speed: int
    crit_rate: float


@dataclass
class StatGrades:
    """属性评级"""
    hp_grade: int
    attack_grade: int
    defense_grade: int
    speed_grade: int
    crit_rate_grade: int


@dataclass
class CharacterData:
    """角色数据模型"""
    character_id: int
    name: str
    character_base_id: int
    default_rarity: int
    character_type: int  # CharacterType
    attribute: int  # Attribute
    position_type: int  # PositionType
    role_type: int  # RoleType
    
    # 基础资源点数
    action_point: int
    passive_point: int
    
    # 等级1的属性
    min_level_stats: BaseStats
    
    # 等级200的属性
    max_level_stats: BaseStats
    
    # 201级起每级加成
    bonus_per_level: BonusStats
    
    # 属性评级
    grades: StatGrades
    
    # 原始数据（保留完整信息）
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TemplateTagValue:
    """模板标签值"""
    level: int
    value: float


@dataclass
class TemplateTag:
    """技能模板标签"""
    tag_name: str
    interpolation_mode: int
    values: List[TemplateTagValue]
    
    def get_value_at_level(self, level: int) -> float:
        """获取指定等级的数值"""
        # 如果没有数值，返回0
        if not self.values:
            return 0.0
        
        # 如果等级小于最小值，返回第一个值
        if level <= self.values[0].level:
            return self.values[0].value
        
        # 如果等级大于最大值，返回最后一个值
        if level >= self.values[-1].level:
            return self.values[-1].value
        
        # 查找等级区间
        for i in range(len(self.values) - 1):
            if self.values[i].level <= level < self.values[i + 1].level:
                # 根据插值模式计算
                if self.interpolation_mode == 1:
                    # 模式1：固定值（返回当前区间的值）
                    return self.values[i].value
                elif self.interpolation_mode == 2:
                    # 模式2：线性插值
                    v1 = self.values[i]
                    v2 = self.values[i + 1]
                    ratio = (level - v1.level) / (v2.level - v1.level)
                    return v1.value + (v2.value - v1.value) * ratio
        
        # 默认返回最后一个值
        return self.values[-1].value


@dataclass
class SkillDescription:
    """技能描述"""
    min_level: int
    template: str


@dataclass
class AdditionalKind:
    """附加技能效果"""
    level: int
    value: int


@dataclass
class DisplayInfo:
    """显示信息"""
    power_tag: Optional[str] = None
    attacks_count_tag: Optional[str] = None
    target_type: Optional[int] = None
    target_range: Optional[int] = None
    target_priority: Optional[int] = None


@dataclass
class SkillData:
    """技能数据模型"""
    skill_id: int
    name: str
    skill_type: int  # SkillType
    skill_kind: int  # SkillKind
    resource_cost: int
    cooldown: int
    cooldown_update_timing: Optional[int]
    default_max_level: int
    features: int
    skill_level_pattern_id: int
    
    # 附加效果类型
    additional_kinds: List[AdditionalKind]
    
    # 技能描述（不同等级可能有不同描述）
    descriptions: List[SkillDescription]
    
    # 模板标签（威力、效果量等数值）
    template_tags: Dict[str, TemplateTag]
    
    # 显示信息
    display_info: DisplayInfo
    
    # 原始数据（保留完整信息）
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def get_description_at_level(self, level: int) -> str:
        """获取指定等级的技能描述"""
        if not self.descriptions:
            return ""
        
        # 找到适用的描述模板
        applicable_desc = self.descriptions[0]
        for desc in self.descriptions:
            if level >= desc.min_level:
                applicable_desc = desc
            else:
                break
        
        return applicable_desc.template
    
    def get_tag_value_at_level(self, tag_name: str, level: int) -> float:
        """获取指定标签在指定等级的数值"""
        if tag_name not in self.template_tags:
            return 0.0
        
        return self.template_tags[tag_name].get_value_at_level(level)


@dataclass
class CharacterSkillMapping:
    """角色技能映射"""
    character_id: int
    skill_ids: List[int]


# ==================== 新增游戏系统数据模型 ====================

@dataclass
class LevelLerpData:
    """等级插值数据"""
    level: int
    amount: float  # 插值系数 (0.0 - 1.0)


@dataclass
class AffectionBonus:
    """好感度加成"""
    affection_level: int
    character_type: int  # 对应CharacterType
    additional_hp: int
    additional_attack: int
    additional_defense: int
    additional_speed: int
    additional_action_point: int
    additional_passive_point: int


@dataclass
class RarityBonus:
    """稀有度加成"""
    character_id: int
    rarity: int
    additional_hp: int
    additional_attack: int
    additional_defense: int
    additional_speed: int
    additional_crit_rate: float
    additional_action_point: int
    additional_passive_point: int


@dataclass
class SchoolLevelBonus:
    """学园等级加成"""
    group_id: int     # 分组ID (1=Type, 2=Attribute)
    level: int        # 学园等级
    hp_bonus: int
    attack_bonus: int
    defense_bonus: int


@dataclass
class SchoolSystem:
    """学园系统定义"""
    actuator_id: int
    name: str
    character_type: Optional[int]  # 如果按Type分组，此字段有值
    character_attribute: Optional[int]  # 如果按Attribute分组，此字段有值
    group_type: int  # 1=Type系, 2=Attribute系


# ==================== 装备系统数据模型 ====================

@dataclass
class EquipmentData:
    """装备数据"""
    equipment_id: int
    name: str
    character_type: int  # 适用角色类型
    equipment_type: int  # 装备类型 (1-4)
    hp_bonus: int
    attack_bonus: int
    defense_bonus: int
    description: str = ""


# ==================== 模块系统数据模型 ====================

@dataclass
class ModuleData:
    """模块定义"""
    module_id: int
    name: str
    character_type: int  # 适用角色类型
    module_type: int  # 模块类型 (1=HP, 2=攻击, 3=防御)


@dataclass
class ModuleStatus:
    """模块状态数据 (不同Tier的属性)"""
    module_id: int
    tier: int
    hp_base: int
    hp_per_level: int
    hp_rate: float
    attack_base: int
    attack_per_level: int
    attack_rate: float
    defense_base: int
    defense_per_level: int
    defense_rate: float
    
    def get_stats_at_level(self, level: int) -> Dict[str, float]:
        """获取指定等级的模块属性"""
        # 计算固定值
        hp_fixed = self.hp_base + self.hp_per_level * max(0, level - 1)
        attack_fixed = self.attack_base + self.attack_per_level * max(0, level - 1)
        defense_fixed = self.defense_base + self.defense_per_level * max(0, level - 1)
        
        return {
            'hp_fixed': hp_fixed,
            'hp_percentage': self.hp_rate,
            'attack_fixed': attack_fixed,
            'attack_percentage': self.attack_rate,
            'defense_fixed': defense_fixed,
            'defense_percentage': self.defense_rate
        }


@dataclass
class GearEffect:
    """模块开孔词条效果"""
    effect_type: int  # GearEffectType
    rank: int  # GearRank (1=S, 2=A, 3=B, 4=C, 5=D)
    effect_value: float  # 百分比值


@dataclass
class ModuleGearData:
    """模块开孔词条定义"""
    gear_id: int
    title: str
    effect_type: int
    effects_by_rank: Dict[int, float]  # {rank: effect_value}


# ==================== 敌方系统数据模型 ====================

@dataclass
class EnemyData:
    """敌方单位数据"""
    enemy_id: int
    name: str
    asset_id: str
    # 基础属性
    hp: int
    attack: int
    defense: int
    speed: int
    # 属性等级 (Grade)
    hp_grade: int
    attack_grade: int
    defense_grade: int
    speed_grade: int
    # 战斗属性
    critical_rate: float
    critical_rate_grade: int
    # 类型信息
    attribute: int  # 属性 (1-6)
    type: int      # 角色类型 (1-3)
    role_type: int # 角色定位
    rarity: int
    # 技能ID列表
    skill_ids: List[int] = field(default_factory=list)


# ==================== 回忆系统数据模型 ====================

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
class MemoryData:
    """回忆卡数据"""
    memory_id: int
    name: str
    description: str
    rarity: int  # 1=SR, 2=SSR, 3=UR
    highlights: List[MemoryHighlight] = field(default_factory=list)

    @property
    def skill_ids(self) -> List[int]:
        return [h.skill_master_id for h in self.highlights if h.skill_master_id]


@dataclass
class CalculatedStats:
    """计算后的最终属性（用于初始化Unit）"""
    hp: int
    attack: int
    defense: int
    speed: int
    critical_rate: float
    critical_damage: float
    advantage_damage: float  # 有利属性伤害倍率
    initial_ap: int
    initial_pp: int
    max_ap: int
    max_pp: int
