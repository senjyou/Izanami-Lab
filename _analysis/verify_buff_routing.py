"""Verify the analytic feature vector DIFFERENTIATES configurations correctly.

Confirms the two properties the new architecture depends on:
  (1) memory sets produce different buff vectors per ally
  (2) position masks route buffs to DIFFERENT allies when slots change
      (so the feature vector detects what the real score cares about)

Zero battles for the routing check; a few for the score sanity check.
"""
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
ev = TacticalEvaluator(str(ROOT), None)


def buff_vector(state, seed=1):
    """Return {ally_name: {effect_type: total_value}} plus score. 1 battle."""
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
                agg = {}
                for b in getattr(u, "buffs", []):
                    agg[b.effect_type] = agg.get(b.effect_type, 0.0) + float(b.value)
                cap[u.name] = agg
        c._apply_memory_card_effects = hooked
        res = c.execute_battle()
        return float(res["score"]["total_score"]), cap
    finally:
        random.setstate(saved)


# --- position swap under a FRONT-ROW-only card set (fixture cards: mask 7) ---
CARD_SETS = {
    "fixture(front-row card 10006 + 4 party-wide + 10005 slot1)": sorted(BASE["memory_ids"]),
    "all-party-wide (10001-10004 + 2 more)": [10001, 10002, 10003, 10004, 10008, 10009],
}

for label, cards in CARD_SETS.items():
    print("=" * 74)
    print(f"memory set: {label}")
    print(f"cards: {cards}")
    base_cfg = dict(BASE, memory_ids=sorted(cards))

    # swap slot 0 (front-left) with slot 3 (back-left)
    swapped = json.loads(json.dumps(base_cfg))
    p = list(swapped["friend_positions"])
    p[0], p[3] = p[3], p[0]
    swapped["friend_positions"] = p

    s_a, a = buff_vector(base_cfg, 9001)
    s_b, b = buff_vector(swapped, 9001)
    print(f"  A positions {base_cfg['friend_positions']}  score={s_a:,.0f}")
    print(f"  B positions {swapped['friend_positions']}  score={s_b:,.0f}")
    print(f"  score delta = {s_b - s_a:+,.0f}  ({(s_b-s_a)/s_a*100:+.2f}%)")

    moved = []
    for name in a:
        if a[name] != b.get(name):
            moved.append(name)
    print(f"  allies whose BUFF VECTOR changed by the swap: {len(moved)}/5")
    for name in moved:
        keys = set(a[name]) | set(b.get(name, {}))
        det = ", ".join(f"{k}: {a[name].get(k,0):g}->{b.get(name,{}).get(k,0):g}"
                        for k in sorted(keys) if a[name].get(k, 0) != b.get(name, {}).get(k, 0))
        print(f"      {name}: {det}")
    print()
