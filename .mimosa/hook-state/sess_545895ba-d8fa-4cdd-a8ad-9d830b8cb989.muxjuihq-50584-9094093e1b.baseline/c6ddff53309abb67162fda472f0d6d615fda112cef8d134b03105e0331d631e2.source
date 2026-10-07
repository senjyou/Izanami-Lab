#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自定义木桩角色数据模型
src/entities_v2/custom_dummy.py

提供自定义木桩的配置数据类和向现有系统注入的构建函数。
负ID避免与真实数据冲突。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from ..data.models import (
    CharacterData, BaseStats, BonusStats, StatGrades,
    SkillData, SkillDescription, AdditionalKind,
    TemplateTag, TemplateTagValue, DisplayInfo,
)
from .enums import TriggerTiming, Attribute, CharacterType, PositionType, RoleType


# ── 效果配置 ──

# 支持的效果类型分类
EFFECT_CATEGORIES = {
    "伤害": ["damage", "hp_ratio_damage"],
    "治疗": ["heal", "heal_over_time"],
    "增益": ["atk_up", "def_up", "spd_up", "crit_rate_up", "crit_dmg_up",
             "dmg_dealt_up", "dmg_taken_down", "shield", "max_hp_up"],
    "减益": ["atk_down", "def_down", "spd_down", "crit_rate_down",
             "dmg_dealt_down", "dmg_taken_up"],
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
}

EFFECT_DISPLAY_REVERSE = {v: k for k, v in EFFECT_TYPE_DISPLAY.items()}

# 状态异常类型
STATUS_TYPE_DISPLAY = {
    "stun": "眩晕", "poison": "毒", "burn": "炎上",
    "freeze": "冻结", "mark": "标记",
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
    crit_damage: float = 1.5
    speed: int = 500
    advantage_damage: float = 0.0
    ap: int = 5
    pp: int = 5
    as_skills: List[CustomASConfig] = field(default_factory=list)
    ps_skills: List[CustomPSConfig] = field(default_factory=list)
    permanent_shield_type: int = 0
    permanent_shield_value: int = 0


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
        level=1,
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


def _build_effect_dict(efg: CustomEffectConfig, effect_idx: int) -> Dict[str, Any]:
    """根据效果配置构建单个效果的字典"""
    effect: Dict[str, Any] = {
        "effect_type": efg.effect_type,
        "target_type": "selected",
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

    # 从效果列表构建effect列表
    effect_list = []
    for i, efg in enumerate(effects):
        effect_list.append(_build_effect_dict(efg, i))

    # 如果没有效果，默认生成一个damage效果
    if not effect_list:
        effect_list.append({
            "effect_type": "damage",
            "target_type": "selected",
            "value_tag": "威力",
        })

    parsed = {
        "skill_id": sid,
        "display_target_type": target_type,
        "display_target_range": target_range,
        "display_target_priority": target_priority,
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
