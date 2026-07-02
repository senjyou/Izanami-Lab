#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
实体枚举定义
src/entities_v2/enums.py
"""

from enum import Enum, auto

class TriggerTiming(Enum):
    """
    触发器触发时机
    对应游戏解包 SkillTriggerTimings.cs
    """
    BATTLE_START = "BattleStart"              # 战斗开始
    WAVE_START = "WaveStart"                  # 波次开始
    WAVE_END = "WaveEnd"                      # 波次结束
    TURN_START = "TurnStart"                  # 回合开始
    TURN_END = "TurnEnd"                      # 回合结束
    BEFORE_SKILL_USE = "BeforeSkillUse"       # 技能使用前（扣除资源后，效果执行前）
    AFTER_SKILL_USE = "AfterSkillUse"         # 技能使用后（效果执行完后）
    BEFORE_SKILL_EFFECTS_APPLY = "BeforeSkillEffectsApply" # 技能效果应用前（目标已定，伤害未出）
    BEFORE_AS_ATTACKED = "BeforeAsAttacked"   # 被AS攻击前
    BEFORE_ANY_ATTACKED = "BeforeAnyAttacked" # 被任意技能攻击前
    BEFORE_ENEMY_AS_ATTACK = "BeforeEnemyAsAttack" # 敌方攻击索敌后、实际攻击前
    BEFORE_ALLY_AS_ATTACK = "BeforeAllyAsAttack" # 友方AS攻击前
    AFTER_AS_ATTACKED = "AfterAsAttacked"     # 被攻击后（反击触发点）
    AFTER_ALLY_ATTACKED = "AfterAllyAttacked" # 友方被攻击后
    AFTER_SELF_ATTACKED = "AfterSelfAttacked" # 自身被攻击后
    AFTER_AS_ATTACKED_ALLY = "AfterAsAttackedAlly" # 友方被AS技能攻击后（仅AS技能触发，且需为主目标）
    AFTER_ALLY_AS_ATTACK = "AfterAllyAsAttack"   # 其他友方AS攻击后
    PAWN_DIED = "PawnDied"                    # 单位死亡
    PAWN_RECEIVED_AURA = "PawnReceivedAura"   # 单位获得Buff/Debuff (Aura)
    PAWN_CAUSED_CRITICAL = "PawnCausedCritical" # 单位造成暴击
    PAWN_RECEIVED_DAMAGE = "PawnReceivedDamage" # 单位受到伤害 (反击触发点)
    PAWN_RECEIVED_HEALING = "PawnReceivedHealing" # 单位受到治疗
    PAWN_KILLED = "PawnKilled"                # 单位击杀敌人（仅击杀者触发）
    PAWN_ANY_KILL = "PawnAnyKill"             # 敌方被击倒（同阵营任意单位击杀均可触发）
    HP_BELOW = "HpBelow"                      # HP低于阈值
    SKILL_USE_COUNT = "SkillUseCount"         # 技能使用次数计数
    UNIT_COUNT_BELOW = "UnitCountBelow"       # 敌军数量低于阈值
    ALLY_CHARGE_USE = "AllyChargeUse"          # 友方使用充能技能时
    CUMULATIVE_DAMAGE = "CumulativeDamage"     # 累计伤害达到阈值
    BATTLE_END = "BattleEnd"                  # 战斗结束

class Side(Enum):
    """阵营"""
    ALLY = "ally"
    ENEMY = "enemy"

class Position(Enum):
    """战场位置"""
    ALLY_LEFT_FRONT = "ally_left_front"
    ALLY_CENTER_FRONT = "ally_center_front"
    ALLY_RIGHT_FRONT = "ally_right_front"
    ALLY_LEFT_BACK = "ally_left_back"
    ALLY_CENTER_BACK = "ally_center_back"
    ALLY_RIGHT_BACK = "ally_right_back"
    ENEMY_LEFT_FRONT = "enemy_left_front"
    ENEMY_CENTER_FRONT = "enemy_center_front"
    ENEMY_RIGHT_FRONT = "enemy_right_front"
    ENEMY_LEFT_BACK = "enemy_left_back"
    ENEMY_CENTER_BACK = "enemy_center_back"
    ENEMY_RIGHT_BACK = "enemy_right_back"

class UnitActionPhase(Enum):
    """
    单位行动阶段
    """
    IDLE = "idle"                    # 空闲/等待
    CHECKING_STATUS = "checking_status"  # 检查状态（眩晕/冰冻/Dot伤害）
    BEFORE_SKILL = "before_skill"    # 技能前摇（资源扣除后，效果前）
    AFTER_SKILL = "after_skill"      # 技能后摇（效果结算后）
    STANDBY = "standby"              # 待机（无法行动或主动待机）

class Attribute(Enum):
    """
    属性类型 (Attribute)
    对应 game_constants.md
    """
    FIRE = 1    # 火
    WATER = 2   # 水
    WIND = 3    # 风
    EARTH = 4   # 土
    LIGHT = 5   # 光
    DARK = 6    # 暗
    NONE = 0    # 无属性

class CharacterType(Enum):
    """
    角色类型 (Character Type)
    对应 game_constants.md
    """
    PHYSICAL = 1  # 物理 (Physical)
    ENERGY = 2    # 能量 (Energy)
    AGILITY = 3   # 敏捷 (Agility)

class RoleType(Enum):
    """
    角色定位 (Role Type)
    对应 game_constants.md
    """
    PHYSICAL_ATTACKER = 1 # 物理攻击手
    EN_ATTACKER = 2       # EN攻击手
    TANK = 3              # 坦克
    SUPPORT = 4           # 辅助
    CONTROL = 5           # 控制

class PositionType(Enum):
    """
    位置适应性 (Position Type)
    对应 game_constants.md
    """
    FRONT = 1     # 前排
    BACK = 2      # 后排
    FLEXIBLE = 3  # 灵活

class DisplayTargetType(Enum):
    """
    目标类型 (DisplayTargetTypes)
    对应 DisplayTargetTypes.cs
    """
    SELF = 1                        # 仅自身
    SELF_AND_FRIENDS = 2            # 自身及全体友方
    ENEMIES = 3                     # 敌方全体（基础）
    FRIENDS = 4                     # 友方全体（不含自身）
    SELF_AND_FRIENDS_AND_ENEMIES = 5 # 全场所有单位
    ADJACENT_ENEMIES = 6            # 主目标相邻的敌方（溅射）

class DisplayTargetRange(Enum):
    """
    目标范围 (DisplayTargetRanges)
    对应 DisplayTargetRanges.cs
    """
    ONE_PAWN = 1    # 单体
    TWO_PAWNS = 2   # 双体（主目标+最近邻）
    THREE_PAWNS = 3 # 三体
    FOUR_PAWNS = 4  # 四体
    ALL_PAWNS = 5   # 全体
    LINE = 6        # 横排 (Row)
    COLUMN = 7      # 竖列 (Column)

class DisplayTargetPriority(Enum):
    """
    目标优先级 (DisplayTargetPriorities)
    对应 DisplayTargetPriorities.cs
    当存在多个可选目标时的排序依据
    
    注：目前仅包含位置优先级。
    特殊优先级（如：HP最低、攻击最高等）可能通过隐藏字段实现，后续补充。
    """
    NEAREST = 0         # 最近 (默认)
    FRONT_LINE = 1      # 前排优先
    BACK_LINE = 2       # 后排优先
    LEFT_COLUMN = 3     # 左列优先
    CENTER_COLUMN = 4   # 中列优先
    RIGHT_COLUMN = 5    # 右列优先
    FARTHEST = 6        # 最遠
    LOWEST_HP_PERCENT = 7  # HP百分比最低优先
    HIGHEST_ATK = 8        # 攻击力最高优先
    HIGHEST_SPEED = 9      # 速度最高优先

class SkillType(Enum):
    """
    技能类型 (Skill Type)
    对应 game_constants.md
    """
    AS = 1          # 主动技能 (Active Skill)
    PS = 2          # 被动技能 (Passive Skill)
    EX = 3          # 必杀技 (EX Skill)

class DamageType(Enum):
    """
    伤害类型
    """
    PHYSICAL = 1      # 物理伤害 (Physical & Agility Type)
    ENERGY = 2        # EN伤害 (Energy Type)
    FIXED = 3         # 固定伤害 (Fixed Damage)
    REFLECTION = 4    # 反射伤害 (Reflection Damage)

class AuraType(Enum):
    """
    Aura类型
    对应 AuraTypes.cs
    """
    BUFF = 1   # 增益
    DEBUFF = 2 # 减益 (含状态异常)

class SkillEffectType(Enum):
    """
    技能效果类型 (SkillEffectTypes)
    对应 SkillEffectTypes.cs
    
    注：百分比与固定值的区别通常由效果数值的ValueTag决定，不在此枚举区分。
    """
    DAMAGE = "Damage"                                 # 1: 造成伤害
    HEAL = "Heal"                                     # 2: 治疗
    
    # 基础数值类
    STATUS_MAX_HP = "StatusMaxHp"                     # 3: 最大HP修正
    STATUS_ATTACK = "StatusAttack"                    # 4: 攻击力修正
    STATUS_DEFENSE = "StatusDefense"                  # 5: 防御力修正
    STATUS_SPEED = "StatusSpeed"                      # 6: 速度修正
    STATUS_CRITICAL_CHANCE = "StatusCriticalChance"   # 7: 暴击率修正
    STATUS_MAX_AP = "StatusMaxAp"                     # 8: 最大AP修正
    STATUS_MAX_PP = "StatusMaxPp"                     # 9: 最大PP修正
    
    # 资源类
    MODIFY_AP = "ModifyAp"                            # 10: 恢复/减少AP (当前值)
    MODIFY_PP = "ModifyPp"                            # 11: 恢复/减少PP (当前值)
    MODIFY_EP = "ModifyEp"                            # 24: 恢复/减少EP (当前值)
    
    # 状态异常 (Debuffs)
    POISON = "Poison"                                 # 12: 毒 (持续伤害)
    CONFLAGRATION = "Conflagration"                   # 13: 炎上 (持续伤害，可叠加)
    FREEZE = "Freeze"                                 # 33: 冻结 (无法行动，受击解除)
    KNOCKOUT = "Knockout"                             # 32: 眩晕/气绝 (无法行动)
    CONFUSION = "Confusion"                           # 混乱 (技能过滤+目标反转+伤害减免)
    MARK = "Mark"                                     # 41: 标记
    ACTION_DAMAGE = "ActionDamage"                    # 行動時ダメージ (行动时受到攻击力x%伤害)
    GENWAKU = "Genwaku"                               # 幻惑 (攻击者持有時、ダメージを回復へ変換)
    
    # 属性/战斗修正
    CRITICAL_BONUS_MODIFICATION = "CriticalBonusModification" # 14: 暴击伤害倍率修正
    ATTRIBUTE_ATTACK = "AttributeAttack"              # 15: 属性攻击力修正 (例如：对火属性伤害增加)
    ATTRIBUTE_DEFENSE = "AttributeDefense"            # 16: 属性防御力修正
    RECEIVED_DAMAGE = "ReceivedDamage"                # 17: 受到的伤害修正 (易伤/减伤)
    DEALT_DAMAGE = "DealtDamage"                      # 23: 造成的伤害修正 (增伤/减伤)
    HEAL_OVER_TIME = "HealOverTime"                   # 25: 持续治疗 (HoT)
    RECEIVED_HEALING = "ReceivedHealing"              # 26: 受到的治疗量修正
    DAMAGE_SPECIAL = "DamageSpecial"                  # 27: 特殊伤害 (如HP依存等)
    ENCHANT_DAMAGE = "EnchantDamage"                  # 34: 附魔伤害 (额外伤害?)
    ENCHANT_ATTACK = "EnchantAttack"                  # 35: 附魔攻击 (攻击属性变化?)
    PENETRATE_DEFENSE = "PenetrateDefense"            # 36: 防御穿透/破防
    MODIFY_SKILL_POWER = "ModifySkillPower"           # 40: 技能威力修正
    
    # 防御/特殊机制
    GUARD = "Guard"                                   # 18: 防御 (减伤)
    DMG_INVULNERABLE = "DmgInvulnerable"               # 44: 伤害无效 (低于阈值攻击无效)
    SHIELD = "Shield"                                 # 22: 护盾 (抵挡伤害)
    INTERCEPT = "Intercept"                           # 20: 援护/拦截
    EVADE = "Evade"                                   # 21: 回避
    SURE_HIT = "SureHit"                              # 31: 必中
    CHEAT_DEATH = "CheatDeath"                        # 30: 不屈 (锁血)
    BLOCK_EVADE = "BlockEvade"                        # 38: 禁止回避 (相当于必中状态?)
    CRITICAL_FORBIDDEN = "CriticalForbidden"           # 42: 会心不可
    SUB_UNIT = "SubUnit"                               # 43: 辅助单元 (盾+追加伤害)
    
    # 元操作
    REMOVE_AURA = "RemoveAura"                        # 19: 移除Aura (驱散)
    BLOCK_AURAS = "BlockAuras"                        # 37: 免疫Aura
    BLOCK_SPECIFIC_AURA = "BlockSpecificAura"         # 39: 免疫特定Aura
    REMOVE_BUFF_BY_TYPE = "RemoveBuffByType"          # 按类型移除buff (如 atk_up/crit_rate_up)
    BLOCK_BUFF_BY_TYPE = "BlockBuffByType"            # 阻止特定类型buff的新付与
    STEALTH = "Stealth"                               # ステルス (优先度降低)
    SPLIT_HEAL_BY_DAMAGE = "SplitHealByDamage"        # 与ダメージ分配回復
    SKILL_POWER_DOWN = "SkillPowerDown"              # 技能威力降低 (SkillPower乘区)
    
    # 脚本类
    SERVER_SCRIPT_INSTANT = "ServerScriptInstant"     # 28: 服务器瞬时脚本
    SERVER_SCRIPT_AURA = "ServerScriptAura"           # 29: 服务器状态脚本
    
    # EP获取量减少
    EP_GAIN_DOWN = "EpGainDown"                       # EP获取量减少debuff

    @property
    def is_static_debuff(self) -> bool:
        """是否为固定的负面效果（不依赖数值）"""
        return self in {
            SkillEffectType.POISON,
            SkillEffectType.CONFLAGRATION,
            SkillEffectType.FREEZE,
            SkillEffectType.KNOCKOUT,
            SkillEffectType.CONFUSION,
            SkillEffectType.MARK,
            SkillEffectType.BLOCK_AURAS, # 通常作为禁疗/禁Buff
            SkillEffectType.BLOCK_SPECIFIC_AURA,
            SkillEffectType.BLOCK_EVADE,
        }

    @property
    def is_static_buff(self) -> bool:
        """是否为固定的正面效果（不依赖数值）"""
        return self in {
            SkillEffectType.SHIELD,
            SkillEffectType.GUARD,
            SkillEffectType.INTERCEPT,
            SkillEffectType.EVADE,
            SkillEffectType.SURE_HIT,
            SkillEffectType.CHEAT_DEATH,
            SkillEffectType.PENETRATE_DEFENSE,
            SkillEffectType.HEAL_OVER_TIME,
            SkillEffectType.ENCHANT_DAMAGE,
            SkillEffectType.ENCHANT_ATTACK,
            SkillEffectType.SUB_UNIT,
            SkillEffectType.DMG_INVULNERABLE,
        }


class AuraUpdateTiming(Enum):
    """
    状态持续/结算时机 (AuraUpdateTimings)
    对应 AuraUpdateTimings.cs
    """
    EPHEMERAL_SKILL_END = 1             # 瞬时效果 (技能结束即逝)
    EPHEMERAL_MANEUVER_END = 2          # 行动结束时 (Action/Standby结束)
    DURABLE_SOURCE_MANEUVER_END = 3     # 施法者行动结束时 (Owner turns)
    DURABLE_TARGET_MANEUVER_END = 4     # 目标行动结束时 (Target turns)
    DURABLE_WHEN_USED_ONCE_PER_SKILL = 5 # 每次技能生效一次 (Charges)
    DURABLE_WHEN_USED = 6               # 生效即消耗 (Hit based)
