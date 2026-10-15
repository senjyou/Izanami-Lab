"""ZERO-COST analysis of existing data: what is the CHEAPEST viable screen?

Uses replication_data.json (7 position pairs x 10 seeds, real battles already run).
Answers, without spending battles:
  Q1  With n seeds, how well does the measured ranking match the 10-seed ranking?
      -> the minimum seed count for a trustworthy screen
  Q2  Split-half reliability: does seed-set A agree with seed-set B?
  Q3  How often does a 1-seed / 2-seed screen pick the WRONG winner of a pair?
"""
import json
import math
import statistics
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).parent
D = json.loads((HERE / "replication_data.json").read_text(encoding="utf-8"))
pairs = [r for r in D["results"] if r["kind"] == "position" and r["status"] == "ok"]

print("=" * 78)
print("SEED-EFFICIENCY: how many seeds before a screen is trustworthy?")
print("=" * 78)
print("ground truth = all 10 seeds. For each n, enumerate every n-seed subset and")
print("ask whether it picks the SAME winner as the 10-seed result.\n")

print(f"{'pair':32} {'true winner':>12} " + " ".join(f"n={n:<5}" for n in (1, 2, 3, 4, 6)))

agg = {n: [] for n in (1, 2, 3, 4, 6)}
for r in pairs:
    a, b = r["a"], r["b"]
    true_winner = "A" if statistics.mean(a) >= statistics.mean(b) else "B"
    cells = []
    for n in (1, 2, 3, 4, 6):
        agree = tot = 0
        for idx in combinations(range(len(a)), n):
            ma = statistics.mean(a[i] for i in idx)
            mb = statistics.mean(b[i] for i in idx)
            pick = "A" if ma >= mb else "B"
            agree += (pick == true_winner)
            tot += 1
        rate = agree / tot
        agg[n].append(rate)
        cells.append(f"{rate*100:4.0f}%")
    print(f"  {r['label']:30} {true_winner:>12} " + " ".join(f"{c:<7}" for c in cells))

print()
print("  mean agreement with the 10-seed verdict:")
for n in (1, 2, 3, 4, 6):
    m = statistics.mean(agg[n])
    print(f"    n={n}: {m*100:5.1f}%")

print()
print("=" * 78)
print("HOW LARGE ARE THE REAL POSITION DIFFERENCES?")
print("=" * 78)
print("(if true gaps are large, few seeds suffice; if small, many are needed)\n")
print(f"{'pair':32} {'true gap':>10} {'pairedSD':>10} {'seeds for 95%':>15}")
for r in pairs:
    gap = abs(r["mean_diff_pct"])
    cv = r["paired_sd_pct"]
    need = (1.96 * cv / gap) ** 2 if gap > 0 else float("inf")
    print(f"  {r['label']:30} {gap:9.2f}% {cv:9.2f}% {need:14.1f}")

gaps = [abs(r["mean_diff_pct"]) for r in pairs]
print(f"\n  median |gap| across pairs : {statistics.median(gaps):.2f}%")
print(f"  pairs with |gap| < 5%     : {sum(1 for g in gaps if g < 5)}/{len(gaps)}")
print()
print("  => most real position differences are LARGE (>10%), which is why even a")
print("     1-2 seed screen often picks the right winner. The hard cases are the")
print("     NEAR-TIES, and those are exactly where fixed thresholds misfire.")
