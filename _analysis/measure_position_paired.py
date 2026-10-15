"""Paired noise for a POSITION swap -- the optimizer's dominant search dimension.

The earlier paired test changed only one memory card (corr 0.983, paired CV 0.93%).
But the layered search explores up to 720 POSITION permutations, and positions
change targeting/order, so the shared-variance cancellation is weaker there.

This measures the representative case. 2 configs x 25 seeds = 50 real battles.
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
SEEDS = list(range(4026, 4026 + 25))

base = json.loads(FIXTURE.read_text(encoding="utf-8"))["state"]
# same characters, same memories, different SLOTS (front<->back swap)
alt = json.loads(json.dumps(base))
p = list(alt["friend_positions"])
p[0], p[3] = p[3], p[0]
alt["friend_positions"] = p

print("A positions:", base["friend_positions"])
print("B positions:", alt["friend_positions"])
print("memories identical:", base["memory_ids"] == alt["memory_ids"])

tmp = tempfile.mkdtemp(prefix="izanami_pos_")
ev = TacticalEvaluator(str(ROOT), tmp)

a, b = [], []
for s in SEEDS:
    sa = ev.evaluate(base, s)
    sb = ev.evaluate(alt, s)
    a.append(sa)
    b.append(sb)
    print(f"  seed {s}: A={sa:>14,.0f} B={sb:>14,.0f} diff={sa-sb:>12,.0f}", flush=True)

d = [x - y for x, y in zip(a, b)]
ma, mb = statistics.mean(a), statistics.mean(b)
sda, sdb, sdd = statistics.stdev(a), statistics.stdev(b), statistics.stdev(d)
cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)
r = cov / (sda * sdb)

print("\n=== POSITION SWAP ===")
print(f"A mean={ma:,.0f} SD={sda:,.0f} CV={sda/ma*100:.2f}%")
print(f"B mean={mb:,.0f} SD={sdb:,.0f} CV={sdb/mb*100:.2f}%")
print(f"mean diff = {statistics.mean(d):,.0f} ({statistics.mean(d)/ma*100:+.2f}%)")
print(f"PAIRED SD = {sdd:,.0f} ({sdd/ma*100:.2f}% of A)")
print(f"corr(A,B) = {r:.3f}")
print(f"variance reduction from pairing: {(1-(sdd**2)/(sda**2+sdb**2))*100:.1f}%")

print("\n=== seeds needed for 95% power at a given true gap ===")
for pct in (5, 3, 2, 1, 0.5):
    n = (1.96 * (sdd / ma * 100) / pct) ** 2
    print(f"  {pct:>4}% -> n ~ {n:7.1f}")

print("\n=== 2SE band at each ladder rung ===")
cv = sdd / ma * 100
for n in (2, 4, 8, 16, 32, 50, 64, 128, 150, 256):
    band = 2 * cv / math.sqrt(n)
    print(f"  n={n:>4}: 95% band = +/-{band:.3f}%   (threshold 3% is {3/band:.1f}x the band)")
