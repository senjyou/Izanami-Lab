#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
单位状态 - 纯数据类

职责：
- 存储单位的所有状态数据
- 提供状态验证方法
- 不包含任何业务逻辑
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


from .enums import UnitActionPhase, Side, Position

@dataclass
class BuffState:
    """Buff状态"""
    buff_id: str
    name: str
    effect_type: str
    value: float
    duration: int
    timing_type: int  # 1=回合制, 2=行动制
    stack_count: int = 1
    value_tag: int = 0 # 0=百分比, 1=固定值
    caster_attack: int = 0 # 快照攻击力 (For Poison/Burn)
    source_unit_id: str = ""
    source_skill_id: int = 0  # 来源技能ID
    is_debuff: bool = False
    hit_limited: int = 0  # 受击次数限制，0=无限制，>0=命中N次后消失
    attack_limited: int = 0  # 被攻击次数限制，0=无限制，>0=被攻击N次后消失（每次攻击全部hit都生效）
    hit_limited_flags: dict = field(default_factory=dict)  # hit_limited相关flags
    sub_unit_hp: int = 0  # 辅助单元当前HP
    sub_unit_max_hp: int = 0  # 辅助单元最大HP
    is_stackable: bool = False  # 是否可叠加buff（技能可叠加buff标记）
    is_memory_buff: bool = False  # 是否为回忆卡buff（无条件可叠加）
    damage_element: int = 0  # DealtDamage属性过滤: 0=全属性, 1=仅物理, 2=仅能量
    triggered_by_attacker: str = ""  # guard专用: 记录触发该guard的攻击者unit_id，攻击者行动结束时清理
    snapshot_crit_rate: float = 0.0  # HOT专用: 快照发起者的暴击率，用于HOT触发时判定暴击
    linked_buff_id: str = ""  # 联动buff: 当此buff消失时，linked_buff_id对应的buff也消失
    threshold_pct: float = 0.0  # dmg_invulnerable专用: 伤害阈值百分比（当前HP的X%）
    caster_alive: bool = False  # caster_alive: 施法者死亡时此buff自动消失
    original_duration_type: str = ""  # 原始duration_type（如"attacker_action"），用于攻击者行动结束时精确清理
    shield_amount: int = 0  # 盾buff贡献的实际盾值，用于叠加盾正确扣除
    hp_threshold: float = 0.0  # 条件性减伤: HP百分比阈值，仅当HP≥此值时减伤生效
    unremovable: bool = False  # 不可解除: 此buff不可被驱散或过期移除


from .enums import UnitActionPhase

@dataclass
class UnitState:
    """
    单位状态 - 纯数据类
    
    设计原则：
    1. 只存储数据，不包含业务逻辑
    2. 所有字段都是公开的
    3. 提供验证方法确保状态一致性
    """
    
    # ========== 基础信息 ==========
    unit_id: str
    name: str
    side: Side
    position: Position
    
    # ========== 角色属性（不可变，来自计算）==========
    character_id: int
    level: int
    element: int  # 1=火, 2=水, 3=风, 4=土, 5=光, 6=暗
    character_type: int  # 1=物理, 2=EN, 3=敏捷
    
    # ========== 基础属性（不可变）==========
    max_hp: int
    attack: int
    defense: int
    speed: int
    crit_rate: float
    crit_damage: float
    advantage_damage: float  # 有利属性伤害倍率
    
    # ========== 资源基准值（回合开始恢复值）==========
    initial_active_point: int  # AP (Active Point)
    initial_passive_point: int # PP (Passive Point)
    max_extra_point: int       # EP (Extra Point)
    
    # ========== 当前状态（可变）==========
    current_hp: int
    current_ap: int
    current_pp: int
    current_ep: int
    
    # ========== 护盾（可变）==========
    shield: int = 0
    physical_shield: int = 0
    en_shield: int = 0
    
    # ========== Buff列表（可变）==========
    buffs: List[BuffState] = field(default_factory=list)
    debuffs: List[BuffState] = field(default_factory=list)
    
    # ========== 技能相关（可变）==========
    skills: List[int] = field(default_factory=list)
    skill_levels: Dict[int, int] = field(default_factory=dict)
    skill_cooldowns: Dict[int, int] = field(default_factory=dict)
    skill_use_count: Dict[int, int] = field(default_factory=dict)
    
    # ========== 战斗流程相关（可变）==========
    action_phase: UnitActionPhase = UnitActionPhase.IDLE
    current_action_priority: int = 0   # 当前行动优先级（用于行动轴排序）
    
    # ========== 战斗统计（可变）==========
    action_count_total: int = 0
    damage_dealt_total: int = 0
    damage_taken_total: int = 0
    
    # ========== 状态标记（可变）==========
    is_alive: bool = True
    is_stunned: bool = False
    is_frozen: bool = False
    is_death_notified: bool = False
    skill_use_count_pending: bool = False
    role_type: int = 0  # RoleType: 1=物理アタッカー, 2=ENアタッカー, 3=タンク, 4=サポート, 5=コントロール
    position_type: int = 0  # PositionType: 1=前排, 2=后排, 3=灵活
    
    fury_count: int = 0  # 愤怒计数器（角色154301专用）
    crit_counter: int = 0  # 暴击计数器（角色119301等专用）
    is_charging: bool = False  # 蓄力中标记（蓄力技能使用后到下次行动前）
    charge_skill_id: int = 0  # 蓄力技能ID（蓄力完成后执行的技能）

    # ========== 援护相关（特殊机制，非buff/debuff）==========
    cover_target: Optional[str] = None  # 当前援护的目标unit_id，None表示没有援护任何人
    cover_skill_id: int = 0  # 援护技能的技能ID
    guard_rate: float = 0.0  # 护卫减伤百分比（百分比形式，如30表示30%）
    guard_active: bool = False  # 护卫是否激活

    # ========== HP阈值跨越检测（用于on_hp_below触发）==========
    prev_hp_percent: float = 100.0  # 上一次记录的HP百分比，用于检测阈值跨越

    # ========== 累计伤害计数（用于on_cumulative_damage触发）==========
    cumulative_hp_damage: int = 0  # 累计受到的HP伤害（仅HP部分，不含盾吸收），成功触发PS后清除

    def validate(self) -> tuple[bool, str]:
        """
        验证状态一致性
        
        Returns:
            (is_valid, error_message)
        """
        # 检查HP
        if not (0 <= self.current_hp <= self.max_hp):
            return False, f"HP异常: {self.current_hp}/{self.max_hp}"
        
        # 检查AP (AP无上限，只检查下限)
        if self.current_ap < 0:
            return False, f"AP异常: {self.current_ap}"
        
        # 检查PP (PP无上限，只检查下限)
        if self.current_pp < 0:
            return False, f"PP异常: {self.current_pp}"
        
        # 检查EP
        if not (0 <= self.current_ep <= self.max_extra_point):
            return False, f"EP异常: {self.current_ep}/{self.max_extra_point}"
        
        # 检查存活状态
        if self.current_hp == 0 and self.is_alive:
            return False, "HP为0但is_alive为True"
        
        if self.current_hp > 0 and not self.is_alive:
            return False, "HP大于0但is_alive为False"
        
        return True, ""
    
    def to_dict(self) -> dict:
        """转换为字典（用于日志和调试）"""
        return {
            'unit_id': self.unit_id,
            'name': self.name,
            'hp': f"{self.current_hp}/{self.max_hp}",
            'ap': f"{self.current_ap} (Init:{self.initial_active_point})",
            'pp': f"{self.current_pp} (Init:{self.initial_passive_point})",
            'ep': f"{self.current_ep}/{self.max_extra_point}",
            'phase': self.action_phase.value,
            'is_alive': self.is_alive,
            'buffs': len(self.buffs),
            'debuffs': len(self.debuffs),
            'side': self.side.value if hasattr(self, 'side') else 'unknown',
            'pos': self.position.name if hasattr(self, 'position') else 'unknown'
        }
