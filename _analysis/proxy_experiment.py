"""Can a ZERO-BATTLE analytic feature vector rank configurations by real score?

Two questions, one experiment:

  Q1 (feasibility) Can we extract the memory-effect feature vector WITHOUT running
     a battle?  Method: build battlefield -> build controller -> call
     _apply_memory_card_effects() directly -> read buff pools. No execute_battle().

  Q2 (predictive power) Does that vector -- plus cheap structural position
     features -- correlate with the REAL score?  This decides whether an analytic
     pre-filter can replace battles.

The earlier routing test showed a position swap moved the score ~12.5% even when
NO memory buff routing changed, so we test memory-only and memory+structure
feature sets separately to see which carries signal.

Budget: 20 configs x 2 seeds = 40 real battles.
"""
import json
import logging
import math
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


# ---------------------------------------------------------------- analytic side
def analytic_features(state):
    """ZERO-BATTLE feature extraction. Returns dict or None. Never calls execute_battle."""
    bf, dl = ev.battlefield(state)
    controller = TacticalExerciseController(
        bf, BattleConfig(max_turns=5, enable_rdps=False), data_loader=dl)
    controller._apply_memory_card_effects()          # static application only

    per_ally, totals = {}, Counter()
    for u in bf.friend_team:
        agg = Counter()
        for b in getattr(u, "buffs", []):
            if getattr(b, "is_memory_buff", False):
                agg[b.effect_type] += float(b.value)
        per_ally[u.name] = (u.position.value, agg)
        for k, v in agg.items():
            totals[k] += v

    memory = dict(totals)
    # structural (still zero-battle): row occupancy + who is where
    pos_vals = [p for p, _ in per_ally.values()]
    front = sum(1 for p in pos_vals if "front" in p)
    memory["_front_row_count"] = front
    memory["_allies"] = len(per_ally)
    return memory, per_ally


# ---------------------------------------------------------------- real battle
def real_score(state, seeds):
    saved = random.getstate()
    try:
        out = []
        for sd in seeds:
            random.seed(sd)
            bf, dl = ev.battlefield(state)
            c = TacticalExerciseController(bf, BattleConfig(max_turns=5, enable_rdps=False),
                                           data_loader=dl)
            out.append(float(c.execute_battle()["score"]["total_score"]))
        return statistics.mean(out)
    finally:
        random.setstate(saved)


def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


# ---------------------------------------------------------------- sample set
rng = random.Random(777)
pos_perms = [
    [100301, 101301, 102301, 103301, 104301, None],
    [103301, 101301, 102301, 100301, 104301, None],
    [104301, 101301, 102301, 103301, 100301, None],
    [100301, 102301, 101301, 103301, 104301, None],
    [101301, 100301, 102301, 103301, 104301, None],
    [100301, 101301, 102301, 104301, 103301, None],
]
mem_sets = [sorted(BASE["memory_ids"])]
while len(mem_sets) < 10:
    cards = sorted(rng.sample(CARD_POOL, 6))
    if cards not in mem_sets:
        mem_sets.append(cards)

configs, seen = [], set()
for i, p in enumerate(pos_perms):
    for m in mem_sets[i:i + 2]:
        key = (tuple(p), tuple(m))
        if key not in seen:
            seen.add(key)
            configs.append(dict(BASE, friend_positions=list(p), memory_ids=list(m)))
for m in mem_sets[:8]:
    key = (tuple(BASE["friend_positions"]), tuple(m))
    if key not in seen:
        seen.add(key)
        configs.append(dict(BASE, memory_ids=list(m)))
configs = configs[:20]

SEEDS = [9101, 9102]
print(f"configs={len(configs)}  seeds={len(SEEDS)}  real battles={len(configs)*len(SEEDS)}")
print()

rows = []
for i, cfg in enumerate(configs):
    feats, per_ally = analytic_features(cfg)          # zero battles
    score = real_score(cfg, SEEDS)                    # 2 battles
    rows.append(dict(idx=i, score=score, feats=feats,
                     positions=cfg["friend_positions"], memories=cfg["memory_ids"]))
    print(f"  cfg {i:2}  score={score:>14,.0f}  mem_buff_kinds={len([k for k in feats if not k.startswith('_')])}")

print()
print("=== correlation of analytic features with REAL score ===")
ys = [r["score"] for r in rows]
keys = sorted({k for r in rows for k in r["feats"]})
scored = []
for k in keys:
    xs = [r["feats"].get(k, 0.0) for r in rows]
    if len(set(xs)) < 2:
        continue
    scored.append((k, spearman(xs, ys)))
scored.sort(key=lambda t: -abs(t[1]))
for k, s in scored:
    print(f"  {k:34} spearman={s:+.3f}")

# combined offensive proxy: attack-ish buffs + speed + crit
def combined(f):
    return (f.get("StatusAttack", 0) * 1.0 + f.get("StatusSpeed", 0) * 500
            + f.get("StatusCriticalChance", 0) * 3000
            + f.get("DealtDamage", 0) * 1000 + f.get("StatusMaxHp", 0) * 2
            + f.get("StatusDefense", 0) * 2)

xs = [combined(r["feats"]) for r in rows]
print(f"\n  {'COMBINED weighted proxy':34} spearman={spearman(xs, ys):+.3f}")

if scored:
    bk, bs = scored[0]
    xs = [r["feats"].get(bk, 0.0) for r in rows]
    byp = [i for i, _ in sorted(enumerate(xs), key=lambda t: -t[1])]
    byt = [i for i, _ in sorted(enumerate(ys), key=lambda t: -t[1])]
    for k in (3, 5):
        print(f"  top-{k} overlap (best single feature vs truth): "
              f"{len(set(byp[:k]) & set(byt[:k]))}/{k}")

(HERE / "proxy_experiment.json").write_text(
    json.dumps(dict(rows=rows, scored=scored, seeds=SEEDS), indent=1, default=str),
    encoding="utf-8")
print(f"\nwrote proxy_experiment.json")
