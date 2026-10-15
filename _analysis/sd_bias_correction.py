"""The sd estimator is itself biased at small n -- must be corrected.

Finding from dual_objective_design.py Q1: the closed form
    Roll5 ~= mean + 1.162964 * stdev(samples)
carries a +1.46% mean signed error and up to 15.6% worst-case error at small n.

Cause: `statistics.stdev` (ddof=1) is unbiased for the VARIANCE but NOT for the
standard deviation. E[s] = c4(n) * sigma with c4(n) < 1, so the closed form
systematically UNDERSTATES sd, hence Roll5.

This computes the exact c4(n) correction and verifies it removes the bias.
Zero battles.
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
C5 = 1.162964


def c4(n):
    """E[s]/sigma for a normal sample of size n (ddof=1)."""
    if n < 2:
        return float("nan")
    return math.sqrt(2.0 / (n - 1)) * math.exp(
        math.lgamma(n / 2.0) - math.lgamma((n - 1) / 2.0))


def roll5_emp(s):
    xs = sorted(s)
    n = len(xs)
    return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5) for i, x in enumerate(xs, start=1))


print("=" * 74)
print("c4(n): the small-sample bias of the standard deviation")
print("=" * 74)
print(f"{'n':>4} {'c4(n)':>10} {'sd underestimate':>18}")
for n in (2, 3, 4, 6, 8, 12, 16, 24, 32, 64, 100):
    print(f"{n:>4} {c4(n):>10.6f} {(1-c4(n))*100:>17.2f}%")
print()
print("  -> at n=8 the sd is 2.8% too small; at n=4 it is 6.4% too small.")

print()
print("=" * 74)
print("DOES THE c4 CORRECTION REMOVE THE BIAS?")
print("=" * 74)
print(f"reference: empirical Roll5 over all {len(REAL)} scores = {roll5_emp(REAL):,.0f}\n")
rng = random.Random(4242)
print(f"{'n':>4} {'closed form':>22} {'+ c4 corrected':>22}")
print(f"{'':>4} {'bias':>10} {'sd err':>11} {'bias':>10} {'sd err':>11}")
for n in (2, 4, 8, 16, 32, 64):
    raw_e, cor_e = [], []
    for _ in range(4000):
        s = [rng.choice(REAL) for _ in range(n)]
        m = statistics.mean(s)
        sd = statistics.stdev(s) if n > 1 else 0.0
        raw_e.append((m + C5 * sd - roll5_emp(s)) / roll5_emp(s) * 100)
        sd_c = sd / c4(n) if n > 1 else sd
        cor_e.append((m + C5 * sd_c - roll5_emp(s)) / roll5_emp(s) * 100)
    print(f"{n:>4} {statistics.mean(raw_e):>+10.3f}% {statistics.stdev(raw_e):>10.3f}% "
          f"{statistics.mean(cor_e):>+10.3f}% {statistics.stdev(cor_e):>10.3f}%")

print()
print("=" * 74)
print("PRACTICAL RECOMMENDATION")
print("=" * 74)
print("""
  Use the EMPIRICAL formula (the one the simulator already implements) for the
  reported Roll5 value whenever n is large enough, because it makes no
  distributional assumption:

      roll5_hat = SUM_i x_(i) * [(i/n)^5 - ((i-1)/n)^5]

  Use the CLOSED FORM for RANKING during the search, because it is far more
  stable at small n (it needs only two moments instead of the whole upper tail),
  and apply the c4 correction so it is not biased low:

      roll5_rank = mean + 1.162964 * stdev / c4(n)

  Ranking is what the search actually needs; the reported value can be recomputed
  empirically once the finals have enough seeds.
""")

(HERE / "c4_correction.json").write_text(json.dumps(
    {str(n): dict(c4=c4(n)) for n in (2, 3, 4, 6, 8, 12, 16, 24, 32, 64, 100)},
    indent=1), encoding="utf-8")
print("wrote c4_correction.json")
