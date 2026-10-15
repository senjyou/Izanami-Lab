"""End-to-end pipeline acceptance against a REAL lineup, with a stub engine.

The point is to exercise the full 4-step pipeline on the user's actual lineups
(so the space, constraints and rendering paths are realistic) while replacing the
battle engine with a deterministic stub. That keeps the run free and lets the
test assert exact expectations about ranking under both objectives.

Real-battle correctness was verified separately (the evaluator reproduces the
official engine bit-for-bit on 火沙耶主c).
"""

import json
import random
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))

from src.optimizer import objective as obj  # noqa: E402
from src.optimizer import search as search_mod  # noqa: E402
from src.optimizer.snapshot import (  # noqa: E402
    build_snapshot, configuration_key, panel_from_dict)


def panel_config_for(positions, level=None):
    """Build a real PanelConfig, the way the GUI hands one to the mixin."""
    return panel_from_dict(panel_for(positions, level))

ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")
failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  OK    {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


# ---------------------------------------------------------------- real lineups
glob = json.loads((ACC / "global_config.json").read_text(encoding="utf-8"))
chars = json.loads((ACC / "char_config.json").read_text(encoding="utf-8"))


def panel_for(positions, level=None):
    panel = {
        "character_level": level or glob["character_level"],
        "school_levels": dict(glob["school_levels"]),
        "equipment_ids": [], "equipment_enabled": True,
        "equipment_bonuses": {int(k): dict(v) for k, v in glob.get("equipment", {}).items()},
        "character_levels": {}, "rarities": {}, "affection_levels": {},
        "modules": {}, "skill_levels": {},
    }
    for cid in positions:
        if not cid:
            continue
        c = chars[str(cid)]
        panel["character_levels"][str(cid)] = c.get("level", glob["character_level"])
        panel["rarities"][str(cid)] = c.get("rarity", glob["default_rarity"])
        panel["affection_levels"][str(cid)] = c.get("affection", glob["default_affection"])
        panel["skill_levels"][str(cid)] = {str(k): v for k, v in c.get("skill_levels", {}).items()}
        gear = c.get("gear", [])
        panel["modules"][str(cid)] = [
            dict(module_id=31 + g,
                 tier=c.get(f"mod_tier_{k}", c.get("mod_tier", 10)),
                 level=c.get(f"mod_level_{k}", c.get("mod_level", 55)),
                 gear_effects=[dict(effect_type=e["effect_type"], value=float(e["value"]))
                               for e in gear if e.get("group") == g])
            for g, k in enumerate(("hp", "atk", "def"))]
    return panel


class StubEngine:
    """Deterministic stand-in: score depends on which slot the empty one is in.

    Slot 1 (the empty slot being leftmost) is made clearly best; slot 6 clearly
    worst. Each profile also carries a spread so the two objectives can disagree.
    """

    def __init__(self, base_scores, spread_scale=1.0):
        self.base = base_scores
        self.spread = spread_scale
        self.calls = 0

    @staticmethod
    def _unit(seed):
        raw = [random.Random(seed * 31 + k * 7919).random() for k in range(12)]
        return sum(raw) - 6.0

    def evaluate(self, state, seed):
        self.calls += 1
        positions = state["friend_positions"]
        empty = positions.index(None) if None in positions else 0
        mean, spread = self.base.get(empty, (1000.0, 10.0))
        return mean + spread * self.spread * self._unit(seed)


# 火沙耶主c: empty slot 1 (index 1) is the current arrangement.
preset = json.loads((ACC / "tactical_presets" / "火沙耶主c.json").read_text(encoding="utf-8"))
positions = preset["friend_positions"]
mems = [int(str(m).split("]")[0].lstrip("[")) for m in preset["mems_friend"]]
selection = {"friends": [c for c in positions if c],
             "friend_positions": positions, "enemy_id": preset["enemy_id"],
             "mems_friend": [f"[{m}]" for m in mems],
             "mem_friend_positions": [f"[{m}]" for m in mems]}
template = build_snapshot(selection, panel_config_for(positions),
                          enemy_id=preset["enemy_id"])

print("=== real template built from 火沙耶主c ===")
print(f"    positions {template['friend_positions']}")
print(f"    memories  {template['memory_ids']}")
check("template validates as 5 characters + 1 empty",
      len([c for c in template["friend_positions"] if c]) == 5)
check("template carries 6 memories", len(template["memory_ids"]) == 6)

constraints = {"memories": {str(m): "必选" for m in template["memory_ids"]}}

print()
print("=== position-only search, mean objective ===")
engine = StubEngine({1: (1000.0, 2.0), 5: (1000.0, 2.0)})
settings = search_mod.SearchSettings(objective=obj.OBJECTIVE_MEAN, budget=400,
                                     change_memories=False, review_seeds=4)
result = search_mod.run_search(engine, template, constraints, settings)
check("search produced candidates", bool(result.candidates), len(result.candidates))
check("battles within budget", result.battles <= 400, result.battles)
check("every candidate has a full cohort",
      all(c["summary"]["n"] == 4 for c in result.candidates))
check("baseline present", any(c["is_baseline"] for c in result.candidates))
print(f"    battles={result.battles} candidates={len(result.candidates)} "
      f"best empty-slot={result.best['friend_positions'].index(None)}")
check("space reports 720 positions", result.space["positions"] == 720,
      result.space)

print()
print("=== the two objectives can disagree on the same lineup ===")
# Empty slot 6 has the higher mean; empty slot 1 has the wider spread, so it wins
# under Roll5.
engine = StubEngine({5: (1200.0, 2.0), 1: (1100.0, 120.0)})
mean_result = search_mod.run_search(
    engine, template, constraints,
    search_mod.SearchSettings(objective=obj.OBJECTIVE_MEAN, budget=1500,
                              change_memories=False, review_seeds=8,
                              adaptive_boost=False))
roll_result = search_mod.run_search(
    engine, template, constraints,
    search_mod.SearchSettings(objective=obj.OBJECTIVE_ROLL5, budget=1500,
                              change_memories=False, review_seeds=8,
                              coarse_seeds=2, adaptive_boost=False))
mean_slot = mean_result.best["friend_positions"].index(None)
roll_slot = roll_result.best["friend_positions"].index(None)
print(f"    mean-mode best empty slot: {mean_slot}")
print(f"    roll5-mode best empty slot: {roll_slot}")
check("mean mode picks the steady arrangement", mean_slot == 5, mean_slot)
check("roll5 mode picks the volatile arrangement", roll_slot == 1, roll_slot)
check("the two modes return different champions", mean_slot != roll_slot)

print()
print("=== rendering paths produce sane output ===")
from gui.optimizer_report import NameResolver, format_report  # noqa: E402
from src.data.data_loader import DataLoader  # noqa: E402

_loader = DataLoader(base_path=str(ROOT))
_loader.load_all()
report = format_report(roll_result.to_dict(), NameResolver(_loader))
check("report mentions the objective", "Roll5" in report, report[:80])
check("report mentions battles", "场" in report)
check("report has a leaderboard", "候选排行" in report or "冠军配置" in report)
check("report shows no raw id list", "memory_ids" not in report)
# The display rules: names, never ids, and no table.
for cid in (100303, 132301, 145301, 112302, 111301):
    check(f"character id {cid} does not appear",
          str(cid) not in report, "raw id leaked into the report")
for mid in mems:
    check(f"memory id {mid} does not appear", str(mid) not in report,
          "raw id leaked into the report")
check("report is JSON-safe (no raw samples)",
      "samples" not in json.dumps(roll_result.to_dict(), ensure_ascii=False))
print("--- report preview (first 24 lines) ---")
for line in report.splitlines()[:24]:
    print("    " + line)

print()
print("=== memory-axis search over a real pool ===")
pool = sorted(mems) + [10010, 10011, 10012, 10013, 10014, 10015]
mem_constraints = {
    "memories": {**{str(m): "必选" for m in mems[:2]},
                 **{str(m): "候选" for m in pool if m not in mems[:2]}}}
engine = StubEngine({}, spread_scale=1.0)
mem_result = search_mod.run_search(
    engine, template, mem_constraints,
    search_mod.SearchSettings(objective=obj.OBJECTIVE_ROLL5, budget=600,
                              change_positions=False, review_seeds=8,
                              coarse_seeds=2))
check("memory search produced candidates", bool(mem_result.candidates))
check("required memories are always present",
      all(all(m in c["memory_ids"] for m in mems[:2]) for c in mem_result.candidates))
check("candidates always carry exactly 6 distinct memories",
      all(len(set(c["memory_ids"])) == 6 for c in mem_result.candidates))
print(f"    memories searched: {mem_result.space['memories']} combinations, "
      f"battles={mem_result.battles}")

print()
if failures:
    print(f"FAILED ({len(failures)}): " + ", ".join(failures))
    sys.exit(1)
print("all end-to-end acceptance checks passed")
