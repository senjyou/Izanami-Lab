"""DECISIVE zero-battle feasibility test for the analytic layer.

Claim to verify: memory cards' static battle_start effects can be computed
analytically (which slot/character gets which stat bonus), so that position
value need NOT be discovered by running battles.

Test: build the SAME battlefield twice with different memory sets --
  (a) no memories
  (b) six cards
and compare the resulting ally unit stats. Any difference is exactly the
"memory contribution" that an analytic model must reproduce.
Also swap two slots and check which allies change -- proving the mask targeting.

Zero battles: TacticalEvaluator.battlefield() only constructs state.
"""
import json
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))

import logging
logging.disable(logging.CRITICAL)

from src.optimizer.engine import TacticalEvaluator  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json").read_text(encoding="utf-8"))["state"]
ROOT_TMP = str(ROOT)

ev = TacticalEvaluator(ROOT_TMP, None)

STATS = ("max_hp", "attack", "defense", "speed", "critical_rate", "critical_damage", "favorable_damage")


def snapshot(state):
    bf, _ = ev.battlefield(state)
    out = []
    for u in bf.friend_team:
        rec = {"name": u.name, "pos": u.position.value}
        for s in STATS:
            if hasattr(u, s):
                rec[s] = round(float(getattr(u, s)), 4)
        out.append(rec)
    return out


state_nomem = dict(BASE, memory_ids=[])
state_mem = dict(BASE, memory_ids=sorted(BASE["memory_ids"]))

a = snapshot(state_nomem)
b = snapshot(state_mem)

print("=== ally stats WITHOUT memories vs WITH the six fixture cards ===")
for ra, rb in zip(a, b):
    print(f"\n  {ra['name']}  (pos {ra['pos']})")
    for s in STATS:
        if s in ra and s in rb:
            d = rb[s] - ra[s]
            mark = f"   <== +{d:g}" if d else ""
            print(f"     {s:18} {ra[s]:>12g} -> {rb[s]:>12g}{mark}")

print("\n=== does swapping two slots change WHICH ally gets the bonus? ===")
alt = json.loads(json.dumps(state_mem))
p = list(alt["friend_positions"])
p[0], p[3] = p[3], p[0]
alt["friend_positions"] = p
c = snapshot(alt)

print("  original positions:", state_mem["friend_positions"])
print("  swapped  positions:", alt["friend_positions"])
diffs = 0
for rb, rc in zip(b, c):
    names = {s: (rb[s], rc[s]) for s in STATS if s in rb and rc.get(s) != rb[s]}
    if names:
        diffs += 1
        print(f"    {rb['name']}: " + "; ".join(f"{k} {v[0]:g}->{v[1]:g}" for k, v in names.items()))
print(f"  allies whose stats changed from the swap: {diffs}/5")
print()
print("  (if the swap changes stats, position is memory-driven -- exactly the")
print("   mechanism the author's empty-memory preselection throws away)")
