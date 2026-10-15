"""Static budget/threshold audit of the layered algorithm under DEFAULT settings.

No battles are run; this only exercises the pure planning functions.
"""
import json
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))

from src.optimizer.model import prepare_search_snapshot  # noqa: E402
from src.optimizer.position_search import PositionSpace  # noqa: E402
from src.optimizer.memory_search import MemorySpace  # noqa: E402
from src.optimizer.search import SearchSettings  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json"
state = json.loads(FIXTURE.read_text(encoding="utf-8"))["state"]

# Default constraints: everything required (as default_constraints() would produce)
constraints = {
    "characters": {str(c): "必选" for c in state["friend_positions"] if c is not None},
    "memories": {str(m): "必选" for m in state["memory_ids"]},
}
s = SearchSettings()          # ALL DEFAULTS, including search_kind default
print("=== SearchSettings() defaults relevant here ===")
for k in ("budget", "search_kind", "layered_base_seeds", "layered_max_seeds",
          "layered_joint_seeds", "layered_review_percent", "review_strategy",
          "quick_max_seeds", "layered_filter", "layered_memory_pruning"):
    print(f"  {k:26} = {getattr(s, k)!r}")

prepared = prepare_search_snapshot(state, constraints, None,
                                   change_fifth=False, change_memories=True,
                                   change_affixes=False)
positions = PositionSpace(prepared, constraints)
memories = MemorySpace(prepared, constraints)

print("\n=== space with NO position constraints (default) ===")
print(f"  legal positions : {positions.total}")
print(f"  memory combos   : {memories.total}  (all 6 required -> C(0,0)=1)")

minimum = positions.total * s.layered_base_seeds
print("\n=== layered bootstrap gate (layered_search.run L377-381) ===")
print(f"  minimum = positions.total * layered_base_seeds = {positions.total} * {s.layered_base_seeds} = {minimum}")
print(f"  default budget = {s.budget}")
print(f"  -> budget < minimum ? {s.budget < minimum}"
      f"   {'*** REFUSES TO START ***' if s.budget < minimum else 'ok'}")

print("\n=== joint space if memories were the searchable dimension ===")
# 2 required + 8 candidates -> C(8,4)=70, the documented regression pool
c2 = {"characters": {str(c): "必选" for c in state["friend_positions"] if c is not None},
      "memories": {**{str(m): "必选" for m in state["memory_ids"][:2]},
                   **{str(m): "候选" for m in state["memory_ids"][2:]}}}
prep2 = prepare_search_snapshot(state, c2, None, change_fifth=False,
                                change_memories=True, change_affixes=False)
m2 = MemorySpace(prep2, c2)
print(f"  2 required + {len(m2.pool)} candidates -> C({len(m2.pool)},{m2.count}) = {m2.total}")

print("\n=== review-admission scaling: 10% of JOINT space (default) ===")
for jt in (1, 10, 70, 525, 2520, 50400):
    cnt = min(jt, max(3, -(-jt * s.layered_review_percent // 100)))
    print(f"  joint_total={jt:>6} -> first-8-seed candidates ~{cnt:>6}"
          f"  -> battles for round 1 = {cnt*8:>8}")
print(f"  (default budget is only {s.budget})")

print("\n=== what 8 seeds buys, given measured PAIRED noise (0.93% CV) ===")
sd_d_pct = 0.93
for n in (2, 4, 8, 50, 150):
    se = sd_d_pct / (n ** 0.5)
    print(f"  n={n:>4} -> SE={se:.3f}% of mean, 2SE (95%) = {2*se:.3f}%")
print("  thresholds used by the algorithm: 3% (4/8 seeds), 5% (final line)")
