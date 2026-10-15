"""Smoke test: verify the stat-capture hook works and stats actually change with memories."""
import json
import logging
import random
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.combat_v2.battle_flow_controller import BattleConfig  # noqa: E402
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController  # noqa: E402
from src.optimizer.engine import TacticalEvaluator  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json").read_text(encoding="utf-8"))["state"]
STAT_KEYS = ("max_hp", "attack", "defense", "speed", "critical_rate",
             "critical_damage", "favorable_damage")

ev = TacticalEvaluator(str(ROOT), None)


def run(state, seed):
    saved = random.getstate()
    cap = {}
    try:
        random.seed(seed)
        bf, dl = ev.battlefield(state)
        c = TacticalExerciseController(bf, BattleConfig(max_turns=5, enable_rdps=False), data_loader=dl)
        orig = c._apply_memory_card_effects

        def hooked():
            orig()
            for u in bf.friend_team:
                cap[u.name] = {k: float(getattr(u, k, 0.0)) for k in STAT_KEYS}
        c._apply_memory_card_effects = hooked
        res = c.execute_battle()
        return float(res["score"]["total_score"]), cap
    finally:
        random.setstate(saved)


nomem = dict(BASE, memory_ids=[])
withmem = dict(BASE, memory_ids=sorted(BASE["memory_ids"]))

s0, c0 = run(nomem, 9001)
s1, c1 = run(withmem, 9001)

print(f"no memories : score={s0:,.0f}  captured allies={len(c0)}")
print(f"with 6 cards: score={s1:,.0f}  captured allies={len(c1)}")
print()

if c0 and c1:
    print("=== post-memory stat comparison (this is what an analytic layer would predict) ===")
    for name in sorted(set(c0) | set(c1)):
        a, b = c0.get(name, {}), c1.get(name, {})
        diffs = {k: (a.get(k), b.get(k)) for k in STAT_KEYS
                 if a.get(k) != b.get(k)}
        if diffs:
            print(f"\n  {name}")
            for k, (x, y) in diffs.items():
                d = (y or 0) - (x or 0)
                print(f"     {k:18} {x:>11,.1f} -> {y:>11,.1f}  ({d:+,.1f})")
    if c0 == c1:
        print("  NO DIFFERENCES -- hook may not be capturing post-memory state")
    else:
        print("\n  OK: memories DO change captured stats -> analytic model is feasible")
else:
    print("  capture FAILED (empty) -- hook did not run")
