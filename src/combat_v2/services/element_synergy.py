from typing import List, Dict
from src.entities_v2.unit_state import UnitState
from src.entities_v2.enums import Side


def _calc_four_element_bonus(elements: List[int]) -> tuple:
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    light_count = 0

    for e in elements:
        if e in (5,):
            light_count += 1
        elif e in (1, 2, 3, 4):
            counts[e] += 1

    if light_count > 0 and any(c > 0 for c in counts.values()):
        best_elem = max(counts, key=counts.get)
        counts[best_elem] += light_count

    sorted_counts = sorted(counts.values(), reverse=True)
    primary = sorted_counts[0]
    secondary = sorted_counts[1] if len(sorted_counts) > 1 else 0

    if primary >= 5:
        return (25.0, 25.0)
    elif primary >= 4:
        return (15.0, 20.0)
    elif primary >= 3 and secondary >= 2:
        return (15.0, 15.0)
    elif primary >= 3:
        return (10.0, 10.0)
    return (0.0, 0.0)


def _calc_dark_bonus(dark_count: int) -> dict:
    bonuses = {"attack": 0.0, "hp": 0.0, "defense": 0.0, "crit_rate": 0.0}

    if dark_count >= 5:
        bonuses["attack"] = 25.0
        bonuses["hp"] = 25.0
        bonuses["defense"] = 30.0
        bonuses["crit_rate"] = 15.0
    elif dark_count >= 4:
        bonuses["attack"] = 15.0
        bonuses["hp"] = 15.0
        bonuses["defense"] = 30.0
        bonuses["crit_rate"] = 15.0
    elif dark_count >= 3:
        bonuses["attack"] = 10.0
        bonuses["hp"] = 10.0
        bonuses["defense"] = 30.0
        bonuses["crit_rate"] = 15.0
    elif dark_count >= 2:
        bonuses["attack"] = 10.0
        bonuses["hp"] = 10.0
        bonuses["defense"] = 30.0
    elif dark_count >= 1:
        bonuses["defense"] = 30.0

    return bonuses


def apply_element_synergy(units: List[UnitState], narrative=None) -> List[UnitState]:
    ally_units = [u for u in units if u.side == Side.ALLY]
    enemy_units = [u for u in units if u.side == Side.ENEMY]

    for side_units in [ally_units, enemy_units]:
        if not side_units:
            continue
        _apply_side_synergy(side_units, narrative)

    return units


def _apply_side_synergy(side_units: List[UnitState], narrative) -> None:
    four_elements = [u.element for u in side_units if u.element in (1, 2, 3, 4, 5)]
    dark_count = sum(1 for u in side_units if u.element == 6)

    atk_pct, hp_pct = _calc_four_element_bonus(four_elements)
    dark_bonus = _calc_dark_bonus(dark_count) if dark_count > 0 else {"attack": 0.0, "hp": 0.0, "defense": 0.0, "crit_rate": 0.0}

    total_atk_pct = atk_pct + dark_bonus["attack"]
    total_hp_pct = hp_pct + dark_bonus["hp"]
    total_def_pct = dark_bonus["defense"]
    total_crit_bonus = dark_bonus["crit_rate"] / 100.0

    side_name = "己方" if side_units[0].side == Side.ALLY else "敌方"
    if narrative:
        parts = []
        if atk_pct > 0:
            parts.append(f"四元素:ATK+{atk_pct:.0f}% HP+{hp_pct:.0f}%")
        if dark_count > 0:
            parts.append(f"暗({dark_count}体):ATK+{dark_bonus['attack']:.0f}% HP+{dark_bonus['hp']:.0f}% DEF+{dark_bonus['defense']:.0f}%")
            if dark_bonus["crit_rate"] > 0:
                parts[-1] += f" CRIT+{dark_bonus['crit_rate']:.0f}%"
        if parts:
            narrative.system_message(f"[组队加成] {side_name}: {' | '.join(parts)}")

    for unit in side_units:
        position = unit.position
        if hasattr(position, 'value'):
            pos_str = position.value
        else:
            pos_str = str(position)
        is_front = "FRONT" in pos_str.upper()
        is_back = "BACK" in pos_str.upper()
        pos_penalty = 0.0
        pt = unit.position_type
        if pt == 1 and is_back:
            pos_penalty = -5.0
        elif pt == 2 and is_front:
            pos_penalty = -5.0

        total_mult_atk = 1.0 + (total_atk_pct + pos_penalty) / 100.0
        total_mult_hp = 1.0 + (total_hp_pct + pos_penalty) / 100.0
        total_mult_def = 1.0 + (total_def_pct + pos_penalty) / 100.0

        unit.attack = int(unit.attack * total_mult_atk)
        unit.max_hp = int(unit.max_hp * total_mult_hp)
        unit.current_hp = unit.max_hp
        unit.defense = int(unit.defense * total_mult_def)

        if total_crit_bonus > 0:
            unit.crit_rate += total_crit_bonus

        if narrative:
            bonus_desc_parts = []
            if total_atk_pct != 0:
                bonus_desc_parts.append(f"ATK {total_atk_pct:+.0f}%")
            if total_hp_pct != 0:
                bonus_desc_parts.append(f"HP {total_hp_pct:+.0f}%")
            if total_def_pct != 0:
                bonus_desc_parts.append(f"DEF {total_def_pct:+.0f}%")
            if pos_penalty != 0:
                bonus_desc_parts.append(f"位置适应 {pos_penalty:+.0f}%")
            if bonus_desc_parts:
                narrative.system_message(f"  [进场属性] {unit.name}: {' | '.join(bonus_desc_parts)} → ATK={unit.attack} HP={unit.max_hp} DEF={unit.defense}")