#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自定义木桩角色数据模型
src/entities_v2/custom_dummy.py

提供自定义木桩的配置数据类和向现有系统注入的构建函数。
负ID避免与真实数据冲突。

配置 schema 版本：2（见 DUMMY_SCHEMA_VERSION）。
v1 → v2 变更：新增 level / sub_element / initial_ep / max_extra_point / note；
序列化统一走 CustomDummyConfig.to_dict() / from_dict()，修复旧版
`hit_count` 键与 dataclass 字段 `hit_count_legacy` 不匹配导致段数丢失的问题。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from ..data.models import (
    CharacterData, BaseStats, BonusStats, StatGrades,
    SkillData, SkillDescription, AdditionalKind,
    TemplateTag, TemplateTagValue, DisplayInfo,
)
from .enums import (
    TriggerTiming, Attribute, CharacterType, PositionType, RoleType,
    DisplayTargetRange, DisplayTargetType,
)


# ── 效果配置 ──

# 配置 schema 版本（写入 JSON，加载时按版本迁移）
DUMMY_SCHEMA_VERSION = 2

# 支持的效果类型分类
EFFECT_CATEGORIES = {
    "伤害": ["damage", "hp_ratio_damage"],
    "治疗": ["heal", "heal_over_time"],
    "增益": ["atk_up", "def_up", "spd_up", "crit_rate_up", "crit_dmg_up",
             "dmg_dealt_up", "dmg_taken_down", "shield", "max_hp_up",
             "heal_efficacy_up", "skill_power_up", "ep_gain_up", "add_max_ap",
             "guard", "dmg_invulnerable", "perfect_evasion"],
    "减益": ["atk_down", "def_down", "spd_down", "crit_rate_down",
             "dmg_dealt_down", "dmg_taken_up",
             "heal_efficacy_down", "ep_gain_down"],
    "状态异常": ["add_status"],
    "资源": ["add_ap", "remove_ap", "add_ep"],
}

# 效果类型显示名映射
EFFECT_TYPE_DISPLAY = {
    "damage": "伤害", "hp_ratio_damage": "HP比例伤害",
    "heal": "治疗", "heal_over_time": "持续治疗",
    "atk_up": "攻击力UP", "def_up": "防御力UP",
    "spd_up": "速度UP", "crit_rate_up": "暴击率UP",
    "crit_dmg_up": "暴击伤害UP", "dmg_dealt_up": "造成伤害UP",
    "dmg_taken_down": "受到伤害DOWN", "shield": "护盾",
    "max_hp_up": "最大HP UP",
    "atk_down": "攻击力DOWN", "def_down": "防御力DOWN",
    "spd_down": "速度DOWN", "crit_rate_down": "暴击率DOWN",
    "dmg_dealt_down": "造成伤害DOWN", "dmg_taken_up": "受到伤害UP",
    "add_status": "状态异常", "add_ap": "AP回复",
    "remove_ap": "AP减少", "add_ep": "EP回复",
    "heal_efficacy_up": "治疗量UP", "heal_efficacy_down": "治疗量DOWN",
    "skill_power_up": "技能威力UP",
    "ep_gain_up": "EP获得UP", "ep_gain_down": "EP获得DOWN",
    "add_max_ap": "最大AP UP",
    "guard": "防御(Guard)", "dmg_invulnerable": "伤害无效",
    "perfect_evasion": "完全回避",
}

EFFECT_DISPLAY_REVERSE = {v: k for k, v in EFFECT_TYPE_DISPLAY.items()}

# 状态异常类型（须与 skill_service._MASTERDATA_STATUS_MAP 的键一致）
STATUS_TYPE_DISPLAY = {
    "stun": "眩晕", "poison": "毒", "burn": "炎上",
    "freeze": "冻结", "mark": "标记",
    "confusion": "混乱", "genwaku": "幻惑", "darkness": "暗闇",
}
STATUS_DISPLAY_REVERSE = {v: k for k, v in STATUS_TYPE_DISPLAY.items()}

# 持续时间类型
DURATION_TYPE_DISPLAY = {"turn": "回合", "action": "行动"}
DURATION_DISPLAY_REVERSE = {v: k for k, v in DURATION_TYPE_DISPLAY.items()}

# 效果需要哪些字段
EFFECT_FIELD_FLAGS = {
    "damage":              {"value": True, "hit_count": True,  "duration": False, "duration_type": False, "status_name": False},
    "hp_ratio_damage":     {"value": True, "hit_count": False, "duration": False, "duration_type": False, "status_name": False},
    "heal":                {"value": True, "hit_count": False, "duration": False, "duration_type": False, "status_name": False},
    "heal_over_time":      {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "atk_up":              {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "def_up":              {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "spd_up":              {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "crit_rate_up":        {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "crit_dmg_up":         {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "dmg_dealt_up":        {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "dmg_taken_down":      {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "shield":              {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "max_hp_up":           {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "atk_down":            {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "def_down":            {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "spd_down":            {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "crit_rate_down":      {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "dmg_dealt_down":      {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "dmg_taken_up":        {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "add_status":          {"value": False, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": True},
    "add_ap":              {"value": True, "hit_count": False, "duration": False, "duration_type": False, "status_name": False},
    "remove_ap":           {"value": True, "hit_count": False, "duration": False, "duration_type": False, "status_name": False},
    "add_ep":              {"value": True, "hit_count": False, "duration": False, "duration_type": False, "status_name": False},
    # v2 新增：buff/debuff 类（均为 value + duration）
    "heal_efficacy_up":    {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "heal_efficacy_down":  {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "skill_power_up":      {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "ep_gain_up":          {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "ep_gain_down":        {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "add_max_ap":          {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "guard":               {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "dmg_invulnerable":    {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
    "perfect_evasion":     {"value": True, "hit_count": False, "duration": True,  "duration_type": True,  "status_name": False},
}


@dataclass
class CustomEffectConfig:
    """单个技能效果配置"""
    effect_type: str = "damage"
    value: float = 100.0
    hit_count: int = 1
    duration: int = 2
    duration_type: str = "turn"
    status_name: str = "stun"


@dataclass
class CustomASConfig:
    name: str = "自定义AS"
    effects: List[CustomEffectConfig] = field(default_factory=lambda: [CustomEffectConfig()])
    cooldown: int = 0
    cooldown_update_timing: int = 1
    target_type: int = 3
    target_range: int = 1
    target_priority: int = 0
    resource_cost: int = 1

    # 向后兼容：旧配置可能仍有 power/hit_count 字段
    power: int = 0
    hit_count_legacy: int = 0

    def get_effects(self) -> List[CustomEffectConfig]:
        """获取效果列表，兼容旧配置的power/hit_count"""
        if self.effects:
            return self.effects
        # 旧配置：从power/hit_count生成damage效果
        if self.power > 0:
            return [CustomEffectConfig(
                effect_type="damage",
                value=float(self.power),
                hit_count=max(1, self.hit_count_legacy) if self.hit_count_legacy > 0 else 1,
            )]
        return [CustomEffectConfig()]


@dataclass
class CustomPSConfig:
    name: str = "自定义PS"
    effects: List[CustomEffectConfig] = field(default_factory=lambda: [CustomEffectConfig()])
    cooldown: int = 0
    cooldown_update_timing: int = 1
    target_type: int = 3
    target_range: int = 1
    target_priority: int = 0
    resource_cost: int = 1
    trigger_timing: str = "BeforeAsAttacked"

    # 向后兼容
    power: int = 0
    hit_count_legacy: int = 0

    def get_effects(self) -> List[CustomEffectConfig]:
        """获取效果列表，兼容旧配置的power/hit_count"""
        if self.effects:
            return self.effects
        if self.power > 0:
            return [CustomEffectConfig(
                effect_type="damage",
                value=float(self.power),
                hit_count=max(1, self.hit_count_legacy) if self.hit_count_legacy > 0 else 1,
            )]
        return [CustomEffectConfig()]


@dataclass
class CustomDummyConfig:
    name: str = "木桩"
    element: int = 1
    character_type: int = 1
    position_type: int = 3
    role_type: int = 1
    hp: int = 10000
    attack: int = 1000
    defense: int = 500
    crit_rate: float = 0.15
    # 暴击伤害「倍率」语义（1.5 = 无额外暴伤；与角色面板同口径）。
    # 注入 UnitState 时会换算为 bonus = crit_damage - 1.5。
    crit_damage: float = 1.5
    speed: int = 500
    # 克制时的额外有利伤害加成（加在 1.25 之上）：0.0 = 无额外，
    # 0.255 = 3 条彩S有利词条（总克制倍率 1.505）。
    advantage_damage: float = 0.0
    ap: int = 5
    pp: int = 5
    as_skills: List[CustomASConfig] = field(default_factory=list)
    ps_skills: List[CustomPSConfig] = field(default_factory=list)
    permanent_shield_type: int = 0
    permanent_shield_value: int = 0
    # ── v2 新增字段 ──
    level: int = 280                 # 单位等级（旧版固定 1，与角色 280 级口径不一致）
    sub_element: int = 0             # 副属性（双属性敌方，0=无）
    initial_ep: float = 0.0          # 初始 EP（需 max_extra_point > 0 才有意义）
    max_extra_point: int = 0         # EP 上限，0=按 EX 技能自动推断（无 EX 则 0）
    note: str = ""                   # 用途备注（打桩口径说明，不影响战斗）
    # 追加技能ID：直接引用技能表中的真实技能（用于复刻演习敌方 AI/技能组，
    # 或给木桩挂一个真实攻击技能）。这些技能不参与 CustomAS/PS 的构建。
    extra_skill_ids: List[int] = field(default_factory=list)

    # ── 序列化 ──
    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 字典（schema v2）。"""
        return {
            "schema_version": DUMMY_SCHEMA_VERSION,
            "name": self.name,
            "element": self.element,
            "character_type": self.character_type,
            "position_type": self.position_type,
            "role_type": self.role_type,
            "hp": self.hp,
            "attack": self.attack,
            "defense": self.defense,
            "crit_rate": self.crit_rate,
            "crit_damage": self.crit_damage,
            "speed": self.speed,
            "advantage_damage": self.advantage_damage,
            "ap": self.ap,
            "pp": self.pp,
            "level": self.level,
            "sub_element": self.sub_element,
            "initial_ep": self.initial_ep,
            "max_extra_point": self.max_extra_point,
            "note": self.note,
            "extra_skill_ids": list(self.extra_skill_ids),
            "permanent_shield_type": self.permanent_shield_type,
            "permanent_shield_value": self.permanent_shield_value,
            "as_skills": [
                {
                    "name": s.name,
                    "effects": [field_dict(e) for e in s.effects],
                    "cooldown": s.cooldown,
                    "cooldown_update_timing": s.cooldown_update_timing,
                    "target_type": s.target_type,
                    "target_range": s.target_range,
                    "target_priority": s.target_priority,
                    "resource_cost": s.resource_cost,
                    # legacy 字段原样保留，避免旧配置回写后丢数据
                    "power": s.power,
                    "hit_count": s.hit_count_legacy,
                }
                for s in self.as_skills
            ],
            "ps_skills": [
                {
                    "name": s.name,
                    "effects": [field_dict(e) for e in s.effects],
                    "cooldown": s.cooldown,
                    "cooldown_update_timing": s.cooldown_update_timing,
                    "target_type": s.target_type,
                    "target_range": s.target_range,
                    "target_priority": s.target_priority,
                    "resource_cost": s.resource_cost,
                    "trigger_timing": s.trigger_timing,
                    "power": s.power,
                    "hit_count": s.hit_count_legacy,
                }
                for s in self.ps_skills
            ],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CustomDummyConfig":
        """从 JSON 字典反序列化，兼容 v1（缺字段走默认值）。"""
        def _effects(raw) -> List[CustomEffectConfig]:
            out = []
            for e in raw or []:
                out.append(CustomEffectConfig(
                    effect_type=e.get("effect_type", "damage"),
                    value=float(e.get("value", 100.0) or 0.0),
                    hit_count=int(e.get("hit_count", 1) or 1),
                    duration=int(e.get("duration", 2) or 0),
                    duration_type=e.get("duration_type", "turn"),
                    status_name=e.get("status_name", "stun"),
                ))
            return out

        def _skill_common(s: Dict[str, Any]) -> Dict[str, Any]:
            return dict(
                name=s.get("name", "自定义技能"),
                effects=_effects(s.get("effects")),
                cooldown=int(s.get("cooldown", 0) or 0),
                cooldown_update_timing=int(s.get("cooldown_update_timing", 1) or 1),
                target_type=int(s.get("target_type", 3) or 3),
                target_range=int(s.get("target_range", 1) or 1),
                target_priority=int(s.get("target_priority", 0) or 0),
                resource_cost=int(s.get("resource_cost", 1) or 0),
                power=int(s.get("power", 0) or 0),
                hit_count_legacy=int(s.get("hit_count", s.get("hit_count_legacy", 0)) or 0),
            )

        return cls(
            name=d.get("name", "木桩"),
            element=int(d.get("element", 1) or 1),
            character_type=int(d.get("character_type", 1) or 1),
            position_type=int(d.get("position_type", 3) or 3),
            role_type=int(d.get("role_type", 1) or 1),
            hp=int(d.get("hp", 10000) or 0),
            attack=int(d.get("attack", 1000) or 0),
            defense=int(d.get("defense", 500) or 0),
            crit_rate=float(d.get("crit_rate", 0.15) or 0.0),
            crit_damage=float(d.get("crit_damage", 1.5) or 1.5),
            speed=int(d.get("speed", 500) or 0),
            advantage_damage=float(d.get("advantage_damage", 0.0) or 0.0),
            ap=int(d.get("ap", 5) or 0),
            pp=int(d.get("pp", 5) or 0),
            permanent_shield_type=int(d.get("permanent_shield_type", 0) or 0),
            permanent_shield_value=int(d.get("permanent_shield_value", 0) or 0),
            level=int(d.get("level", 280) or 280),
            sub_element=int(d.get("sub_element", 0) or 0),
            initial_ep=float(d.get("initial_ep", 0.0) or 0.0),
            max_extra_point=int(d.get("max_extra_point", 0) or 0),
            note=d.get("note", "") or "",
            extra_skill_ids=[int(x) for x in (d.get("extra_skill_ids") or [])],
            as_skills=[CustomASConfig(**_skill_common(s)) for s in (d.get("as_skills") or [])],
            ps_skills=[CustomPSConfig(**_skill_common(s), trigger_timing=s.get("trigger_timing", "BeforeAsAttacked"))
                       for s in (d.get("ps_skills") or [])],
        )


def field_dict(e: "CustomEffectConfig") -> Dict[str, Any]:
    """CustomEffectConfig → dict（asdict 的显式版，保证键名稳定）。"""
    return {
        "effect_type": e.effect_type,
        "value": e.value,
        "hit_count": e.hit_count,
        "duration": e.duration,
        "duration_type": e.duration_type,
        "status_name": e.status_name,
    }


# ── 配置校验 ──

# 合法枚举范围（与 gui/constants.py、enums.py 对齐）
_VALID_ELEMENT = (1, 2, 3, 4, 5, 6)
_VALID_CHAR_TYPE = (1, 2, 3)
_VALID_POSITION_TYPE = (1, 2, 3)
_VALID_ROLE_TYPE = (1, 2, 3, 4, 5)
_VALID_SHIELD_TYPE = (0, 1, 2, 3)
_VALID_TARGET_TYPE = tuple(range(1, 6))
_VALID_TARGET_RANGE = tuple(range(1, 8))
_VALID_TARGET_PRIORITY = tuple(range(0, 6))
MAX_AS_SKILLS = 4
MAX_PS_SKILLS = 4
MAX_EXTRA_SKILLS = 8


def validate_dummy_config(cfg: CustomDummyConfig) -> List[tuple]:
    """校验木桩配置。

    Returns:
        [(level, message), ...]，level ∈ {"error", "warning", "info"}。
        error 会导致注册被拒绝；warning/info 仅提示。
    """
    issues: List[tuple] = []

    def err(msg): issues.append(("error", msg))
    def warn(msg): issues.append(("warning", msg))
    def info(msg): issues.append(("info", msg))

    if not (cfg.name or "").strip():
        err("名称不能为空")
    if cfg.level <= 0 or cfg.level > 999:
        err(f"等级必须在 1~999（当前 {cfg.level}）")
    if cfg.element not in _VALID_ELEMENT:
        err(f"属性非法：{cfg.element}")
    if cfg.sub_element and cfg.sub_element not in _VALID_ELEMENT:
        err(f"副属性非法：{cfg.sub_element}")
    if cfg.character_type not in _VALID_CHAR_TYPE:
        err(f"类型非法：{cfg.character_type}")
    if cfg.position_type not in _VALID_POSITION_TYPE:
        err(f"位置非法：{cfg.position_type}")
    if cfg.role_type not in _VALID_ROLE_TYPE:
        err(f"定位非法：{cfg.role_type}")
    if cfg.hp < 1:
        err(f"HP 必须 ≥ 1（当前 {cfg.hp}）")
    for label, val in (("ATK", cfg.attack), ("DEF", cfg.defense), ("速度", cfg.speed),
                       ("AP", cfg.ap), ("PP", cfg.pp)):
        if val < 0:
            err(f"{label} 不能为负（当前 {val}）")
    if not (0.0 <= cfg.crit_rate <= 1.0):
        err(f"暴击率必须在 0~1（当前 {cfg.crit_rate}）")
    if not (1.0 <= cfg.crit_damage <= 10.0):
        err(f"暴击伤害倍率必须在 1.0~10.0（当前 {cfg.crit_damage}；1.5=无额外暴伤）")
    if not (-1.25 <= cfg.advantage_damage <= 3.0):
        err(f"有利加成必须在 -1.25~3.0（当前 {cfg.advantage_damage}；0.255=3条彩S词条）")
    elif cfg.advantage_damage > 1.0:
        warn("有利加成 > 1.0，克制倍率将超过 2.25，请确认取值口径")
    if cfg.permanent_shield_type not in _VALID_SHIELD_TYPE:
        err(f"永久盾类型非法：{cfg.permanent_shield_type}")
    if cfg.permanent_shield_type and cfg.permanent_shield_value <= 0:
        warn("已选择永久盾类型但盾值为 0，不会产生护盾")
    if cfg.max_extra_point < 0:
        err("EP 上限不能为负")
    if cfg.max_extra_point == 0 and cfg.initial_ep > 0:
        warn("设置了初始 EP 但 EP 上限为 0（自动推断），若该木桩无 EX 技能则 EP 会被清零")
    if len(cfg.as_skills) > MAX_AS_SKILLS:
        err(f"AS 技能最多 {MAX_AS_SKILLS} 个（当前 {len(cfg.as_skills)}）")
    if len(cfg.ps_skills) > MAX_PS_SKILLS:
        err(f"PS 技能最多 {MAX_PS_SKILLS} 个（当前 {len(cfg.ps_skills)}）")
    if len(cfg.extra_skill_ids) > MAX_EXTRA_SKILLS:
        warn(f"追加技能超过 {MAX_EXTRA_SKILLS} 个（当前 {len(cfg.extra_skill_ids)}），行为可能与预期不同")
    for sid in cfg.extra_skill_ids:
        if not isinstance(sid, int) or sid <= 0:
            err(f"追加技能ID必须为正整数：{sid!r}")

    def _check_skill(s, label: str):
        if s.cooldown < 0:
            err(f"{label} 冷却不能为负")
        if s.resource_cost < 0:
            err(f"{label} 消耗不能为负")
        if s.target_type not in _VALID_TARGET_TYPE:
            warn(f"{label} 目标类型 {s.target_type} 不在常用范围 1~5")
        if s.target_range not in _VALID_TARGET_RANGE:
            warn(f"{label} 范围 {s.target_range} 不在常用范围 1~7")
        if s.target_priority not in _VALID_TARGET_PRIORITY:
            warn(f"{label} 优先级 {s.target_priority} 不在 0~5")
        if not s.effects and s.power <= 0:
            warn(f"{label} 没有任何效果，该技能不会产生结算")
        if s.target_type == 3 and s.target_range not in (1, 5):
            info(f"{label} 范围 {s.target_range} 会被实际结算归类为"
                 f"{'单体' if s.target_range == 1 else '全体'}（引擎只区分单/全，"
                 f"详见审计文档 §3.1-2）")
        for i, e in enumerate(s.effects, 1):
            if e.effect_type not in EFFECT_FIELD_FLAGS:
                err(f"{label} 效果#{i} 类型未支持：{e.effect_type}")
                continue
            flags = EFFECT_FIELD_FLAGS[e.effect_type]
            if flags.get("hit_count") and e.hit_count < 1:
                err(f"{label} 效果#{i} 段数必须 ≥ 1")
            if flags.get("value") and e.effect_type == "damage" and e.value <= 0:
                err(f"{label} 效果#{i} 伤害威力必须 > 0")
            if flags.get("duration") and e.duration < 0:
                err(f"{label} 效果#{i} 持续时间不能为负")
            if flags.get("duration") and e.duration == 0:
                warn(f"{label} 效果#{i} 持续填 0 表示「永久」，如需 1 回合请填 1")
            if flags.get("duration_type") and e.duration_type not in ("turn", "action"):
                err(f"{label} 效果#{i} 计时类型非法：{e.duration_type}")
            if flags.get("status_name") and e.status_name not in STATUS_TYPE_DISPLAY:
                err(f"{label} 效果#{i} 状态类型非法：{e.status_name}")
            # 增益/治疗配「敌方全体」会被按「给自己」处理（v2 作用对象修复），提示用户
            if (s.target_type == 3 and e.effect_type in FRIENDLY_EFFECT_TYPES
                    and e.effect_type not in HOSTILE_EFFECT_TYPES):
                info(f"{label} 效果#{i}「{EFFECT_TYPE_DISPLAY.get(e.effect_type, e.effect_type)}」"
                     f"是增益/治疗类，实际作用对象为自身（不会落到敌方）")

    for i, s in enumerate(cfg.as_skills, 1):
        _check_skill(s, f"AS{i}")
    for i, s in enumerate(cfg.ps_skills, 1):
        _check_skill(s, f"PS{i}")

    if not cfg.as_skills and not cfg.ps_skills:
        info("没有任何技能：该木桩在战斗中会一直待机（适合做纯打桩靶）")
    if cfg.hp > 100_000_000:
        info("HP > 1e8：数值已远超真实单位，用作「不会被打死的靶子」，请勿当作游戏内数值")
    if cfg.level != 280:
        info(f"等级 {cfg.level} 与当前拉表标准（280 级）不同")

    return issues


def config_errors(cfg: CustomDummyConfig) -> List[str]:
    return [m for lv, m in validate_dummy_config(cfg) if lv == "error"]


# 引擎中没有任何派发点的触发时机（GUI 曾可选但永不触发）
# 证据见 docs/木桩功能审计.md §3.1-4（TriggerService.check_triggers 的调用点集合）
DEAD_TRIGGER_TIMINGS = frozenset({
    "BeforeSkillEffectsApply",
    "PawnReceivedDamage",
    "PawnReceivedHealing",
    "BattleEnd",
})


def filter_trigger_timings(options: List[tuple]) -> List[tuple]:
    """过滤掉引擎永不派发的触发时机，返回 [(显示名, 枚举值), ...]。"""
    return [(label, value) for label, value in options if value not in DEAD_TRIGGER_TIMINGS]


def _make_template_tag(name: str, value: float) -> TemplateTag:
    return TemplateTag(
        tag_name=name,
        interpolation_mode=1,
        values=[TemplateTagValue(level=1, value=value)],
    )


def build_synthetic_character_data(
    dummy_index: int,
    cfg: CustomDummyConfig,
) -> CharacterData:
    char_id = -(dummy_index + 1)
    stats = BaseStats(
        level=max(1, cfg.level),
        hp=cfg.hp,
        attack=cfg.attack,
        defense=cfg.defense,
        speed=cfg.speed,
        crit_rate=cfg.crit_rate,
    )
    return CharacterData(
        character_id=char_id,
        name=cfg.name,
        character_base_id=char_id,
        default_rarity=1,
        character_type=cfg.character_type,
        attribute=cfg.element,
        sub_attribute=cfg.sub_element if cfg.sub_element and cfg.sub_element != cfg.element else 0,
        position_type=PositionType(cfg.position_type).value if cfg.position_type in (1, 2, 3) else PositionType.FLEXIBLE.value,
        role_type=RoleType(cfg.role_type).value if cfg.role_type in (1, 2, 3, 4, 5) else RoleType.PHYSICAL_ATTACKER.value,
        action_point=cfg.ap,
        passive_point=cfg.pp,
        min_level_stats=stats,
        max_level_stats=stats,
        bonus_per_level=BonusStats(hp=0, attack=0, defense=0, speed=0, crit_rate=0.0),
        grades=StatGrades(hp_grade=1, attack_grade=1, defense_grade=1,
                          speed_grade=1, crit_rate_grade=1),
    )


def _skill_id_for(dummy_index: int, is_ps: bool, skill_idx: int) -> int:
    base = -(dummy_index + 1) * 1000
    offset = 500 if is_ps else 0
    return base - offset - skill_idx


# ── 效果作用对象解析（v2 修复） ──────────────────────────────────────
#
# v1 把每个效果的 target_type 硬编码为 "selected"，而引擎的
# `SkillService._resolve_target_type` 不认识这个字符串（白名单只有
# self/friends/enemies/all/... ），最终落到兜底值 ENEMIES：
#   · damage / debuff / add_status / remove_ap 恰好落在敌方 → 看起来正常；
#   · buff / heal / shield / HoT 也落在敌方 → 等于「给对手上 buff / 治疗对手」。
# 同时技能级的 target_type / target_range 只写进 display_*，不参与索敌，
# 导致「打谁、打几个」不可控（详见 docs/木桩功能审计.md §3.1）。
#
# 修复策略：按效果性质 + 技能级目标组合成引擎认识的 effect target_type。
#   · 友善类（治疗/增益/护盾/资源回复）默认落在自己或友方，绝不落到敌方；
#   · 敌对类（伤害/减益/状态异常/资源削减）按技能级目标落在敌方；
#   · 技能级 target_type 语义沿用 GUI 的展示枚举（1=自身 2=自身+友方
#     3=敌方全体 4=友方全体 5=全场）。

FRIENDLY_EFFECT_TYPES = frozenset({
    "heal", "heal_over_time", "shield", "max_hp_up", "guard",
    "dmg_invulnerable", "perfect_evasion",
    "atk_up", "def_up", "spd_up", "crit_rate_up", "crit_dmg_up",
    "dmg_dealt_up", "dmg_taken_down",
    "heal_efficacy_up", "skill_power_up", "ep_gain_up", "add_max_ap",
    "add_ap", "add_ep",
})
HOSTILE_EFFECT_TYPES = frozenset({
    "damage", "hp_ratio_damage", "add_status", "remove_ap",
    "atk_down", "def_down", "spd_down", "crit_rate_down",
    "dmg_dealt_down", "dmg_taken_up",
    "heal_efficacy_down", "ep_gain_down",
})


def _effect_target_key(effect_type: str, target_type: int, target_range: int) -> str:
    """把「效果性质 + 技能级目标」翻译成引擎认得的 effect target_type。"""
    friendly = effect_type not in HOSTILE_EFFECT_TYPES
    tt = int(target_type or 3)

    if tt == 1:                     # 自身
        return "self"
    if tt == 2:                     # 自身 + 友方
        return "self_and_friends"
    if tt == 4:                     # 友方全体
        return "ally_all" if friendly else "friends"
    if tt == 5:                     # 全场
        return "all"
    # tt == 3 敌方全体（默认值）
    if friendly:
        # 增益/治疗配「敌方全体」没有意义，按「给自己」处理，避免打到对手
        return "self"
    return "enemy_single" if int(target_range or 1) == 1 else "enemies"


def _build_effect_dict(efg: CustomEffectConfig, effect_idx: int,
                       target_type: int = 3, target_range: int = 1) -> Dict[str, Any]:
    """根据效果配置构建单个效果的字典（含作用对象解析）。"""
    effect: Dict[str, Any] = {
        "effect_type": efg.effect_type,
        "target_type": _effect_target_key(efg.effect_type, target_type, target_range),
    }

    flags = EFFECT_FIELD_FLAGS.get(efg.effect_type, {})

    if flags.get("value", False):
        if efg.effect_type == "damage":
            # damage使用value_tag引用template tag
            tag_name = f"威力_{effect_idx}" if effect_idx > 0 else "威力"
            effect["value_tag"] = tag_name
        else:
            effect["value"] = efg.value

    if flags.get("hit_count", False) and efg.hit_count > 1:
        if efg.effect_type == "damage":
            tag_name = f"攻撃回数_{effect_idx}" if effect_idx > 0 else "攻撃回数"
            effect["hit_count_tag"] = tag_name
        else:
            effect["hit_count"] = efg.hit_count

    if flags.get("duration", False) and efg.duration > 0:
        effect["duration"] = efg.duration

    if flags.get("duration_type", False):
        effect["duration_type"] = efg.duration_type

    if flags.get("status_name", False) and efg.status_name:
        effect["status_name"] = efg.status_name
        effect["flags"] = {"status_type": efg.status_name}

    return effect


def build_custom_skill_data(dummy_index: int, is_ps: bool, skill_idx: int,
                            name: str, effects: List[CustomEffectConfig],
                            cooldown: int, cooldown_update_timing: int,
                            target_type: int, target_range: int, target_priority: int,
                            resource_cost: int) -> SkillData:
    sid = _skill_id_for(dummy_index, is_ps, skill_idx)
    skill_type = 2 if is_ps else 1

    # 从效果列表构建template tags
    tags: Dict[str, TemplateTag] = {}
    for i, efg in enumerate(effects):
        flags = EFFECT_FIELD_FLAGS.get(efg.effect_type, {})
        if flags.get("value", False) and efg.effect_type == "damage":
            tag_name = f"威力_{i}" if i > 0 else "威力"
            tags[tag_name] = _make_template_tag(tag_name, efg.value)
        if flags.get("hit_count", False) and efg.effect_type == "damage" and efg.hit_count > 1:
            tag_name = f"攻撃回数_{i}" if i > 0 else "攻撃回数"
            tags[tag_name] = _make_template_tag(tag_name, float(efg.hit_count))

    # 确保至少有一个威力tag（兼容旧逻辑）
    if not any("威力" in k for k in tags):
        tags["威力"] = _make_template_tag("威力", 100.0)

    return SkillData(
        skill_id=sid,
        name=name,
        skill_type=skill_type,
        skill_kind=0,
        resource_cost=resource_cost,
        cooldown=cooldown if cooldown > 0 else 0,
        cooldown_update_timing=cooldown_update_timing if cooldown > 0 else None,
        default_max_level=1,
        features=0,
        skill_level_pattern_id=0,
        additional_kinds=[],
        descriptions=[],
        template_tags=tags,
        display_info=DisplayInfo(
            target_type=target_type,
            target_range=target_range,
            target_priority=target_priority,
        ),
    )


def build_custom_parsed_skill(
    dummy_index: int, is_ps: bool, skill_idx: int,
    target_type: int, target_range: int, target_priority: int,
    effects: List[CustomEffectConfig],
    trigger_timing: Optional[str] = None,
) -> Dict[str, Any]:
    sid = _skill_id_for(dummy_index, is_ps, skill_idx)

    # 从效果列表构建effect列表（作用对象由 效果性质 × 技能级目标 决定）
    effect_list = []
    for i, efg in enumerate(effects):
        effect_list.append(_build_effect_dict(efg, i, target_type, target_range))

    # 如果没有效果，默认生成一个damage效果（打到单个敌人）
    if not effect_list:
        effect_list.append({
            "effect_type": "damage",
            "target_type": "enemy_single",
            "value_tag": "威力",
        })

    # 让 display_target_* 与实际效果索敌保持一致。
    # 旧实现里 display_target_range 被「攻击前预扫描」使用，而伤害按 effect.target_type
    # 结算；两者不一致会让触发器/援护选错目标（见 docs/木桩功能审计.md §3.1-2）。
    keys = {e["target_type"] for e in effect_list}
    single_keys = {"self", "enemy_single", "ally_single", "triggered_by", "drawn_target"}
    eff_range = DisplayTargetRange.ONE_PAWN.value if keys <= single_keys \
        else DisplayTargetRange.ALL_PAWNS.value

    if "all" in keys:
        eff_type = DisplayTargetType.SELF_AND_FRIENDS_AND_ENEMIES.value
    elif keys & {"enemies", "enemy_single"}:
        eff_type = DisplayTargetType.ENEMIES.value
    elif keys == {"self"}:
        eff_type = DisplayTargetType.SELF.value
    elif "self_and_friends" in keys or "ally_all" in keys:
        eff_type = DisplayTargetType.SELF_AND_FRIENDS.value
    elif "friends" in keys:
        eff_type = DisplayTargetType.FRIENDS.value
    else:
        eff_type = DisplayTargetType.ENEMIES.value

    parsed = {
        "skill_id": sid,
        "display_target_type": eff_type,
        "display_target_range": eff_range,
        "display_target_priority": target_priority,
        # 保留用户原始配置，便于调试/回显（不参与索敌）
        "configured_target_type": target_type,
        "configured_target_range": target_range,
        "effect_blocks": [
            {
                "block_id": 0,
                "effects": effect_list,
            }
        ],
    }
    if trigger_timing:
        parsed["trigger_type"] = TriggerTiming(trigger_timing).value
    return parsed


def collect_custom_skill_ids(cfg: CustomDummyConfig, dummy_index: int) -> List[int]:
    ids = []
    for i, as_cfg in enumerate(cfg.as_skills):
        ids.append(_skill_id_for(dummy_index, False, i + 1))
    for i, ps_cfg in enumerate(cfg.ps_skills):
        ids.append(_skill_id_for(dummy_index, True, i + 1))
    return ids
