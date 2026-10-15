"""Does the jackpot stacking simply not get enough turns to snowball?

Observation: the bunny's crit stacks grow 1 -> 3/4 over the whole 5-turn battle,
yet variance stayed flat (CV 3.78%). Test the user's own explanation:

  "战术演习是5回合的，回合数越长，上下限差距会越大"

Hypothesis: the positive feedback needs more turns to compound. If we run the
same lineup with MORE turns, the variance should grow and the distribution should
become right-skewed -- which would confirm both the mechanic AND the user's point.

Control: the baseline lineup under the same turn counts, to separate
"bunny feedback" from "more turns = more randomness in general".

Budget: 2 lineups x 3 turn-counts x 15 seeds = 90 battles (each combination is
its own case of 15 battles).
"""
import json
import logging
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.combat_v2.battle_flow_controller import BattleConfig  # noqa: E402
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController  # noqa: E402
from src.optimizer.engine import TacticalEvaluator  # noqa: E402

HERE = Path(__file__).parent
BASE = json.loads((ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json").read_text(encoding="utf-8"))["state"]
ev = TacticalEvaluator(str(ROOT), None)
BUNNY = 112302
SEEDS = list(range(21026, 21026 + 15))
TURNS = (5, 10, 20)


def run(cfg, seed, turns):
    saved = random.getstate()
    try:
        random.seed(seed)
        bf, dl = ev.battlefield(cfg)
        c = TacticalExerciseController(bf, BattleConfig(max_turns=turns, enable_rdps=False),
                                       data_loader=dl)
        res = c.execute_battle()
        return float(res["score"]["total_score"])
    finally:
        random.setstate(saved)


def roll5(xs):
    xs = sorted(xs)
    n = len(xs)
    return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5) for i, x in enumerate(xs, start=1))


def stats(xs):
    mean = statistics.mean(xs)
    sd = statistics.stdev(xs) if len(xs) > 1 else 0
    n = len(xs)
    m2 = sum((x - mean) ** 2 for x in xs) / n
    m3 = sum((x - mean) ** 3 for x in xs) / n
    return dict(mean=mean, sd=sd, cv=sd / mean * 100 if mean else 0,
                lo=min(xs), hi=max(xs), ratio=(max(xs) / min(xs)) if min(xs) else 0,
                skew=(m3 / (m2 ** 1.5)) if m2 else 0, roll5=roll5(xs))


bunny = json.loads(json.dumps(BASE))
bunny["friend_positions"] = [BUNNY, 101301, 102301, 103301, 104301, None]
bunny["panel"]["skill_levels"] = dict(
    bunny["panel"].get("skill_levels", {}),
    **{str(BUNNY): {str(s): 15 for s in (110057, 120126, 120127, 120128, 130132)}})
bunny["memory_ids"] = sorted(BASE["memory_ids"])
base = dict(BASE, memory_ids=sorted(BASE["memory_ids"]))

print("=" * 80)
print("DOES THE JACKPOT FEEDBACK NEED MORE TURNS TO COMPOUND?")
print("=" * 80)
print(f"n={len(SEEDS)} seeds per cell\n")
print(f"{'lineup':22} {'turns':>6} {'mean':>13} {'CV':>7} {'max/min':>8} {'skew':>7} {'p90/p10':>8}")

rows = []
for label, cfg in (("baseline", base), ("bunny-carry", bunny)):
    for t in TURNS:
        xs = [run(cfg, s, t) for s in SEEDS]
        st = stats(xs)
        p10 = sorted(xs)[int(0.10 * (len(xs) - 1))]
        p90 = sorted(xs)[int(0.90 * (len(xs) - 1))]
        st.update(label=label, turns=t, p10=p10, p90=p90,
                  p9010=(p90 / p10) if p10 else 0)
        rows.append(st)
        print(f"  {label:20} {t:>6} {st['mean']:>13,.0f} {st['cv']:>6.2f}% "
              f"{st['ratio']:>7.3f}x {st['skew']:>+7.3f} {st['p9010']:>7.3f}x")

print()
print("=" * 80)
print("VARIANCE GROWTH WITH TURNS")
print("=" * 80)
for label in ("baseline", "bunny-carry"):
    sub = [r for r in rows if r["label"] == label]
    print(f"\n  {label}:")
    for r in sub:
        print(f"    turns={r['turns']:>3}  CV={r['cv']:5.2f}%  "
              f"max/min={r['ratio']:.3f}x  skew={r['skew']:+.3f}  "
              f"Roll5/mean={r['roll5']/r['mean']:.4f}")
    if len(sub) >= 2:
        print(f"    CV growth 5->20 turns: {sub[0]['cv']:.2f}% -> {sub[-1]['cv']:.2f}% "
              f"({sub[-1]['cv']/sub[0]['cv']:.2f}x)")

# bunny vs baseline at each turn count
print()
print("  bunny / baseline CV ratio per turn count:")
for t in TURNS:
    b = next(r for r in rows if r["label"] == "baseline" and r["turns"] == t)
    u = next(r for r in rows if r["label"] == "bunny-carry" and r["turns"] == t)
    print(f"    turns={t:>3}: baseline {b['cv']:5.2f}%  bunny {u['cv']:5.2f}%  "
          f"ratio {u['cv']/b['cv']:.2f}x")

(HERE / "turns_variance.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("\nwrote turns_variance.json")
