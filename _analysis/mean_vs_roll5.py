"""ZERO-BATTLE: how badly does ranking by MEAN diverge from ranking by Roll5?

This does not depend on reproducing the user's exact 2x lineup. It asks a purely
structural question: if the player's payoff is E[max of 5] (Roll5) and the
optimizer selects by MEAN, when do the two disagree about which build is better?

Method: simulate pairs of candidate builds as distributions with controllable
CV and skew, compute mean and Roll5 for each, and measure how often the ranking
flips. Uses only the simulator's own Roll5 formula (tactical_exercise.py:1062).

No battles. This isolates the ALGORITHMIC consequence, which stands whatever the
exact variance of any particular lineup turns out to be.
"""
import math
import random
import statistics
from pathlib import Path

HERE = Path(__file__).parent


def roll5(samples):
    """E[max of 5] from an empirical sample, exactly as the simulator computes it."""
    xs = sorted(samples)
    n = len(xs)
    return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5) for i, x in enumerate(xs, start=1))


def make_samples(rng, mean, cv, skew=0.0, n=4000, cap=None):
    """Draw a distribution with target mean/CV and optional right-skew."""
    sd = mean * cv
    out = []
    for _ in range(n):
        # base normal
        z = rng.gauss(0, 1)
        # optional right skew via a chi-like tail injection
        if skew > 0 and rng.random() < 0.12:
            z += skew * abs(rng.gauss(0, 1)) * 1.8
        v = mean + z * sd
        v = max(v, mean * 0.05)
        if cap:
            v = min(v, cap)
        out.append(v)
    return out


print("=" * 78)
print("MEAN-RANKING vs ROLL5-RANKING: when do they disagree?")
print("=" * 78)
print("Two builds, A and B. A has slightly higher MEAN; B has higher variance.")
print("Which build does each objective prefer?\n")

rng = random.Random(20261013)
BASE = 10_000_000

print(f"{'CV_A':>6} {'CV_B':>6} {'mean A':>13} {'mean B':>13} {'roll5 A':>13} {'roll5 B':>13} "
      f"{'mean picks':>11} {'roll5 picks':>12} {'agree?':>7}")

disagreements = 0
total = 0
for cv_a, cv_b in [(0.03, 0.03), (0.03, 0.08), (0.03, 0.15), (0.03, 0.25),
                   (0.03, 0.40), (0.05, 0.50)]:
    for mean_b_frac in (0.99, 0.995, 1.0, 1.005, 1.01):
        # A: mean BASE, moderate CV.  B: slightly different mean, higher CV.
        a = make_samples(rng, BASE, cv_a)
        b = make_samples(rng, BASE * mean_b_frac, cv_b)
        ma, mb = statistics.mean(a), statistics.mean(b)
        ra, rb = roll5(a), roll5(b)
        mean_pick = "A" if ma >= mb else "B"
        roll_pick = "A" if ra >= rb else "B"
        agree = mean_pick == roll_pick
        total += 1
        if not agree:
            disagreements += 1
        if cv_b >= 0.15 or not agree:
            print(f"{cv_a*100:5.1f}% {cv_b*100:5.1f}% {ma:>13,.0f} {mb:>13,.0f} "
                  f"{ra:>13,.0f} {rb:>13,.0f} {mean_pick:>11} {roll_pick:>12} "
                  f"{'yes' if agree else 'NO':>7}")

print()
print(f"  disagreements: {disagreements}/{total} = {disagreements/total*100:.0f}%")
print()
print("=" * 78)
print("HOW MUCH DOES ROLL5 REWARD VARIANCE?")
print("=" * 78)
print("Same mean, different CV -- Roll5 uplift over the mean:\n")
print(f"{'CV':>7} {'mean':>13} {'roll5':>13} {'roll5/mean':>11} {'p90/p50':>9}")
for cv in (0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50):
    s = make_samples(rng, BASE, cv, n=6000)
    m = statistics.mean(s)
    r5 = roll5(s)
    ss = sorted(s)
    p50 = ss[len(ss) // 2]
    p90 = ss[int(0.9 * (len(ss) - 1))]
    print(f"{cv*100:6.0f}% {m:>13,.0f} {r5:>13,.0f} {r5/m:>11.4f} {p90/p50:>8.3f}x")

print()
print("=" * 78)
print("CONSEQUENCE FOR THE AUTHOR'S ALGORITHM")
print("=" * 78)
print("""
The author's optimizer selects by COMMON-SEED MEAN and spends its whole budget
reducing uncertainty (more seeds -> tighter mean estimate). But if the payoff is
Roll5 = E[max of 5], then:

  1. A build with the same mean but higher CV can have a HIGHER Roll5, and the
     mean-based optimizer will never see it -- it may even actively screen it out
     during variance-penalising stages.
  2. The seeds spent shrinking the confidence interval of the MEAN are spent on
     the wrong statistic: Roll5 is driven by the UPPER TAIL, which needs the
     distribution shape, not a tighter mean.
  3. The simulator ALREADY computes roll5_mean from the empirical sample
     (tactical_exercise.py:1062), so no new statistics engine is needed.
""")
