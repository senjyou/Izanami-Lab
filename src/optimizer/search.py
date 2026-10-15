"""The optimizer search: enumerate, coarse-screen, refine, rank.

Pipeline
--------
1. **Enumerate** legal candidates (positions x memories) without running battles.
2. **Coarse screen** every candidate with a single seed. One seed already agrees
   with the full-sample verdict about 90% of the time on measured real lineups,
   because true differences between layouts are large (median ~14%). The screen
   only removes clearly-poor candidates; it is not asked to rank precisely.
3. **Refine** the survivors with a full common-seed cohort (default 8 seeds,
   which is the smallest count whose Roll5 estimate is trustworthy -- one seed
   understates Roll5 by ~12%, eight seeds by ~1.7%).
4. **Rank** by the chosen objective and report.

Why this replaces multi-stage threshold screening
-------------------------------------------------
The previous design screened repeatedly with fixed percentage thresholds. Those
thresholds are wider than the noise they gate (measured: a 3% line against a
+/-5.25% band at 4 seeds), so they mostly removed unlucky candidates; and under a
best-of-5 objective, penalising variance removes the very candidates that win.
Here, seeds are spent only where they change a decision.

Budget
------
Battles are counted exactly: one per evaluation. The coarse pass is capped so the
refine pass always has room. Anything unspent is reported, never silently reused.
"""

import copy
import json
import math
import random
import time

from src.optimizer import objective as obj
from src.optimizer import space as space_mod
from src.optimizer.snapshot import configuration_key

MODE_TACTICAL = "tactical"
MODE_CIRCLE = "circle"


class Stopped(Exception):
    """Raised internally when the user stops the search."""


class SearchSettings:
    """User-facing search options. Deliberately small."""

    def __init__(self, objective=obj.OBJECTIVE_MEAN, budget=1200, seed=2026,
                 change_positions=True, change_memories=True,
                 review_seeds=8, coarse_seeds=1, adaptive_boost=True,
                 max_coarse=None, workers=0):
        self.objective = objective
        self.budget = int(budget)
        self.seed = int(seed)
        self.change_positions = bool(change_positions)
        self.change_memories = bool(change_memories)
        self.review_seeds = int(review_seeds)
        self.coarse_seeds = int(coarse_seeds)
        self.adaptive_boost = bool(adaptive_boost)
        self.max_coarse = max_coarse
        # 0 means automatic: one battle process per logical CPU, which is what the
        # official batch simulator does.
        self.workers = int(workers)
        self.validate()

    def validate(self):
        if self.objective not in obj.OBJECTIVES:
            raise ValueError(f"未知优化目标：{self.objective!r}")
        if self.budget < 1:
            raise ValueError("战斗预算必须是正整数")
        if not 0 <= self.seed <= 2 ** 31 - 1:
            raise ValueError("随机种子须为 0 到 2147483647 之间的整数")
        if self.coarse_seeds < 1:
            raise ValueError("粗筛种子数至少为 1")
        if self.review_seeds < 1:
            raise ValueError("精评种子数至少为 1")
        if self.objective == obj.OBJECTIVE_ROLL5 and self.coarse_seeds < 2:
            raise ValueError(
                "Roll5 目标需要至少 2 个粗筛种子：只有 1 个种子时，波动大的候选"
                "会因为一次运气好或坏就被误筛，而它恰恰是 Roll5 想找的候选")
        if self.objective == obj.OBJECTIVE_ROLL5 and self.review_seeds < 2:
            raise ValueError("Roll5 目标至少需要 2 个精评种子才能估计波动")
        if not self.change_positions and not self.change_memories:
            raise ValueError("至少要选择一个搜索维度（站位或回忆）")
        if self.workers < 0 or self.workers > 64:
            raise ValueError("并行进程数须为 0（自动）或 1-64 之间的整数")

    def seed_list(self, count, offset):
        """Return ``count`` seeds from a named block, for reproducibility."""
        return [self.seed + offset + i for i in range(count)]

    def as_dict(self):
        return dict(objective=self.objective, budget=self.budget, seed=self.seed,
                    change_positions=self.change_positions,
                    change_memories=self.change_memories,
                    review_seeds=self.review_seeds,
                    coarse_seeds=self.coarse_seeds,
                    adaptive_boost=self.adaptive_boost,
                    max_coarse=self.max_coarse, workers=self.workers)


# Seed blocks. Kept far apart so the coarse, refine and boost cohorts never
# overlap, and so a cohort is always internally consistent.
COARSE_OFFSET = 0
REVIEW_OFFSET = 100_000
BOOST_OFFSET = 200_000


class SearchResult:
    """Everything the caller needs to display and apply a result."""

    def __init__(self, settings, mode):
        self.settings = settings
        self.mode = mode
        self.best = None
        self.best_summary = None
        self.baseline = None
        self.baseline_summary = None
        self.candidates = []            # list of dicts, best first
        self.battles = 0
        self.cache_hits = 0
        self.elapsed = 0.0
        self.termination = "未开始"
        self.detail = ""
        self.space = {}
        self.stop_requested = False

    def to_dict(self):
        return dict(
            mode=self.mode, settings=self.settings.as_dict(),
            objective=self.settings.objective,
            best=self.best, best_summary=_plain(self.best_summary),
            baseline=self.baseline, baseline_summary=_plain(self.baseline_summary),
            candidates=[dict({k: v for k, v in c.items() if k != "state"},
                             summary=_plain(c["summary"]))
                        for c in self.candidates],
            battles=self.battles, cache_hits=self.cache_hits,
            elapsed=self.elapsed, termination=self.termination,
            detail=self.detail, space=self.space)


def _plain(summary):
    """Drop raw samples from a summary before serialising."""
    if not summary:
        return None
    return {k: v for k, v in summary.items() if k != "samples"}


class Search:
    """Runs the pipeline against an evaluator.

    ``evaluator`` only needs an ``evaluate(state, seed) -> float`` method, so the
    same search drives the tactical-exercise and circle-battle modes.
    """

    def __init__(self, evaluator, settings, mode=MODE_TACTICAL,
                 stop=None, progress=None, pool=None):
        self.evaluator = evaluator
        self.settings = settings
        self.mode = mode
        self.stop = stop or (lambda: False)
        self.progress = progress or (lambda info: None)
        self.pool = pool                   # parallel battle pool, or None
        self.cache = {}                 # (configuration_key, seed) -> score
        self.battles = 0
        self.cache_hits = 0
        self.rng = random.Random(settings.seed)
        self.result = SearchResult(settings, mode)
        self.started = time.monotonic()

    # ---------------------------------------------------------------- evaluate
    def _evaluate(self, state, seed):
        """Evaluate one (state, seed), reusing a cached score when possible."""
        return self._evaluate_many(state, [seed])[0]

    def _evaluate_many(self, state, seeds):
        return self._evaluate_jobs([(state, list(seeds))], "战斗")[0]

    def _evaluate_jobs(self, jobs, phase="战斗"):
        """Evaluate many (state, seeds) pairs, using the pool when available.

        Returns a list of score lists parallel to ``jobs``. Only uncached battles
        are fought, and results are cached per (configuration, seed), so a seed
        shared between two candidates is never fought twice.

        Dispatch granularity is the BATTLE, not the candidate. Sending one job per
        candidate would hand a whole seed cohort to a single worker, so a search
        with few candidates and many seeds per candidate would run serially no
        matter how many workers were configured. A battle's state pickles in
        ~0.02 ms against a ~250 ms fight, so per-battle dispatch costs ~0.01% and
        keeps every worker busy.
        """
        if not jobs:
            return []

        # Split each job into cached and missing seeds.
        keys = []
        missing = []
        known = []
        for state, seeds in jobs:
            key = configuration_key(state)
            keys.append(key)
            have = {}
            need = []
            for seed in seeds:
                cached = self.cache.get((key, seed))
                if cached is None:
                    need.append(seed)
                else:
                    have[seed] = cached
            missing.append(need)
            known.append(have)
            self.cache_hits += len(have)

        # Flatten every missing battle into one task list, remembering where each
        # belongs so results can be reassembled in submission order.
        tasks = []
        owner = []
        for index in range(len(jobs)):
            if not missing[index]:
                continue
            state = jobs[index][0]
            for seed in missing[index]:
                tasks.append((state, seed))
                owner.append((index, seed))

        if tasks:
            if self.pool is not None:
                flat = self.pool.evaluate_battles(tasks, phase=phase)
            else:
                flat = [float(self.evaluator.evaluate(state, seed))
                        for state, seed in tasks]
            for (index, seed), score in zip(owner, flat):
                self.cache[(keys[index], seed)] = float(score)
                known[index][seed] = float(score)
            self.battles += len(flat)
            if len(flat) < len(tasks):
                # The run was stopped early; the tail was never fought. Leave
                # those seeds absent so callers can tell "not evaluated" from 0.
                self.result.stop_requested = True

        out = []
        for index, (_state, seeds) in enumerate(jobs):
            have = known[index]
            if any(seed not in have for seed in seeds):
                out.append(None)          # incomplete: not evaluated
            else:
                out.append([have[seed] for seed in seeds])
        return out

    # ------------------------------------------------------------------- steps
    def _coarse(self, template, constraints, reserve_for_baseline=0):
        """Step 2: screen candidates cheaply, sampled across the space.

        Sampling matters: candidates are drawn uniformly from the whole space
        rather than taken as a prefix of enumeration order, because a prefix
        would only examine arrangements adjacent to the current one and leave
        most of the space unvisited.

        Ranking the screen matters just as much. Under ROLL5 the screen MUST NOT
        rank on the sample mean alone: with a single seed a volatile candidate is
        scored by one lucky draw, so it lands mid-table and gets cut before it can
        show its best-of-five advantage -- exactly the candidate the objective
        wants. Ranking by the objective's own key fixes that, and is why ROLL5
        requires two coarse seeds (a variance needs two samples).

        BUDGET ACCOUNTING: the cap is converted from battles to candidates by
        dividing by ``coarse_seeds``. Treating a battle budget as a candidate
        count silently overspent it by that factor -- under ROLL5 a 12000-battle
        budget bought 15984 battles, exhausted itself in the screen, and left
        nothing for refinement, so the run reported no candidates at all.
        """
        settings = self.settings
        budget = settings.budget
        review_cost = settings.review_seeds
        coarse_cost = settings.coarse_seeds
        # Leave room to refine at least two candidates plus the baseline cohort,
        # so the coarse pass can never consume the budget the later steps need.
        # The reserve is expressed in BATTLES, and the cap is then converted into
        # a candidate count, so the two units cannot drift apart again.
        reserve = max(review_cost * 2, budget // 3) + reserve_for_baseline
        affordable_battles = max(coarse_cost, budget - reserve)
        coarse_cap = max(1, affordable_battles // coarse_cost)
        if settings.max_coarse is not None:
            coarse_cap = min(coarse_cap, max(1, int(settings.max_coarse)))

        plan = space_mod.space_plan(template, constraints, settings, self.rng)
        seed = settings.seed_list(coarse_cost, COARSE_OFFSET)

        # Build the whole batch first, then evaluate it in ONE dispatch. Submitting
        # candidates one at a time would leave the pool idle between round trips,
        # which is what made the serial version feel slow.
        batch = []
        seen = set()
        for state, arrangement, memory_set in plan.iter_states(coarse_cap):
            key = configuration_key(state)
            if key in seen:
                continue                     # same battle twice; skip
            seen.add(key)
            batch.append((key, state, arrangement, memory_set))
        if not batch:
            return []

        jobs = [(item[1], seed) for item in batch]
        results = self._evaluate_jobs(jobs, phase="粗筛")
        if self.stop():
            self.result.stop_requested = True

        screened = []
        total = min(coarse_cap, plan.total)
        for (key, state, arrangement, memory_set), scores in zip(batch, results):
            if scores is None:               # skipped by an early stop
                continue
            mean = sum(scores) / len(scores)
            screened.append(dict(key=key, state=state, arrangement=arrangement,
                                 memory_set=memory_set, coarse_mean=mean,
                                 coarse_rank=obj.rank_key(scores, settings.objective),
                                 coarse_scores=scores))
            self.progress(dict(phase="粗筛", done=len(screened), total=total,
                               battles=self.battles))
        return screened

    def _refine(self, screened, reserve_for_baseline=0):
        """Steps 3-4: full common-seed cohorts for the coarse leaders."""
        settings = self.settings
        if not screened:
            return []
        # Order by the objective's own key, so a candidate that looks good on
        # best-of-five is not cut for looking merely average on one seed.
        screened.sort(key=lambda row: -row["coarse_rank"])
        seeds = settings.seed_list(settings.review_seeds, REVIEW_OFFSET)

        # Admit whole cohorts only: a candidate whose full seed group does not fit
        # in the remaining budget is left out rather than ranked on a partial one.
        affordable = []
        spent = 0
        for row in screened:
            cost = _missing(self.cache, row["key"], seeds)
            if self.battles + spent + cost > settings.budget - reserve_for_baseline:
                break
            affordable.append(row)
            spent += cost

        # A shortfall is NORMAL when sampling, not a failure: the screen always
        # covers more candidates than the budget can refine, so "some were left
        # out" is the expected outcome of every successful run. Reporting it as
        # 预算不足 made a run that ranked hundreds of candidates look like a
        # failure. The distinction that matters is whether ANYTHING was ranked.
        skipped = len(screened) - len(affordable)
        if not affordable:
            self.result.termination = "预算不足"
            self.result.detail = (f"预算不足以完成任何一个完整 "
                                  f"{settings.review_seeds} 种子精评；"
                                  f"请提高预算或缩小卡池")
            return []
        if skipped:
            self.result.detail = (f"粗筛 {len(screened)} 个候选，"
                                  f"预算可精评 {len(affordable)} 个"
                                  f"（另有 {skipped} 个未精评）")
        return self._refine_admitted(affordable, seeds)

    def _refine_admitted(self, affordable, seeds):
        """Fight the full seed cohort for each admitted candidate."""
        jobs = [(row["state"], seeds) for row in affordable]
        results = self._evaluate_jobs(jobs, phase="精评")
        if self.stop():
            self.result.stop_requested = True

        refined = []
        for row, scores in zip(affordable, results):
            if scores is None:               # skipped by an early stop
                continue
            summary = obj.summarise(scores, self.settings.objective)
            refined.append(dict(row, scores=scores, summary=summary))
            self.progress(dict(phase="精评", done=len(refined),
                               total=len(affordable), battles=self.battles,
                               best=summary["rank"]))
        return refined

    def _boost(self, refined):
        """Optional: extra seeds for candidates whose spread is still uncertain."""
        settings = self.settings
        if not settings.adaptive_boost:
            return refined
        boosted_seeds = settings.seed_list(
            max(settings.review_seeds * 2, settings.review_seeds + 8), BOOST_OFFSET)

        # Select all candidates that need more seeds and can afford them, then
        # fight them in one batch rather than one candidate at a time.
        chosen = []
        spent = 0
        for row in refined:
            if not obj.needs_boost(row["summary"]):
                continue
            cost = _missing(self.cache, row["key"], boosted_seeds)
            if self.battles + spent + cost > settings.budget:
                continue                     # skip; existing data stands
            chosen.append(row)
            spent += cost
        if not chosen:
            return refined

        jobs = [(row["state"], boosted_seeds) for row in chosen]
        results = self._evaluate_jobs(jobs, phase="追加采样")
        if self.stop():
            self.result.stop_requested = True

        for row, extra in zip(chosen, results):
            if extra is None:                # skipped by an early stop
                continue
            combined = list(dict.fromkeys(row["scores"] + extra))
            # Recompute on the union so repeated seeds cannot be double counted.
            row["scores"] = combined
            row["summary"] = obj.summarise(combined, settings.objective)
        self.progress(dict(phase="追加采样", battles=self.battles))
        return refined

    # -------------------------------------------------------------------- run
    def run(self, template, constraints, baseline_state):
        """Execute the pipeline. Returns the populated :class:`SearchResult`."""
        result = self.result
        try:
            position_count, memory_count, combined = space_mod.space_size(
                template, constraints, self.settings)
            result.space = dict(positions=position_count, memories=memory_count,
                                combined=combined)

            baseline_key = configuration_key(baseline_state)
            # Reserve the baseline's own cohort up front. Evaluating it only as
            # an afterthought meant a tight budget could be spent entirely on
            # other candidates and then find nothing left, leaving the user
            # unable to tell whether optimizing actually helped.
            baseline_seeds = self.settings.seed_list(self.settings.review_seeds,
                                                     REVIEW_OFFSET)
            baseline_cost = _missing(self.cache, baseline_key, baseline_seeds)

            screened = self._coarse(template, constraints,
                                    reserve_for_baseline=baseline_cost)
            refined = self._refine(screened, reserve_for_baseline=baseline_cost)
            refined = self._boost(refined)

            # The unchanged lineup must always be represented.
            if not any(r["key"] == baseline_key for r in refined):
                cost = _missing(self.cache, baseline_key, baseline_seeds)
                if self.battles + cost <= self.settings.budget:
                    scores = self._evaluate_many(baseline_state, baseline_seeds)
                    if scores is not None:    # None means an early stop
                        summary = obj.summarise(scores, self.settings.objective)
                        refined.append(dict(key=baseline_key, state=baseline_state,
                                            arrangement=tuple(baseline_state["friend_positions"]),
                                            memory_set=tuple(sorted(baseline_state["memory_ids"])),
                                            coarse_mean=sum(scores) / len(scores),
                                            coarse_rank=summary["rank"],
                                            coarse_scores=list(scores), scores=scores,
                                            summary=summary))

            refined.sort(key=lambda row: -row["summary"]["rank"])
            result.candidates = [
                dict(rank=i + 1, key=row["key"], state=row["state"],
                     arrangement=list(row["arrangement"]),
                     memory_ids=list(row["memory_set"]),
                     summary=row["summary"],
                     is_baseline=(row["key"] == baseline_key))
                for i, row in enumerate(refined)]
            for row in result.candidates:
                if row["is_baseline"]:
                    result.baseline = row["state"]
                    result.baseline_summary = row["summary"]
                    break
            if result.candidates and result.best is None:
                result.best = result.candidates[0]["state"]
                result.best_summary = result.candidates[0]["summary"]

            # A user stop takes priority over a budget shortfall: the user asked
            # for the run to end, and that is the more useful thing to report.
            # Reporting "预算不足" for a deliberate stop would be misleading.
            #
            # Otherwise the run succeeded whenever anything was ranked, even if
            # the budget ran out partway through the refine pass: sampling always
            # screens more candidates than the budget can refine, so a shortfall
            # is the normal outcome and not a failure. Only an empty result is.
            if result.stop_requested:
                result.termination = "用户停止"
                result.detail = "保留已完成完整种子组的候选"
            elif not refined:
                result.termination = "无可用候选"
                result.detail = (result.detail
                                 or "没有候选获得完整的精评种子组")
            else:
                result.termination = "完成"
                if len(refined) < len(screened):
                    result.detail = (f"粗筛 {len(screened)} 个候选，"
                                     f"精评 {len(refined)} 个"
                                     f"（其余 {len(screened) - len(refined)} 个"
                                     f"受预算限制未精评）")
                else:
                    result.detail = (f"粗筛 {len(screened)} 个候选，"
                                     f"精评 {len(refined)} 个")
        except Stopped:
            result.termination = "用户停止"
        except Exception as exc:                       # surface, do not mask
            result.termination = "出错"
            result.detail = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            result.battles = self.battles
            result.cache_hits = self.cache_hits
            result.elapsed = time.monotonic() - self.started
        return result


def _missing(cache, key, seeds):
    """How many of these seeds are not yet cached (each costs one battle)."""
    return sum(1 for seed in seeds if (key, seed) not in cache)


def run_search(evaluator, template, constraints, settings,
               mode=MODE_TACTICAL, stop=None, progress=None,
               baseline_state=None, pool=None):
    """Convenience wrapper: build a :class:`Search` and run it once."""
    search = Search(evaluator, settings, mode=mode, stop=stop, progress=progress,
                    pool=pool)
    baseline_state = baseline_state or template
    return search.run(template, constraints, baseline_state)
