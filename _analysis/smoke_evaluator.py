"""Smoke test: the optimizer evaluator must reproduce the official engine score.

The evaluator rebuilds a battlefield the way the official batch simulator does.
If it diverges even slightly, the optimizer would optimize a different number
than the player sees, so this compares against the official path directly.

Runs 3 real battles for one known-good configuration.
"""
import json
import logging
import random
import sys
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
from src.optimizer.engine import Evaluator  # noqa: E402
from src.optimizer.snapshot import panel_from_dict  # noqa: E402

HERE = Path(__file__).parent
ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")

preset = json.loads((ACC / "tactical_presets" / "火沙耶主c.json").read_text(encoding="utf-8"))
glob = json.loads((ACC / "global_config.json").read_text(encoding="utf-8"))
chars = json.loads((ACC / "char_config.json").read_text(encoding="utf-8"))


def mem_id(entry):
    return int(str(entry).split("]")[0].lstrip("["))


positions = preset["friend_positions"]
memories = sorted(mem_id(m) for m in preset["mems_friend"])

panel = {
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
    panel["character_levels"][str(cid)] = c.get("level", glob["character_level"])
    panel["rarities"][str(cid)] = c.get("rarity", glob["default_rarity"])
    panel["affection_levels"][str(cid)] = c.get("affection", glob["default_affection"])
    panel["skill_levels"][str(cid)] = {str(k): v for k, v in c.get("skill_levels", {}).items()}
    gear = c.get("gear", [])
    mods = []
    for g, key in enumerate(("hp", "atk", "def")):
        mods.append(dict(module_id=31 + g,
                         tier=c.get(f"mod_tier_{key}", c.get("mod_tier", 10)),
                         level=c.get(f"mod_level_{key}", c.get("mod_level", 55)),
                         gear_effects=[dict(effect_type=e["effect_type"],
                                            value=float(e["value"]))
                                       for e in gear if e.get("group") == g]))
    panel["modules"][str(cid)] = mods

state = {"schema": 1, "enemy_id": preset["enemy_id"],
         "friend_positions": list(positions), "memory_ids": memories,
         "panel": panel}

SEEDS = [777001, 777002, 777003]

# ---- optimizer path ----
ev = Evaluator(str(ROOT), None, mode="tactical")
print("=== optimizer evaluator ===")
opt_scores = []
for seed in SEEDS:
    score = ev.evaluate(state, seed)
    opt_scores.append(score)
    print(f"  seed {seed}: {score:,.0f}")

# ---- official path, replicated inline ----
print()
print("=== official batch-simulator path (independent rebuild) ===")
loader = DataLoader(base_path=str(ROOT))
loader.load_all()
loader.get_tactical_exercise_enemies()

ALLY = [Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT, Position.ALLY_RIGHT_FRONT,
        Position.ALLY_LEFT_BACK, Position.ALLY_CENTER_BACK, Position.ALLY_RIGHT_BACK]
ENEMY = [Position.ENEMY_LEFT_FRONT, Position.ENEMY_CENTER_FRONT, Position.ENEMY_RIGHT_FRONT,
         Position.ENEMY_LEFT_BACK, Position.ENEMY_CENTER_BACK, Position.ENEMY_RIGHT_BACK]

official_scores = []
for seed in SEEDS:
    random.seed(seed)
    pc = panel_from_dict(panel)
    pl = pc.get_player_config()
    sc = StatCalculator(loader.load_level_lerp_data(), data_loader=loader)
    bf = BattlefieldState()
    for i, cid in enumerate(positions):
        if cid is None:
            continue
        u = _create_unit_worker(loader, pc, pl, sc, cid, Side.ALLY, ALLY[i])
        bf.add_unit(u)
    edata = loader.get_tactical_exercise_enemies()[preset["enemy_id"]]
    epos = ENEMY[max(0, min(5, int(edata.get("position", 2)) - 1))]
    bf.add_unit(_create_tactical_enemy_worker(loader, edata, epos))
    for mid in memories:
        m = loader.get_memory(mid)
        bf.memory_cards.append(MemoryCard(
            mid, m.name, m.description, m.rarity,
            [MemoryHighlight(**{k: getattr(h, k) for k in h.__dataclass_fields__})
             for h in m.highlights]))
    cfg = BattleConfig(max_axes := None) if False else BattleConfig(max_turns=5, enable_rdps=False)
    ctrl = TacticalExerciseController(bf, cfg, data_loader=loader)
    res = ctrl.execute_battle()
    official_scores.append(float(res["score"]["total_score"]))
    print(f"  seed {seed}: {official_scores[-1]:,.0f}")

print()
print("=== comparison ===")
ok = True
for seed, a, b in zip(SEEDS, opt_scores, official_scores):
    same = abs(a - b) < 1e-6
    ok = ok and same
    print(f"  seed {seed}: optimizer={a:,.0f}  official={b:,.0f}  "
          f"{'IDENTICAL' if same else 'MISMATCH'}")
print()
print("RESULT:", "evaluator matches the official engine" if ok
      else "MISMATCH -- evaluator is not scoring the same battle")
sys.exit(0 if ok else 1)
