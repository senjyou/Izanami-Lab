"""Measure where optimizer battle time goes, against the official batch path.

Compares, for the same configuration and N battles:

  A. the optimizer's Evaluator (one evaluate() call per battle)
  B. the official batch simulator's per-battle loop (from batch_simulator.py)
  C. an "optimizer without per-battle rebuild" variant, to size the overhead

The goal is a number: how many battles per second each path delivers, and what
fraction of the optimizer's time is spent rebuilding versus fighting.
"""

import cProfile
import io
import json
import logging
import pstats
import random
import sys
import time
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.combat_v2.battle_flow_controller import BattleConfig  # noqa: E402
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController  # noqa: E402
from src.data.data_loader import DataLoader  # noqa: E402
from src.data.stat_calculator import StatCalculator  # noqa: E402
from src.entities_v2.battlefield_state import BattlefieldState  # noqa: E402
from src.entities_v2.enums import Position, Side  # noqa: E402
from src.entities.memory_card import MemoryCard, MemoryHighlight  # noqa: E402
from src.utils.batch_simulator import (  # noqa: E402
    _create_tactical_enemy_worker, _create_unit_worker)
from src.optimizer.engine import Evaluator, BattleDataView  # noqa: E402
from src.optimizer.snapshot import panel_from_dict  # noqa: E402

ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")
N = 40

glob = json.loads((ACC / "global_config.json").read_text(encoding="utf-8"))
chars = json.loads((ACC / "char_config.json").read_text(encoding="utf-8"))
preset = json.loads((ACC / "tactical_presets" / "火沙耶主c.json").read_text(encoding="utf-8"))
positions = preset["friend_positions"]
mems = sorted(int(str(m).split("]")[0].lstrip("[")) for m in preset["mems_friend"])

panel_data = {
    "character_level": glob["character_level"],
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
    panel_data["character_levels"][str(cid)] = c.get("level", glob["character_level"])
    panel_data["rarities"][str(cid)] = c.get("rarity", glob["default_rarity"])
    panel_data["affection_levels"][str(cid)] = c.get("affection", glob["default_affection"])
    panel_data["skill_levels"][str(cid)] = {str(k): v for k, v in c.get("skill_levels", {}).items()}
    gear = c.get("gear", [])
    panel_data["modules"][str(cid)] = [
        dict(module_id=31 + g,
             tier=c.get(f"mod_tier_{k}", c.get("mod_tier", 10)),
             level=c.get(f"mod_level_{k}", c.get("mod_level", 55)),
             gear_effects=[dict(effect_type=e["effect_type"], value=float(e["value"]))
                           for e in gear if e.get("group") == g])
        for g, k in enumerate(("hp", "atk", "def"))]

state = {"schema": 1, "enemy_id": preset["enemy_id"],
         "friend_positions": list(positions), "memory_ids": mems,
         "panel": panel_data}

ALLY = [Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT, Position.ALLY_RIGHT_FRONT,
        Position.ALLY_LEFT_BACK, Position.ALLY_CENTER_BACK, Position.ALLY_RIGHT_BACK]
ENEMY = [Position.ENEMY_LEFT_FRONT, Position.ENEMY_CENTER_FRONT, Position.ENEMY_RIGHT_FRONT,
         Position.ENEMY_LEFT_BACK, Position.ENEMY_CENTER_BACK, Position.ENEMY_RIGHT_BACK]

print(f"=== A. optimizer Evaluator, {N} battles ===")
ev = Evaluator(str(ROOT), None, mode="tactical")
t0 = time.perf_counter()
for i in range(N):
    ev.evaluate(state, 900000 + i)
tA = time.perf_counter() - t0
print(f"    {tA:.2f}s total   {N/tA:.1f} battles/s   {tA/N*1000:.0f} ms/battle")

print()
print(f"=== B. official batch loop, {N} battles ===")
loader = DataLoader(base_path=str(ROOT))
loader.load_all()
loader.get_tactical_exercise_enemies()
t0 = time.perf_counter()
for i in range(N):
    random.seed(900000 + i)
    pc = panel_from_dict(panel_data)
    pl = pc.get_player_config()
    sc = StatCalculator(loader.load_level_lerp_data(), data_loader=loader)
    bf = BattlefieldState()
    for j, cid in enumerate(positions):
        if cid is None:
            continue
        bf.add_unit(_create_unit_worker(loader, pc, pl, sc, cid, Side.ALLY, ALLY[j]))
    ed = loader.get_tactical_exercise_enemies()[preset["enemy_id"]]
    epos = ENEMY[max(0, min(5, int(ed.get("position", 2)) - 1))]
    bf.add_unit(_create_tactical_enemy_worker(loader, ed, epos))
    for mid in mems:
        m = loader.get_memory(mid)
        bf.memory_cards.append(MemoryCard(
            mid, m.name, m.description, m.rarity,
            [MemoryHighlight(**{k: getattr(h, k) for k in h.__dataclass_fields__})
             for h in m.highlights]))
    Tac = TacticalExerciseController(
        bf, BattleConfig(max_turns=5, enable_rdps=False), data_loader=loader)
    Tac.execute_battle()
tB = time.perf_counter() - t0
print(f"    {tB:.2f}s total   {N/tB:.1f} battles/s   {tB/N*1000:.0f} ms/battle")

print()
print(f"=== C. official path but REUSING one loader view per battle only ===")
# Same as B, but isolates how much of B is the per-battle panel/StatCalculator work.
t0 = time.perf_counter()
pc = panel_from_dict(panel_data)
pl = pc.get_player_config()
lerp = loader.load_level_lerp_data()
for i in range(N):
    random.seed(900000 + i)
    sc = StatCalculator(lerp, data_loader=loader)
    bf = BattlefieldState()
    for j, cid in enumerate(positions):
        if cid is None:
            continue
        bf.add_unit(_create_unit_worker(loader, pc, pl, sc, cid, Side.ALLY, ALLY[j]))
    ed = loader.get_tactical_exercise_enemies()[preset["enemy_id"]]
    epos = ENEMY[max(0, min(5, int(ed.get("position", 2)) - 1))]
    bf.add_unit(_create_tactical_enemy_worker(loader, ed, epos))
    for mid in mems:
        m = loader.get_memory(mid)
        bf.memory_cards.append(MemoryCard(
            mid, m.name, m.description, m.rarity,
            [MemoryHighlight(**{k: getattr(h, k) for k in h.__dataclass_fields__})
             for h in m.highlights]))
    Tac = TacticalExerciseController(
        bf, BattleConfig(max_turns=5, enable_rdps=False), data_loader=loader)
    Tac.execute_battle()
tC = time.perf_counter() - t0
print(f"    {tC:.2f}s total   {N/tC:.1f} battles/s   {tC/N*1000:.0f} ms/battle")

print()
print("=== ratio ===")
print(f"    optimizer / official = {tA/tB:.2f}x slower")
print(f"    optimizer / reused   = {tA/tC:.2f}x slower")

print()
print(f"=== profile of the optimizer path ({N} battles) ===")
pr = cProfile.Profile()
pr.enable()
for i in range(N):
    ev.evaluate(state, 950000 + i)
pr.disable()
s = io.StringIO()
pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(22)
for line in s.getvalue().splitlines()[:34]:
    print("    " + line)
