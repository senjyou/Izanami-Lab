"""Turn the replication data into the decision-relevant calibration curve.

Question: with the optimizer's own rule (4 common seeds, 3% line),
for a pair whose TRUE difference is delta, how often does the gate decide
the same way -- and does that match what the full 10-seed evidence says?

Ground truth proxy = the 10-seed mean difference (our best estimate of delta).
"""
import json
import math
import statistics
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).parent
DATA = json.loads((HERE / "replication_data.json").read_text(encoding="utf-8"))
SEEDS = DATA["seeds"]

print("=" * 78)
print("PAIRING EFFECTIVENESS: does comparing on COMMON seeds cancel variance?")
print("=" * 78)
print(f"{'pair':32} {'rawSD':>7} {'pairedSD':>9} {'r':>7}  {'variance removed':>16}")
for kind in ("position", "memory"):
    print(f"-- {kind} --")
    for r in DATA["results"]:
        if r["kind"] != kind or r["status"] != "ok":
            continue
        # variance removed = 1 - var(diff)/(varA+varB)
        va = r["sda_pct"] ** 2
        vb = r["sdb_pct"] ** 2
        vd = r["paired_sd_pct"] ** 2
        removed = (1 - vd / (va + vb)) * 100 if (va + vb) else float("nan")
        print(f"  {r['label']:30} {r['sda_pct']:6.2f}% {r['paired_sd_pct']:8.2f}% "
              f"{r['corr']:+7.3f}  {removed:15.1f}%")

print()
print("=" * 78)
print("GATE CALIBRATION (optimizer rule: 4 common seeds, 3% line)")
print("=" * 78)
print("ground truth = 10-seed mean difference; gate says 'pass' if mean(B) >= 0.97*mean(A)")
print()
print(f"{'pair':32} {'true delta':>11} {'95% band':>10} {'pass rate':>10} {'verdict':>18}")

rows = []
for r in DATA["results"]:
    if r["kind"] != "position" or r["status"] != "ok":
        continue
    delta = r["mean_diff_pct"]              # (A-B)/A : positive => B worse than A
    cv = r["paired_sd_pct"]
    band = 2 * cv / math.sqrt(len(SEEDS))
    # gate passes when B is NOT more than 3% worse than A
    pr = r["four_seed_pass_rate"]
    if 0.05 < pr < 0.95:
        verdict = "UNSTABLE"
    elif pr >= 0.95:
        verdict = "always pass"
    else:
        verdict = "always reject"
    rows.append((r["label"], delta, band, pr, verdict, cv))
    print(f"  {r['label']:30} {delta:+10.2f}% {band:9.2f}% {pr*100:9.1f}% {verdict:>18}")

print()
print("=" * 78)
print("WHAT THIS MEANS FOR SEED COUNT")
print("=" * 78)
pos_cv = statistics.mean([r["paired_sd_pct"] for r in DATA["results"]
                          if r["kind"] == "position" and r["status"] == "ok"])
mem_cv = statistics.mean([r["paired_sd_pct"] for r in DATA["results"]
                          if r["kind"] == "memory" and r["status"] == "ok"])
raw_cv = statistics.mean([r["sda_pct"] for r in DATA["results"] if r["status"] == "ok"])

print(f"mean raw single-battle SD      : {raw_cv:5.2f}%")
print(f"POSITION paired SD             : {pos_cv:5.2f}%  (pairing removes "
      f"{(1-(pos_cv/raw_cv)**2)*100:.0f}% of the variance)")
print(f"MEMORY   paired SD             : {mem_cv:5.2f}%  (pairing removes "
      f"{(1-(mem_cv/raw_cv)**2)*100:.0f}% of the variance)")
print()
print("95% resolution band by seed count, on the POSITION dimension:")
for n in (2, 4, 8, 16, 32, 50, 128):
    print(f"  n={n:>4}: +/-{2*pos_cv/math.sqrt(n):5.2f}%   "
          f"(3% threshold is {3/(2*pos_cv/math.sqrt(n)):4.2f}x the band)")
print()
print(f"seeds to resolve a true 3% position gap (95%): {(1.96*pos_cv/3)**2:.1f}")
print(f"seeds to resolve a true 1% position gap (95%): {(1.96*pos_cv/1)**2:.1f}")
print(f"seeds to resolve a true 3% memory   gap (95%): {(1.96*mem_cv/3)**2:.1f}")
