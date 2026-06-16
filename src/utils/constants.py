"""
战斗模拟器常量定义

定义了角色类型、属性、职能、位置适应性、评级等枚举常量
"""

from enum import IntEnum


# ==================== 角色相关 ====================

class CharacterType(IntEnum):
    """角色类型"""
    PHYSICAL = 1  # 物理类型
    EN = 2        # EN类型
    AGILITY = 3   # 敏捷类型


class Attribute(IntEnum):
    """属性类型（官方称呼为性格特质）"""
    FIRE = 1   # 火 (Aggressive - アグレッシブ)
    WATER = 2  # 水 (Smart - スマート)
    WIND = 3   # 风 (Shy - シャイ)
    EARTH = 4  # 地 (Cute - キュート)
    LIGHT = 5  # 光 (Comical - コミカル)
    DARK = 6   # 暗 (Clever - クレバー)


# 属性克制关系：克制者 -> 被克制者
ATTRIBUTE_ADVANTAGE = {
    Attribute.FIRE: Attribute.WIND,
    Attribute.WIND: Attribute.EARTH,
    Attribute.EARTH: Attribute.WATER,
    Attribute.WATER: Attribute.FIRE,
    Attribute.LIGHT: Attribute.DARK,
    Attribute.DARK: Attribute.LIGHT,
}

# 属性克制伤害倍率
ATTRIBUTE_ADVANTAGE_MULTIPLIER = 1.25


class RoleType(IntEnum):
    """职能类型"""
    PHYSICAL_ATTACKER = 1  # 物理攻击手
    EN_ATTACKER = 2        # EN攻击手
    TANK = 3               # 坦克
    SUPPORT = 4            # 支援
    CONTROL = 5            # 控制


class PositionType(IntEnum):
    """位置适应类型"""
    FRONT = 1      # 前排适性
    BACK = 2       # 后排适性
    FLEXIBLE = 3   # 前后排均可


# 位置不适应惩罚：扣除HP、攻击力、防御各5%
POSITION_MISMATCH_PENALTY = 0.05


class StatGrade(IntEnum):
    """属性评级"""
    D = 1
    C = 2
    B = 3
    A = 4
    S = 5


# ==================== 技能相关 ====================

class SkillType(IntEnum):
    """技能类型"""
    AS = 1  # Active Skill (主动技能)
    PS = 2  # Passive Skill (被动技能)
    EX = 3  # Extra Skill (必杀技)


class SkillKind(IntEnum):
    """技能种类/效果类别"""
    ATTACK = 1       # 攻击类
    GUARD = 2        # 防御类
    # 其他种类待补充 (3-14)


# ==================== 战斗相关 ====================

# 资源点数
# 注意：实际资源点数由角色在CharacterMaster中的基础值和CharacterRarityStatusMaster中的稀有度加成共同决定
DEFAULT_AP = None  # AP点数由稀有度决定，无固定默认值
DEFAULT_PP = None  # PP点数由稀有度决定，无固定默认值
INITIAL_EP = 0  # 初始EP点数

# 暴击相关
BASE_CRIT_MULTIPLIER = 1.5  # 基础暴击伤害倍率

# 位置定义
class Position(IntEnum):
    """战场位置"""
    LEFT_FRONT = 1    # 左前位
    CENTER_FRONT = 2  # 中前位
    RIGHT_FRONT = 3   # 右前位
    LEFT_BACK = 4     # 左后位
    CENTER_BACK = 5   # 中后位
    RIGHT_BACK = 6    # 右后位


# 前排位置集合
FRONT_POSITIONS = {Position.LEFT_FRONT, Position.CENTER_FRONT, Position.RIGHT_FRONT}

# 后排位置集合
BACK_POSITIONS = {Position.LEFT_BACK, Position.CENTER_BACK, Position.RIGHT_BACK}


# ==================== 稀有度相关 ====================

class Rarity(IntEnum):
    """稀有度等级"""
    R = 1
    R_PLUS = 2
    SR = 3
    SR_PLUS = 4
    SSR = 5
    SSR_PLUS = 6
    UR = 7
    UR_PLUS = 8
    LR = 9
    LR_PLUS_1 = 10
    LR_PLUS_2 = 11
    LR_PLUS_3 = 12
    LR_PLUS_4 = 13
    LR_PLUS_5 = 14


# LR及以上稀有度可解锁技能等级上限至15级
LR_SKILL_LEVEL_UNLOCK_RARITY = Rarity.LR
DEFAULT_MAX_SKILL_LEVEL = 10
LR_MAX_SKILL_LEVEL = 15

# 角色等级相关
MAX_LEVEL_BEFORE_BONUS = 200  # 200级以前使用插值成长(CharacterStatusLerpAmountMaster)
BONUS_LEVEL_START = 201       # 201级起使用每级加成值

# 好感度系统
MIN_AFFECTION_LEVEL = 1   # 最低好感度等级
MAX_AFFECTION_LEVEL = 40  # 最高好感度等级

# 学园等级系统 (Actuator System)
# 学园系统分为两类：
# - Type系统 (GroupId=1): 按角色类型(物理/EN/敏捷)提供加成
# - Attribute系统 (GroupId=2): 按角色属性(6种性格)提供加成
class ActuatorGroupType(IntEnum):
    """学园系统分组类型"""
    TYPE_BASED = 1      # 按角色类型分组
    ATTRIBUTE_BASED = 2  # 按角色属性分组


# ==================== 装备系统 ====================

class EquipmentType(IntEnum):
    """装备类型"""
    SENSOR = 1        # 传感器 (センサー)
    ACTUATOR = 2      # 执行器 (アクチュエーター)
    BATTERY = 3       # 电池 (バッテリー)
    JET_ENGINE = 4    # 发动机 (ジェットエンジン)


# 装备满级数值 (160级)
EQUIPMENT_MAX_LEVEL = 160
EQUIPMENT_STATS = {
    EquipmentType.SENSOR: {
        'hp': 2420,
        'attack': 4810,
        'defense': 0
    },
    EquipmentType.ACTUATOR: {
        'hp': 3330,
        'attack': 3770,
        'defense': 0
    },
    EquipmentType.BATTERY: {
        'hp': 3330,
        'attack': 0,
        'defense': 1930
    },
    EquipmentType.JET_ENGINE: {
        'hp': 2420,
        'attack': 0,
        'defense': 2840
    }
}


# ==================== 模块系统 ====================

class ModuleType(IntEnum):
    """模块类型"""
    HP = 1       # 体力模块 (体力モジュール)
    ATTACK = 2   # 攻击模块 (攻撃モジュール)
    DEFENSE = 3  # 防御模块 (防御モジュール)


# 模块阶段和等级
MIN_MODULE_TIER = 1
MAX_MODULE_TIER = 8
MAX_MODULE_LEVEL_PER_TIER = 45  # Tier8最高45级

# 模块Tier8满级数值 (Tier8, Level 45)
MODULE_TIER8_MAX_STATS = {
    ModuleType.HP: {
        'base': 3028,      # HpBase=2500, HpPerLevel=12, 45级=2500+12*44
        'percentage': 0.08  # 8%
    },
    ModuleType.ATTACK: {
        'base': 2271,      # AttackBase=1875, AttackPerLevel=9, 45级=1875+9*44
        'percentage': 0.08  # 8%
    },
    ModuleType.DEFENSE: {
        'base': 1265,      # DefenseBase=1045, DefensePerLevel=5, 45级=1045+5*44
        'percentage': 0.08  # 8%
    }
}

# 模块开孔系统
GEAR_SOCKETS_PER_MODULE = 3  # 每个模块固定3个词条孔
# 注意：每个模块的3个词条必须是不同类型，不能重复
# 例如：可以是 攻击+HP+速度，但不能是 攻击×3


class GearEffectType(IntEnum):
    """模块开孔词条效果类型"""
    NONE = 1                    # 无效果
    ATTRIBUTE_DAMAGE = 2        # 有利属性伤害 (克制伤害)
    HP_BOOST = 3               # HP增加
    ATTACK_BOOST = 4           # 攻击力增加
    DEFENSE_BOOST = 5          # 防御力增加
    SPEED_BOOST = 6            # 速度增加
    CRIT_RATE_BOOST = 7        # 暴击率加算
    CRIT_DAMAGE_BOOST = 8      # 暴击伤害增加


class GearRank(IntEnum):
    """词条稀有度"""
    S = 1
    A = 2
    B = 3
    C = 4
    D = 5


# 基础暴击伤害倍率
BASE_CRIT_DAMAGE = 1.5  # 150%

