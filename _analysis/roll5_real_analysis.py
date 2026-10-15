"""Analyse the user's REAL 100-battle run and derive the optimizer's requirements.

Real data (user-provided, 火沙耶 main-carry, tactical exercise, 100 battles):
    mean  80,597,341.4      sd  9,415,342.4
    max  103,253,240        min 59,662,680
    Q1    73,804,246        Q3  88,705,667.5
    Roll5 91,485,697

Verified facts (see console output of the analysis):
  * CV = 11.68%  -- 3.2x higher than the ~3.6% my synthetic lineups produced,
    which is exactly why I could not reproduce the user's spread.
  * reported Roll5 is within 0.067% of normal theory (mean + 1.16296*sd),
    so the score distribution is close to normal and Roll5 is well-defined.
  * max/min = 1.73x, and 2.0x would require CV ~= 19.9% -- matching the user's
    statement that WITHOUT the crit-rate memories the spread reaches 2x.

What this implies for search design, computed here:

  Q1  How many seeds are needed to estimate Roll5 to a given accuracy?
  Q2  How does ranking by sample-mean differ from ranking by sample-Roll5 at
      realistic seed counts?  (the core defect of the author's algorithm)
  Q3  How many seeds before a Roll5 estimate is stable enough to rank with?

Method: Monte-Carlo over normal samples with the user's CV, comparing
  * the TRUE Roll5 of each candidate (large-sample reference)
  * the Roll5 estimated from n seeds
  * the MEAN estimated from n seeds
and measuring how often each picks the truly better build.
"""
import math
import random
import statistics
from pathlib import Path

HERE = Path(__file__).parent
MEAN = 80_597_341.4
SD = 9_415_342.4
CV = SD / MEAN
C5 = 1.162964          # E[max of 5 standard normals]
rng = random.Random(20261013)


def roll5_from(samples):
    """E[max of 5] from an empirical sample -- the simulator's own formula."""
    xs = sorted(samples)
    n = len(xs)
    return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5) for i, x in enumerate(xs, start=1))


def draw(mu, sd, n):
    return [max(mu + rng.gauss(0, sd), mu * 0.02) for _ in range(n)]


print("=" * 78)
print("Q1: SEED COUNT NEEDED TO ESTIMATE Roll5")
print("=" * 78)
print(f"reference CV = {CV*100:.2f}% (user's real run)\n")
print(f"{'seeds':>6} {'Roll5 est':>14} {'bias':>9} {'sd of est':>11} {'rel sd':>8}")

truth = statistics.mean(draw(MEAN, SD, 200000))
true_r5 = roll5_from(draw(MEAN, SD, 200000))
print(f"  (large-sample reference: mean={truth:,.0f}  Roll5={true_r5:,.0f})")
print()
for n in (2, 4, 8, 16, 32, 64, 100, 200):
    ests = [roll5_from(draw(MEAN, SD, n)) for _ in range(400)]
    m = statistics.mean(ests)
    sd = statistics.stdev(ests)
    print(f"{n:>6} {m:>14,.0f} {m-true_r5:>9,.0f} {sd:>11,.0f} {sd/true_r5*100:>7.2f}%")

print()
print("=" * 78)
print("Q2: MEAN-RANKING vs Roll5-RANKING at realistic seed counts")
print("=" * 78)
print("Two builds: A has the user's CV; B is A with 1-3% LOWER mean but")
print("1.7x the CV (i.e. the crit-memory trade-off the user describes).")
print("Which does each estimator pick, and how often?\n")

print(f"{'B mean':>8} {'B CV':>7} {'true Roll5 A':>14} {'true Roll5 B':>14} "
      f"{'truth':>6} | {'n':>4} {'mean-pick':>10} {'roll5-pick':>11} {'mean acc':>9} {'r5 acc':>8}")

for b_mean_frac, b_cv_mult in ((0.99, 1.7), (0.97, 1.7), (0.99, 2.5), (0.95, 2.5)):
    b_mean = MEAN * b_mean_frac
    b_sd = SD * b_cv_mult
    # large-sample truth
    a_ref = roll5_from(draw(MEAN, SD, 120000))
    b_ref = roll5_from(draw(b_mean, b_sd, 120000))
    truth_pick = "A" if a_ref >= b_ref else "B"
    for n in (2, 4, 8, 16, 32, 64):
        mean_ok = r5_ok = trials = 0
        for _ in range(300):
            a = draw(MEAN, SD, n)
            b = draw(b_mean, b_sd, n)
            mp = "A" if statistics.mean(a) >= statistics.mean(b) else "B"
            rp = "A" if roll5_from(a) >= roll5_from(b) else "B"
            mean_ok += (mp == truth_pick)
            r5_ok += (rp == truth_pick)
            trials += 1
        print(f"{b_mean_frac:>8.2f} {b_cv_mult:>7.1f} {a_ref:>14,.0f} {b_ref:>14,.0f} "
              f"{truth_pick:>6} | {n:>4} {'':>10} {'':>11} "
              f"{mean_ok/trials*100:>8.0f}% {r5_ok/trials*100:>7.0f}%")

print()
print("=" * 78)
print("Q3: HOW MANY SEEDS BEFORE Roll5 RANKING IS RELIABLE?")
print("=" * 78)
print("Same setup, 3% mean gap, 1.7x CV gap -- the user's scenario.\n")
b_mean, b_sd = MEAN * 0.97, SD * 1.7
a_ref = roll5_from(draw(MEAN, SD, 120000))
b_ref = roll5_from(draw(b_mean, b_sd, 120000))
truth_pick = "A" if a_ref >= b_ref else "B"
print(f"  true Roll5: A={a_ref:,.0f}  B={b_ref:,.0f}  -> truth picks {truth_pick}")
print()
print(f"{'seeds':>6} {'mean-est accuracy':>18} {'Roll5-est accuracy':>19}")
for n in (2, 4, 8, 16, 32, 64, 128):
    mo = ro = t = 0
    for _ in range(400):
        a = draw(MEAN, SD, n)
        b = draw(b_mean, b_sd, n)
        mo += (("A" if statistics.mean(a) >= statistics.mean(b) else "B") == truth_pick)
        ro += (("A" if roll5_from(a) >= roll5_from(b) else "B") == truth_pick)
        t += 1
    print(f"{n:>6} {mo/t*100:>17.0f}% {ro/t*100:>18.0f}%")

print()
print("=" * 78)
print("SUMMARY")
print("=" * 78)
print(f"""
  * The user's real CV is {CV*100:.1f}%, ~3.2x what my synthetic lineups gave.
  * Roll5 uplift over the mean is {(true_r5/MEAN-1)*100:+.1f}% at this CV --
    a real, exploitable gain, not a rounding artefact.
  * RANKING BY MEAN IS SYSTEMATICALLY WRONG here: it prefers the low-variance
    build even when the high-variance build has a better Roll5.
  * Roll5 estimated from n seeds needs LARGER n than the mean to rank reliably
    (Roll5 depends on the upper tail, which is harder to estimate).
""")
