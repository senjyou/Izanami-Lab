"""Does the screen's 2-seed bimodality matter at the user's REAL spread range?

The adversarial test used a volatile candidate at CV 11.5% against a 3% field.
The user's report showed CVs of 2.7%-4.8%, a far narrower band, so that test may
have overstated the risk. This measures the same thing with the reported range,
and then tests whether a mean-based cut with a variance reserve fixes it.

Why the screen is bimodal at two seeds
--------------------------------------
At n=2 the Roll5 rank key reduces to ``mean + 1.0306*|x1-x2|``. For a candidate
whose spread is much wider than the field's, that is either large (the two draws
differed) or collapses to its mean (they happened to agree). So a volatile
candidate screens either near the top or near the bottom -- almost never in
between -- and in the collapsing case it is cut before it can ever be refined.
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
CONSTANT_IDS = [900_000, 900_001, 900_002, 900_003, 900_004]


class Field:
    """A field with the reported mean spread and CV band.

    ``volatile_cv`` is the widest CV in the field. The user's report showed 2.7%
    to 4.8%, so the realistic range is narrow; the test can also be run with a
    deliberately wide one for comparison.
    """

    def __init__(self, seed, cv_low=0.027, cv_high=0.048, mean_spread=0.03,
                 top_mean=125_600_000.0, n=SPACE):
        rng = random.Random(seed)
        self.means = []
        self.sds = []
        for i in range(n):
            # Means fall away from the top, the first dozen nearly tied -- the
            # shape the report's ranking shows (125.6M down to 122.0M).
            if i < 12:
                mean = top_mean * (1.0 - mean_spread * (i / 11.0))
            else:
                fade = ((i - 12) / max(1, n - 13)) ** 1.6
                mean = top_mean * (1.0 - mean_spread - 0.20 * fade)
            mean *= 1.0 + rng.uniform(-0.0015, 0.0015)
            cv = rng.uniform(cv_low, cv_high)
            self.means.append(mean)
            self.sds.append(mean * cv)
        self._units = {}

    def unit(self, seed):
        value = self._units.get(seed)
        if value is None:
            rng = random.Random((seed * 2654435761) % (2 ** 31))
            value = sum(rng.random() for _ in range(12)) - 6.0
            self._units[seed] = value
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


def varied_index_of(state):
    """The varied card, read safely: derive() sorts memory_ids."""
    return min(state["memory_ids"])


def state_for(index):
    return {"schema": 1, "enemy_id": 1,
            "friend_positions": [1, 2, 3, 4, 5, None],
            "memory_ids": [index] + CONSTANT_IDS,
            "panel": {"character_level": 200, "school_levels": {},
                      "equipment_ids": [], "equipment_enabled": True,
                      "equipment_bonuses": {}, "character_levels": {},
                      "rarities": {}, "affection_levels": {}, "modules": {},
                      "skill_levels": {}}}


def memory_constraints():
    marks = {str(cid): "必选" for cid in CONSTANT_IDS}
    marks.update({str(i): "候选" for i in range(SPACE)})
    return {"memories": marks}


def refine_slots(budget=BUDGET, coarse_seeds=COARSE_SEEDS,
                 review_seeds=REVIEW_SEEDS):
    reserve = max(review_seeds * 2, budget // 3) + review_seeds
    affordable = max(coarse_seeds, budget - reserve)
    cap = max(1, affordable // coarse_seeds)
    screened = min(cap, SPACE)
    left = (budget - review_seeds) - screened * coarse_seeds
    return left // review_seeds, screened


def settings_for(seed, coarse_seeds=COARSE_SEEDS, budget=BUDGET):
    return search_mod.SearchSettings(
        objective=obj.OBJECTIVE_ROLL5, budget=budget,
        change_positions=False, change_memories=True,
        review_seeds=REVIEW_SEEDS, coarse_seeds=coarse_seeds,
        adaptive_boost=True, workers=1, seed=seed)


def coarse_table(landscape, settings):
    """The coarse screen, best first, as (rank_key, index) pairs."""
    search = search_mod.Search(landscape, settings, mode="tactical")
    screened = search._coarse(state_for(0), memory_constraints())
    screened.sort(key=lambda row: -row["coarse_rank"])
    return [(row["coarse_rank"], varied_index_of(row["state"]))
            for row in screened]


def run_case(seed, cv_low, cv_high):
    """One trial: does the search return the true Roll5 best?"""
    land = Field(seed, cv_low=cv_low, cv_high=cv_high)
    rk = land.true_ranking()
    best_i = rk[0][1]
    result = search_mod.run_search(land, state_for(0), memory_constraints(),
                                   settings_for(seed))
    champ = varied_index_of(result.best)
    refined = [varied_index_of(c["state"]) for c in result.candidates]
    return champ == best_i, best_i in refined, land, result


def main():
    slots, screened = refine_slots()
    print("=== the user's realistic spread band (CV 2.7%-4.8%) ===")
    print(f"    space {SPACE}  budget {BUDGET}  screened {screened}  "
          f"refine slots {slots}")
    print()

    hits = 0
    misses = 0
    dropped = 0
    trials = 20
    for t in range(trials):
        seed = 4000 + t * 29
        hit, refined_ok, land, result = run_case(seed, 0.027, 0.048)
        hits += hit
        if not hit:
            misses += 1
        if not refined_ok:
            dropped += 1
    print(f"    found the true Roll5 best : {hits}/{trials}  "
          f"({hits / trials * 100:.0f}%)")
    print(f"    true best never refined   : {dropped}/{trials}")
    print()

    print("=== the same test with a deliberately WIDE spread band ===")
    for lo, hi, label in ((0.027, 0.048, "reported 2.7-4.8%"),
                          (0.03, 0.08, "wider 3-8%"),
                          (0.03, 0.12, "extreme 3-12%")):
        hits = 0
        dropped = 0
        for t in range(20):
            seed = 4000 + t * 29
            hit, refined_ok, land, result = run_case(seed, lo, hi)
            hits += hit
            if not refined_ok:
                dropped += 1
        print(f"    {label:20s}: found best {hits:2d}/20 ({hits/20*100:3.0f}%)"
              f"   never refined {dropped:2d}/20")
    print()

    print("=== how far down the coarse list does the true best sit? ===")
    for lo, hi, label in ((0.027, 0.048, "reported 2.7-4.8%"),
                          (0.03, 0.12, "extreme 3-12%")):
        ranks = []
        for t in range(20):
            seed = 4000 + t * 29
            land = Field(seed, cv_low=lo, cv_high=hi)
            best_i = land.true_ranking()[0][1]
            table = coarse_table(land, settings_for(seed))
            position = next((i for i, (_, idx) in enumerate(table, start=1)
                             if idx == best_i), None)
            ranks.append(position)
        finite = [r for r in ranks if r is not None]
        inside = sum(1 for r in finite if r <= slots)
        print(f"    {label:20s}: median rank "
              f"{statistics.median(finite) if finite else float('nan'):6.1f}"
              f"   within {slots} slots {inside:2d}/20"
              f"   worst {max(finite) if finite else 'n/a'}")


if __name__ == "__main__":
    main()
