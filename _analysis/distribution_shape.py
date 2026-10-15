"""Is a 1-seed screen defensible? Test the user's objection directly.

The user reports seeing 100-sample batches where max/min exceeded 2x on the SAME
lineup. My own 10-seed data showed only 1.17x. For a normal distribution with
CV 5%, 100 samples gives max/min ~1.3x -- so a >2x range cannot be explained by
sample size alone. Either
   (a) some lineups have much higher variance than the one I measured, or
   (b) the score distribution is heavily skewed / bimodal (crit chains, kill
       thresholds, timeout cliffs), making mean+-SD a poor description.

This measures ONE lineup at 60 seeds and inspects the full distribution shape,
which decides whether "1 seed is enough" can hold at all.

Budget: 60 battles (one case).
"""
import json
import logging
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.optimizer.engine import TacticalEvaluator  # noqa: E402

HERE = Path(__file__).parent
BASE = json.loads((ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json").read_text(encoding="utf-8"))["state"]
ev = TacticalEvaluator(str(ROOT), None)

SEEDS = list(range(12026, 12026 + 60))
cfg = dict(BASE, memory_ids=sorted(BASE["memory_ids"]))

scores = []
for s in SEEDS:
    scores.append(ev.evaluate(cfg, s))

scores_sorted = sorted(scores)
n = len(scores)
mean = statistics.mean(scores)
sd = statistics.stdev(scores)
lo, hi = min(scores), max(scores)

print("=" * 78)
print("SINGLE LINEUP, 60 SEEDS -- distribution shape")
print("=" * 78)
print(f"n        : {n}")
print(f"mean     : {mean:,.0f}")
print(f"sd       : {sd:,.0f}  (CV {sd/mean*100:.2f}%)")
print(f"min      : {lo:,.0f}")
print(f"max      : {hi:,.0f}")
print(f"max/min  : {hi/lo:.3f}x")
print(f"range    : {hi-lo:,.0f}  ({(hi-lo)/mean*100:.1f}% of mean)")
print()

# normality / skew diagnostics
q = statistics.quantiles(scores, n=4)
print("quartiles:")
print(f"  Q1 {q[0]:,.0f}   median {q[1]:,.0f}   Q3 {q[2]:,.0f}")
iqr = q[2] - q[0]
print(f"  IQR {iqr:,.0f}")
print()

# skewness & kurtosis (moment based)
m2 = sum((x - mean) ** 2 for x in scores) / n
m3 = sum((x - mean) ** 3 for x in scores) / n
m4 = sum((x - mean) ** 4 for x in scores) / n
skew = m3 / (m2 ** 1.5) if m2 else 0.0
kurt = m4 / (m2 ** 2) - 3 if m2 else 0.0
print(f"skewness : {skew:+.3f}   (0 = symmetric)")
print(f"excess kurtosis: {kurt:+.3f}   (0 = normal; >0 = heavy tails)")
print()

# how far do the extremes sit in SD units?
print("extremes in SD units:")
print(f"  min is {(lo-mean)/sd:+.2f} SD from mean")
print(f"  max is {(hi-mean)/sd:+.2f} SD from mean")
print()

# expected max/min for a NORMAL distribution at this n and CV
try:
    from statistics import NormalDist
    nd = NormalDist()
    p_ext = 1 - (1 / (2 * n))          # ~ expected extreme quantile
    z = nd.inv_cdf(1 - 1 / (2 * n))
    exp_lo = mean - z * sd
    exp_hi = mean + z * sd
    print(f"for a NORMAL dist with this CV at n={n}:")
    print(f"  expected min ~{exp_lo:,.0f}  max ~{exp_hi:,.0f}  ratio ~{exp_hi/exp_lo:.3f}x")
    print()
except Exception:
    pass

# histogram
print("histogram:")
nbins = 12
width = (hi - lo) / nbins if hi > lo else 1
for i in range(nbins):
    a = lo + i * width
    b = a + width
    c = sum(1 for x in scores if (a <= x < b) or (i == nbins - 1 and x == hi))
    bar = "#" * c
    print(f"  {a:>12,.0f} - {b:>12,.0f} | {bar} {c}")

print()
print("=" * 78)
print("WHAT THIS MEANS FOR A 1-SEED SCREEN")
print("=" * 78)
for k in (1, 2, 4, 8, 16, 32, 60):
    sub = scores_sorted[:k]
    print(f"  worst-case (min of first {k:2} seeds) = {min(sub):>13,.0f}"
          f"   vs mean {mean:>13,.0f}   understate by {(mean-min(sub))/mean*100:5.1f}%")

(HERE / "distribution_single_lineup.json").write_text(
    json.dumps(dict(scores=scores, seeds=SEEDS, mean=mean, sd=sd,
                    min=lo, max=hi, skew=skew, kurtosis=kurt), indent=1), encoding="utf-8")
print(f"\nwrote distribution_single_lineup.json")
