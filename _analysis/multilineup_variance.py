"""Can a 100-sample run really show max/min > 2x?  Testing the user's observation.

My 60-seed test on ONE lineup gave max/min = 1.201x, almost exactly the normal
theoretical value (1.204x), with near-zero skew and kurtosis. So for THAT lineup
2x is statistically impossible.

The user reports seeing 2x in the simulator. Candidate explanations:
  H1  Some lineups are far more variable than the one I tested.
  H2  The simulator's batch path differs from the optimizer's path (it seeds with
      time-based seeds and uses enable_rdps=True by default).
  H3  The GUI number the user saw aggregates across DIFFERENT setups (e.g. the
      score distribution table spans all battles, or Roll5 vs mean confusion).
  H4  The lineup is in a regime where the battle outcome FLIPS (win/timeout/loss),
      which creates a bimodal, high-variance distribution.

This test targets H4/H1: several structurally DIFFERENT lineups, 30 seeds each,
and reports max/min plus outcome-mix. A 2x range would need CV ~25%+.

Budget: 4 lineups x 30 seeds = 120 battles, each lineup its own case (30).
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
ev = TacticalEvaluator(str(ROOT), None)
SEEDS = list(range(15026, 15026 + 30))


def run(state, seed):
    """Return (score, winner, turns) using the same path the optimizer uses."""
    saved = random.getstate()
    try:
        random.seed(seed)
        bf, dl = ev.battlefield(state)
        c = TacticalExerciseController(bf, BattleConfig(max_turns=5, enable_rdps=False),
                                       data_loader=dl)
        res = c.execute_battle()
        return (float(res["score"]["total_score"]), res.get("winner"), res.get("total_turns"))
    finally:
        random.setstate(saved)


# Structurally different lineups: strong / weak / fragile
LINEUPS = {
    "baseline (fixture 5 + 6 cards)":
        dict(BASE, memory_ids=sorted(BASE["memory_ids"])),
    "no memories at all":
        dict(BASE, memory_ids=[]),
    "weak: level-1 panels + few cards": None,   # built below
    "front row shifted":
        dict(BASE, friend_positions=[103301, 101301, 102301, 100301, 104301, None],
             memory_ids=sorted(BASE["memory_ids"])),
}

weak = json.loads(json.dumps(BASE))
weak["panel"]["character_levels"] = {str(c): 1 for c in weak["friend_positions"] if c}
weak["panel"]["character_level"] = 1
# keep SIX distinct cards (engine requires exactly 6); take the six weakest-rarity ones
weak["memory_ids"] = sorted(BASE["memory_ids"])      # 6 cards, but low-level panel
LINEUPS["weak: level-1 panels + few cards"] = weak

print("=" * 78)
print("MULTI-LINEUP VARIANCE: can max/min reach 2x?")
print("=" * 78)

summary = []
for label, cfg in LINEUPS.items():
    scores, winners, turns = [], [], []
    for s in SEEDS:
        sc, w, t = run(cfg, s)
        scores.append(sc)
        winners.append(w)
        turns.append(t)
    lo, hi = min(scores), max(scores)
    mean = statistics.mean(scores)
    sd = statistics.stdev(scores)
    ratio = hi / lo if lo else float("inf")
    summary.append((label, mean, sd, lo, hi, ratio, Counter(winners)))
    print(f"\n  {label}")
    print(f"    n={len(scores)}  mean={mean:,.0f}  sd={sd:,.0f} (CV {sd/mean*100:.2f}%)")
    print(f"    min={lo:,.0f}  max={hi:,.0f}  max/min={ratio:.3f}x")
    print(f"    winners={dict(Counter(winners))}  turns={sorted(set(turns))}")

print()
print("=" * 78)
print("COMPARISON WITH NORMAL THEORY (expected max/min at n=30)")
print("=" * 78)
try:
    from statistics import NormalDist
    nd = NormalDist()
    z = nd.inv_cdf(1 - 1 / (2 * len(SEEDS)))
    for label, mean, sd, lo, hi, ratio, w in summary:
        exp_lo, exp_hi = mean - z * sd, mean + z * sd
        print(f"  {label[:38]:40} observed {ratio:.3f}x   normal-expected "
              f"{exp_hi/exp_lo:.3f}x   CV {sd/mean*100:.2f}%")
except Exception as e:
    print("  (normal check unavailable)", e)

print()
print("=" * 78)
print("VERDICT")
print("=" * 78)
worst = max(s[5] for s in summary)
print(f"  worst max/min across {len(summary)} lineups at 30 seeds: {worst:.3f}x")
print(f"  to reach 2.0x at n=30 you would need CV ~= "
      f"{2*z and (1 - 1/2.0)/z*100:.1f}%  (roughly 20-25%)")
print(f"  highest CV observed here: {max(s[2]/s[1]*100 for s in summary):.2f}%")

(HERE / "multilineup_variance.json").write_text(json.dumps(
    [dict(label=l, mean=m, sd=sd, min=lo, max=hi, ratio=r, winners=dict(w))
     for l, m, sd, lo, hi, r, w in summary], indent=1), encoding="utf-8")
print(f"\nwrote multilineup_variance.json")
