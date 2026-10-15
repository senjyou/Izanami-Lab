"""DECISIVE: using the user's REAL 100 scores, how wrong is mean-based ranking?

Uses real_lineup_reproduction.json (100 genuine battle scores from the user's own
火沙耶主c config, mean ~82.7M, CV 12.0%).

Two things are measured, both at ZERO additional battle cost:

  A. Resampling with replacement, how accurately can n seeds estimate Roll5?
     (already known to be biased low; this quantifies the RANKING consequence)

  B. The scenario the user actually cares about: comparing a LOW-variance build
     against a HIGH-variance build that has a lower mean. The high-variance build
     is the user's own distribution; the low-variance one is theirs with the
     variance scaled down. Who wins under each objective, and how often does each
     estimator get it right?
"""
import json
import math
import random
import statistics
from pathlib import Path

HERE = Path(__file__).parent
D = json.loads((HERE / "real_lineup_reproduction.json").read_text(encoding="utf-8"))
REAL = D["scores"]
MEAN = statistics.mean(REAL)
SD = statistics.stdev(REAL)
CV = SD / MEAN
C5 = 1.162964


def roll5(samples):
    xs = sorted(samples)
    n = len(xs)
    return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5) for i, x in enumerate(xs, start=1))


print("=" * 78)
print("BASED ON THE USER'S REAL 100 SCORES")
print("=" * 78)
print(f"  n={len(REAL)}  mean={MEAN:,.0f}  sd={SD:,.0f}  CV={CV*100:.2f}%")
print(f"  roll5(bootstrap of all 100) = {roll5(REAL):,.0f}")
print(f"  now, suppose each seed costs one battle...")

print()
print("=" * 78)
print("PART A: which statistic is READABLE at low seed counts?")
print("=" * 78)
rng = random.Random(2026)
print(f"{'seeds':>6} {'mean est':>14} {'mean err':>10} {'Roll5 est':>14} {'Roll5 err':>11}")
for n in (1, 2, 4, 8, 16, 32, 64, 100):
    means, r5s = [], []
    for _ in range(2000):
        samp = [rng.choice(REAL) for _ in range(n)]
        means.append(statistics.mean(samp))
        r5s.append(roll5(samp))
    me, re_ = statistics.mean(means), statistics.mean(r5s)
    print(f"{n:>6} {me:>14,.0f} {(me-MEAN)/MEAN*100:>+9.2f}% {re_:>14,.0f} "
          f"{(re_-roll5(REAL))/roll5(REAL)*100:>+10.2f}%")

print()
print("=" * 78)
print("PART B: low-variance vs high-variance -- who wins, and who does each")
print("        estimator pick?  (the user's real scenario)")
print("=" * 78)
print("""
  LOW  = the same mean, but variance scaled DOWN (e.g. stacked crit-rate memories)
  HIGH = the user's real distribution (volatile crit-stacking carry)
  Both are the same EV; only the SPREAD differs.
""")
print(f"{'sd scale':>9} {'true mean':>13} {'true Roll5':>14} {'truth':>6} "
      f"{'meanpick':>9} {'r5pick':>8} {'mean acc':>9} {'r5 acc':>8}")
for scale, label in ((0.3, "LOW var"), (0.5, "LOW var"), (0.7, "LOW var")):
    # LOW build: same mean, smaller sd.  Draw from a normal with that sd.
    low_sd = SD * scale
    low_samples = [max(MEAN + rng.gauss(0, low_sd), MEAN * 0.02) for _ in range(20000)]
    low_mean_true = statistics.mean(low_samples)
    low_r5_true = roll5(low_samples)
    high_mean_true = MEAN
    high_r5_true = roll5(REAL)
    truth = "LOW" if low_r5_true >= high_r5_true else "HIGH"
    for n in (2, 4, 8, 16, 32, 64):
        acc_m = acc_r = 0
        for _ in range(1500):
            l = [max(MEAN + rng.gauss(0, low_sd), MEAN * 0.02) for _ in range(n)]
            h = [rng.choice(REAL) for _ in range(n)]
            mp = "LOW" if statistics.mean(l) >= statistics.mean(h) else "HIGH"
            rp = "LOW" if roll5(l) >= roll5(h) else "HIGH"
            acc_m += (mp == truth)
            acc_r += (rp == truth)
        if n in (2, 8, 32):
            print(f"{scale:>9.1f} {low_mean_true:>13,.0f} {low_r5_true:>14,.0f} "
                  f"{'':>6} {'':>9} {'':>8}")
        print(f"{'':>9} {'':>13} {'':>14} {truth:>6} {'':>9} {'':>8} "
              f"{acc_m/1500*100:>8.0f}% {acc_r/1500*100:>7.0f}%   (n={n})")

print()
print("=" * 78)
print("PART C: the 'crit memories' trade-off the user described")
print("=" * 78)
print("""  Adding crit-rate memories: raises the MEAN a little, LOWERS the variance a lot.
  Removing them:             lowers the MEAN a little, RAISES the variance a lot.
  Which is better depends entirely on whether you score mean or Roll5.
""")
print(f"{'variant':>34} {'mean':>13} {'sd':>12} {'Roll5':>14} {'Roll5/mean':>11}")
rows = []
for label, m_frac, sd_frac in (("with crit memories (user's build)", 1.000, 1.000),
                               ("fewer crit memories", 0.985, 1.35),
                               ("no crit memories", 0.970, 1.70),
                               ("no crit, max variance", 0.955, 2.00)):
    m = MEAN * m_frac
    s = SD * sd_frac
    samp = [max(m + rng.gauss(0, s), m * 0.02) for _ in range(20000)]
    mm = statistics.mean(samp)
    r5 = roll5(samp)
    rows.append((label, mm, s, r5))
    print(f"{label:>34} {mm:>13,.0f} {s:>12,.0f} {r5:>14,.0f} {r5/mm:>11.4f}")

best_mean = max(rows, key=lambda r: r[1])
best_r5 = max(rows, key=lambda r: r[3])
print()
print(f"  best by MEAN  : {best_mean[0]}")
print(f"  best by Roll5 : {best_r5[0]}")
print(f"  -> agree? {'YES' if best_mean[0]==best_r5[0] else 'NO -- the two objectives pick differently'}")

(HERE / "real_decisive.json").write_text(json.dumps(dict(rows=rows), indent=1), encoding="utf-8")
print("\nwrote real_decisive.json")
