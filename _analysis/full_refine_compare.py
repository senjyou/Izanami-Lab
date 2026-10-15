"""The decisive test: does refining everything change the answer?

The user's question, answered directly rather than by inference: run the same
search at the reported budget (which refines ~51 of 210) and at a budget large
enough to refine ALL 210, then compare the two champions.

If the champion is the same -- or its score differs by less than the noise -- the
159 unrefined candidates did not matter. If the fully-refined run finds something
meaningfully better, they did.

Also separates the two possible causes of a miss:
  * the SCREEN dropped the winner (it was never refined), or
  * the REFINE ranking put a slightly worse candidate first (measurement noise).

Those need different fixes, so the test reports them separately.
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
FULL_BUDGET = 60_000          # enough to screen and refine all 210 with 8 seeds
REVIEW_SEEDS = 8
COARSE_SEEDS = 2
CONSTANT_IDS = [900_000, 900_001, 900_002, 900_003, 900_004]


class Field:
    """A field calibrated to the reported run (means and CV band)."""

    def __init__(self, seed, cv_low=0.027, cv_high=0.048, mean_spread=0.03,
                 top_mean=125_600_000.0, n=SPACE):
        rng = random.Random(seed)
        self.means = []
        self.sds = []
        for i in range(n):
            if i < 12:
                mean = top_mean * (1.0 - mean_spread * (i / 11.0))
            else:
                fade = ((i - 12) / max(1, n - 13)) ** 1.6
                mean = top_mean * (1.0 - mean_spread - 0.20 * fade)
            mean *= 1.0 + rng.uniform(-0.0015, 0.0015)
            self.means.append(mean)
            self.sds.append(mean * rng.uniform(cv_low, cv_high))
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

    def true_roll5(self, index, n=6000, base=10_000_000):
        draws = sorted(self.means[index] + self.sds[index] * self.unit(base + s)
                       for s in range(n))
        return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5)
                   for i, x in enumerate(draws, start=1))

    def true_ranking(self):
        scored = [(self.true_roll5(i), i) for i in range(SPACE)]
        scored.sort(reverse=True)
        return scored


def varied_index_of(state):
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


def run(landscape, budget, seed):
    settings = search_mod.SearchSettings(
        objective=obj.OBJECTIVE_ROLL5, budget=budget,
        change_positions=False, change_memories=True,
        review_seeds=REVIEW_SEEDS, coarse_seeds=COARSE_SEEDS,
        adaptive_boost=False, workers=1, seed=seed)
    return search_mod.run_search(landscape, state_for(0), memory_constraints(),
                                 settings)


def main():
    print("=== partial budget (as reported) vs refining EVERYTHING ===")
    print(f"    partial budget : {BUDGET:,} battles")
    print(f"    full budget    : {FULL_BUDGET:,} battles (all 210 refined)")
    print()

    trials = 16
    same = 0
    shortfalls = []
    screen_drops = 0
    refine_noise = 0
    for t in range(trials):
        seed = 7000 + t * 37
        land = Field(seed)
        truth = land.true_ranking()
        true_best = truth[0][1]
        true_of = {i: v for v, i in truth}

        partial = run(land, BUDGET, seed)
        full = run(land, FULL_BUDGET, seed)
        champ_partial = varied_index_of(partial.best)
        champ_full = varied_index_of(full.best)

        if champ_partial == champ_full:
            same += 1
        # Shortfall of the partial champion against the true best.
        shortfalls.append((true_of[true_best] - true_of[champ_partial])
                          / true_of[true_best] * 100)
        # Which stage lost the true best in the partial run?
        refined = [varied_index_of(c["state"]) for c in partial.candidates]
        if true_best not in refined:
            screen_drops += 1
        elif champ_partial != true_best:
            refine_noise += 1

    print(f"    partial and full agree on the champion : {same}/{trials}"
          f"  ({same / trials * 100:.0f}%)")
    print(f"    median shortfall vs true best          : "
          f"{statistics.median(shortfalls):.4f}%")
    print(f"    worst shortfall                        : {max(shortfalls):.4f}%")
    print()
    print("    where the true best was lost (partial run):")
    print(f"      screen never refined it  : {screen_drops}/{trials}")
    print(f"      refined but ranked lower : {refine_noise}/{trials}")
    print(f"      (both zero means it was found)          : "
          f"{trials - screen_drops - refine_noise}/{trials}")
    print()

    # How big is the refine stage's own noise? Compare the champion's measured
    # score against its true score.
    print("=== is the gap inside the measurement noise? ===")
    land = Field(7000)
    truth = land.true_ranking()
    true_of = {i: v for v, i in truth}
    result = run(land, BUDGET, 7000)
    for cand in result.candidates[:5]:
        idx = varied_index_of(cand["state"])
        measured = cand["summary"]["rank"]
        true_value = true_of[idx]
        err = (measured - true_value) / true_value * 100
        print(f"    #{cand['rank']:2d} index {idx:3d}  measured {measured:,.0f}"
              f"  true {true_value:,.0f}  error {err:+.2f}%")
    print()
    top_gap = (true_of[truth[0][1]] - true_of[truth[1][1]]) / true_of[truth[0][1]] * 100
    print(f"    true gap between #1 and #2 : {top_gap:.4f}%")
    print(f"    => if the measured error exceeds that gap, the refine ranking")
    print(f"       cannot reliably tell them apart -- which is the real limit.")


if __name__ == "__main__":
    main()
