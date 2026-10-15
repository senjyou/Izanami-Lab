"""Both objectives supported: what does the search need to do differently?

Requirement: the user picks MEAN or ROLL5 per run.

Key question this answers: can ONE search serve both objectives, or do the two
objectives need different search behaviour? If one seed-sample set can rank under
both metrics, the algorithm only needs one extra recorded statistic (stdev) and a
switch at ranking time -- much less work than two search modes.

Uses the user's REAL 100 scores (real_lineup_reproduction.json).
Zero additional battles.
"""
import json
import math
import random
import statistics
from pathlib import Path

HERE = Path(__file__).parent
REAL = json.loads((HERE / "real_lineup_reproduction.json").read_text(encoding="utf-8"))["scores"]
MEAN = statistics.mean(REAL)
SD = statistics.stdev(REAL)
CV = SD / MEAN
C5 = 1.162964


def roll5(s):
    xs = sorted(s)
    n = len(xs)
    return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5) for i, x in enumerate(xs, start=1))


print("=" * 78)
print("Q1: is Roll5 = mean + c*sd a safe SUBSTITUTE for the empirical Roll5?")
print("=" * 78)
print("If yes, the algorithm needs only (mean, sd) and a flag -- no second search.\n")
bias, err = [], []
for n in (2, 4, 8, 16, 32, 64, 100):
    rng = random.Random(1000 + n)
    for _ in range(4000):
        s = [rng.choice(REAL) for _ in range(n)]
        if n < 2 or statistics.stdev(s) == 0:
            continue
        emp = roll5(s)
        approx = statistics.mean(s) + C5 * statistics.stdev(s)
        bias.append((approx - emp) / emp * 100)
print(f"  over n in 2..100, {len(bias)} resamples:")
print(f"    mean signed error  : {statistics.mean(bias):+.3f}%")
print(f"    sd of error        : {statistics.stdev(bias):.3f}%")
print(f"    worst |error|      : {max(abs(b) for b in bias):.3f}%")
print()
print("  -> the closed form tracks the empirical Roll5 closely, so a SINGLE")
print("     sample set serves both objectives; only the ranking key changes.")

print()
print("=" * 78)
print("Q2: do MEAN and ROLL5 ever agree on the winner?  (how often mode matters)")
print("=" * 78)
print("Pairs of builds drawn from a plausible neighbourhood: mean varies +/-6%,")
print("sd varies 0.5x..2.5x (the crit-memory trade-off).\n")
rng = random.Random(20261014)
agree = disagree = 0
examples = []
for _ in range(4000):
    mA = MEAN * rng.uniform(0.94, 1.06); sA = SD * rng.uniform(0.5, 2.5)
    mB = MEAN * rng.uniform(0.94, 1.06); sB = SD * rng.uniform(0.5, 2.5)
    # exact metrics for normals: mean, and mean + C5*sd for Roll5
    mean_pick = "A" if mA >= mB else "B"
    r5_pick = "A" if (mA + C5 * sA) >= (mB + C5 * sB) else "B"
    if mean_pick == r5_pick:
        agree += 1
    else:
        disagree += 1
        if len(examples) < 6:
            examples.append((mA, sA, mB, sB, mean_pick, r5_pick))
print(f"  agree    : {agree}/{agree+disagree} = {agree/(agree+disagree)*100:.1f}%")
print(f"  DISAGREE : {disagree}/{agree+disagree} = {disagree/(agree+disagree)*100:.1f}%")
print()
print("  examples where the two objectives pick differently:")
print(f"    {'A(mean)':>12} {'A(sd)':>11} {'B(mean)':>12} {'B(sd)':>11} "
      f"{'mean':>5} {'roll5':>6}")
for mA, sA, mB, sB, mp, rp in examples:
    print(f"    {mA:>12,.0f} {sA:>11,.0f} {mB:>12,.0f} {sB:>11,.0f} {mp:>5} {rp:>6}")

print()
print("=" * 78)
print("Q3: SEED REQUIREMENT for each objective, on the real distribution")
print("=" * 78)
print("How many seeds before the RANKING (not the value) stabilises?\n")
rng = random.Random(777)
# reference: a fixed target build the searcher must not lose
target_mean, target_sd = MEAN * 0.97, SD * 1.7      # high-variance, lower mean
print(f"  reference target: mean={target_mean:,.0f}  sd={target_sd:,.0f}  "
      f"(mean is {0.97:.0%} of the user's, sd {1.7:.1f}x)")
print(f"  user's own build: mean={MEAN:,.0f}  sd={SD:,.0f}")

for obj in ("mean", "roll5"):
    print(f"\n  objective = {obj.upper()}")
    print(f"    {'seeds':>6} {'est. of user build':>20} {'est. of target':>18} "
          f"{'picks target':>13}")
    for n in (2, 4, 8, 16, 32, 64):
        hits = 0
        trials = 800
        for _ in range(trials):
            u = [rng.choice(REAL) for _ in range(n)]
            t = [max(target_mean + rng.gauss(0, target_sd), 0) for _ in range(n)]
            if obj == "mean":
                u_m, t_m = statistics.mean(u), statistics.mean(t)
            else:
                u_m = statistics.mean(u) + C5 * (statistics.stdev(u) if n > 1 else 0)
                t_m = statistics.mean(t) + C5 * (statistics.stdev(t) if n > 1 else 0)
            hits += (t_m >= u_m)
        print(f"    {n:>6} {'':>20} {'':>18} {hits/trials*100:>12.0f}%")

print()
print("=" * 78)
print("DESIGN CONSEQUENCE")
print("=" * 78)
print("""
  1. ONE search serves both modes. Record (mean, sd) per candidate; the mode only
     changes the RANKING KEY:
         MEAN  mode -> key = mean
         ROLL5 mode -> key = mean + 1.162964 * sd
     No second search pass, no separate code path in the stage pipeline.

  2. The variance-penalising screen (quick_review.py:38 `mean > max(gap*ref, 3*SE)`)
     is SAFE under MEAN mode and HARMFUL under ROLL5 mode. It must become
     mode-dependent -- or simply be relaxed, since it also costs seeds.

  3. Seed budget must satisfy the STRICTER of the two modes. Roll5 is the harder
     statistic (extreme-value, biased low at small n), so it sets the floor:
     ~8 seeds minimum, 16-32 for decisions.

  4. The two modes can legitimately return DIFFERENT champions from the same
     search -- that is correct behaviour, not a bug. The UI must show which mode
     produced the result, and ideally both rankings side by side.
""")
