"""Measure PAIRED difference noise between two configurations on common seeds.

The optimizer always compares candidates on the SAME seed set ("共同种子"), so the
relevant noise is the SD of the per-seed DIFFERENCE, not the raw score SD.
Shared variance (crit rolls, targeting luck that affects both equally) cancels.

This decides whether the 2->4->8->...-seed ladder and its 3%/5% thresholds are
well calibrated.  Budget: 2 configs x 25 seeds = 50 real battles (case limit 100).
"""
import json
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))

from src.optimizer.engine import TacticalEvaluator  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json"
SEEDS = list(range(3026, 3026 + 25))

base = json.loads(FIXTURE.read_text(encoding="utf-8"))["state"]

# Config B: swap one shared memory card -> same team, same positions, different memories.
alt = json.loads(json.dumps(base))
mem_pool = sorted(alt["memory_ids"])
alt["memory_ids"] = sorted(mem_pool[:-1] + [10010]) if 10010 not in mem_pool else mem_pool

print("config A memories:", base["memory_ids"])
print("config B memories:", alt["memory_ids"])
print("positions identical:", base["friend_positions"] == alt["friend_positions"])

tmp = tempfile.mkdtemp(prefix="izanami_paired_")
ev = TacticalEvaluator(str(ROOT), tmp)

a_scores, b_scores = [], []
for seed in SEEDS:
    sa = ev.evaluate(base, seed)
    sb = ev.evaluate(alt, seed)
    a_scores.append(sa)
    b_scores.append(sb)
    print(f"  seed {seed}: A={sa:>14,.0f}  B={sb:>14,.0f}  diff={sa-sb:>12,.0f}", flush=True)

diffs = [a - b for a, b in zip(a_scores, b_scores)]
ma, mb = statistics.mean(a_scores), statistics.mean(b_scores)
sd_a, sd_b = statistics.stdev(a_scores), statistics.stdev(b_scores)
sd_d = statistics.stdev(diffs)
mean_d = statistics.mean(diffs)

print("\n=== RAW (unpaired) noise ===")
print(f"A mean={ma:,.0f}  SD={sd_a:,.0f}  CV={sd_a/ma*100:.2f}%")
print(f"B mean={mb:,.0f}  SD={sd_b:,.0f}  CV={sd_b/mb*100:.2f}%")

print("\n=== PAIRED difference (the decision-relevant noise) ===")
print(f"mean diff = {mean_d:,.0f}  ({mean_d/ma*100:+.2f}% of A)")
print(f"SD of diff = {sd_d:,.0f}  ({sd_d/ma*100:.2f}% of A)")

# correlation between A and B (shared variance)
cov = sum((a - ma) * (b - mb) for a, b in zip(a_scores, b_scores)) / (len(a_scores) - 1)
r = cov / (sd_a * sd_b)
print(f"corr(A,B)  = {r:.3f}   <- 1.0 means shared luck is fully cancelled by pairing")
print(f"variance reduction from pairing: {(1 - (sd_d**2)/(sd_a**2+sd_b**2))*100:.1f}%")

print("\n=== how many seeds to resolve a given TRUE gap (paired, 95% power) ===")
for pct in (5, 3, 2, 1, 0.5):
    delta = ma * pct / 100
    n = (1.96 * sd_d / delta) ** 2
    print(f"  {pct:>4}% gap -> n ~ {n:6.1f} seed pairs")

print("\n=== what the algorithm's ladder actually achieves (paired SE) ===")
for n in (2, 4, 8, 16, 32, 50, 64, 128, 150, 256):
    se = sd_d / (n ** 0.5)
    print(f"  n={n:>4}: SE of diff = {se:,.0f} ({se/ma*100:.3f}% of A)"
          f"  |  smallest resolvable gap (2SE) = {2*se/ma*100:.2f}%")
