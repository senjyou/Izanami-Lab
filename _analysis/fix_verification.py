"""Verify the reported failure is fixed, end to end, with real battles skipped.

Reproduces the user's exact scenario:

    objective  Roll5, budget 12000
    pool       the whole 164-card catalogue (what the dialog used to send)
    result     "预算不足 / 没有候选完成完整的精评种子组"

and shows what happens now for three cases:

  A. the old full-catalogue pool    -> still unsearchable, but the budget is
     honoured and a pool warning is shown up front
  B. a 12-card pool                 -> completes with ranked candidates
  C. a 16-card pool                 -> completes with ranked candidates

The search runs against a stub evaluator (no real battles), so this measures the
accounting and the plan, not the engine.
"""
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))

from src.optimizer import budget as budget_mod
from src.optimizer import objective as obj
from src.optimizer import search as search_mod

ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")
failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  OK    {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


class StubEngine:
    """Deterministic scores with a real spread, so Roll5 ranking is meaningful.

    The empty slot's index seeds a per-candidate mean and spread, so candidates
    genuinely differ and the ranking has something to rank.
    """

    def __init__(self):
        self.calls = 0

    @staticmethod
    def _unit(seed):
        import random
        raw = [random.Random(seed * 31 + k * 7919).random() for k in range(12)]
        return sum(raw) - 6.0

    def evaluate(self, state, seed):
        self.calls += 1
        positions = state["friend_positions"]
        empty = positions.index(None) if None in positions else 0
        # Mean varies by position AND by the memory set, so both axes matter.
        mem_sum = sum(state["memory_ids"]) % 1000
        mean = 5000.0 + empty * 137.0 + mem_sum * 0.7
        spread = 20.0 + (empty * 31.0) % 120
        return mean + spread * self._unit(seed)


def state_for(pool, pinned=()):
    memories = sorted(set(pool))
    pinned = set(pinned)
    need = 6 - len(pinned)
    if need > 0:
        filler = [m for m in range(900001, 900001 + need)]
        memories = sorted(pinned | set(filler))
    return {"schema": 1, "enemy_id": 381305,
            "friend_positions": [100303, None, 132301, 145301, 112302, 111301],
            "memory_ids": memories,
            "panel": {"character_level": 408, "school_levels": {},
                      "equipment_ids": [], "equipment_enabled": True,
                      "equipment_bonuses": {}, "character_levels": {},
                      "rarities": {}, "affection_levels": {}, "modules": {},
                      "skill_levels": {}}}


def run(pool_size, budget, objective_name, effort="standard"):
    """Run one search over a pool of this many cards."""
    pool = list(range(1, pool_size + 1))
    state = state_for(pool)
    constraints = {"memories": {str(m): "候选" for m in pool}}
    settings = search_mod.SearchSettings(
        objective=objective_name, budget=budget, change_memories=True,
        change_positions=True, review_seeds=8 if objective_name == "roll5" else 2,
        coarse_seeds=2 if objective_name == "roll5" else 1, workers=1)
    stub = StubEngine()
    t0 = time.perf_counter()
    # The stub is in-process, so no pool is used; the accounting is identical.
    result = search_mod.run_search(stub, state, constraints, settings, pool=None)
    return result, time.perf_counter() - t0


print("=== A. the reported case: full 164-card catalogue, budget 12000, Roll5 ===")
plan = budget_mod.plan_search(720 * math.comb(164, 6), obj.OBJECTIVE_ROLL5)
print(f"    space        : 720 x C(164,6) = {720 * math.comb(164, 6):,}")
print(f"    plan budget  : {plan['budget']:,}   coverage={plan['coverage']*100:.8f}%")
print(f"    estimate says: {budget_mod.describe_plan(plan)[:80]}...")
result, elapsed = run(164, 12000, "roll5")
print(f"    run: battles={result.battles:,}  candidates={len(result.candidates)}"
      f"  termination={result.termination}  ({elapsed:.1f}s)")
check("budget was honoured (not overspent)", result.battles <= 12000,
      f"{result.battles} > 12000")
check("the run produced ranked candidates", bool(result.candidates),
      f"{len(result.candidates)} candidates, {result.termination}")
check("termination is not '无可用候选'", result.termination != "无可用候选",
      result.termination)
print(f"    detail: {result.detail}")

print()
print("=== B/C. a bounded pool completes comfortably ===")
for pool_size in (12, 16):
    plan = budget_mod.plan_search(720 * math.comb(pool_size, 6), obj.OBJECTIVE_ROLL5)
    result, elapsed = run(pool_size, 12000, "roll5")
    print(f"    pool={pool_size:2d}: space={720 * math.comb(pool_size, 6):>12,}"
          f"  plan={plan['budget']:>6,}"
          f"  ran={result.battles:>6,}  candidates={len(result.candidates):>3}"
          f"  {result.termination}  ({elapsed:.1f}s)")
    check(f"pool={pool_size}: honoured budget", result.battles <= 12000,
          result.battles)
    check(f"pool={pool_size}: ranked candidates present", bool(result.candidates))
    check(f"pool={pool_size}: baseline evaluated",
          any(c["is_baseline"] for c in result.candidates))

print()
print("=== the estimate for each case (what the dialog will show) ===")
for name, pool_size, objective_name in (
        ("全卡池 164", 164, "roll5"),
        ("12 张", 12, "roll5"),
        ("16 张", 16, "roll5"),
        ("12 张 / 均值", 12, "mean")):
    space = 720 * math.comb(pool_size, 6)
    plan = budget_mod.plan_search(space, objective_name)
    print(f"    {name:14s} space={space:>18,}  budget={plan['budget']:>7,}"
          f"  screened={plan['screened']:>6,}  refined={plan['refined']}")

print()
if failures:
    print(f"FAILED ({len(failures)}): " + ", ".join(failures))
    sys.exit(1)
print("reported-failure verification passed")
