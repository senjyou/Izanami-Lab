"""Second position-swap pair: is the low paired correlation robust?

n=25 gives corr SE ~ 1/sqrt(n-3) ~ 0.21, so a single r is imprecise. This adds a
SECOND, independent position swap so the two estimates can be compared. 50 battles.
"""
import json
import math
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))

from src.optimizer.engine import TacticalEvaluator  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json"
SEEDS = list(range(5026, 5026 + 25))

base = json.loads(FIXTURE.read_text(encoding="utf-8"))["state"]

# Different swap than run 1: centre-front <-> right-back  (positions 1 and 5)
alt = json.loads(json.dumps(base))
p = list(alt["friend_positions"])
p[1], p[5] = p[5], p[1]
alt["friend_positions"] = p

print("A:", base["friend_positions"])
print("B:", alt["friend_positions"])

tmp = tempfile.mkdtemp(prefix="izanami_pos2_")
ev = TacticalEvaluator(str(ROOT), tmp)

a, b = [], []
for s in SEEDS:
    a.append(ev.evaluate(base, s))
    b.append(ev.evaluate(alt, s))

d = [x - y for x, y in zip(a, b)]
ma, mb = statistics.mean(a), statistics.mean(b)
sda, sdb, sdd = statistics.stdev(a), statistics.stdev(b), statistics.stdev(d)
cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)
r = cov / (sda * sdb)
n = len(a)
se_r = 1 / math.sqrt(n - 3)          # Fisher-ish SE for correlation
# 95% CI on r via Fisher z
z = math.atanh(max(-0.999, min(0.999, r)))
lo, hi = math.tanh(z - 1.96 / math.sqrt(n - 3)), math.tanh(z + 1.96 / math.sqrt(n - 3))

print("\n=== POSITION SWAP #2 (centre-front <-> right-back) ===")
print(f"A mean={ma:,.0f} SD={sda:,.0f} CV={sda/ma*100:.2f}%")
print(f"B mean={mb:,.0f} SD={sdb:,.0f} CV={sdb/mb*100:.2f}%")
print(f"mean diff = {statistics.mean(d):,.0f} ({statistics.mean(d)/ma*100:+.2f}%)")
print(f"PAIRED SD = {sdd:,.0f} ({sdd/ma*100:.2f}% of A)")
print(f"corr(A,B) = {r:.3f}   95% CI = [{lo:.3f}, {hi:.3f}]  (SE_r~{se_r:.2f})")
print(f"variance reduction from pairing: {(1-(sdd**2)/(sda**2+sdb**2))*100:.1f}%")

print("\n=== COMPARISON OF THE TWO POSITION SWAPS ===")
print("  swap #1 (front-left <-> back-left) : corr = -0.104, paired CV = 6.09%")
print(f"  swap #2 (centre-front <-> right-back): corr = {r:+.3f}, paired CV = {sdd/ma*100:.2f}%")
print("  memory swap (reference)             : corr = +0.983, paired CV = 0.93%")

print("\n=== seeds for 95% power at this paired CV ===")
cv = sdd / ma * 100
for pct in (3, 2, 1):
    print(f"  {pct:>3}% gap -> n ~ {(1.96*cv/pct)**2:6.1f}")
print(f"  2SE band at n=4 = +/-{2*cv/2:.2f}% ; at n=8 = +/-{2*cv/math.sqrt(8):.2f}%")
