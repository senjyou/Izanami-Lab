"""CLEAN VARIANCE DECOMPOSITION -- fixes the confound in proxy_experiment.py.

The previous run mixed position changes and memory changes across configs, so
feature/score correlations were confounded: position dominates the score, so any
memory-derived feature was effectively noise (or anti-correlated by accident of
pairing). This separates the two axes by design:

  Arm M (memory axis): FIXED positions, VARY memory set  -> memory's contribution
  Arm P (position axis): FIXED memory set, VARY positions -> position's contribution

Then we can say which axis a new algorithm should spend battles on.

Budget: 6 configs x 2 seeds x 2 arms = 24 battles.
"""
import json
import logging
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.combat_v2.battle_flow_controller import BattleConfig  # noqa: E402
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController  # noqa: E402
from src.optimizer.engine import TacticalEvaluator  # noqa: E402

HERE = Path(__file__).parent
BASE = json.loads((ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json").read_text(encoding="utf-8"))["state"]
CARD_POOL = [10001, 10002, 10003, 10004, 10005, 10006, 10007, 10008, 10009, 10010,
             10011, 10012, 10013, 20021, 20092, 30021, 30023]
ev = TacticalEvaluator(str(ROOT), None)
SEEDS = [9201, 9202]


def analytic_buff_vector(state):
    """Zero-battle: apply memory effects, read the resulting memory-buff totals."""
    bf, dl = ev.battlefield(state)
    c = TacticalExerciseController(bf, BattleConfig(max_turns=5, enable_rdps=False), data_loader=dl)
    c._apply_memory_card_effects()
    tot = Counter()
    for u in bf.friend_team:
        for b in getattr(u, "buffs", []):
            if getattr(b, "is_memory_buff", False):
                tot[b.effect_type] += float(b.value)
    return dict(tot)


def real_score(state):
    saved = random.getstate()
    try:
        vals = []
        for sd in SEEDS:
            random.seed(sd)
            bf, dl = ev.battlefield(state)
            c = TacticalExerciseController(bf, BattleConfig(max_turns=5, enable_rdps=False),
                                           data_loader=dl)
            vals.append(float(c.execute_battle()["score"]["total_score"]))
        return statistics.mean(vals)
    finally:
        random.setstate(saved)


POS_PERMS = [
    [100301, 101301, 102301, 103301, 104301, None],
    [103301, 101301, 102301, 100301, 104301, None],
    [104301, 101301, 102301, 103301, 100301, None],
    [100301, 102301, 101301, 103301, 104301, None],
    [101301, 100301, 102301, 103301, 104301, None],
    [100301, 101301, 102301, 104301, 103301, None],
]

rng = random.Random(31337)
MEM_SETS = [sorted(BASE["memory_ids"])]
while len(MEM_SETS) < 6:
    cards = sorted(rng.sample(CARD_POOL, 6))
    if cards not in MEM_SETS:
        MEM_SETS.append(cards)

BASE_POS = list(BASE["friend_positions"])
FIXED_MEM = sorted(BASE["memory_ids"])


def report(label, rows):
    scores = [r["score"] for r in rows]
    lo, hi = min(scores), max(scores)
    mean = statistics.mean(scores)
    sd = statistics.stdev(scores) if len(scores) > 1 else 0.0
    print(f"\n  {label}")
    print(f"    n={len(rows)}  mean={mean:,.0f}  sd={sd:,.0f} ({sd/mean*100:.2f}%)")
    print(f"    range {lo:,.0f} .. {hi:,.0f}   spread={((hi-lo)/mean)*100:.2f}%")
    return dict(sd_pct=sd / mean * 100, spread_pct=(hi - lo) / mean * 100, scores=scores)


print("=" * 76)
print("ARM M: positions FIXED, memory set VARIES")
print("=" * 76)
arm_m = []
for i, cards in enumerate(MEM_SETS):
    cfg = dict(BASE, friend_positions=list(BASE_POS), memory_ids=list(cards))
    sc = real_score(cfg)
    bv = analytic_buff_vector(cfg)
    arm_m.append(dict(i=i, score=sc, buffs=bv, cards=cards))
    print(f"  mem {i}: score={sc:>14,.0f}  cards={cards}")

print()
print("=" * 76)
print("ARM P: memory set FIXED, positions VARY")
print("=" * 76)
arm_p = []
for i, pp in enumerate(POS_PERMS):
    cfg = dict(BASE, friend_positions=list(pp), memory_ids=list(FIXED_MEM))
    sc = real_score(cfg)
    arm_p.append(dict(i=i, score=sc, positions=pp))
    print(f"  pos {i}: score={sc:>14,.0f}  positions={pp}")

print()
print("=" * 76)
print("DECOMPOSITION")
print("=" * 76)
m = report("MEMORY axis (positions fixed)", arm_m)
p = report("POSITION axis (memory fixed)", arm_p)

print()
print(f"  memory-axis spread : {m['spread_pct']:6.2f}%   (sd {m['sd_pct']:.2f}%)")
print(f"  position-axis spread: {p['spread_pct']:6.2f}%   (sd {p['sd_pct']:.2f}%)")
if m["sd_pct"]:
    print(f"  ratio (position / memory) by sd: {p['sd_pct']/m['sd_pct']:.1f}x")
print()
print("  memory-buff vector per config (analytic, zero-battle):")
for r in arm_m:
    print(f"    mem {r['i']}: {r['buffs']}")

# does the buff vector track the memory-axis score at all?
def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rr = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                rr[order[k]] = avg
            i = j + 1
        return rr
    rx, ry = ranks(xs), ranks(ys)
    import math
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0

ys = [r["score"] for r in arm_m]
keys = sorted({k for r in arm_m for k in r["buffs"]})
print()
print("  within the memory arm, does each buff type track score?")
for k in keys:
    xs = [r["buffs"].get(k, 0.0) for r in arm_m]
    if len(set(xs)) > 1:
        print(f"    {k:30} spearman={spearman(xs, ys):+.3f}")

(HERE / "decomposition.json").write_text(json.dumps(
    dict(arm_m=[{k: v for k, v in r.items()} for r in arm_m],
         arm_p=arm_p, memory=m, position=p, seeds=SEEDS), indent=1, default=str), encoding="utf-8")
print("\nwrote decomposition.json")
