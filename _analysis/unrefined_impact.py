"""Does leaving candidates unrefined change the answer?

The question, made measurable: with a fixed budget the search screens every
candidate cheaply and refines only a subset. Could an unrefined candidate really
be the best one, so the reported champion is wrong?

Method
------
A stub evaluator stands in for the battle engine, seeded so that every candidate
has a KNOWN true distribution of scores. That lets the true best-of-five be
computed exactly (from the true parameters, by many samples), and then compared
against what the search actually returns.

The stub's landscape is calibrated to the user's real run so the answer is not an
artifact of unrealistic numbers:

    space            210 candidates (one position x 210 memory sets)
    budget           828 battles (the auto estimate for that space)
    top-10 spread    ~3%   (125.6M down to 121.9M in the report)
    CV               2.7%-4.8%  (as reported)

The measurement that matters is **how often the search's champion is the true
champion**, and **where the true champion sat in the coarse screen** -- the
second one says whether the screen is dropping winners.
"""

import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))

from src.optimizer import budget as budget_mod
from src.optimizer import objective as obj
from src.optimizer import search as search_mod

# Calibrated to the user's reported run.
SPACE = 210
BUDGET = 828
TOP_MEAN = 125_600_000.0
# The report's top 10 spanned 125.6M down to 121.96M, i.e. ~3%.
TOP_SPREAD = 0.030
# Reported CVs ranged 2.7% to 4.8%, so spread varies by roughly +/-40%.
CV_VARIATION = 0.40
BASE_CV = 0.036
N_CANDIDATES = SPACE
# How far the tail of the space sits below the top.
SPACE_FRACTION = 0.20


class Landscape:
    """A fixed set of candidates with known true (mean, sd).

    Each candidate's score for a seed is ``mean + sd * unit(seed)`` with ``unit``
    a deterministic, approximately standard-normal value. Because the parameters
    are known, the true best-of-five can be computed from them directly rather
    than estimated.

    The top of the distribution is calibrated to the user's run: the leading
    candidates sit within a few percent of each other (the report showed a ~3%
    spread across the top 10), and their spreads vary enough that the ranking is
    genuinely decided by variance -- which is the case where a coarse screen
    ranked on two draws could plausibly drop the winner.
    """

    def __init__(self, seed=12345, n=SPACE, space_fraction=SPACE_FRACTION,
                 base_cv=BASE_CV, top_spread=TOP_SPREAD, cv_variation=CV_VARIATION):
        rng = random.Random(seed)
        self.means = []
        self.sds = []
        for i in range(n):
            # The first few candidates are nearly tied; the rest fall away
            # quickly, which is the shape the report's ranking shows.
            if i < 12:
                mean = TOP_MEAN * (1.0 - top_spread * (i / 11.0))
            else:
                fade = ((i - 12) / max(1, n - 13)) ** 1.6
                mean = TOP_MEAN * (1.0 - top_spread
                                   - space_fraction * fade)
            mean *= 1.0 + rng.uniform(-0.0015, 0.0015)
            # Spread varies per candidate: a memory set that stacks crit damage
            # has a wider spread and a lower mean, which is exactly the trade-off
            # a best-of-five objective is supposed to notice.
            cv = base_cv * rng.uniform(1.0 - cv_variation, 1.0 + cv_variation)
            self.means.append(mean)
            self.sds.append(mean * cv)
        self.calls = 0
        self._unit_cache = {}

    def unit(self, seed):
        """A deterministic ~N(0,1) value, cached by seed."""
        value = self._unit_cache.get(seed)
        if value is None:
            rng = random.Random(seed * 2654435761 % (2 ** 31))
            raw = [rng.random() for _ in range(12)]
            value = sum(raw) - 6.0
            self._unit_cache[seed] = value
        return value

    def evaluate(self, state, seed):
        self.calls += 1
        index = state["memory_ids"][0]
        return self.means[index] + self.sds[index] * self.unit(seed)

    def true_roll5(self, index, n=2000):
        """The candidate's true best-of-five, from its known parameters.

        Computed by sampling ``n`` independent draws and taking the empirical
        order statistic, which converges to the true value.
        """
        draws = [self.means[index] + self.sds[index] * self.unit(s)
                 for s in range(10_000_000, 10_000_000 + n)]
        draws.sort()
        return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5)
                   for i, x in enumerate(draws, start=1))

    def true_ranking(self):
        """Every candidate's true best-of-five, best first."""
        scored = [(self.true_roll5(i), i) for i in range(len(self.means))]
        scored.sort(reverse=True)
        return scored


def state_for(index):
    return {"schema": 1, "enemy_id": 1,
            "friend_positions": [1, 2, 3, 4, 5, None],
            "memory_ids": [index, 2, 3, 4, 5, 6],
            "panel": {"character_level": 200, "school_levels": {},
                      "equipment_ids": [], "equipment_enabled": True,
                      "equipment_bonuses": {}, "character_levels": {},
                      "rarities": {}, "affection_levels": {}, "modules": {},
                      "skill_levels": {}}}


def run_search(landscape, budget=BUDGET, change_positions=False):
    """Run the real pipeline over the landscape."""
    settings = search_mod.SearchSettings(
        objective=obj.OBJECTIVE_ROLL5, budget=budget,
        change_positions=change_positions, change_memories=True,
        review_seeds=8, coarse_seeds=2, adaptive_boost=True, workers=1)
    constraints = {"memories": {str(i): "候选"
                                for i in range(len(landscape.means))}}
    template = state_for(0)
    return search_mod.run_search(landscape, template, constraints, settings)


def coarse_rank_of(landscape, target, budget=BUDGET):
    """Where ``target`` lands in the COARSE screen, and whether that admits it.

    Runs the screen exactly as the search does (2 seeds per candidate), then sorts
    by the same rank key and reports the target's position. This is the number
    that decides whether an unrefined candidate could have been the winner: if the
    true best screens outside the refine cut, the search can never refine it.
    """
    settings = search_mod.SearchSettings(
        objective=obj.OBJECTIVE_ROLL5, budget=budget,
        change_positions=False, change_memories=True,
        review_seeds=8, coarse_seeds=2, adaptive_boost=True, workers=1)
    constraints = {"memories": {str(i): "候选"
                                for i in range(len(landscape.means))}}
    template = state_for(0)
    search = search_mod.Search(landscape, settings, mode="tactical")
    screened = search._coarse(template, constraints)
    screened.sort(key=lambda row: -row["coarse_rank"])

    # How many candidates the refine pass could afford.
    review_cost = settings.review_seeds
    reserve = max(review_cost * 2, budget // 3) + review_cost
    affordable = max(settings.coarse_seeds, budget - reserve)
    cap = max(1, affordable // settings.coarse_seeds)
    screened_n = min(cap, len(landscape.means))
    left = (budget - review_cost) - screened_n * settings.coarse_seeds
    refine_slots = left // review_cost

    position = None
    for index, row in enumerate(screened, start=1):
        if row["state"]["memory_ids"][0] == target:
            position = index
            break
    return position, screened, refine_slots


def main():
    print("=== building the landscape and the true ranking ===")
    landscape = Landscape()
    ranking = landscape.true_ranking()
    truth_best = ranking[0][1]
    print(f"    candidates      : {len(landscape.means)}")
    print(f"    true best index : {truth_best}")
    print(f"    top-5 true Roll5: "
          + ", ".join(f"{v:,.0f}" for v, _ in ranking[:5]))
    spread = (ranking[0][0] - ranking[9][0]) / ranking[0][0] * 100
    print(f"    top-10 spread   : {spread:.2f}%  (report showed ~3%)")

    print()
    print("=== what the search returns ===")
    train_landscape = Landscape()          # same seed -> same landscape
    result = run_search(train_landscape)
    print(f"    battles         : {result.battles} (budget {BUDGET})")
    print(f"    screened        : {result.detail}")
    print(f"    candidates      : {len(result.candidates)}")
    champion = result.best["memory_ids"][0]
    print(f"    search champion : index {champion}")
    print(f"    true champion   : index {truth_best}")
    hit = champion == truth_best
    print(f"    -> found the true best? {'YES' if hit else 'NO'}")

    # Where did the true best sit in the coarse screen, and was it refined?
    refined_ids = [c["state"]["memory_ids"][0] for c in result.candidates]
    print()
    print(f"    was the true best refined? "
          f"{'YES' if truth_best in refined_ids else 'NO'}")
    if truth_best in refined_ids:
        pos = refined_ids.index(truth_best) + 1
        print(f"    its rank in the output: #{pos}")

    # How good was the reported champion really?
    true_of_champion = dict((i, v) for v, i in ranking)[champion]
    print(f"    champion's true Roll5  : {true_of_champion:,.0f}")
    print(f"    best possible          : {ranking[0][0]:,.0f}")
    loss = (ranking[0][0] - true_of_champion) / ranking[0][0] * 100
    print(f"    shortfall vs best      : {loss:.3f}%")

    print()
    print("=== where does the TRUE best land in the coarse screen? ===")
    # This is the number that decides whether an unrefined candidate mattered:
    # if the true best screens below the refine cut, no budget would ever refine
    # it, and the reported champion is the screen's error, not the budget's.
    positions = []
    admitted = 0
    slots_seen = []
    for t in range(12):
        land = Landscape(seed=1000 + t * 7)
        rk = land.true_ranking()
        best_i = rk[0][1]
        pos, screened, slots = coarse_rank_of(land, best_i)
        positions.append(pos)
        slots_seen.append(slots)
        if pos is not None and pos <= slots:
            admitted += 1
    print(f"    refine slots available          : {slots_seen[0]} candidates")
    print(f"    true best's coarse rank (median): {statistics.median(positions)}")
    print(f"    true best's coarse rank (worst) : {max(positions)}")
    print(f"    true best reached the refine cut: {admitted}/12")
    print(f"    => if it always reaches the cut, the {159} unrefined cannot")
    print(f"       contain a candidate better than the reported champion.")

    print()
    print("=== the real end-to-end outcome ===")
    hits = 0
    losses = []
    missing = 0
    trials = 12
    for t in range(trials):
        land = Landscape(seed=1000 + t * 7)
        rk = land.true_ranking()
        best_i = rk[0][1]
        res = run_search(land)
        champ = res.best["memory_ids"][0]
        refined = [c["state"]["memory_ids"][0] for c in res.candidates]
        if champ == best_i:
            hits += 1
        if best_i not in refined:
            missing += 1
        true_champ = dict((i, v) for v, i in rk)[champ]
        losses.append((rk[0][0] - true_champ) / rk[0][0] * 100)
    print(f"    trials                          : {trials}")
    print(f"    found the true best             : {hits}/{trials}"
          f"  ({hits / trials * 100:.0f}%)")
    print(f"    true best was never refined     : {missing}/{trials}")
    print(f"    median shortfall vs best        : {statistics.median(losses):.3f}%")
    print(f"    worst shortfall                 : {max(losses):.3f}%")
    print(f"    shortfall if the screen had been perfect: 0.000%")

    print()
    print("=== does more budget fix it? ===")
    for budget in (828, 1650, 3300):
        land = Landscape()
        res = run_search(land, budget=budget)
        rk = land.true_ranking()
        champ = res.best["memory_ids"][0]
        true_champ = dict((i, v) for v, i in rk)[champ]
        loss = (rk[0][0] - true_champ) / rk[0][0] * 100
        print(f"    budget {budget:5d}: refined {len(res.candidates):3d}/210"
              f"  champion shortfall {loss:6.3f}%"
              f"  {'FOUND BEST' if champ == rk[0][1] else ''}")


if __name__ == "__main__":
    main()
