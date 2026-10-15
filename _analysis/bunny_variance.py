"""Measure variance on a 発情バニー (112302) main-carry lineup.

Why this matters
----------------
The user's optimization target is Roll5 = E[max of 5 daily attempts], NOT the mean.
112302's ジャックポット (130132) is a POSITIVE FEEDBACK loop:
    "自身の攻撃が会心攻撃になるたびに発動。自身の会心率を{crt}%、会心ダメージを
     {crtdmg}%上昇させる（重複可）"
Every crit stacks more crit chance AND crit damage -> unbounded accumulation.
With four supports feeding it, the run can either snowball to a huge score or
fizzle. That makes the distribution right-skewed and heavy-tailed, which:
  * breaks the normal-theory reasoning behind my earlier "1-2 seeds is enough"
  * makes the MEAN a poor target; the upper tail (what Roll5 rewards) is what matters

This measures the distribution shape and compares a bunny-carry lineup against
the balanced baseline, at 40 seeds each (each its own case).

Budget: 2 lineups x 40 seeds = 80 battles.
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

from src.optimizer.engine import TacticalEvaluator  # noqa: E402

HERE = Path(__file__).parent
BASE = json.loads((ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json").read_text(encoding="utf-8"))["state"]
ev = TacticalEvaluator(str(ROOT), None)
SEEDS = list(range(18026, 18026 + 40))

BUNNY = 112302


def roll5(scores):
    """E[max of 5] from the empirical distribution (same formula the simulator uses)."""
    xs = sorted(scores)
    n = len(xs)
    return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5) for i, x in enumerate(xs, start=1))


def describe(label, scores):
    xs = sorted(scores)
    n = len(xs)
    mean = statistics.mean(xs)
    sd = statistics.stdev(xs)
    lo, hi = xs[0], xs[-1]
    m2 = sum((x - mean) ** 2 for x in xs) / n
    m3 = sum((x - mean) ** 3 for x in xs) / n
    skew = m3 / (m2 ** 1.5) if m2 else 0.0
    p10 = xs[int(0.10 * (n - 1))]
    p50 = xs[int(0.50 * (n - 1))]
    p90 = xs[int(0.90 * (n - 1))]
    r5 = roll5(xs)
    print(f"\n  {label}")
    print(f"    mean {mean:>13,.0f}   sd {sd:>12,.0f}  CV {sd/mean*100:5.2f}%")
    print(f"    min  {lo:>13,.0f}   max {hi:>12,.0f}  max/min {hi/lo if lo else 0:.3f}x")
    print(f"    p10  {p10:>13,.0f}   p50 {p50:>12,.0f}  p90 {p90:>13,.0f}")
    print(f"    skew {skew:+6.3f}    range/mean {(hi-lo)/mean*100:5.1f}%")
    print(f"    Roll5 E[max of 5] {r5:>13,.0f}   (vs mean {mean:,.0f} = "
          f"{(r5/mean-1)*100:+.1f}%)")
    print(f"    p90/p10 ratio {p90/p10 if p10 else 0:.3f}x")
    return dict(label=label, mean=mean, sd=sd, lo=lo, hi=hi, skew=skew,
                roll5=r5, p10=p10, p50=p50, p90=p90, scores=xs)


def run(cfg):
    return [ev.evaluate(cfg, s) for s in SEEDS]


# --- lineup A: bunny as main carry, four supports ---
bunny = json.loads(json.dumps(BASE))
bunny["friend_positions"] = [BUNNY, 101301, 102301, 103301, 104301, None]
bunny["panel"]["character_levels"] = {str(c): 355 for c in bunny["friend_positions"] if c}
bunny["panel"]["rarities"] = {str(c): 14 for c in bunny["friend_positions"] if c}
bunny["memory_ids"] = sorted(BASE["memory_ids"])

print("=" * 78)
print("VARIANCE: bunny-carry (発情バニー 112302) vs balanced baseline")
print("=" * 78)
print(f"seeds: {SEEDS[0]}..{SEEDS[-1]}  (n={len(SEEDS)} each)")

rows = []
rows.append(describe("baseline (fixture lineup)", run(dict(BASE, memory_ids=sorted(BASE["memory_ids"])))))
rows.append(describe("bunny main-carry (112302 + 4 supports)", run(bunny)))

print()
print("=" * 78)
print("COMPARISON")
print("=" * 78)
b, u = rows[0], rows[1]
print(f"  CV            : baseline {b['sd']/b['mean']*100:5.2f}%   bunny {u['sd']/u['mean']*100:5.2f}%"
      f"   ratio {(u['sd']/u['mean'])/(b['sd']/b['mean']):.2f}x")
print(f"  max/min       : baseline {b['hi']/b['lo']:.3f}x   bunny {u['hi']/u['lo']:.3f}x")
print(f"  p90/p10       : baseline {b['p90']/b['p10']:.3f}x   bunny {u['p90']/u['p10']:.3f}x")
print(f"  skew          : baseline {b['skew']:+.3f}   bunny {u['skew']:+.3f}")
print(f"  Roll5 uplift  : baseline {(b['roll5']/b['mean']-1)*100:+.1f}%   "
      f"bunny {(u['roll5']/u['mean']-1)*100:+.1f}%")

print()
print("  bunny histogram:")
xs = u["scores"]
lo, hi = xs[0], xs[-1]
nb = 10
w = (hi - lo) / nb if hi > lo else 1
for i in range(nb):
    a = lo + i * w
    bnd = a + w
    c = sum(1 for x in xs if (a <= x < bnd) or (i == nb - 1 and x == hi))
    print(f"    {a:>13,.0f} - {bnd:>13,.0f} | {'#'*c} {c}")

(HERE / "bunny_variance.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print(f"\nwrote bunny_variance.json")
