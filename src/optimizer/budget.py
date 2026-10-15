"""Battle-budget planning: how many battles a search should be given.

Why this exists
---------------
The budget used to be a bare number the user had to guess, and the number meant
nothing without knowing the space. Two things are computed here instead:

* **What a search costs**, from the shape of the space and the objective. A
  high-variance objective (best-of-five) needs more seeds per candidate than a
  mean, so the same space costs more, and that is reflected rather than assumed.
* **How much of the space a budget can actually cover.** Sampling n candidates
  from a space of N leaves the best found candidate at roughly the 1/(n+1)
  quantile. Saying that out loud is the honest way to present a sampling search:
  a huge discrete space cannot be searched exhaustively, and a budget that hides
  that fact just produces a confident-looking answer built on a thin sample.

The estimator is deliberately conservative about *coverage* and generous about
*refinement*: a coarse screen only has to be good enough not to throw away the
winner, so its seeds are few, while the candidates that reach the final ranking
need enough seeds for the variance estimate to mean something.
"""

import math

from src.optimizer import objective as obj

# If the space is no larger than this, the whole space is screened -- exhaustive
# is strictly better than sampling when it is affordable.
COVER_LIMIT = 3000

# Screen samples when the space is larger than COVER_LIMIT. Each draw is cheap
# (coarse_seeds battles), and more draws put the best found candidate closer to
# the true best.
SCREEN_SAMPLES = 3000

# How many screened candidates get a full seed cohort. The screen's ranking is
# noisy on purpose, so the survivors are re-measured rather than trusted.
REFINE_COUNT = 40

# How much of the refine cost to reserve for the adaptive re-sampling of
# candidates whose spread is still uncertain.
BOOST_FRACTION = 0.25

EFFORT_FAST = "fast"
EFFORT_STANDARD = "standard"
EFFORT_THOROUGH = "thorough"

EFFORT_LABELS = {
    EFFORT_FAST: "快速",
    EFFORT_STANDARD: "标准",
    EFFORT_THOROUGH: "精细",
}

# Screen-sample counts per effort level. Each must be at least COVER_LIMIT, so
# that a space just past the exhaustive threshold is still screened at least as
# thoroughly as an exhaustive pass would have screened it. Otherwise widening the
# pool would LOWER the plan, which reads as "a bigger space is cheaper".
EFFORT_PLAN = {
    EFFORT_FAST: (COVER_LIMIT, 20),
    EFFORT_STANDARD: (SCREEN_SAMPLES, REFINE_COUNT),
    EFFORT_THOROUGH: (12000, 80),
}


def seeds_for(objective):
    """Return (coarse_seeds, review_seeds) that the objective requires.

    Best-of-five needs a spread, and a spread needs two samples, so a Roll5
    screen cannot be cheaper than two seeds per candidate. The mean needs only a
    location and tolerates one.
    """
    if objective == obj.OBJECTIVE_ROLL5:
        return 2, 8
    return 1, 2


def plan_search(space_total, objective, effort=EFFORT_STANDARD,
                cover_limit=COVER_LIMIT, review_seeds=None):
    """Describe a search: how much of the space is screened and what it costs.

    ``review_seeds`` overrides the objective's default cohort size. The caller
    should pass whatever the run will actually use, so the estimate and the run
    cannot disagree -- an estimate built on 8 seeds beside a run using 2 is off by
    a factor of four in the refine budget, which is how a plausible-looking plan
    produced a result where every "refined" candidate was only two battles deep.

    Returns a dict with the numbers both the estimator and the UI need, so the
    dialog and the search itself cannot disagree about what a budget buys.
    """
    space_total = max(1, int(space_total))
    coarse_seeds, default_review = seeds_for(objective)
    if review_seeds is None:
        review_seeds = default_review
    review_seeds = max(1, int(review_seeds))
    screen_samples, refine_count = EFFORT_PLAN.get(effort, EFFORT_PLAN[EFFORT_STANDARD])

    if space_total <= cover_limit:
        screened = space_total
        exhaustive = True
    else:
        # Never screen fewer than an exhaustive pass would have: the plan has to
        # be monotonic in the space size, or widening the pool would lower the
        # estimate and read as "a bigger search is cheaper".
        screened = max(screen_samples, cover_limit)
        screened = min(screened, space_total)
        exhaustive = screened >= space_total
    refined = min(screened, refine_count)

    coarse_battles = screened * coarse_seeds
    refine_battles = refined * review_seeds
    baseline_battles = review_seeds              # the unchanged lineup, always
    boost_battles = int(refine_battles * BOOST_FRACTION)

    # The expected best-found percentile of a uniform sample of `n` from `N`
    # (without replacement) is 1/(n+1) -- the first order statistic of a uniform.
    coverage = screened / space_total
    expected_best_percentile = 100.0 / (screened + 1)

    return dict(
        space_total=space_total,
        screened=screened,
        refined=refined,
        coarse_seeds=coarse_seeds,
        review_seeds=review_seeds,
        coarse_battles=coarse_battles,
        refine_battles=refine_battles,
        baseline_battles=baseline_battles,
        boost_battles=boost_battles,
        budget=coarse_battles + refine_battles + baseline_battles + boost_battles,
        exhaustive=exhaustive,
        coverage=coverage,
        expected_best_percentile=expected_best_percentile,
        effort=effort,
    )


def estimate_budget(space_total, objective, effort=EFFORT_STANDARD):
    """Battle budget for a search of this space under this objective."""
    return plan_search(space_total, objective, effort=effort)["budget"]


def describe_plan(plan):
    """One-line, honest description of what a budget buys, for the dialog."""
    if plan["exhaustive"]:
        head = f"将完整评估全部 {plan['screened']:,} 个候选"
    else:
        head = (f"将抽样评估 {plan['screened']:,} 个候选"
                f"（占空间 {plan['coverage'] * 100:.4f}%）")
    return (f"{head}，其中前 {plan['refined']} 名做 {plan['review_seeds']} 种子精评；"
            f"预计最优候选位于前 {plan['expected_best_percentile']:.2f}%；"
            f"约需 {plan['budget']:,} 场战斗")


def minimum_budget(space_total, objective):
    """The smallest budget that can still produce one ranked candidate.

    Below this the search cannot complete a single refine cohort, so it would
    report "no candidates" -- better to refuse up front and say why.
    """
    _, review_seeds = seeds_for(objective)
    coarse_seeds, _ = seeds_for(objective)
    return coarse_seeds + review_seeds * 2
