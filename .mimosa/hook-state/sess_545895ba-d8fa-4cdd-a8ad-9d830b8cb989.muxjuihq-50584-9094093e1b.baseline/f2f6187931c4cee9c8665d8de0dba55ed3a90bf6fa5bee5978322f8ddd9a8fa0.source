"""
游戏枚举定义
对应客户端 C# 代码中的枚举
"""

from enum import IntEnum, IntFlag

class DisplayTargetTypes(IntEnum):
    """显示目标类型 (对应 DisplayTargetTypes.cs)"""
    Self = 1
    SelfAndFriends = 2
    Enemies = 3
    Friends = 4
    SelfAndFriendsAndEnemies = 5

class DisplayTargetRanges(IntEnum):
    """显示目标范围 (对应 DisplayTargetRanges.cs)"""
    OnePawn = 1
    TwoPawns = 2
    ThreePawns = 3
    FourPawns = 4
    AllPawns = 5
    Line = 6
    Column = 7

class AdditionalSkillKindFlags(IntFlag):
    """技能额外类型标记 (对应 AdditionalSkillKindFlags.cs)"""
    None_ = 0
    Attack = 1        # 攻击
    Support = 2       # 支援 (Buff/AP)
    Interference = 4  # 妨害 (Debuff/Stun)
    Recovery = 8      # 恢复 (Heal)

class ElementType(IntEnum):
    """属性类型"""
    Aggressive = 1  # 红色
    Shy = 2         # 蓝色
    Cute = 3        # 绿色
    Smart = 4       # 黄色
    Comical = 5     # 紫色
    Clever = 6      # 橙色
