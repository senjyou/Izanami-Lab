# -*- coding: utf-8 -*-
"""自定义木桩内置预设库。

设计目的
-------
木桩长期停留在「一堆手填数字」的状态：每次拉表都要重新拍一遍 HP/ATK/DEF/速度，
口径无法复现，也无法对照旧榜。这里把**有明确出处的口径**固化成预设：

- 「旧榜口径靶」：复刻旧输出榜的敌方设定（DEF 25000、克制 1.505），
  用于新旧榜对照（出处：用户提供的《MGG 角色输出数据表》，`角色输出表!F4`）。
- 「演习阶段 N 靶」：由真实演习敌方（`data/tactical_exercise_enemies.json`）
  按 `TacticalExerciseController` 的阶段成长公式换算，避免手填。
- 「演习敌方复刻」：同一套换算 + 真实技能组（`extra_skill_ids`），
  用于生存端/带 AI 的对手脚本。

约定
----
- 所有「打桩靶」都把 HP 放大到 1e8 级，并在 `note` 里显式注明「数值放大、
  非游戏内真实值」——因为游戏没有「无敌」木桩，这是公开可解释的近似。
- 预设只是**初始配置**，用户可以继续编辑。属性需要按被测角色的克制关系调整。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .custom_dummy import CustomDummyConfig
from .dummy_factory import (
    stage_atk_def_hp_multiplier,
    stage_crit_bonus,
    stage_speed_multiplier,
)

# 打桩靶的放大 HP（避免 5 回合内被打死导致伤害统计被打断）
# 定标依据（2026-10-22 实测）：6 槽「每角色最优语境」队伍 5 回合可打出 98.76M，
# 1e8 的木桩会被打死并升阶（DEF 上升污染计量）；按「≥3× 实测最大团队分」取 5e8。
DUMMY_METER_HP = 500_000_000

# 旧榜口径常量（出处：《MGG 角色输出数据表》角色输出表!F4 与 主页!K5/H28）
LEGACY_DEF = 25000
LEGACY_ADVANTAGE_BONUS = 0.255  # 3 条彩S「有利属性伤害」词条 = 3 × 8.5%

# 默认用于换算的演习敌方（惨禍：桃園める，enemy_id=93109）
DEFAULT_EXERCISE_ENEMY_ID = 93109

# ── 标准演习 Boss 口径常量 ──────────────────────────────────────────
#
# 出处：`data/tactical_exercise_enemies.json` 全部 56 个演习敌方的统计中位数。
# 复算方法见 tests/test_exercise_dummy_enemy.py::test_standard_boss_panel_matches_median。
#   HP 中位数 370683.5 / ATK 10411.5 / DEF 5807.5 / SPD 599 / 暴击 0.18 / AP=PP=4
#   （56 个敌方 AP/PP 全为 4，rarity 全为 9=LR）
STANDARD_BOSS_HP_REAL = 370_684     # real 模式：中位数四舍五入（会死会升阶）
STANDARD_BOSS_ATTACK = 10_412
STANDARD_BOSS_DEFENSE = 5_808
STANDARD_BOSS_SPEED = 599
STANDARD_BOSS_CRIT_RATE = 0.18
STANDARD_BOSS_AP = 4
STANDARD_BOSS_PP = 4
# 「1EX + 2AS + 2PS」在 56 个敌方中占 37/56≈66%，取其典型组合
# = 93109 惨禍：桃園める 的真实技能组（210001 为 EX，cost 6 → EP 上限 6）
STANDARD_BOSS_SKILL_IDS = [210001, 220012, 220013, 230251, 230007]
# 类型/定位沿用技能组来源单位 93109（type=3 敏捷 / role_type=4 辅助），
# 四个属性靶**只有属性不同**，其余面板完全一致，保证跨角色可比。
STANDARD_BOSS_CHARACTER_TYPE = 3
STANDARD_BOSS_ROLE_TYPE = 4
# 56 个演习敌方的 rarity 全为 9（LR）。注意：模拟器不消费 rarity
# （木桩面板是显式数值，不走稀有度成长），此处仅作为口径记录。
STANDARD_BOSS_RARITY = 9
# 演习敌方只有火水土风四属（游戏内无光暗演习敌方，光暗角色只能打非克制）
STANDARD_BOSS_ELEMENTS = {1: "火", 2: "水", 3: "风", 4: "土"}
# 预设 key 用的英文属性名（std_boss_fire_meter 等）
STANDARD_BOSS_ELEMENT_KEYS = {1: "fire", 2: "water", 3: "wind", 4: "earth"}
# HP 模式：meter=纯输出计量（1e8，5 回合内不被打死）；real=真实 HP（会死会升阶）
STANDARD_BOSS_HP_MODES = {"meter": DUMMY_METER_HP, "real": STANDARD_BOSS_HP_REAL}


@dataclass
class DummyPreset:
    key: str
    label: str
    description: str
    make: Any  # Callable[[], CustomDummyConfig]
    tags: Optional[List[str]] = None

    def build(self) -> CustomDummyConfig:
        return self.make()

    @property
    def tag_list(self) -> List[str]:
        return list(self.tags or [])


# ── 基础预设 ────────────────────────────────────────────────────────

def make_blank() -> CustomDummyConfig:
    return CustomDummyConfig(name="木桩", note="空白配置：全部取默认值")


def make_legacy_dps_target() -> CustomDummyConfig:
    """旧输出榜口径打桩靶（DEF 25000 / 克制 1.505）。"""
    return CustomDummyConfig(
        name="打桩靶·旧榜口径",
        element=3,              # 风：默认被火属性角色克制，按需修改
        character_type=1,
        position_type=3,
        role_type=3,
        hp=DUMMY_METER_HP,
        attack=1000,
        defense=LEGACY_DEF,
        crit_rate=0.15,
        crit_damage=1.5,
        speed=500,
        advantage_damage=LEGACY_ADVANTAGE_BONUS,
        ap=0, pp=0,
        level=280,
        note=(
            "复刻旧输出榜口径：敌方 DEF=25000、克制倍率 1.505（1.25+0.255）。"
            "HP 放大到 1e8 仅为避免被打死，不代表游戏内真实血量；"
            "无技能=战斗中始终待机。请把「属性」改成被你角色克制的属性；"
            "非克制对照请把有利加成改为 0 并选中性属性。"
        ),
    )


def make_zero_def_target() -> CustomDummyConfig:
    """零防靶：用于标定乘区（暴击/增伤/克制）而不受防御减法干扰。"""
    return CustomDummyConfig(
        name="打桩靶·零防",
        element=3, character_type=1, position_type=3, role_type=3,
        hp=DUMMY_METER_HP, attack=1000, defense=0, crit_rate=0.0, crit_damage=1.5,
        speed=500, advantage_damage=0.0, ap=0, pp=0, level=280,
        note="DEF=0、目标不暴击、无技能。用于分离「攻击×威力×乘区」与防御减法的影响；HP 为放大值。",
    )


# ── 演习敌方换算 ────────────────────────────────────────────────────

def _exercise_enemy(data_loader: Any, enemy_id: int) -> Dict[str, Any]:
    enemies = data_loader.get_tactical_exercise_enemies() or {}
    data = enemies.get(int(enemy_id))
    if not data:
        raise KeyError(f"未找到演习敌方 {enemy_id}")
    return data


def exercise_stats_at_stage(data_loader: Any, enemy_id: int, stage: int) -> Dict[str, float]:
    """按演习阶段成长公式换算敌方面板（与 TacticalExerciseController 同式）。"""
    d = _exercise_enemy(data_loader, enemy_id)
    m = stage_atk_def_hp_multiplier(stage)
    return {
        "hp": float(d.get("hp", 0)) * m,
        "attack": float(d.get("attack", 0)) * m,
        "defense": float(d.get("defense", 0)) * m,
        "speed": float(d.get("speed", 0)) * stage_speed_multiplier(stage),
        "crit_rate": float(d.get("critical_rate", 0.0)) + stage_crit_bonus(stage),
    }


def make_exercise_stage_target(data_loader: Any, stage: int = 10,
                               enemy_id: int = DEFAULT_EXERCISE_ENEMY_ID) -> CustomDummyConfig:
    """演习阶段打桩靶：真实敌方面板换算 + HP 放大 + 不行动。"""
    d = _exercise_enemy(data_loader, enemy_id)
    st = exercise_stats_at_stage(data_loader, enemy_id, stage)
    return CustomDummyConfig(
        name=f"打桩靶·演习阶段{stage}",
        element=int(d.get("attribute", 1)),
        character_type=int(d.get("type", 3)),
        position_type=3,
        role_type=int(d.get("role_type", 3)),
        hp=DUMMY_METER_HP,
        attack=int(st["attack"]),
        defense=int(st["defense"]),
        crit_rate=min(1.0, max(0.0, st["crit_rate"])),
        crit_damage=1.5,
        speed=int(st["speed"]),
        advantage_damage=0.0,
        ap=0, pp=0,
        level=280,
        note=(
            f"由演习敌方 {enemy_id}「{d.get('name', '')}」按阶段成长公式换算："
            f"ATK/DEF/HP ×{stage_atk_def_hp_multiplier(stage):.4f}、SPD ×{stage_speed_multiplier(stage):.2f}、"
            f"暴击 +{stage_crit_bonus(stage):.2f}。HP 放大到 1e8 仅为打桩不打死的近似；无技能=始终待机。"
        ),
    )


def make_exercise_enemy_replica(data_loader: Any, stage: int = 10,
                                enemy_id: int = DEFAULT_EXERCISE_ENEMY_ID) -> CustomDummyConfig:
    """演习敌方复刻：真实面板（不放大 HP）+ 真实技能组，用于生存端/带 AI 对手。"""
    d = _exercise_enemy(data_loader, enemy_id)
    st = exercise_stats_at_stage(data_loader, enemy_id, stage)
    return CustomDummyConfig(
        name=f"演习复刻·阶段{stage}",
        element=int(d.get("attribute", 1)),
        character_type=int(d.get("type", 3)),
        position_type=3,
        role_type=int(d.get("role_type", 3)),
        hp=max(1, int(st["hp"])),
        attack=int(st["attack"]),
        defense=int(st["defense"]),
        crit_rate=min(1.0, max(0.0, st["crit_rate"])),
        crit_damage=1.5,
        speed=int(st["speed"]),
        advantage_damage=0.0,
        ap=int(d.get("action_point", 4)),
        pp=int(d.get("passive_point", 4)),
        level=280,
        note=(
            f"演习敌方 {enemy_id}「{d.get('name', '')}」阶段 {stage} 的复刻："
            f"面板按阶段公式换算，技能组直接引用原技能ID {d.get('skill_ids', [])}。"
            "用于生存端测量或「带 AI 的对手脚本」；注意真实演习中敌方死亡会复活升阶。"
        ),
        extra_skill_ids=[int(x) for x in (d.get("skill_ids") or [])],
    )


# ── 标准演习 Boss（56 敌方中位数口径） ──────────────────────────────

def _median(values: List[float]) -> Optional[float]:
    vals = sorted(float(v) for v in values)
    n = len(vals)
    if n == 0:
        return None
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def exercise_element_medians(data_loader: Any, element: int) -> Dict[str, float]:
    """该属性演习敌方的中位数面板（仅供 note 参考，不参与 Boss 面板构建）。

    标准 Boss 刻意**不**使用「每属各自的中位数」：土属 DEF 中位数 6393、
    火属 5619，若按属性各取中位数，同一个角色换成不同属性靶时对位不可比。
    """
    try:
        enemies = data_loader.get_tactical_exercise_enemies() or {}
    except Exception:
        enemies = {}
    sel = [d for d in enemies.values() if int(d.get("attribute", 0) or 0) == int(element)]
    out: Dict[str, float] = {}
    for key, field in (("hp", "hp"), ("attack", "attack"), ("defense", "defense"),
                       ("speed", "speed"), ("crit_rate", "critical_rate")):
        m = _median([float(d.get(field, 0) or 0) for d in sel])
        if m is not None:
            out[key] = m
    out["count"] = float(len(sel))
    return out


def make_standard_exercise_boss(data_loader: Any, element: int = 3,
                                hp_mode: str = "meter") -> CustomDummyConfig:
    """标准演习 Boss：56 个演习敌方的统计中位数面板。

    口径（与真实演习敌方单位零差异，见 dummy_factory.build_dummy_unit_state
    的 `enemy_style=True`）：
      - 面板取 56 敌方中位数：HP 370684 / ATK 10412 / DEF 5808 / SPD 599 / 暴击 0.18
      - 四属（火 1 / 水 2 / 风 3 / 土 4）**只改属性**，其余面板完全相同 → 跨角色可比
      - AP=PP=4、技能组 = 1EX+2AS+2PS（210001/220012/220013/230251/230007）
      - crit_damage=1.5（= 无额外暴伤）、advantage_damage=0.0
      - 单位 level=1、EP 上限 = 所有 EX 技能 cost 的最大值（=6），由 enemy_style 保证

    Args:
        data_loader: DataLoader（可为 None；仅用于在 note 里附该属中位数参考）
        element: 1=火 2=水 3=风 4=土（游戏演习没有光暗敌方，传入 5/6 会抛 ValueError）
        hp_mode: "meter"=HP 1e8（纯输出计量，5 回合不被打死）
                 "real"=HP 370684（会死、会按阶段公式复活升阶）

    Returns:
        CustomDummyConfig
    """
    element = int(element)
    if element not in STANDARD_BOSS_ELEMENTS:
        raise ValueError(
            f"标准演习 Boss 只支持火/水/风/土（element∈{{1,2,3,4}}），收到 {element}；"
            "游戏内演习没有光/暗敌方"
        )
    if hp_mode not in STANDARD_BOSS_HP_MODES:
        raise ValueError(f"HP 模式只能是 {sorted(STANDARD_BOSS_HP_MODES)}，收到 {hp_mode!r}")

    elem_name = STANDARD_BOSS_ELEMENTS[element]
    hp = STANDARD_BOSS_HP_MODES[hp_mode]
    meter = hp_mode == "meter"

    note_lines = [
        f"标准演习 Boss（{elem_name}属，{'计量' if meter else '真实'}HP）："
        f"面板 = 全部 56 个演习敌方的统计中位数 HP {STANDARD_BOSS_HP_REAL:,} / "
        f"ATK {STANDARD_BOSS_ATTACK:,} / DEF {STANDARD_BOSS_DEFENSE:,} / SPD {STANDARD_BOSS_SPEED} / "
        f"暴击 {STANDARD_BOSS_CRIT_RATE} / AP=PP={STANDARD_BOSS_AP}（rarity=LR）。"
    ]
    if meter:
        note_lines.append(
            f"HP 放大到 {DUMMY_METER_HP:,}：纯输出计量口径，5 回合内不会被打死，"
            "score 只反映我方输出（不代表游戏内真实血量）。"
        )
    else:
        note_lines.append(
            f"HP = {STANDARD_BOSS_HP_REAL:,}（真实口径）：会被击杀，死亡后按演习阶段公式"
            "复活升阶（HP/ATK/DEF ×(1+0.2n+0.005·max(0,n−3)·max(0,n−2))、SPD ×(1+0.05n)、暴击 +0.01n）。"
        )
    note_lines.append(
        "四属靶只有属性不同（火1/水2/风3/土4），其余面板与技能完全一致，保证跨角色可比；"
        "游戏演习没有光/暗敌方（光暗角色只能打非克制）。"
        f"技能组 1EX+2AS+2PS = {STANDARD_BOSS_SKILL_IDS}（取自 93109 惨禍：桃園める，"
        "该组合在 56 敌方中占 66%）；crit_damage=1.5（无额外暴伤）、advantage_damage=0。"
        "作为演习敌方上场时按 enemy_style 口径构建：单位等级 1、EP 上限 = 最大 EX 消耗（6）。"
    )
    if data_loader is not None:
        try:
            med = exercise_element_medians(data_loader, element)
        except Exception:
            med = {}
        if med.get("count"):
            note_lines.append(
                f"参考：{elem_name}属敌方（{int(med['count'])} 个）自身中位数为 "
                f"DEF {med.get('defense', 0):.0f} / HP {med.get('hp', 0):.0f} / "
                f"ATK {med.get('attack', 0):.0f} / SPD {med.get('speed', 0):.0f}；"
                "本预设刻意统一使用总体中位数，避免换属性后对位不可比。"
            )

    return CustomDummyConfig(
        name=f"标准演习Boss·{elem_name}·{'计量HP' if meter else '真实HP'}",
        element=element,
        character_type=STANDARD_BOSS_CHARACTER_TYPE,
        position_type=3,
        role_type=STANDARD_BOSS_ROLE_TYPE,
        hp=hp,
        attack=STANDARD_BOSS_ATTACK,
        defense=STANDARD_BOSS_DEFENSE,
        crit_rate=STANDARD_BOSS_CRIT_RATE,
        crit_damage=1.5,           # 无额外暴伤（对齐真实演习敌方 crit_damage=0.0）
        speed=STANDARD_BOSS_SPEED,
        advantage_damage=0.0,      # 无额外有利加成（对齐真实演习敌方）
        ap=STANDARD_BOSS_AP,
        pp=STANDARD_BOSS_PP,
        level=280,                 # 木桩面板 = 满级口径；演习敌方单位 level 由 enemy_style 置 1
        max_extra_point=0,         # 0 = 自动推断（= 最大 EX 消耗 = 6）
        extra_skill_ids=list(STANDARD_BOSS_SKILL_IDS),
        note="".join(note_lines),
    )


# ── 预设清单 ────────────────────────────────────────────────────────

def builtin_presets(data_loader: Any = None) -> List[DummyPreset]:
    """返回可用预设列表（data_loader 为空时只返回不依赖游戏数据的预设）。"""
    presets: List[DummyPreset] = [
        DummyPreset("blank", "空白木桩",
                    "全部默认值，手动配置", make_blank, ["基础"]),
        DummyPreset("legacy_dps", "打桩靶·旧榜口径",
                    f"DEF {LEGACY_DEF} / 克制 1.505 / 不行动（对照旧输出榜）",
                    make_legacy_dps_target, ["打桩", "旧榜对照"]),
        DummyPreset("zero_def", "打桩靶·零防",
                    "DEF 0 / 不行动（分离防御减法影响）",
                    make_zero_def_target, ["打桩"]),
    ]
    # 标准演习 Boss：四属 × 两种 HP 模式（meter/real），面板与技能组完全一致
    for _elem, _elem_name in STANDARD_BOSS_ELEMENTS.items():
        for _mode, _mode_name in (("meter", "计量HP"), ("real", "真实HP")):
            presets.append(DummyPreset(
                f"std_boss_{STANDARD_BOSS_ELEMENT_KEYS[_elem]}_{_mode}",
                f"标准演习Boss·{_elem_name}·{_mode_name}",
                f"56 敌方中位数面板 / {'HP 1e8 不死' if _mode == 'meter' else 'HP 370684 会升阶'} / "
                f"1EX+2AS+2PS / {_elem_name}属",
                (lambda e=_elem, m=_mode: make_standard_exercise_boss(data_loader, e, m)),
                ["演习", "标准Boss", "计量" if _mode == "meter" else "升阶"],
            ))
    if data_loader is not None:
        try:
            enemies = data_loader.get_tactical_exercise_enemies() or {}
        except Exception:
            enemies = {}
        if enemies:
            presets += [
                DummyPreset("exercise_s10", "打桩靶·演习阶段10",
                            "真实演习敌方按阶段公式换算 + HP 放大（不行动）",
                            lambda: make_exercise_stage_target(data_loader, 10),
                            ["打桩", "演习"]),
                DummyPreset("exercise_s0", "打桩靶·演习阶段0",
                            "演习初始阶段面板（不行动）",
                            lambda: make_exercise_stage_target(data_loader, 0),
                            ["打桩", "演习"]),
                DummyPreset("replica_s10", "演习复刻·阶段10（带技能）",
                            "真实面板 + 真实技能组，用于生存端测量",
                            lambda: make_exercise_enemy_replica(data_loader, 10),
                            ["生存", "演习"]),
            ]
    return presets


def get_preset(key: str, data_loader: Any = None) -> Optional[DummyPreset]:
    for p in builtin_presets(data_loader):
        if p.key == key:
            return p
    return None
