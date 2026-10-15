"""The adversarial case: can the 2-seed screen drop a Roll5 winner?

The previous run showed the true best usually screens near the top. But that
landscape's winner also had the highest MEAN, so a screen ranked on two draws
would find it almost by accident.

The case that tests the screen properly is the one a best-of-five objective is
FOR: a candidate whose mean is lower but whose spread is much wider, so it wins
on the best of five. At two seeds its rank key is dominated by whichever single
draw it happened to get, so it can screen far down the list -- and if it falls
below the refine cut, the search can never refine it and the reported champion is
wrong.

Method: plant one deliberately volatile candidate in the middle of the space and
measure (a) its coarse rank across many random seed bases and (b) whether the
search finds it.
"""

import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))

from src.optimizer import objective as obj
from src.optimizer import search as search_mod

SPACE = 210
BUDGET = 828
REVIEW_SEEDS = 8
COARSE_SEEDS = 2

# A steady cluster near the top, and one volatile candidate placed in the middle.
STEADY_MEAN = 120_000_000.0
STEADY_CV = 0.030
VOLATILE_MEAN = 117_000_000.0     # 2.5% lower mean ...
VOLATILE_CV = 0.115               # ... but roughly 4x the spread
VARIED_CANDIDATES = 209


class Landscape:
    """One volatile candidate among many steady ones.

    ``volatile_index`` is where the wide-spread candidate sits in the memory
    ordering, and ``varied`` makes the steady cluster's spread differ slightly so
    the coarse ranking is not a tie.
    """

    def __init__(self, seed, volatile_index=105, varied=True):
        rng = random.Random(seed)
        self.volatile_index = volatile_index
        self.means = []
        self.sds = []
        for i in range(SPACE):
            if i == volatile_index:
                self.means.append(VOLATILE_MEAN)
                self.sds.append(VOLATILE_MEAN * VOLATILE_CV)
                continue
            # Steady candidates: nearly tied means, mildly varying spread.
            mean = STEADY_MEAN * (1.0 + rng.uniform(-0.002, 0.002))
            cv = STEADY_CV * (rng.uniform(0.85, 1.20) if varied else 1.0)
            self.means.append(mean)
            self.sds.append(mean * cv)
        self._unit_cache = {}

    def unit(self, seed):
        value = self._unit_cache.get(seed)
        if value is None:
            rng = random.Random((seed * 2654435761) % (2 ** 31))
            value = sum(rng.random() for _ in range(12)) - 6.0
            self._unit_cache[seed] = value
        return value

    def evaluate(self, state, seed):
        index = varied_index_of(state)
        return self.means[index] + self.sds[index] * self.unit(seed)

    def true_roll5(self, index, n=4000, base=10_000_000):
        draws = sorted(self.means[index] + self.sds[index] * self.unit(base + s)
                       for s in range(n))
        return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5)
                   for i, x in enumerate(draws, start=1))

    def true_ranking(self):
        scored = [(self.true_roll5(i), i) for i in range(SPACE)]
        scored.sort(reverse=True)
        return scored


def state_for(index):
    """A lineup whose VARIED memory is identified by a marker that survives sorting.

    ``derive()`` sorts ``memory_ids``, so the varied card cannot be read back as
    ``memory_ids[0]``: with ids ``[105, 2, 3, 4, 5, 6]`` the sort puts 2 first and
    every candidate looks like index 2. The varied id is therefore placed BELOW
    the five constants, which makes ``min(memory_ids)`` the varied index and keeps
    it stable under sorting.
    """
    constants = [900_000, 900_001, 900_002, 900_003, 900_004]
    return {"schema": 1, "enemy_id": 1,
            "friend_positions": [1, 2, 3, 4, 5, None],
            "memory_ids": [index] + CONSTANT_IDS,
            "panel": {"character_level": 200, "school_levels": {},
                      "equipment_ids": [], "equipment_enabled": True,
                      "equipment_bonuses": {}, "character_levels": {},
                      "rarities": {}, "affection_levels": {}, "modules": {},
                      "skill_levels": {}}}


def varied_index_of(state):
    """Recover the varied index from a (possibly sorted) memory set."""
    return min(state["memory_ids"])


# The five cards every lineup shares in this test.
CONSTANT_IDS = [900_000, 900_001, 900_002, 900_003, 900_004]


def memory_constraints():
    """Constraints giving exactly ``SPACE`` candidates: 5 required + 210 pool.

    The five shared cards are marked REQUIRED so the space is exactly the 210
    varying cards with one slot to fill -- the shape the user's run reported
    ("空间 1 站位 × 210 回忆 = 210"). Without this the pool would contribute
    C(210,6) = 110 billion combinations and the test would measure a different
    problem entirely.
    """
    marks = {str(cid): "必选" for cid in CONSTANT_IDS}
    marks.update({str(i): "候选" for i in range(SPACE)})
    return {"memories": marks}


def refine_slots(budget=BUDGET, coarse_seeds=COARSE_SEEDS,
                 review_seeds=REVIEW_SEEDS, space=SPACE):
    """How many candidates are screened and how many the refine pass affords.

    Depends on ``coarse_seeds``: screening more thoroughly per candidate costs
    proportionally more, so a larger coarse cohort screens FEWER candidates. That
    trade-off is the whole point of the comparison below.
    """
    reserve = max(review_seeds * 2, budget // 3) + review_seeds
    affordable = max(coarse_seeds, budget - reserve)
    cap = max(1, affordable // coarse_seeds)
    screened = min(cap, space)
    left = (budget - review_seeds) - screened * coarse_seeds
    return left // review_seeds, screened


def coarse_rank(landscape, target, settings):
    """The target's position in the coarse screen for this seed base."""
    search = search_mod.Search(landscape, settings, mode="tactical")
    constraints = memory_constraints()
    screened = search._coarse(state_for(0), constraints)
    screened.sort(key=lambda row: -row["coarse_rank"])
    for position, row in enumerate(screened, start=1):
        if varied_index_of(row["state"]) == target:
            return position
    return None


def main():
    slots, screened_n = refine_slots()
    print("=== the adversarial setup ===")
    print(f"    space                     : {SPACE} candidates")
    print(f"    budget                    : {BUDGET}  -> {screened_n} screened, "
          f"{slots} refine slots")
    print(f"    steady candidates         : mean {STEADY_MEAN:,.0f}, CV {STEADY_CV:.1%}")
    print(f"    volatile candidate        : mean {VOLATILE_MEAN:,.0f} "
          f"({(VOLATILE_MEAN/STEADY_MEAN-1)*100:+.1f}%), CV {VOLATILE_CV:.1%}")
    print()

    # Does the volatile candidate really win on best-of-five?
    land = Landscape(seed=777)
    ranking = land.true_ranking()
    rank_of_volatile = next(i for i, (_, idx) in enumerate(ranking, start=1)
                            if idx == land.volatile_index)
    print(f"    volatile's TRUE rank      : #{rank_of_volatile} of {SPACE}")
    print(f"    volatile's true Roll5     : "
          f"{dict((i, v) for v, i in ranking)[land.volatile_index]:,.0f}")
    print(f"    best steady true Roll5    : {ranking[0][0]:,.0f}")
    print(f"    -> the volatile build {'WINS' if rank_of_volatile == 1 else 'does not win'}"
          f" on best-of-five")
    print()

    print("=== its COARSE rank across 20 seed bases ===")
    ranks = []
    for t in range(20):
        land = Landscape(seed=500 + t * 31)
        settings = search_mod.SearchSettings(
            objective=obj.OBJECTIVE_ROLL5, budget=BUDGET,
            change_positions=False, change_memories=True,
            review_seeds=REVIEW_SEEDS, coarse_seeds=COARSE_SEEDS,
            adaptive_boost=False, workers=1, seed=2000 + t * 13)
        position = coarse_rank(land, land.volatile_index, settings)
        ranks.append(position)
    unscreened = sum(1 for r in ranks if r is None)
    finite = [r for r in ranks if r is not None]
    print(f"    best coarse rank          : {min(finite) if finite else 'n/a'}")
    print(f"    median coarse rank        : "
          f"{statistics.median(finite) if finite else 'n/a'}")
    print(f"    worst coarse rank         : {max(finite) if finite else 'n/a'}")
    inside = sum(1 for r in finite if r <= slots)
    print(f"    within the {slots} refine slots : {inside}/20"
          f"  ({inside/20*100:.0f}%)")
    if unscreened:
        print(f"    never screened            : {unscreened}/20")
    print(f"    => {20-inside}/20 runs DROPPED it: the search could never refine it")
    print()

    print("=== end-to-end: does the search return it? ===")
    found = 0
    trials = 20
    for t in range(trials):
        land = Landscape(seed=500 + t * 31)
        settings = search_mod.SearchSettings(
            objective=obj.OBJECTIVE_ROLL5, budget=BUDGET,
            change_positions=False, change_memories=True,
            review_seeds=REVIEW_SEEDS, coarse_seeds=COARSE_SEEDS,
            adaptive_boost=True, workers=1, seed=2000 + t * 13)
        constraints = memory_constraints()
        result = search_mod.run_search(land, state_for(0), constraints, settings)
        if result.best and varied_index_of(result.best) == land.volatile_index:
            found += 1
    print(f"    found the volatile winner : {found}/{trials}"
          f"  ({found/trials*100:.0f}%)")
    print()

    print("=== does screening more thoroughly per candidate help? ===")
    print("    (more coarse seeds costs proportionally more, so FEWER candidates")
    print("     get screened -- the trade-off this comparison measures)")
    for coarse_seeds in (2, 4, 8, 16):
        slots_n, screened_n2 = refine_slots(coarse_seeds=coarse_seeds)
        ranks = []
        for t in range(20):
            land = Landscape(seed=500 + t * 31)
            settings = search_mod.SearchSettings(
                objective=obj.OBJECTIVE_ROLL5, budget=BUDGET,
                change_positions=False, change_memories=True,
                review_seeds=REVIEW_SEEDS, coarse_seeds=coarse_seeds,
                adaptive_boost=False, workers=1, seed=2000 + t * 13)
            ranks.append(coarse_rank(land, land.volatile_index, settings))
        # A candidate that was never screened has no rank; count it as dropped.
        dropped_unscreened = sum(1 for r in ranks if r is None)
        finite = [r for r in ranks if r is not None]
        inside = sum(1 for r in finite if r <= slots_n)
        median = statistics.median(finite) if finite else float("nan")
        print(f"    coarse_seeds={coarse_seeds:2d}: screened {screened_n2:3d}"
              f"  refine slots {slots_n:3d}  median rank {median:6.1f}"
              f"  reached cut {inside}/20 ({inside/20*100:3.0f}%)"
              + (f"  never screened {dropped_unscreened}" if dropped_unscreened else ""))


if __name__ == "__main__":
    main()


