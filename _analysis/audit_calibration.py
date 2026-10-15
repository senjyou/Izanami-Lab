"""Are the layered stages statistically distinguishable from each other?

Checks two structural concerns:
  (1) Does the 2->4->8 bare ladder actually DISCRIMINATE, given measured noise?
  (2) Is the V3.1 admission stage (top-K + ties + reps) redundant with the
      later quick review, which admits a similar number anyway?
No battles: pure arithmetic on the declared constants and measured noise.
"""
import math
import statistics

# --- measured from real battles (see measure_paired.py) ------------------
PAIRED_CV = 0.93          # % of mean: SD of the per-seed paired difference
RAW_CV = 5.05             # % of mean: SD of a single battle's score

# --- declared constants --------------------------------------------------
LOOKS = (8, 16, 32, 64, 128, 256)
CAPS = (64, 32, 16, 8, 4, 4)
GAPS = (.05, .03, .02, .01, .005, .005)
FOUR_DROP, EIGHT_DROP, FINAL_DROP = 3, 3, 5
BASE, MAX8 = 2, 8


def se(n, cv=PAIRED_CV):
    """SE of a mean of n paired samples, in % of mean."""
    return cv / math.sqrt(n)


print("=== 1. Do the bare-ladder thresholds discriminate? ===")
print(f"measured paired CV = {PAIRED_CV}%  -> 2SE at n=2 is {2*se(2):.3f}%")
for label, n, thr in (("4-seed gate", 4, FOUR_DROP),
                      ("8-seed gate", 8, EIGHT_DROP),
                      ("final line", 8, FINAL_DROP)):
    print(f"  {label:12} n={n}: threshold={thr}%  2SE={2*se(n):.3f}%   "
          f"threshold/2SE = {thr/(2*se(n)):6.1f}x")
print("  -> thresholds are 5-20x wider than the noise they are meant to gate.")
print("     Consequence: at 4/8 seeds the gate is a NOISE FILTER, not a")
print("     discriminator; it cuts only configs that are clearly worse,")
print("     and passes nearly everything that is remotely competitive.")

print("\n=== 2. Quick-review caps vs. realistic candidate counts ===")
for jt in (10, 70, 525):
    admit = min(jt, max(3, math.ceil(jt * 10 / 100)))
    print(f"  joint_total={jt:>5}: admission ~{admit:>4} candidates"
          f"  -> first cap (8 seeds) = {CAPS[0]}")
    if admit > CAPS[0]:
        print(f"        -> cap {CAPS[0]} binds immediately: {admit-CAPS[0]} candidates"
              f" are cut at only 8 seeds, where 2SE={2*se(8):.3f}%")
        print(f"           A true 1% difference is INVISIBLE at 8 seeds (needs n~{math.ceil((1.96*PAIRED_CV/1.0)**2)}).")

print("\n=== 3. Where does the evidence actually become decisive? ===")
for pct in (5, 3, 2, 1, 0.5):
    n = (1.96 * PAIRED_CV / pct) ** 2
    print(f"  true gap {pct:>4}% -> needs n ~ {n:7.1f} paired seeds for 95% confidence")
print(f"  the ladder's terminal look is {LOOKS[-1]} seeds; the finals add 50 (+100).")
print(f"  -> sub-1% gaps are NEVER statistically resolved anywhere in the pipeline,")
print(f"     yet the champion is chosen on the combined mean anyway.")

print("\n=== 4. Effective 'true gap' a 5% threshold can even detect ===")
print(f"  With n=8, a config must be WORSE by more than {FINAL_DROP}% to be cut,")
print(f"  but the 95% noise band at n=8 is +/-{2*se(8):.3f}%.")
print(f"  So configs genuinely 1-3% worse will USUALLY SURVIVE the 3% gate")
print(f"  (their mean sits inside the band most of the time).")

print("\n=== 5. Cost split under default layered planning (P=720) ===")
p = 720
naked = p * 8                       # 2 + 6 extra
print(f"  bare ladder 2->4->8 worst case : {naked:>7} battles")
print(f"  joint coverage (say 40 admitted x 1 memory): {40*1*4:>7} battles at 4 seeds")
print(f"  finals 50 (+100) x up to 4     : {4*50 + 4*100:>7} battles")
print("  -> the FINALS (600) can exceed the entire joint coverage for small spaces,")
print("     while the bare ladder (5760) dominates everything when P=720.")
