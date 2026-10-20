"""Shared module tiers. Raw percentages remain engine inputs; no rounding/clamping."""
import math
from dataclasses import dataclass

ATTRIBUTE_NAMES = {0: "无效果", 1: "HP", 2: "攻击力", 3: "防御力", 4: "速度", 5: "暴击率", 6: "暴击伤害", 7: "有利伤害"}
QUALITIES = ("白", "金", "彩")
GRADES = ("D", "C", "B", "A", "S")
# 表内数值必须与"游戏词条显示口径"一致，也就是
# src/importer/gear_math.py::gear_value_percent（B 口径 = floor(f32*10000)/100）。
# 2026-10-20 起模拟器战斗也采用 B 口径，所以导入值会直接落在这张表上。
#
# 注意白S 与 彩S 速度这两档：游戏里 ×10000 后的 float32 落在略小于整数的位置
# （如 速度彩S: 719.9999389648438 → floor 719 → 7.19），因此显示/战斗口径是
# 7.19 / 3.59 / 1.66，而不是数学上的 7.2 / 3.6 / 1.67。这里按游戏实际值填。
# Rainbow values verified against the supplied ModuleGearEffectMaster.json;
# white/gold values follow the supplied tier table.
_BASE = ((.5,.79,1.08,1.37,1.66), (.75,1.18,1.62,2.06,2.49), (1,1.58,2.16,2.75,3.33))
_VALUES = {
    1: _BASE, 2: _BASE, 3: _BASE,
    4: ((1,1.75,2.25,3,3.59), (1.5,2.62,3.37,4.49,5.4), (2,3.5,4.5,6,7.19)),
    5: ((1,1.75,2.4,3,3.5), (1.5,2.62,3.59,4.49,5.25), (2,3.5,4.8,6,7)),
    6: ((2.5,4.25,5.75,7,8.25), (3.75,6.37,8.62,10.5,12.37), (5,8.5,11.5,14,16.5)),
    7: ((2.5,3.25,3.63,4,4.25), (3.75,4.87,5.43,6,6.37), (5,6.5,7.25,8,8.5)),
}
MATCH_TOLERANCE = 1e-8  # Binary floating noise only, never display rounding.

@dataclass(frozen=True)
class AffixTier:
    effect_type: int
    quality: str
    grade: str
    value: float

    @property
    def label(self):
        return self.quality + self.grade

STANDARD_TIERS = tuple(AffixTier(t,q,g,float(_VALUES[t][qi][gi]))
                       for t in _VALUES for qi,q in enumerate(QUALITIES) for gi,g in enumerate(GRADES))

def standard_tiers(effect_type=None):
    """Enumerate the full table, or the 15 tiers of one numeric attribute."""
    return tuple(t for t in STANDARD_TIERS if effect_type is None or t.effect_type == effect_type)

def standard_value(effect_type, quality, grade):
    return float(_VALUES[effect_type][QUALITIES.index(quality)][GRADES.index(grade)])

def match_tiers(effect_type, value):
    """All matches in deterministic white/gold/rainbow, D..S order; 0 has no tier."""
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value):
        return ()
    return tuple(t for t in STANDARD_TIERS if t.effect_type == effect_type
                 and abs(t.value-value) <= MATCH_TOLERANCE)

def is_standard(effect_type, value):
    return bool(match_tiers(effect_type, value))

# Keep V1's exact 20 candidates, all derived from the shared standard tiers.
_CANDIDATE_LABELS = {2: ("彩S","彩A","金S","金A","金B","金C","金D"),
                     4: ("彩S","彩A","彩B","彩C","彩D","金S","金A","金B","金C","金D"),
                     5: ("彩S",), 6: ("彩S",), 7: ("彩S",)}
OPTIMIZER_AFFIXES = {typ: tuple((label, standard_value(typ,label[0],label[1])) for label in labels)
                    for typ,labels in _CANDIDATE_LABELS.items()}

def is_optimizer_affix(effect_type, value):
    return any(value == v for _,v in OPTIMIZER_AFFIXES.get(effect_type, ()))

def describe_affix(effect_type, value):
    name = ATTRIBUTE_NAMES.get(effect_type,str(effect_type))
    if effect_type == 0:
        return "无效果"
    matches = match_tiers(effect_type,value)
    grade = "/".join(t.label for t in matches) if matches else "自定义"
    return f"{name} {grade} {value}%"
