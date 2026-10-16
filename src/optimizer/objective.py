"""The ranking objective shared by every V3.2 stage.

The ported algorithm ranks on the sample mean everywhere. This module introduces one
indirection so a second objective can be selected WITHOUT perturbing the first:

    rank_key(samples, "mean") == statistics.mean(samples)      exactly

That equality is the whole safety property. The ported code is being adopted because
other users have validated its behaviour, so the mean path must remain numerically
identical -- not "close", identical. Roll5 is then added alongside it, and only the
call sites that RANK candidates consult this module.

Why Roll5 needs more than a mean
--------------------------------
``roll5`` is the expected best of five daily attempts. For a normal-ish score it has a
closed form in the sample mean and standard deviation,

    E[max of 5] = mean + C5 * sd / c4(n)

so it is a statistic over the WHOLE sample set, not a per-sample value. That has a
consequence the ranking sites must respect: a per-seed difference cannot be turned into
a Roll5 difference, because Roll5 depends on the spread across seeds and not just their
level. Anywhere the ported code compares two candidates seed-by-seed it must therefore
compare Roll5 estimates whose uncertainty is obtained by resampling the shared seeds --
which is what :func:`paired_gap` does, and why it exists rather than reusing the
per-seed standard error.
"""

import math
import random
import statistics

OBJECTIVE_MEAN = "mean"
OBJECTIVE_ROLL5 = "roll5"
OBJECTIVE_FLOOR = "floor"
OBJECTIVES = (OBJECTIVE_MEAN, OBJECTIVE_ROLL5, OBJECTIVE_FLOOR)

OBJECTIVE_LABELS = {
    OBJECTIVE_MEAN: "均值（稳定）",
    OBJECTIVE_ROLL5: "当日最高 Roll5",
    OBJECTIVE_FLOOR: "保底（最差 10%）",
}

# Objectives whose value is NOT a per-sample quantity. The mean of a difference is
# the difference of the means, so a per-seed difference carries MEAN exactly. Roll5
# reads the spread across seeds and the floor reads their minimum, so neither can be
# carried that way -- their paired comparisons must resample the shared seeds.
NONLINEAR_OBJECTIVES = (OBJECTIVE_ROLL5, OBJECTIVE_FLOOR)


def needs_resampling(objective):
    """True when a paired comparison must resample rather than difference per seed."""
    return objective in NONLINEAR_OBJECTIVES

# Expected max of five standard draws: E[max of 5] = C5 * sigma for a normal.
C5 = 1.162964


def c4(n):
    """Unbiased-standard-deviation correction for a sample of ``n``.

    A sample standard deviation underestimates sigma; dividing by c4(n) removes the
    bias. Without it the Roll5 estimate is systematically low, by about 12% at n=2.
    """
    if n < 2:
        return 1.0
    return math.sqrt(2.0 / (n - 1)) * math.exp(
        math.lgamma(n / 2.0) - math.lgamma((n - 1) / 2.0))


def roll5(samples):
    """The objective's value for a sample set, from mean and spread.

    Falls back to the mean with fewer than two samples, where no spread exists.
    """
    if not samples:
        return 0.0
    if len(samples) < 2:
        return float(samples[0])
    return statistics.mean(samples) + C5 * statistics.stdev(samples) / c4(len(samples))


# The floor objective reads the 10th percentile rather than the sample minimum.
# Measured estimator variance, relative to the mean, on n-seed cohorts (200k
# cohorts, CV=10%):
#
#     n     min     10% quantile
#     128   22.5x   2.81x
#     256   39.5x   2.87x
#     1024  126.5x  2.91x
#
# Two reasons the minimum is the wrong statistic:
#   * its variance falls only like 1/ln(n) -- measured, var(128)/var(1024) = 1.42x
#     where 1/n would give 8x -- so no reachable seed budget makes it precise;
#   * it is not a consistent estimator of anything fixed: as n grows it estimates a
#     more extreme quantile, so the estimate keeps drifting to the worst case ever.
# The 10th percentile converges like 1/n (measured 7.41x over the same range) and is
# only ~2.8x noisier than the mean, which a bounded seed ladder can actually supply.
FLOOR_QUANTILE = 0.10


def quantile(samples, p):
    """Linear-interpolation quantile -- the numpy/type-7 definition.

    Spelled out here rather than imported so the optimizer keeps its existing
    dependency set (math/random/statistics only) and so the interpolation rule is
    explicit: with n samples the position is ``p*(n-1)``, interpolated between the
    two neighbours. At small n this sits near the minimum (conservative), and it
    converges to the true p-quantile as n grows.
    """
    xs = sorted(float(s) for s in samples)
    n = len(xs)
    if n == 0:
        return 0.0
    if n == 1:
        return xs[0]
    position = p * (n - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return xs[lower]
    fraction = position - lower
    return xs[lower] + fraction * (xs[upper] - xs[lower])


def floor(samples):
    """The floor objective: the 10th-percentile score of the sample set.

    Used where EVERY battle is real and counts -- a circle stage, unlike the tactical
    exercise's five daily attempts -- so the guarantee matters more than the upside.
    Raising this raises the worst tenth of outcomes, which is a quantity more samples
    genuinely sharpen (see ``FLOOR_QUANTILE``).
    """
    if not samples:
        return 0.0
    return quantile(samples, FLOOR_QUANTILE)


def rank_key(samples, objective=OBJECTIVE_MEAN):
    """The value candidates are ranked by.

    For ``mean`` this is ``statistics.mean`` itself -- same call, same result -- so
    the ported algorithm's ordering is untouched. The other objectives add their own
    statistic on top of the same sample set.
    """
    if not samples:
        return 0.0
    if objective == OBJECTIVE_ROLL5:
        return roll5(samples)
    if objective == OBJECTIVE_FLOOR:
        return floor(samples)
    return statistics.mean(samples)


def summarise(samples, objective=OBJECTIVE_MEAN):
    """The reported statistics for one candidate."""
    if not samples:
        return dict(n=0, mean=0.0, sd=0.0, cv=0.0, min=0.0, max=0.0,
                    roll5=0.0, floor=0.0, rank=0.0, objective=objective, samples=[])
    n = len(samples)
    mean = statistics.mean(samples)
    sd = statistics.stdev(samples) if n > 1 else 0.0
    return dict(
        n=n,
        mean=mean,
        sd=sd,
        cv=(sd / mean * 100.0) if mean else 0.0,
        min=min(samples),
        max=max(samples),
        roll5=roll5(samples) if n > 1 else mean,
        floor=quantile(samples, FLOOR_QUANTILE),
        rank=rank_key(samples, objective),
        objective=objective,
        samples=list(samples),
    )


def paired_gap(leader, candidate, objective=OBJECTIVE_MEAN, iterations=200,
               seed=12345):
    """The leader-minus-candidate gap, with a standard error, on the SAME seeds.

    For ``mean`` this reproduces the ported behaviour exactly: the gap is the mean of
    the per-seed differences and the error is its standard error, because the mean of a
    difference is the difference of the means.

    For ``roll5`` that identity does NOT hold -- Roll5 reads the spread, so a per-seed
    difference says nothing about the difference of Roll5 values. Instead the shared
    seeds are resampled with replacement and both candidates' Roll5 recomputed on each
    resample; the spread of those differences is the error. Resampling the PAIRED seeds
    (rather than the two candidates independently) keeps the common-seed correlation,
    which is what makes the comparison sharp.

    Returns ``(gap, standard_error, n)``; the error is ``None`` when it cannot be
    estimated, so a caller can fall back rather than treat it as zero.
    """
    n = min(len(leader), len(candidate))
    if n < 2:
        return None, None, n

    if not needs_resampling(objective):
        diffs = [a - b for a, b in zip(leader, candidate)]
        gap = statistics.mean(diffs)
        return gap, statistics.stdev(diffs) / math.sqrt(n), n

    gap = rank_key(leader[:n], objective) - rank_key(candidate[:n], objective)
    if iterations <= 0:
        return gap, None, n
    rng = random.Random(seed)
    draws = []
    for _ in range(iterations):
        picks = [rng.randrange(n) for _ in range(n)]
        left = [leader[i] for i in picks]
        right = [candidate[i] for i in picks]
        draws.append(rank_key(left, objective) - rank_key(right, objective))
    if len(draws) < 2:
        return gap, None, n
    return gap, statistics.stdev(draws), n


def relative_gap(leader, candidate, objective=OBJECTIVE_MEAN):
    """The gap as a fraction of the leader, matching the ported percentage rule."""
    lead = rank_key(leader, objective)
    if not lead:
        return 0.0
    return (lead - rank_key(candidate, objective)) / lead


def resolution_seeds(samples_a, samples_b, objective=OBJECTIVE_MEAN,
                     target_p=0.05):
    """Seeds needed for the A-vs-B gap to become decisive.

    Answers "is this ranking resolvable at all?". When the answer is in the thousands,
    the honest report is that the two are tied rather than that more runs would settle
    it. Used for diagnostics, not for a promotion decision.
    """
    gap, se, n = paired_gap(samples_a, samples_b, objective, iterations=0)
    if gap is None or not se:
        return None
    if gap == 0:
        return None
    return int(math.ceil((1.96 * se / abs(gap)) ** 2 * n))


