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
from typing import List, Dict, Optional, Set
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
    threshold_base: str = ""  # dmg_taken_down_threshold专用: 阈值基数来源（"current_hp"/"max_hp"），空=current_hp
    caster_alive: bool = False  # caster_alive: 施法者死亡时此buff自动消失
    original_duration_type: str = ""  # 原始duration_type（如"attacker_action"），用于攻击者行动结束时精确清理
    shield_amount: int = 0  # 盾buff贡献的实际盾值，用于叠加盾正确扣除
    shield_decay_pct: int = 0  # shield每行动衰减百分比（基于initial_shield_value）
    initial_shield_value: int = 0  # shield初始值（用于衰减计算）
    shield_decay_skipped_first: bool = False  # 衰减型盾: 是否已跳过施法当次行动（首次衰减前为False）
    hp_threshold: float = 0.0  # 条件性减伤: HP百分比阈值，仅当HP≥此值时减伤生效
    unremovable: bool = False  # 不可解除: 此buff不可被驱散或过期移除
    mark_condition: str = ""  # mark条件: 仅当攻击者持有指定mark_name时此buff/debuff才生效
    hp_ratio_dynamic: bool = False  # 动态减伤(130155): 减伤值随持有者实时HP比例变化（HP越低效果越高）
    hp_ratio_dynamic_direct: bool = False  # 动态减伤(130156): 减伤值随持有者实时HP比例变化（HP越高效果越高，线性HP100%→max HP0%→0）
    target_hp_ratio_higher_than_self: bool = False  # 条件增伤(130155 Lv11+): 仅对HP比例高于自身的敌人生效
    link_mode: str = ""  # damage_link专用: "bidirectional"=双向链接，空=单向
    block_status_list: list = field(default_factory=list)  # BlockSpecificAura专用: 被免疫的状态类型列表（如["knockout"]）
    block_status_count: int = 0  # BlockSpecificAura专用: 阻止状态异常次数限制，0=无限制，>0=阻止N个状态后消耗
    block_debuffs: bool = False  # BlockBuffByType扩展: True=阻止全debuff新付与（如141301 風紀委員会の管轄だよ～ L11+ デバフ無効）
    block_buffs: bool = False  # BlockBuffByType扩展: True=阻止全buff新付与（如230169 バフシャット「対象に向けられるバフを無効にする」）
    heal_base: str = ""  # HOT专用: 治疗基数来源（"atk"/"max_hp"/"lost_hp"），空=默认atk
    skip_restore: bool = False  # 跳过恢复逻辑: 当次行动新施加的buff在行动结束时正常递减duration（如「再起律動」)
    just_applied: bool = False  # 当次行动中由add_aura施加/刷新/忽略的buff标记，process_maneuver_end跳过递减
    confusion_dmg_reduction: float = 0.0  # 混乱专用: 伤害减免百分比（如50表示减免50%）
    confusion_proxy_atk_pct: float = 0.0  # 混乱专用: 代理数值百分比（如10表示ATK×10%替代ATK-DEF）
    sub_unit_link_group: str = ""  # [GAME_BUG_SIMULATION] 跨目标联动失效: 同一次技能(如110050)创建的多个子機共享同一link_group，任一失效时其余同步失效
    source_death_remove: bool = False  # 付与者死亡时清除: 施法者被击败时此buff/debuff自动消失（如130161 PS1 def_down「防御デバフは付与者が倒れると解除される」）


@dataclass
class DamageLinkEntry:
    """ダメージリンク独立存储条目（不属于buff/debuff，不受buff移除影响）。

    设计要点：
    - link关系存储在双方单位上（双向施加），任一方死亡时双方同步清除
    - direction字段区分转送方向：
      - "outgoing": 持有者受伤害时，转送给partner_unit_id
      - "incoming": partner_unit_id受伤害时，转送给持有者（仅作为配对记录，不主动触发）
      - "bidirectional": 双向（兼容旧逻辑）
    - 不受remove_buff/remove_debuff影响，只能通过remove_damage_links effect或单位死亡清除
    """
    link_id: str  # 唯一ID（uuid），同一link关系的双方共享同一link_id
    partner_unit_id: str  # 配对单位ID（接收转送伤害的单位）
    value: float  # 转送比例(%)
    source_skill_id: int  # 来源技能ID
    source_unit_id: str  # 施法者ID（用于追溯）
    direction: str = "outgoing"  # "outgoing"/"incoming"/"bidirectional"
    is_unremovable: bool = False  # 解除不可（仍可被remove_damage_links清除）
    is_sharing: bool = False  # 伤害共享（源目标不回退HP，如110071/210114）vs 伤害转移（默认）
    duration: int = -1  # 持续时间，-1=永久
    duration_type: str = ""  # "action"/"turn"/""，空=永久
    just_applied: bool = False  # 当次行动新施加标记，process_maneuver_end跳过递减


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
    current_ep: float  # EP允许小数存储（ep_gain_down debuff影响）
    
    # ========== 护盾（可变）==========
    shield: int = 0
    physical_shield: int = 0
    en_shield: int = 0
    
    # ========== Buff列表（可变）==========
    buffs: List[BuffState] = field(default_factory=list)
    debuffs: List[BuffState] = field(default_factory=list)

    # ========== ダメージリンク（独立存储，不属于buff/debuff）==========
    # 重构后：damage_link不再作为buff存储，改为独立字段
    # 不受remove_buff/remove_debuff影响，只能通过remove_damage_links effect或单位死亡清除
    damage_links: List[DamageLinkEntry] = field(default_factory=list)
    
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
    is_confused: bool = False
    is_genwaku: bool = False
    is_darkness: bool = False
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
    reflect_rate: float = 0.0  # 反射伤害百分比（百分比形式，如50表示反射受到伤害的50%），cover期间生效

    # ========== HP阈值跨越检测（用于on_hp_below触发）==========
    prev_hp_percent: float = 100.0  # 上一次记录的HP百分比，用于检测阈值跨越

    # ========== 累计伤害计数（用于on_cumulative_damage触发）==========
    cumulative_hp_damage: int = 0  # 累计受到的HP伤害（仅HP部分，不含盾吸收），成功触发PS后清除

    # ========== once_per_battle PS触发记录 ==========
    # 记录已成功触发的once_per_battle PS skill_id，确保整个战斗中只触发一次
    once_per_battle_triggered: Set[int] = field(default_factory=set)

    # ========== 最近受到的伤害（用于反撃系PS，如ストイックリコイル）==========
    last_received_damage: int = 0  # 最近一次受到的伤害（包括被盾吸收的部分，不含溢出）

    # ========== max_hp_up计算基准（原始base max_hp，不受stage up影响）==========
    # max_hp_up增量基于此字段计算，而非当前max_hp
    # 战斗开始时由__post_init__初始化为max_hp；synergy等比例修改max_hp时同步缩放
    # stage up重置max_hp时不修改此字段（保持原始base，避免max_hp_up增量随stage膨胀）
    _base_max_hp_for_calc: int = 0

    def __post_init__(self):
        if self._base_max_hp_for_calc == 0:
            self._base_max_hp_for_calc = self.max_hp

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
