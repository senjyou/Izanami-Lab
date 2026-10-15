"""Clean test: estimator bias against POPULATION truth (fixes the confound).

The previous test compared each small-sample estimate against the EMPIRICAL Roll5
of that SAME sample. That is confounded, because the empirical Roll5 of a small
sample is itself biased low (the max of n points underestimates the true max).
So "closed form looks too high" was an artefact of a biased reference.

Correct reference: the POPULATION Roll5 of the user's distribution, estimated
from a very large sample. Then measure each small-sample estimator against it.

Also: for the SEARCH, what matters is RANKING, not absolute value. So we also
measure rank accuracy of each estimator.  Zero battles.
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
C5 = 1.162964


def roll5_emp(s):
    xs = sorted(s)
    n = len(xs)
    return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5) for i, x in enumerate(xs, start=1))


def c4(n):
    if n < 2:
        return float("nan")
    return math.sqrt(2.0 / (n - 1)) * math.exp(
        math.lgamma(n / 2.0) - math.lgamma((n - 1) / 2.0))


# ---- population truth: fit the user's distribution and take a huge sample ----
rng = random.Random(31337)
POP = [max(MEAN + rng.gauss(0, SD), MEAN * 0.02) for _ in range(400000)]
TRUE_R5 = roll5_emp(POP)
print("=" * 74)
print("POPULATION TRUTH (fitted to the user's real 100 scores)")
print("=" * 74)
print(f"  mean={MEAN:,.0f}  sd={SD:,.0f}  CV={SD/MEAN*100:.2f}%")
print(f"  TRUE Roll5 (400k sample) = {TRUE_R5:,.0f}")
print(f"  closed form mean+c*sd    = {MEAN + C5*SD:,.0f}  "
      f"({(MEAN+C5*SD-TRUE_R5)/TRUE_R5*100:+.3f}%)")

print()
print("=" * 74)
print("ESTIMATOR BIAS vs POPULATION TRUTH (clean, unbiased reference)")
print("=" * 74)
print(f"{'n':>4} | {'empirical':>12} {'bias':>9} | {'closed':>12} {'bias':>9} | "
      f"{'closed+c4':>12} {'bias':>9}")
for n in (2, 4, 8, 16, 32, 64, 128):
    e_emp, e_raw, e_c4 = [], [], []
    for _ in range(6000):
        s = [rng.choice(POP) for _ in range(n)]
        m = statistics.mean(s)
        sd = statistics.stdev(s) if n > 1 else 0.0
        e_emp.append(roll5_emp(s))
        e_raw.append(m + C5 * sd)
        e_c4.append(m + C5 * sd / c4(n) if n > 1 else m)
    def bias(v):
        return (statistics.mean(v) - TRUE_R5) / TRUE_R5 * 100
    print(f"{n:>4} | {statistics.mean(e_emp):>12,.0f} {bias(e_emp):>+8.2f}% | "
          f"{statistics.mean(e_raw):>12,.0f} {bias(e_raw):>+8.2f}% | "
          f"{statistics.mean(e_c4):>12,.0f} {bias(e_c4):>+8.2f}%")

print()
print("=" * 74)
print("RANKING ACCURACY (what the search actually needs)")
print("=" * 74)
print("Two builds: A = user's distribution; B = mean x0.97, sd x1.7 (high variance)")
print("TRUE Roll5: A < B, so the correct pick is B.\n")
b_mean, b_sd = MEAN * 0.97, SD * 1.7
pb = [max(b_mean + rng.gauss(0, b_sd), 0) for _ in range(200000)]
A_true, B_true = TRUE_R5, roll5_emp(pb)
truth = "B" if B_true > A_true else "A"
print(f"  TRUE: A={A_true:,.0f}  B={B_true:,.0f}  -> correct = {truth}\n")
print(f"{'n':>4} {'mean-key':>10} {'empirical Roll5':>17} {'closed form':>13} {'closed+c4':>11}")
for n in (2, 4, 8, 16, 32, 64):
    ok_mean = ok_emp = ok_raw = ok_c4 = 0
    T = 800
    for _ in range(T):
        a = [rng.choice(POP) for _ in range(n)]
        b = [rng.choice(pb) for _ in range(n)]
        sa = statistics.stdev(a) if n > 1 else 0.0
        sb = statistics.stdev(b) if n > 1 else 0.0
        ma, mb = statistics.mean(a), statistics.mean(b)
        ok_mean += (("A" if ma >= mb else "B") == truth)
        ok_emp += (("A" if roll5_emp(a) >= roll5_emp(b) else "B") == truth)
        ok_raw += (("A" if ma + C5 * sa >= mb + C5 * sb else "B") == truth)
        ca = C5 * sa / c4(n) if n > 1 else 0
        cb = C5 * sb / c4(n) if n > 1 else 0
        ok_c4 += (("A" if ma + ca >= mb + cb else "B") == truth)
    print(f"{n:>4} {ok_mean/T*100:>9.0f}% {ok_emp/T*100:>16.0f}% "
          f"{ok_raw/T*100:>12.0f}% {ok_c4/T*100:>10.0f}%")

print()
print("=" * 74)
print("CONCLUSION")
print("=" * 74)
print("""
  * Against POPULATION truth the closed form is close to unbiased, and the
    empirical small-sample formula is biased LOW (it cannot see the tail it is
    trying to estimate). My earlier 'c4 makes it worse' result was an artefact of
    comparing against that biased same-sample reference.
  * For RANKING, the closed form is at least as good as the empirical formula and
    needs only two moments, so it is the better search key.
  * Report the EMPIRICAL value once n is large (finals), because it assumes no
    distribution shape.
""")
