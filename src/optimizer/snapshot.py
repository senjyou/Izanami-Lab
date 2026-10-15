"""Snapshot handling: build, validate and key a candidate lineup state.

A "snapshot" is the complete, self-contained description of one battle setup:
which characters stand in which slots, which shared memories are equipped, and
the full panel (levels, rarities, affection, skills, modules) for exactly those
characters. It is plain JSON-safe data -- no Tk objects, no dataclasses -- so it
can be pickled into a worker process, hashed for caching, and written to disk.

The optimizer never mutates the caller's state. Every candidate is derived by
copying a template and replacing only the two fields being searched
(``friend_positions`` and ``memory_ids``), which keeps the fixed half of the
configuration shared and cheap.
"""

import copy
import hashlib
import json
import math

from src.config.character_config import ModuleConfig
from src.config.panel_config import PanelConfig
from src.config.player_config import SchoolLevels

# Fields of the panel that are per-character. Everything else is global.
PER_CHARACTER_FIELDS = ("modules", "skill_levels", "character_levels",
                        "rarities", "affection_levels")

SLOT_COUNT = 6
ALLY_COUNT = 5   # five characters plus exactly one empty slot
MEMORY_COUNT = 6


class SnapshotError(ValueError):
    """Raised when a snapshot cannot describe a legal battle."""


# --------------------------------------------------------------------------- #
# GUI <-> snapshot conversion
# --------------------------------------------------------------------------- #

def panel_to_dict(panel):
    """Serialise a PanelConfig to plain JSON-safe data."""
    from dataclasses import asdict
    return json.loads(json.dumps(asdict(panel), ensure_ascii=False))


def panel_from_dict(data):
    """Rebuild a PanelConfig from plain data (int keys are restored)."""
    data = copy.deepcopy(data)
    data["school_levels"] = SchoolLevels(**data.get("school_levels", {}))
    for key in ("equipment_bonuses", "character_levels", "rarities",
                "affection_levels"):
        data[key] = {int(k): v for k, v in data.get(key, {}).items()}
    data["modules"] = {int(k): [ModuleConfig(**m) for m in v]
                       for k, v in data.get("modules", {}).items()}
    data["skill_levels"] = {int(k): {int(s): lv for s, lv in v.items()}
                            for k, v in data.get("skill_levels", {}).items()}
    return PanelConfig(**data)


def memory_id(entry):
    """Accept a memory as an int or as the GUI's "[12345] name" strings."""
    if isinstance(entry, bool):
        raise SnapshotError(f"无法识别回忆编号：{entry!r}")
    if isinstance(entry, int):
        return entry
    if not entry:
        return None
    text = str(entry).strip()
    if text.startswith("["):
        text = text[1:].split("]")[0]
    try:
        return int(text)
    except ValueError:
        raise SnapshotError(f"无法识别回忆编号：{entry!r}") from None


def build_snapshot(selection, panel, enemy_id=None):
    """Build a snapshot from a tab's selection dict and a PanelConfig.

    ``selection`` is what a tab's ``_get_selection()`` returns: it carries
    ``friend_positions`` (or ``friends``) and ``mems_friend`` (or
    ``mem_friend_positions``). ``enemy_id`` is supplied separately because the
    circle-battle tab derives its enemies from season/stage rather than a single
    enemy selection.

    The panel is trimmed to the participating characters so that unused saved
    configurations cannot influence the cache key or the battle.
    """
    positions = selection.get("friend_positions")
    if positions is None:
        positions = list(selection.get("friends", []))
    positions = list(positions)
    if len(positions) > SLOT_COUNT:
        raise SnapshotError(f"站位不能超过 {SLOT_COUNT} 个，收到 {len(positions)}")
    positions = positions + [None] * (SLOT_COUNT - len(positions))

    raw_memories = selection.get("mems_friend",
                                selection.get("mem_friend_positions", []))
    memories = [memory_id(m) for m in raw_memories]
    memories = [m for m in memories if m is not None]

    if enemy_id is None:
        enemy_id = selection.get("enemy_id")

    panel_data = panel_to_dict(panel)
    selected = {str(c) for c in positions if c is not None}
    for field in PER_CHARACTER_FIELDS:
        panel_data[field] = {k: v for k, v in panel_data[field].items()
                             if k in selected}

    return {"schema": 1, "enemy_id": enemy_id, "friend_positions": positions,
            "memory_ids": memories, "panel": panel_data}


def selection_from_snapshot(state):
    """Convert a snapshot back into a tab selection dict."""
    return {
        "friends": [c for c in state["friend_positions"] if c is not None],
        "friend_positions": list(state["friend_positions"]),
        "enemy_id": state.get("enemy_id"),
        "mems_friend": [f"[{m}]" for m in state["memory_ids"]],
        "mem_friend_positions": [f"[{m}]" for m in state["memory_ids"]],
    }


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def validate(state, data_loader=None, strict_affixes=True):
    """Check that a snapshot can drive a battle. Raises SnapshotError."""
    positions = state.get("friend_positions")
    if not isinstance(positions, list) or len(positions) != SLOT_COUNT:
        raise SnapshotError(f"站位必须为 {SLOT_COUNT} 个槽位")
    placed = [c for c in positions if c is not None]
    if len(placed) != ALLY_COUNT:
        raise SnapshotError(f"必须恰好 {ALLY_COUNT} 名角色上场（当前 {len(placed)}）")
    if len(set(placed)) != len(placed):
        raise SnapshotError("同一角色不能占据多个站位")
    for cid in placed:
        if not isinstance(cid, int) or isinstance(cid, bool):
            raise SnapshotError(f"角色编号必须是整数：{cid!r}")

    memories = state.get("memory_ids")
    if not isinstance(memories, list) or len(memories) != MEMORY_COUNT:
        raise SnapshotError(f"必须选择 {MEMORY_COUNT} 张全队共享回忆")
    if len(set(memories)) != MEMORY_COUNT:
        raise SnapshotError("共享回忆不能重复")

    if data_loader is not None:
        for cid in placed:
            if not data_loader.get_character_by_id(cid):
                raise SnapshotError(f"未知角色编号 {cid}")
        for mid in memories:
            if not data_loader.get_memory(mid):
                raise SnapshotError(f"未知回忆编号 {mid}")
        enemy_id = state.get("enemy_id")
        if enemy_id is not None:
            enemies = data_loader.get_tactical_exercise_enemies()
            if enemy_id not in enemies:
                raise SnapshotError(f"未知敌方编号 {enemy_id}")

    panel = state.get("panel") or {}
    for cid in placed:
        modules = panel.get("modules", {}).get(str(cid))
        if modules is None:
            continue
        if len(modules) != 3:
            raise SnapshotError(f"角色 {cid} 的模块数量必须为 3")
        for index, module in enumerate(modules):
            effects = module.get("gear_effects") or []
            if strict_affixes:
                _check_affixes(cid, index, effects)
    return True


def _check_affixes(cid, module_index, effects):
    """Only structural checks: three entries with distinct, integer types.

    Values are deliberately NOT range-checked here. A fixed manual build may
    legitimately hold non-standard values; only generated candidates must come
    from the candidate table (checked in ``space``).
    """
    if len(effects) != 3:
        raise SnapshotError(f"角色 {cid} 模块{module_index + 1}必须有3条词条")
    types = []
    for effect in effects:
        if not isinstance(effect, dict):
            raise SnapshotError(f"角色 {cid} 模块{module_index + 1}词条结构错误")
        typ = effect.get("effect_type")
        if typ is not None and (isinstance(typ, bool) or not isinstance(typ, int)):
            raise SnapshotError(f"角色 {cid} 词条属性编号必须是整数")
        value = effect.get("value", 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            raise SnapshotError(f"角色 {cid} 词条数值必须是有限数字")
        types.append(typ)
    if len(set(types)) != len(types):
        raise SnapshotError(f"角色 {cid} 模块{module_index + 1}的属性不能重复")


# --------------------------------------------------------------------------- #
# Cache key
# --------------------------------------------------------------------------- #

def active_view(state):
    """Return the part of a snapshot that can affect the battle.

    Unused saved configurations are dropped, and shared memories are sorted
    because their effect does not depend on slot order. Keeping the key tight
    means two genuinely identical battles share one cache entry.
    """
    out = {k: copy.deepcopy(v) for k, v in state.items() if k != "panel"}
    out["memory_ids"] = sorted(out.get("memory_ids", []))
    panel = {k: copy.deepcopy(v) for k, v in state["panel"].items()
             if k not in PER_CHARACTER_FIELDS}
    selected = {str(c) for c in state["friend_positions"] if c is not None}
    for field in PER_CHARACTER_FIELDS:
        mapping = state["panel"].get(field, {})
        panel[field] = {str(k): copy.deepcopy(v) for k, v in mapping.items()
                        if str(k) in selected}
    out["panel"] = panel
    return out


def configuration_key(state):
    """Stable hash identifying a battle configuration (ignoring the seed)."""
    view = active_view(state)
    # Normalise per-character defaults so that an explicit default and an
    # omitted value do not produce two keys for the same battle.
    panel = view["panel"]
    selected = {str(c) for c in view["friend_positions"] if c is not None}
    global_level = panel.get("character_level")
    panel["character_levels"] = {
        cid: panel.get("character_levels", {}).get(cid, global_level)
        for cid in selected}
    panel.pop("character_level", None)
    panel["affection_levels"] = {
        cid: panel.get("affection_levels", {}).get(cid, 1) for cid in selected}
    bonuses = panel.get("equipment_bonuses") or {}
    panel["equipment_bonuses"] = {
        str(typ): {stat: (bonuses.get(str(typ)) or {}).get(stat, 0)
                   for stat in ("hp", "attack", "defense")}
        for typ in (1, 2, 3)}
    for modules in panel.get("modules", {}).values():
        for module in modules:
            module["gear_effects"] = [
                {"effect_type": g.get("effect_type"),
                 "value": float(g.get("value", 0))}
                for g in module.get("gear_effects", [])]
    payload = json.dumps(view, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
