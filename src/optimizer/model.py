"""JSON snapshots: fixed engine inputs and strict optimizer candidates (no formulas)."""
import copy
import hashlib
import json
import math
import logging
from dataclasses import asdict
from pathlib import Path

from src.config.character_config import ModuleConfig
from src.config.panel_config import PanelConfig
from src.config.player_config import SchoolLevels

from src.data.module_affixes import OPTIMIZER_AFFIXES as AFFIXES, ATTRIBUTE_NAMES
OPTIMIZER_LOG = logging.getLogger("izanami.optimizer")


def diagnostic_configuration_id(state):
    """Works even for incomplete/illegal input, before the strict cache key exists."""
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()[:16]


class AffixValidationError(ValueError):
    """An affix-only error is recoverable; structural and engine errors are not."""
    def __init__(self, message, state, character_id, module_number, actual):
        super().__init__(message)
        self.state = state
        self.details = {"character_id": character_id, "module_number": module_number,
                        "actual_affixes": copy.deepcopy(actual),
                        "configuration_id": diagnostic_configuration_id(state)}


def record_diagnostic(notes, **details):
    if notes is not None and len(notes) < 1000:
        notes.append(copy.deepcopy(details))
    log = OPTIMIZER_LOG.warning if ("修复" in details.get("action", "") or
                                    "错误" in details.get("action", "")) else OPTIMIZER_LOG.info
    log("优化器配置处理：%s", json.dumps(details, ensure_ascii=False, default=str))


def _affix_problem(gears):
    if gears is None:
        return "缺少词条"
    if not isinstance(gears, list):
        raise ValueError(f"模块词条数据必须是列表，实际为 {type(gears).__name__}")
    if any(not isinstance(g, dict) for g in gears):
        raise ValueError("模块词条数据必须是字典列表")
    if any(g.get("effect_type") is not None and
           (isinstance(g.get("effect_type"), bool) or not isinstance(g.get("effect_type"), int))
           for g in gears):
        raise ValueError("词条属性编号必须是整数或缺省，不能是列表/对象/字符串")
    if len(gears) != 3 or len({g.get("effect_type") for g in gears}) != 3:
        return "必须有3条不同属性的词条"
    for g in gears:
        typ, value = g.get("effect_type"), g.get("value")
        allowed = [v for _, v in AFFIXES.get(typ, ())]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value not in allowed):
            return f"词条 {typ}/{value} 不在V1合法列表"
    return None


def _legal_gears(gears):
    """Create a separate candidate; retain exact candidates, never snap manual values."""
    problem = _affix_problem(gears)
    if not problem:
        return copy.deepcopy(gears)
    if gears is None:
        gears = []
    used, result = set(), []
    for i in range(3):
        old = gears[i] if i < len(gears) else {}
        typ = old.get("effect_type")
        if typ not in AFFIXES or typ in used:
            typ = next(t for t in AFFIXES if t not in used)
        value = old.get("value", 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            value = 0
        number = value if any(value == v for _, v in AFFIXES[typ]) else AFFIXES[typ][-1][1]
        result.append(dict(old, effect_type=typ, value=number))
        used.add(typ)
    return result


def panel_to_dict(panel):
    # JSON canonicalization also removes int/string key differences after loading.
    return json.loads(json.dumps(asdict(panel), ensure_ascii=False))


def panel_from_dict(data):
    data = copy.deepcopy(data)
    data["school_levels"] = SchoolLevels(**data.get("school_levels", {}))
    for key in ("equipment_bonuses", "character_levels", "rarities", "affection_levels"):
        data[key] = {int(k): v for k, v in data.get(key, {}).items()}
    data["modules"] = {int(k): [ModuleConfig(**m) for m in v]
                       for k, v in data.get("modules", {}).items()}
    data["skill_levels"] = {int(k): {int(s): lv for s, lv in v.items()}
                            for k, v in data.get("skill_levels", {}).items()}
    return PanelConfig(**data)


def memory_id(entry):
    if isinstance(entry, int):
        return entry
    if not entry:
        return None
    try:
        return int(str(entry).split("]")[0].lstrip("["))
    except ValueError:
        raise ValueError(f"无法识别回忆编号：{entry}") from None


def snapshot(selection, panel):
    positions = selection.get("friend_positions")
    if positions is None:
        positions = list(selection.get("friends", []))
    positions = list(positions) + [None] * (6 - len(positions))
    memories = [memory_id(m) for m in selection.get("mem_friend_positions",
                                                   selection.get("mems_friend", []))]
    memories = [m for m in memories if m is not None]
    panel_data = panel_to_dict(panel)
    selected = {str(c) for c in positions if c is not None}
    for field in ("modules", "skill_levels", "character_levels", "rarities", "affection_levels"):
        panel_data[field] = {k: v for k, v in panel_data[field].items() if k in selected}
    return {"schema": 1, "enemy_id": selection.get("enemy_id"),
            "friend_positions": positions, "memory_ids": memories,
            "panel": panel_data}


def selection_from_snapshot(state):
    return {"enemy_id": state["enemy_id"], "friend_positions": state["friend_positions"],
            "friends": [c for c in state["friend_positions"] if c is not None],
            "mem_friend_positions": [f"[{m}]" for m in state["memory_ids"]],
            "mems_friend": [f"[{m}]" for m in state["memory_ids"]]}


def validate_snapshot(state, dl=None, affixes=True, *, allow_empty_memories=False,
                      check_enemy=True):
    """Validate a lineup snapshot.

    ``check_enemy`` exists for 对抗压制战: a circle stage fields its own multi-enemy
    lineup and never reads ``state["enemy_id"]``, so requiring a valid tactical boss
    there would reject every legitimate circle snapshot. It defaults to True, so the
    ported tactical behaviour is unchanged.
    """
    positions = state.get("friend_positions", [])
    chars = [c for c in positions if c is not None]
    if len(positions) != 6 or len(chars) != 5 or len(set(chars)) != 5:
        raise ValueError("必须选择5名不同角色、6个站位且恰好1个空位")
    memories = state.get("memory_ids", [])
    if not (allow_empty_memories and memories == []) and (len(memories) != 6 or len(set(memories)) != 6):
        raise ValueError("必须选择6张不同的全队共享回忆")
    panel = panel_from_dict(active_snapshot(state)["panel"])
    for cid in chars:
        if not isinstance(cid, int) or cid <= 0 or (dl and not dl.get_character_by_id(cid)):
            raise ValueError(f"角色 {cid} 不存在；V1暂不支持自定义木桩")
        modules = panel.modules.get(cid, [])
        for i, module in enumerate(modules, 1):
            gears = module.gear_effects
            if not isinstance(gears, list):
                raise AffixValidationError(f"角色 {cid} 模块{i}词条必须为列表", state, cid, i, gears)
            for slot, gear in enumerate(gears, 1):
                if not isinstance(gear, dict):
                    raise AffixValidationError(f"角色 {cid} 模块{i}词条{slot}必须为字典", state, cid, i, gears)
                typ, value = gear.get("effect_type", 0), gear.get("value", 0)
                if (isinstance(typ, bool) or not isinstance(typ, int) or typ not in range(8)
                        or isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value)):
                    raise AffixValidationError(f"角色 {cid} 模块{i}词条{slot}属性={typ!r} 数值={value!r}："
                                               "属性须为0..7且数值为有限数字", state, cid, i, gears)
        if not affixes:
            continue
        if len(modules) != 3:
            raise AffixValidationError(f"角色 {cid} 必须有3个模块", state, cid, None,
                                       [m.gear_effects for m in modules])
        for i, module in enumerate(modules, 1):
            gears = module.gear_effects
            problem = _affix_problem(gears)
            if problem:
                raise AffixValidationError(f"角色 {cid} 模块{i}{problem}", state, cid, i, gears)
    if dl:
        # The boss check only makes sense when the snapshot names one. A circle stage
        # supplies no tactical enemy_id -- its enemies come from the stage lineup --
        # so validating `None` against the tactical boss list would reject every
        # legitimate circle snapshot. When there IS an id, it must still be a real one.
        enemy_id = state.get("enemy_id")
        if check_enemy and enemy_id is not None \
                and enemy_id not in dl.get_tactical_exercise_enemies():
            raise ValueError("请选择有效的战术演习Boss")
        if any(not dl.get_memory(m) for m in memories):
            raise ValueError("包含不存在的回忆")
    return panel


def default_constraints(state):
    chars = [c for c in state["friend_positions"] if c is not None]
    return {"characters": {str(c): "必选" for c in chars},
            "memories": {str(m): "必选" for m in state["memory_ids"]}}


def validate_constraints(state, constraints, dl=None, require_current=True):
    for key, current, size in (("characters", [c for c in state["friend_positions"] if c is not None], 5),
                               ("memories", state["memory_ids"], 6)):
        pool = constraints.get(key, {})
        if any(v not in ("必选", "候选") for v in pool.values()):
            raise ValueError("约束标记只能为必选或候选；未列出的对象自动排除")
        required = {int(c) for c, v in pool.items() if v == "必选"}
        available = {int(c) for c in pool}
        label = "角色" if key == "characters" else "回忆"
        if len(required) > size:
            raise ValueError(f"必选{label}{len(required)}个，超过{size}个上限")
        if len(available) < size:
            raise ValueError(f"{label}必选与候选合计{len(available)}个，无法补齐{size}个")
        if require_current and (not required.issubset(current) or not set(current).issubset(available)):
            raise ValueError("当前阵容不满足必选/候选约束")
        if dl:
            for ident in available:
                valid = dl.get_character_by_id(ident) if key == "characters" else dl.get_memory(ident)
                if not valid or ident <= 0:
                    raise ValueError(f"约束中存在无效编号 {ident}")


def initialize_character(state, cid, dl=None, diagnostics=None, *, operation="初始化候选",
                         fifth_replacement=False, optimize_affixes=True):
    """Initialize a character IN AN ALREADY PRIVATE snapshot, never global config.

    Existing fixed fields and legal affixes are retained. Missing fixed fields use
    PanelConfig/engine defaults; absent modules use the original GUI's 10/55 defaults.
    Every fallback and affix repair is recorded separately from the manual baseline.
    """
    panel, key = state["panel"], str(cid)
    if not optimize_affixes and key in panel.get("modules", {}):
        return  # Existing fixed configuration is an exact engine input, including sparse gear.
    configuration_id = diagnostic_configuration_id(state)
    context = dict(character_id=cid, operation=operation, fifth_replacement=fifth_replacement,
                   configuration_id=configuration_id)
    char = dl.get_character_by_id(cid) if dl else None
    if dl and not char:
        raise ValueError(f"角色 {cid} 不存在；操作={operation}，配置={configuration_id}")
    defaults = {"character_levels": panel.get("character_level", 200),
                "affection_levels": 1}
    if char:
        defaults["rarities"] = char.default_rarity
    for field, value in defaults.items():
        mapping = panel.setdefault(field, {})
        if not isinstance(mapping, dict):
            raise ValueError(f"角色{cid} {field}必须是字典；操作={operation}，配置={configuration_id}")
        if key not in mapping:
            mapping[key] = value
            record_diagnostic(diagnostics, **context, action="采用固定参数默认值",
                              field=field, default_value=value, source="PanelConfig/原引擎默认值",
                              module_number=None, actual_affixes=None)
    skills = panel.setdefault("skill_levels", {}).setdefault(key, {})
    if not isinstance(skills, dict):
        raise ValueError(f"角色{cid}技能等级必须是字典；操作={operation}，配置={configuration_id}")
    if dl:
        for sid in dl.load_character_skills().get(cid, []):
            if str(sid) not in skills and sid not in skills:
                skills[str(sid)] = 1  # Original battle engine's .get(skill_id, 1).
                record_diagnostic(diagnostics, **context, action="采用固定参数默认值",
                                  field=f"skill_levels.{sid}", default_value=1,
                                  source="原战斗引擎未配置技能等级默认为1",
                                  module_number=None, actual_affixes=None)
    mods = panel.setdefault("modules", {}).setdefault(key, [])
    if not isinstance(mods, list) or any(not isinstance(m, dict) for m in mods):
        raise ValueError(f"角色{cid}模块结构必须是字典列表；操作={operation}，配置={configuration_id}")
    if len(mods) > 3:
        raise ValueError(f"角色{cid}有{len(mods)}个模块，结构不支持；操作={operation}，配置={configuration_id}")
    if len(mods) < 3 and not char:
        raise ValueError(f"角色{cid}缺少模块固定参数，需要角色数据加载器；操作={operation}，配置={configuration_id}")
    while len(mods) < 3:
        mods.append({})
    for i, mod in enumerate(mods, 1):
        defaults = {"tier": 10, "level": 55}
        if char:
            defaults["module_id"] = char.character_type * 10 + i
        for field, value in defaults.items():
            if field not in mod:
                mod[field] = value
                record_diagnostic(diagnostics, **context, action="采用模块固定参数默认值",
                                  field=field, default_value=value, module_number=i,
                                  source="原GUI模块默认Tier10/等级55及角色类型模块ID",
                                  actual_affixes=mod.get("gear_effects", []))
        if "module_id" not in mod:
            raise ValueError(f"角色{cid}模块{i}缺少module_id；操作={operation}，配置={configuration_id}")
        gears = mod.get("gear_effects", [])
        if not optimize_affixes:
            continue  # Fixed manual/custom inputs are never candidate-initialized.
        try:
            problem = _affix_problem(gears)
        except ValueError as exc:
            record_diagnostic(diagnostics, **context, action="不可恢复的词条结构错误",
                              module_number=i, actual_affixes=gears, error=str(exc))
            raise ValueError(f"角色{cid}模块{i}：{exc}；操作={operation}，配置={configuration_id}") from exc
        if problem:
            mod["gear_effects"] = _legal_gears(gears)
            record_diagnostic(diagnostics, **context, action="修复候选模块词条", reason=problem,
                              module_number=i, actual_affixes=gears,
                              initialized_affixes=mod["gear_effects"])


def _constrained_ids(current, pool, size):
    required = [int(k) for k, mark in pool.items() if mark == "必选"]
    available = [int(k) for k in pool]
    chosen = list(required)
    chosen += [c for c in current if c is not None and c in available and c not in chosen]
    chosen += [c for c in available if c not in chosen]
    return chosen[:size]


def prepare_search_snapshot(state, constraints, dl=None, diagnostics=None, *,
                            change_fifth=True, change_memories=True, change_affixes=True):
    """Create a legal starting lineup under new constraints; manual state is untouched."""
    out = copy.deepcopy(state)
    validate_constraints(out, constraints, dl, require_current=False)
    chosen = _constrained_ids(out["friend_positions"], constraints["characters"], 5)
    original_chars = {c for c in state["friend_positions"] if c is not None}
    required_chars = {int(k) for k, v in constraints["characters"].items() if v == "必选"}
    available_chars = {int(k) for k in constraints["characters"]}
    if not change_fifth and (not required_chars.issubset(original_chars)
                             or not original_chars.issubset(available_chars)):
        raise ValueError("当前角色阵容不满足新约束；请开启允许更换第五人，或恢复原五人的必选/候选标记")
    required_memories = {int(k) for k, v in constraints["memories"].items() if v == "必选"}
    available_memories = {int(k) for k in constraints["memories"]}
    if not change_memories and (not required_memories.issubset(state["memory_ids"])
                                or not set(state["memory_ids"]).issubset(available_memories)):
        raise ValueError("当前回忆阵容不满足新约束；请开启允许调整回忆，或恢复原六张回忆的标记")
    retained = {c for c in out["friend_positions"] if c in chosen}
    additions = iter(c for c in chosen if c not in retained)
    for i, cid in enumerate(out["friend_positions"]):
        if cid is not None and cid not in chosen:
            out["friend_positions"][i] = next(additions)
    # A valid original has exactly five occupied positions, so no empty slot is filled.
    out["memory_ids"] = _constrained_ids(out["memory_ids"], constraints["memories"], 6)
    # Preserve memory order when no constraint change is needed: order can matter.
    if required_memories.issubset(state["memory_ids"]) and set(state["memory_ids"]).issubset(
            int(k) for k in constraints["memories"]):
        out["memory_ids"] = list(state["memory_ids"])
    if out["friend_positions"] != state["friend_positions"] or out["memory_ids"] != state["memory_ids"]:
        record_diagnostic(diagnostics, action="按新约束建立搜索起点", operation="初始化搜索起点",
                          character_id=None, module_number=None, actual_affixes=None,
                          fifth_replacement=out["friend_positions"] != state["friend_positions"],
                          configuration_id=diagnostic_configuration_id(state),
                          friend_positions=out["friend_positions"], memory_ids=out["memory_ids"])
    active = {c for c in out["friend_positions"] if c is not None}
    for key in constraints["characters"]:
        cid = int(key)
        if cid not in active and not change_fifth:
            continue
        if not change_affixes and cid in original_chars:
            continue  # Even an absent module configuration is a valid fixed engine input.
        initialize_character(out, cid, dl, diagnostics,
                             operation="初始化搜索起点" if cid in active else "初始化第五人候选",
                             fifth_replacement=cid not in state["friend_positions"], optimize_affixes=change_affixes)
    validate_snapshot(out, dl, affixes=change_affixes)
    validate_constraints(out, constraints, dl)
    return out


def active_snapshot(state):
    """Only participating characters are battle inputs; inactive configs remain source data."""
    # Filter BEFORE copying: large unused candidate pools are not battle inputs.
    out = {key: copy.deepcopy(value) for key, value in state.items() if key != "panel"}
    out["panel"] = {key: copy.deepcopy(value) for key, value in state["panel"].items()
                    if key not in ("modules", "skill_levels", "character_levels", "rarities", "affection_levels")}
    selected = {str(c) for c in state["friend_positions"] if c is not None}
    for field in ("modules", "skill_levels", "character_levels", "rarities", "affection_levels"):
        mapping = state["panel"].get(field, {})
        if not isinstance(mapping, dict):
            raise ValueError(f"面板字段{field}必须是字典；配置={diagnostic_configuration_id(state)}")
        out["panel"][field] = {str(k): copy.deepcopy(v) for k, v in mapping.items() if str(k) in selected}
    return out


def configuration_key(state):
    state = active_snapshot(state)
    state["memory_ids"] = sorted(state["memory_ids"])
    selected = {str(c) for c in state["friend_positions"] if c is not None}
    for field in ("modules", "skill_levels", "character_levels", "rarities", "affection_levels"):
        state["panel"][field] = {str(k): v for k, v in state["panel"].get(field, {}).items() if str(k) in selected}
    panel = state["panel"]
    panel["character_levels"] = {cid: panel["character_levels"].get(cid, panel["character_level"]) for cid in selected}
    panel.pop("character_level")  # All participating levels are now explicit.
    panel["affection_levels"] = {cid: panel["affection_levels"].get(cid, 1) for cid in selected}
    panel["equipment_bonuses"] = {str(typ): {stat: panel["equipment_bonuses"].get(str(typ), {}).get(stat, 0)
                                              for stat in ("hp", "attack", "defense")} for typ in (1, 2, 3)}
    for modules in state["panel"]["modules"].values():
        for module in modules:
            module["gear_effects"] = [{"effect_type": g.get("effect_type"),
                                      "value": float(g.get("value", 0))}
                                      for g in module.get("gear_effects", [])]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def legalize_affixes(state):
    """Explicit user-requested conversion only; never alters modules/levels/skills."""
    state = copy.deepcopy(state)
    for cid in state["friend_positions"]:
        if cid is None:
            continue
        mods = state["panel"]["modules"].get(str(cid), [])
        if len(mods) != 3:
            raise ValueError(f"角色{cid}缺少3个模块；请在角色参数中配置")
        for mod in mods:
            old = mod["gear_effects"]
            used, new = set(), []
            for i in range(3):
                gear = old[i] if i < len(old) else {}
                typ = gear.get("effect_type")
                if typ not in AFFIXES or typ in used:
                    typ = next(t for t in AFFIXES if t not in used)
                used.add(typ)
                value = float(gear.get("value", 0))
                grade, number = min(AFFIXES[typ], key=lambda item: abs(item[1] - value))
                new.append({"effect_type": typ, "value": number})
            mod["gear_effects"] = new
    return state
