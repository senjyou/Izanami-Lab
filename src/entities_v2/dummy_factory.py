# -*- coding: utf-8 -*-
"""自定义木桩 → 战斗单位 的统一构建入口。

背景
----
在 v2 之前，木桩单位的构建代码在 `gui/app.py::_create_unit` 与
`src/utils/batch_simulator.py::_create_unit_worker` 各写了一份（逐字段重复），
任何口径调整（例如 `crit_damage - 1.5`、`advantage_damage`、永久盾拆分）
都必须改两处，极易漂移。本模块把这一段收敛为唯一实现，
两处调用点改为委托本模块。

语义约定（与真实角色 `_create_unit` 对齐）
--------------------------------------
- `UnitState.crit_damage` 存的是「额外暴伤」= 配置倍率 − 1.5；
- `UnitState.advantage_damage` 存的是「克制额外加成」= 配置值，最终克制倍率
  为 `1.25 + advantage_damage`（非克制为 1.0）；
- 永久盾按物理/EN/全伤害三型拆到 `physical_shield` / `en_shield` / `shield`。
"""

from __future__ import annotations

from typing import Any, List, Optional

from .custom_dummy import CustomDummyConfig
from .enums import Side
from .unit_state import UnitState

# 单位ID前缀：友方木桩用 D（Dummy），敌方统用 E（与既有实现一致，勿改）
_DUMMY_ALLY_PREFIX = "D"
_ENEMY_PREFIX = "E"

# 游戏内暴击伤害基础倍率（UnitState.crit_damage 以「额外值」存储）
BASE_CRIT_DAMAGE = 1.5


def compute_max_extra_point(data_loader: Any, skill_ids: List[int], mode: str = "first") -> int:
    """按技能表中的 EX 技能（skill_type == 3）推断 EP 上限；无 EX 则为 0。

    Args:
        mode: "first"（默认，木桩既有口径：取第一个 EX 的消耗）
              "max"（与真实演习敌方一致：取所有 EX 消耗的最大值）
    """
    found = []
    for sid in skill_ids or []:
        sk = data_loader.get_skill_by_id(sid)
        if sk and sk.skill_type == 3:
            found.append(sk.resource_cost)
            if mode != "max":
                return sk.resource_cost
    return max(found) if found else 0


def build_dummy_unit_state(
    data_loader: Any,
    char_id: int,
    side: Side,
    position: Any,
    side_prefix: Optional[str] = None,
    enemy_style: bool = False,
) -> Optional[UnitState]:
    """构建木桩 UnitState。

    Args:
        data_loader: DataLoader（需已注册该木桩）
        char_id: 负数的木桩角色ID
        side: 阵营
        position: 站位枚举
        side_prefix: 覆盖单位ID前缀（默认友方 "D" / 敌方 "E"）
        enemy_style: True 时对齐「真实演习敌方」的构建口径：
            等级=1、EP 上限取所有 EX 消耗的最大值。
            用于「标准演习 Boss」木桩，保证与 tactical_exercise 的真实敌方单位零差异。
            默认 False，保持队伍战木桩的既有行为。

    Returns:
        UnitState；配置缺失时返回 None。
    """
    cfg: Optional[CustomDummyConfig] = data_loader.get_custom_dummy_config(char_id)
    char = data_loader.get_character_by_id(char_id)
    if cfg is None or char is None:
        return None

    skill_ids = data_loader._custom_character_skills.get(char_id, [])
    if cfg.max_extra_point and cfg.max_extra_point > 0:
        max_ep = int(cfg.max_extra_point)
    else:
        max_ep = compute_max_extra_point(data_loader, skill_ids,
                                         mode="max" if enemy_style else "first")

    prefix = side_prefix or (_DUMMY_ALLY_PREFIX if side == Side.ALLY else _ENEMY_PREFIX)

    phys_shield = cfg.permanent_shield_value if cfg.permanent_shield_type == 1 else 0
    en_shield = cfg.permanent_shield_value if cfg.permanent_shield_type == 2 else 0
    all_shield = cfg.permanent_shield_value if cfg.permanent_shield_type == 3 else 0

    # 初始 EP 不得超过上限（上限为 0 时强制归零，避免出现「有 EP 但无 EP 条」的非法态）
    initial_ep = float(cfg.initial_ep or 0.0)
    if max_ep <= 0:
        initial_ep = 0.0
    else:
        initial_ep = max(0.0, min(initial_ep, float(max_ep)))

    return UnitState(
        unit_id=f"{prefix}_{char_id}",
        name=char.name,
        side=side,
        position=position,
        character_id=char_id,
        level=1 if enemy_style else max(1, int(cfg.level or 280)),
        element=char.attribute,
        sub_element=getattr(char, "sub_attribute", 0) or 0,
        character_type=char.character_type,
        max_hp=cfg.hp,
        current_hp=cfg.hp,
        attack=cfg.attack,
        defense=cfg.defense,
        speed=cfg.speed,
        crit_rate=cfg.crit_rate,
        crit_damage=cfg.crit_damage - BASE_CRIT_DAMAGE,
        advantage_damage=cfg.advantage_damage,
        initial_active_point=cfg.ap,
        initial_passive_point=cfg.pp,
        max_extra_point=max_ep,
        current_ap=cfg.ap,
        current_pp=cfg.pp,
        current_ep=initial_ep,
        shield=all_shield,
        physical_shield=phys_shield,
        en_shield=en_shield,
        skills=skill_ids,
        skill_levels={sid: 15 for sid in skill_ids},
        skill_cooldowns={},
        role_type=getattr(char, "role_type", 0),
        position_type=getattr(char, "position_type", 0),
        revive_total=max(0, int(cfg.revive_count or 0)),
        revive_mult_start=float(cfg.revive_mult_start),
        revive_mult_step=float(cfg.revive_mult_step),
    )


# ── 演习阶段属性换算（供木桩预设使用） ──────────────────────────────

def stage_atk_def_hp_multiplier(stage: int) -> float:
    """战术演习阶段 n 的 ATK/DEF/HP 倍率。

    与 `TacticalExerciseController._resurrect_enemy` 保持一致：
        1 + 0.2·n + 0.005·max(0, n−3)·max(0, n−2)
    """
    n = max(0, int(stage))
    return 1.0 + 0.2 * n + 0.005 * max(0, n - 3) * max(0, n - 2)


def stage_speed_multiplier(stage: int) -> float:
    n = max(0, int(stage))
    return 1.0 + 0.05 * n


def stage_crit_bonus(stage: int) -> float:
    return 0.01 * max(0, int(stage))
