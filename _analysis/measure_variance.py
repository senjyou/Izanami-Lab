"""Measure real score dispersion for ONE fixed configuration across seeds.

The optimizer's whole seed ladder (2->4->8->...->256) and its 3%/5% thresholds
are calibrated against presumed noise. This measures the actual noise.
Budget: 30 real battles (project convention caps a case at 100).
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
SEEDS = list(range(2026, 2026 + 30))

state = json.loads(FIXTURE.read_text(encoding="utf-8"))["state"]
tmp = tempfile.mkdtemp(prefix="izanami_variance_")
ev = TacticalEvaluator(str(ROOT), tmp)

scores = []
for seed in SEEDS:
    s = ev.evaluate(state, seed)
    scores.append(s)
    print(f"  seed {seed}: {s:,.2f}", flush=True)

mean = statistics.mean(scores)
sd = statistics.stdev(scores)
print("\n=== SAME configuration, 30 different seeds ===")
print(f"n        : {len(scores)}")
print(f"mean     : {mean:,.2f}")
print(f"stdev    : {sd:,.2f}")
print(f"min      : {min(scores):,.2f}")
print(f"max      : {max(scores):,.2f}")
print(f"range    : {max(scores)-min(scores):,.2f}")
print(f"CV       : {sd/mean*100:.4f}%   <- relative noise of a single battle")
print(f"range/mean: {(max(scores)-min(scores))/mean*100:.4f}%")
# How many seeds to resolve a 3% difference with this noise?  n = (z*sd/ delta)^2
for delta_pct in (5, 3, 1, 0.5):
    delta = mean * delta_pct / 100
    n80 = (1.2816 * sd / delta) ** 2
    n95 = (1.96 * sd / delta) ** 2
    print(f"  to resolve {delta_pct:>4}% diff: n~{n80:6.1f} (80% power), n~{n95:6.1f} (95% power)")
