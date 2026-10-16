"""Budgeted joint-neighborhood search with restarts and common-seed reevaluation."""
import copy
import math
import logging
import random
import statistics
import time
import os
from dataclasses import asdict, dataclass, replace

from src.optimizer import objective as obj
from src.optimizer.memory_search import MemorySpace, run_memory_search
from src.optimizer.scheduling import combination_start, diverse_elites, members, plan_combinations

from src.optimizer.model import (AFFIXES, AffixValidationError, active_snapshot, configuration_key,
                                 diagnostic_configuration_id, initialize_character,
                                 prepare_search_snapshot, record_diagnostic,
                                 validate_constraints, validate_snapshot, write_json)

LOG = logging.getLogger("izanami.optimizer")


@dataclass
class SearchSettings:
    budget: int = 200
    seed: int = 2026
    search_seeds: int = 2
    validation_seeds: int = 10
    # Which objective every stage ranks by. "mean" preserves the ported behaviour
    # exactly -- rank_key returns statistics.mean itself -- so the validated V3.2
    # ordering is untouched. "roll5" adds the expected-best-of-five uplift.
    objective: str = "mean"
    automatic: bool = True
    change_fifth: bool = False
    change_positions: bool = False
    change_memories: bool = False
    change_affixes: bool = True
    dynamic_speed: bool = True
    speed_dependent: bool = True
    special_actions: bool = True
    progress_interval: float = .5
    memory_exhaustive_limit: int = 500
    battle_workers: int = 2
    search_kind: str = "legacy"  # old files retain their V2.4 dispatch until explicitly migrated
    layered_filter: bool = True
    layered_memory_pruning: bool = False  # Opt-in; old settings retain V2.9.1 enumeration.
    layered_drop_percent: int = 10
    layered_base_seeds: int = 2
    layered_max_seeds: int = 4
    layered_joint_seeds: int = 1
    layered_review_percent: int = 10
    review_strategy: str = 'quick'
    quick_max_seeds: int = 128
    layered_quick_four_drop_percent: int = 3
    layered_quick_eight_drop_percent: int = 3
    layered_quick_final_drop_percent: int = 5
    layered_quick_top_count: int = 12
    layered_quick_rank_limit: int = 60

    def validate(self):
        if self.objective not in ("mean", "roll5", "floor"):
            raise ValueError("优化目标须为均值、当日最高 Roll5 或保底（最低分）")
        if type(self.layered_memory_pruning) is not bool:
            raise ValueError('无效回忆剪枝开关须为布尔值')
        for key in ('layered_quick_four_drop_percent','layered_quick_eight_drop_percent','layered_quick_final_drop_percent'):
            if type(getattr(self,key)) is not int or not 0<=getattr(self,key)<=30:
                raise ValueError('分层快速预选允许落后须为0–30%的整数')
        for key in ('layered_quick_top_count','layered_quick_rank_limit'):
            if type(getattr(self,key)) is not int or not 1<=getattr(self,key)<=720:
                raise ValueError('分层快速预选参考名次与晋级名次须为1–720')
        if self.review_strategy not in ('quick','rigorous'):
            raise ValueError('复评方式须为快速或严谨')
        if type(self.quick_max_seeds) is not int or self.quick_max_seeds not in (64,128,256):
            raise ValueError('快速复评最多共同种子数须为64、128或256')
        if self.search_kind not in ("legacy", "memory", "positions", "joint", "layered"):
            raise ValueError("未知优化模式")
        if self.automatic and self.search_kind in ("memory", "positions"):
            expected = (False, self.search_kind == "positions", self.search_kind == "memory", False)
            if (self.change_fifth, self.change_positions, self.change_memories, self.change_affixes) != expected:
                raise ValueError("独立回忆/站位模式必须固定其他搜索维度；请重新选择模式")
        if self.automatic and self.search_kind == 'layered':
            if (self.change_fifth,self.change_positions,self.change_memories,self.change_affixes)!=(False,True,True,False):
                raise ValueError('分层联合模式只调整站位和回忆，必须固定角色与词条')
        if (type(self.layered_filter) is not bool or type(self.layered_drop_percent) is not int
                or not 0 <= self.layered_drop_percent <= 30):
            raise ValueError('裸装允许落后幅度须为0–30%的整数')
        if (type(self.layered_base_seeds) is not int or type(self.layered_max_seeds) is not int
                or not 2 <= self.layered_base_seeds <= self.layered_max_seeds <= 20):
            raise ValueError('裸装基础至少2种子，最大种子数须在基础数量至20之间')
        if type(self.layered_joint_seeds) is not int or not 1<=self.layered_joint_seeds<=20:
            raise ValueError('联合基础共同种子数须为1–20')
        if type(self.layered_review_percent) is not int or not 1<=self.layered_review_percent<=100:
            raise ValueError('联合统计复评入围比例须为1–100%')
        if type(self.battle_workers) is not int or self.battle_workers not in (0, 1, 2, 3, 4, 6, 8):
            raise ValueError("并行战斗进程数须为自动、1、2、3、4、6或8")
        if not isinstance(self.seed, int) or not 0 <= self.seed <= 2**31 - 1:
            raise ValueError("随机种子须为0到2147483647之间的整数")
        if not 1 <= self.search_seeds <= 20 or not 2 <= self.validation_seeds <= 100:
            raise ValueError("搜索种子数应为1–20，复评种子数应为2–100")
        if not isinstance(self.budget, int) or self.budget < 1:
            raise ValueError("模拟预算须为正整数；小预算将减少覆盖与复评")
        if not isinstance(self.memory_exhaustive_limit, int) or not 0 <= self.memory_exhaustive_limit <= 10000:
            raise ValueError("回忆穷举上限应为0–10000（0关闭）")
        if not math.isfinite(self.progress_interval) or self.progress_interval < 0:
            raise ValueError("进度间隔须为非负有限数")


def mutate(state, constraints, settings, rng, restart=False, *, loader=None, diagnostics=None):
    """Produces legal joint moves, including simultaneous changes across characters."""
    out = copy.deepcopy(state)
    positions = out["friend_positions"]
    operation = "扰动重启/多词条联合修改" if restart else "合法邻域/多词条联合修改"
    replacement = None
    if settings.change_fifth and (restart or rng.random() < .3):
        required = {int(c) for c, mark in constraints["characters"].items() if mark == "必选"}
        unlocked = [i for i, c in enumerate(positions) if c is not None and c not in required]
        candidates = [int(c) for c in constraints["characters"] if int(c) not in positions]
        if unlocked and candidates:
            slot, replacement = rng.choice(unlocked), rng.choice(candidates)
            previous = positions[slot]
            initialize_character(out, replacement, loader, diagnostics,
                                 operation=operation + "/第五人替换", fifth_replacement=True, optimize_affixes=settings.change_affixes)
            positions[slot] = replacement
            record_diagnostic(diagnostics, action="第五人替换", operation=operation,
                              character_id=replacement, replaced_character_id=previous,
                              module_number=None, actual_affixes=None, fifth_replacement=True,
                              configuration_id=diagnostic_configuration_id(out))
    if settings.change_affixes:
        chars = [c for c in out["friend_positions"] if c is not None]
        cells = [(str(c), m) for c in chars for m in range(3)]
        count = rng.randint(2, 7) if restart else rng.choice((1, 1, 2, 2, 3, 4))
        for cid, mi in rng.sample(cells, min(count, len(cells))):
            module = out["panel"]["modules"][cid][mi]
            old = module["gear_effects"]
            if restart or rng.random() < .35:
                types = rng.sample(list(AFFIXES), 3)
                module["gear_effects"] = [
                    {"effect_type": typ, "value": rng.choice(AFFIXES[typ])[1]} for typ in types]
            else:
                slot = rng.randrange(3)
                used = {g["effect_type"] for i, g in enumerate(old) if i != slot}
                choices = [(typ, value) for typ in AFFIXES if typ not in used
                           for _, value in AFFIXES[typ]
                           if (typ, value) != (old[slot]["effect_type"], old[slot]["value"])]
                typ, value = rng.choice(choices)
                old[slot] = {"effect_type": typ, "value": value}
    if settings.change_positions and (restart or rng.random() < .3):
        a, b = rng.sample(range(6), 2)
        positions[a], positions[b] = positions[b], positions[a]
    if settings.change_memories and (restart or rng.random() < .3):
        required = {int(m) for m, mark in constraints["memories"].items() if mark == "必选"}
        unlocked = [i for i, m in enumerate(out["memory_ids"]) if m not in required]
        candidates = [int(m) for m in constraints["memories"] if int(m) not in out["memory_ids"]]
        if unlocked and candidates:
            out["memory_ids"][rng.choice(unlocked)] = rng.choice(candidates)
    try:
        validate_snapshot(out, affixes=settings.change_affixes)
    except AffixValidationError as exc:
        record_diagnostic(diagnostics, action="修复生成候选", operation=operation,
                          fifth_replacement=replacement is not None, **exc.details)
        # Repair only affixes. Malformed fixed data or engine errors still propagate.
        for cid in out["friend_positions"]:
            if cid is not None:
                initialize_character(out, cid, loader, diagnostics, operation=operation,
                                     fifth_replacement=replacement is not None, optimize_affixes=settings.change_affixes)
        validate_snapshot(out, affixes=settings.change_affixes)
    validate_constraints(out, constraints)
    out["memory_ids"] = sorted(out["memory_ids"])
    return out


class Stopped(Exception):
    pass


class BudgetedSearch:
    def __init__(self, evaluator, original, constraints, settings, stop=None, progress=None, output=None, heartbeat=None):
        self.evaluator, self.original = evaluator, copy.deepcopy(original)
        self.constraints, self.settings = copy.deepcopy(constraints), settings
        self.stop = stop or (lambda: False)
        self.progress = progress or (lambda result: None)
        self.progress_heartbeat=heartbeat
        self.output = output
        self.cache, self.elite = {}, {}
        self.done, self.cache_hits, self.attempts, self.restarts = 0, 0, 0, 0
        self.started = time.monotonic()
        from src.optimizer.performance import PerformanceLedger
        self.performance=PerformanceLedger()
        self.best = copy.deepcopy(original)
        self.search_start = None
        self.initialization_notes, self.candidate_diagnostics = [], []
        self.evaluated_character_sets = set()
        self.current_operation = "初始化"
        self.baseline_satisfies_constraints = False
        self.best_search = self.baseline_search = self.baseline_mean = self.best_mean = None
        self.best_validation_count = 0
        self.baseline_validation_seeds = []
        self.search_seed_list = [settings.seed + i for i in range(settings.search_seeds)]
        self.validation_seed_list = [settings.seed + 100000 + i for i in range(settings.validation_seeds)]
        self.rng = random.Random(settings.seed)
        self.reports_emitted = 0
        self._last_report_time, self._last_phase = -math.inf, None
        self._speed_key, self._speed_preview = None, ("尚未构建", ())
        self.duplicate_candidates = 0
        self.budget_phase = "baseline"
        self.phase_simulations = dict.fromkeys(("baseline", "basic", "refinement", "validation", "independent"), 0)
        self.combination_total, self.combination_stats = 1, {}
        self.budget_plan = {"total": settings.budget, "policy": "尚在初始化；未分配组合基础预算"}
        self._configuration_keys = set()
        self.search_mode = "启发式搜索"
        self.termination_reason = self.termination_detail = None
        self.memory_total = self.memory_set_total = None
        self.memory_covered = 0
        self.memory_order_policy = "无序集合（共享回忆不依赖槽位）"
        self.memory_order_reason = "游戏规则：共享回忆效果与槽位无关；评价边界统一按ID排序"
        self.memory_evaluations, self.memory_rounds = [], []
        self.position_total, self.position_covered = None, 0
        self.position_evaluations, self.position_constraints = [], {}
        self.evaluation_requests = self.seed_evaluation_requests = 0
        self.ignored_seed_repetitions = self.duplicate_cache_pairs_skipped = 0
        self.stagnant_teams = set()
        self._duplicate_streaks = {}
        self.stage_progress={}
        self._heartbeat_at=-math.inf
        if hasattr(evaluator,"progress_callback"):evaluator.progress_callback=self.heartbeat
        self.evaluation_limit = settings.budget
        self.cross_cohorts = os.environ.get('IZANAMI_OPTIMIZER_COHORTS','1') != '0'
        self.statistical_review = None
        self.independent_validation = None
        self.search_champion = None
        self.search_champion_score = None
        self.search_champion_seeds = []

    @property
    def budget_phase(self):return self._budget_phase

    @budget_phase.setter
    def budget_phase(self,value):
        self._budget_phase=value
        self.performance.phase(value)
        if hasattr(self.evaluator,'current_phase'):self.evaluator.current_phase=value

    def heartbeat(self,force=False):
        if self.progress_heartbeat is None:return
        now=time.monotonic()
        if not force and now-self._heartbeat_at<max(.1,self.settings.progress_interval):return
        self._heartbeat_at=now
        stats=getattr(self.evaluator,'stats',{})
        done=max(self.done,stats.get('completed_battles',0))
        stage=dict(self.stage_progress)
        stage['completed_samples']=max(0,done-stage.get('started_at_simulations',done))
        payload=dict(progress_only=True,phase=stage.get('label','正在搜索'),stage_progress=stage,
                     simulations=done,budget_spent=self._budget_spent(),unused_budget=self.settings.budget-self._budget_spent(),
                     elapsed=now-self.started,simulations_per_second=done/max(now-self.started,.001),
                     settings={'budget':self.settings.budget},search_mode=self.search_mode,
                     memory_total=self.memory_total,memory_covered=self.memory_covered,
                     unique_configurations=len(self._configuration_keys),cache_hits=self.cache_hits,
                     in_flight_tasks=stats.get('in_flight_tasks',0),running_tasks=stats.get('running_tasks',0),
                     dispatched_not_started_tasks=stats.get('dispatched_not_started_tasks',0),pending_batch_tasks=stats.get('pending_batch_tasks',0))
        if self.position_total is not None:
            payload.update(position_total=self.position_total, position_covered=self.position_covered)
        if hasattr(self,'layered_run'):payload.update(self.layered_run.report_fields(False,heartbeat=True))
        with self.performance.measure('progress_publish_seconds'):self.progress_heartbeat(payload)

    def begin_stage(self,label,total,planned_samples=0,round_index=None):
        self.stage_progress=dict(label=label,candidate_total=total,completed_candidates=0,
                                 planned_samples=planned_samples,started_at_simulations=max(self.done,getattr(self.evaluator,'stats',{}).get('completed_battles',0)),
                                 round_index=round_index)
        self.heartbeat(force=True)

    def _budget_spent(self):
        stats=getattr(self.evaluator,'stats',{})
        # A failed/unknown task cannot be silently reused as unspent budget.
        return max(self.done,stats.get('submitted_tasks',stats.get('completed_battles',0)+stats.get('failed_tasks',0)))

    def _key(self, state):
        return configuration_key(state)

    def finish(self, reason, detail, stopped=False):
        self.termination_reason, self.termination_detail = reason, detail
        phase = f"已停止（{reason}）；{detail}" if stopped else f"{reason}；{detail}"
        return self.report(phase, final=True)


    def report(self, phase, final=False, force=False):
        now = time.monotonic()
        if not (final or force or phase != self._last_phase
                or now - self._last_report_time >= (max(2., self.settings.progress_interval)
                    if self.progress_heartbeat is not None else self.settings.progress_interval)):
            return None
        build_started=time.monotonic()
        self._last_report_time, self._last_phase = now, phase
        self.reports_emitted += 1
        speed_key = self._key(self.best)
        if speed_key != self._speed_key:
            if hasattr(self.evaluator, "speed_preview"):
                self._speed_preview = self.evaluator.speed_preview(self.best)
            else:
                self._speed_preview = (self.evaluator.speed_ranking(self.best),
                                       self.evaluator.speed_signature(self.best))
            self._speed_key = speed_key
        elapsed = time.monotonic() - self.started
        result = {"schema": 1, "phase": phase, "final": final, "simulations": self.done,
                  "elapsed": elapsed, "simulations_per_second": self.done / max(elapsed, .001),
                  "cache_hits": self.cache_hits, "candidate_attempts": self.attempts,
                  "unique_configurations": len(self._configuration_keys), "restarts": self.restarts,
                  "reports_emitted": self.reports_emitted,
                  "unused_budget": self.settings.budget - self._budget_spent(),
                  "budget_spent": self._budget_spent(),
                  "duplicate_candidates": self.duplicate_candidates,
                  "search_mode": self.search_mode,
                  "termination_reason": self.termination_reason,
                  "termination_detail": self.termination_detail,
                  "evaluation_requests": self.evaluation_requests,
                  "seed_evaluation_requests": self.seed_evaluation_requests,
                  "ignored_seed_repetitions": self.ignored_seed_repetitions,
                  "duplicate_cache_pairs_skipped": self.duplicate_cache_pairs_skipped,
                  "stagnant_character_sets": [list(team) for team in sorted(self.stagnant_teams)],
                  "memory_total": self.memory_total, "memory_set_total": self.memory_set_total,
                  "memory_covered": self.memory_covered if self.memory_total is not None else None,
                  "memory_uncovered": self.memory_total-self.memory_covered if self.memory_total is not None else None,
                  "memory_coverage": self.memory_covered/self.memory_total if self.memory_total else None,
                  "configuration_key_version": 2,
                  "memory_order_policy": self.memory_order_policy,
                  "memory_order_reason": self.memory_order_reason,
                  "memory_evaluations": self.memory_evaluations, "memory_rounds": self.memory_rounds,
                  "reevaluation_simulations": self.phase_simulations["validation"],
                  "budget_plan": self.budget_plan, "phase_simulations": self.phase_simulations,
                  "combination_total": self.combination_total,
                  "combination_coverage": [dict(characters=list(team), **{
                      key: value for key, value in stats.items() if key != "keys"},
                      unique_configurations=len(stats["keys"]))
                      for team, stats in sorted(self.combination_stats.items())],
                  "combination_coverage_complete": sum(
                      stats["planned"] and (stats["basic_simulations"] > 0 or stats["baseline_simulations"] > 0)
                      for stats in self.combination_stats.values()) == self.combination_total,
                  "elite_summary": [dict(characters=list(members(state)),
                                         positions=state["friend_positions"], memories=state["memory_ids"],
                                         configuration_key=key, search_score=score, state=copy.deepcopy(state))
                                    for key, (score, state) in self.elite.items()],
                  "original": self.original, "best": dict(self.best, memory_ids=sorted(self.best["memory_ids"])), "constraints": self.constraints,
                  "search_start": self.search_start,
                  "baseline_satisfies_constraints": self.baseline_satisfies_constraints,
                  "initialization_notes": self.initialization_notes,
                  "candidate_diagnostics": self.candidate_diagnostics,
                  "evaluated_character_sets": [list(c) for c in sorted(self.evaluated_character_sets)],
                  "settings": asdict(self.settings), "search_seeds": self.search_seed_list,
                  "statistical_review": self.statistical_review,
                  "independent_validation": self.independent_validation,
                  "search_champion": self.search_champion,
                  "search_champion_score": self.search_champion_score,
                  "search_champion_seeds": self.search_champion_seeds,
                  "validation_seeds": self.validation_seed_list,
                  "baseline_search_score": self.baseline_search, "best_search_score": self.best_search,
                  "baseline_mean": self.baseline_mean, "best_mean": self.best_mean,
                  "baseline_validation_seeds": self.baseline_validation_seeds,
                  "baseline_validation_seed_count": len(self.baseline_validation_seeds),
                  "best_validation_seed_count": self.best_validation_count,
                  "validation_requested_seed_count": (150 if self.independent_validation.get("extra_triggered") else 50) if self.independent_validation else self.settings.validation_seeds,
                  "validation_complete": (self.independent_validation.get("extra_executed",False) if self.independent_validation.get("extra_triggered") else self.independent_validation.get("initial_completed",False)) if self.independent_validation else self.best_validation_count >= self.settings.validation_seeds,
                  "speed_pruning_enabled": False,
                  "speed_pruning_reason": "V1仅显示初始敌我速度排名；战术敌人阶段增速及技能动态影响尚未证明安全，故不按排名丢弃候选",
                  "best_speed_ranking": self._speed_preview[0],
                  "initial_speed_rank_signature": self._speed_preview[1]}
        result["ranking_comparison_context"] = {"scope":"single-search", "score":"total_score"}
        result["stage_progress"]=dict(self.stage_progress)
        result["stage_progress"]["completed_samples"]=max(0,self.done-self.stage_progress.get("started_at_simulations",self.done))
        if self.performance.enabled:
            self.performance.seconds["result_construct_seconds"]=self.performance.seconds.get("result_construct_seconds",0.)+time.monotonic()-build_started
            self.performance.calls["result_construct_seconds"]=self.performance.calls.get("result_construct_seconds",0)+1
        result["in_flight_tasks"]=getattr(self.evaluator,"stats",{}).get("in_flight_tasks",0)
        result["pending_batch_tasks"]=getattr(self.evaluator,"stats",{}).get("pending_batch_tasks",0)
        for field in ("running_tasks","dispatched_not_started_tasks"):
            result[field]=getattr(self.evaluator,"stats",{}).get(field,0)
        result["performance_diagnostics"]=self.performance.snapshot(self.phase_simulations)
        result["worker_phase_diagnostics"]=copy.deepcopy(getattr(self.evaluator,"phase_stats",{}))
        result["parallel_diagnostics"] = dict(getattr(self.evaluator, "stats", {}))
        total_seconds=elapsed + result["parallel_diagnostics"].get("coordinator_initialization_seconds",0.)
        result["parallel_diagnostics"].update(total_seconds=total_seconds, throughput=self.done / max(total_seconds, .001), cache_hits=self.cache_hits)
        if self.position_total is not None:
            result.update(position_total=self.position_total, position_covered=self.position_covered,
                          position_uncovered=self.position_total-self.position_covered,
                          position_coverage=self.position_covered/self.position_total,
                          position_evaluations=self.position_evaluations, position_rounds=self.memory_rounds,
                          position_constraints=self.position_constraints,
                          position_coverage_complete=self.position_covered == self.position_total,
                          memory_evaluations=[], memory_rounds=[])
        if getattr(self,'shared_review',False):
            result.update(combined_champion=getattr(self,'combined_champion',None),
                actual_review_strategy=self.settings.review_strategy,
                review_limits=dict(quick_max_seeds=self.settings.quick_max_seeds,
                    rigorous_planned_looks=(self.statistical_review or {}).get('planned_looks',[])),
                review_candidate_template=self.review_candidate_template)
            if final:
                recorded_joint={row['configuration_key'] for row in self.layered_run.joint} if hasattr(self,'layered_run') else set()
                result['review_seed_scores']=[dict(configuration_key=k,seed=seed,score=score)
                    for (k,seed),score in self.cache.items() if k in self.review_evidence_keys and k not in recorded_joint]
        if hasattr(self,'layered_run'):result.update(self.layered_run.report_fields(final))
        with self.performance.measure("result_publish_seconds"):
            if self.output:
                write_json(self.output, result)
            self.progress(copy.deepcopy(result))
        return result

    def estimate(self, state, seeds):
        with self.performance.measure("configuration_key_seconds"):
            key = self._key(state)
        cache_began=time.monotonic()
        unique_seeds = list(dict.fromkeys(seeds))
        self.ignored_seed_repetitions += len(seeds) - len(unique_seeds)
        seeds = unique_seeds
        self.evaluation_requests += 1
        needed = sum((key, seed) not in self.cache for seed in seeds)
        if self._budget_spent() + needed > self.evaluation_limit:
            raise Stopped("预算不足以完成当前种子集合")
        missing = [seed for seed in seeds if (key, seed) not in self.cache]
        self.seed_evaluation_requests += len(seeds)
        self.cache_hits += len(seeds) - len(missing)
        if self.performance.enabled:self.performance.seconds["cache_lookup_seconds"]=self.performance.seconds.get("cache_lookup_seconds",0.)+time.monotonic()-cache_began
        team=members(state)
        team_stats=self._team_stats(team)
        def accept(seed, score):
            self._accept_score(key,seed,score,state)
        try:
            if missing:
                with self.performance.measure("configuration_construct_seconds"):
                    canonical = dict(active_snapshot(state), memory_ids=sorted(state["memory_ids"]))
            if hasattr(self.evaluator, "evaluate_many") and missing:
                from src.optimizer.parallel import EvaluationStopped
                try:
                    self.evaluator.evaluate_many(canonical, key, missing, accept)
                except EvaluationStopped as exc:
                    raise Stopped(str(exc)) from exc
            else:
                for seed in missing:
                    if self.stop():
                        raise Stopped()
                    with self.performance.measure("direct_battle_seconds"):
                        score=self.evaluator.evaluate(canonical, seed)
                    accept(seed,score)
                    self.heartbeat()
            if self.stop():
                raise Stopped()
        except Stopped:
            raise
        except Exception:
            LOG.exception("战斗评价失败：操作=%s 配置=%s 第五人替换=%s 角色=%s 模块=%s seeds=%s",
                          self.current_operation, diagnostic_configuration_id(state),
                          state["friend_positions"] != self.original["friend_positions"],
                          state["friend_positions"], state["panel"].get("modules"), missing)
            raise
        return self._rank_value(key, seeds)

    def _rank_value(self, key, seeds):
        """The value a candidate is ranked by, on these seeds.

        Under ``objective="mean"`` this is ``statistics.mean`` verbatim, so every
        ported V3.2 comparison is unchanged. Under ``roll5`` it is the
        expected-best-of-five, which reads the spread across the seeds as well as
        their level -- which is the whole point of that mode.
        """
        samples=[self.cache[key, seed] for seed in seeds]
        return obj.rank_key(samples, getattr(self.settings,'objective','mean') or 'mean')

    def _accept_score(self,key,seed,score,state):
        if not isinstance(score,(int,float)) or not math.isfinite(score):
            raise ValueError('战斗引擎返回无效分数')
        if (key,seed) in self.cache:
            raise RuntimeError('重复返回已缓存的战斗任务，停止以保护预算')
        self.cache[key,seed]=score
        team=members(state);self.evaluated_character_sets.add(team)
        stats=self._team_stats(team)
        stats['simulations']+=1;stats[self.budget_phase+'_simulations']+=1
        stats['keys'].add(key);self._configuration_keys.add(key)
        self.phase_simulations[self.budget_phase]+=1;self.done+=1

    def evaluate_cohorts(self,cohorts,on_result):
        """Bounded (token,state,seeds) windows; callbacks publish in input order.

        A window reserves all new (key,seed) identities BEFORE transport. Near
        budget exhaustion only a complete logical prefix is admitted. Every
        complete cohort is preserved on interruption; incomplete ones have
        only cached samples and never a comparable mean.
        """
        if not self.cross_cohorts or not hasattr(self.evaluator,'evaluate_cohorts'):
            for token,state,seeds in cohorts:on_result(token,self.estimate(state,seeds))
            return
        iterator=iter(cohorts);carry=None;exhausted=False
        capacity=max(1,2*getattr(self.evaluator,'count',1))
        while not exhausted or carry is not None:
            if self.stop():raise Stopped('用户主动停止')
            chunk=[];reserved=set();new_cost=0
            while len(chunk)<capacity:
                item=carry if carry is not None else next(iterator,None);carry=None
                if item is None:exhausted=True;break
                token,state,requested_seeds=item
                with self.performance.measure('configuration_key_seconds'):key=self._key(state)
                seeds=list(dict.fromkeys(requested_seeds))
                missing=[seed for seed in seeds if (key,seed) not in self.cache and (key,seed) not in reserved]
                if self._budget_spent()+new_cost+len(missing)>self.evaluation_limit:
                    if chunk:carry=item;break
                    self.evaluation_requests+=1
                    self.ignored_seed_repetitions+=len(requested_seeds)-len(seeds)
                    raise Stopped('预算不足以完成当前种子集合')
                self.evaluation_requests+=1;self.seed_evaluation_requests+=len(seeds)
                self.ignored_seed_repetitions+=len(requested_seeds)-len(seeds)
                self.cache_hits+=len(seeds)-len(missing)
                canonical=None
                if missing:
                    with self.performance.measure('configuration_construct_seconds'):
                        canonical=dict(active_snapshot(state),memory_ids=sorted(state['memory_ids']))
                chunk.append((token,state,key,seeds,canonical,missing))
                reserved.update((key,seed) for seed in missing);new_cost+=len(missing)
            if not chunk:break
            states={key:state for _,state,key,_,_,_ in chunk}
            def accept(key,seed,score):self._accept_score(key,seed,score,states[key])
            self.evaluator.stats['reserved_cohort_samples']=new_cost
            try:
                from src.optimizer.parallel import EvaluationStopped
                try:
                    jobs=((key,canonical,missing) for _,_,key,_,canonical,missing in chunk if missing)
                    if new_cost:self.evaluator.evaluate_cohorts(jobs,accept,planned_samples=new_cost)
                except EvaluationStopped as exc:raise Stopped(str(exc)) from exc
            finally:
                self.evaluator.stats['reserved_cohort_samples']=0
                # Complete means only, even if transport stopped after later
                # cohorts finished. No stage's screening runs until we return.
                for token,state,key,seeds,_,_ in chunk:
                    if seeds and all((key,seed) in self.cache for seed in seeds):
                        on_result(token,self._rank_value(key,seeds))
            if self.stop():raise Stopped('用户主动停止')

    def _team_stats(self, team):
        return self.combination_stats.setdefault(team, dict(
            planned=False, basic_target=0, simulations=0, basic_simulations=0,
            baseline_simulations=0, refinement_simulations=0, validation_simulations=0, independent_simulations=0,
            starts=0, attempts=0, best_search_score=None, keys=set()))

    def _retain(self, state, score):
        key = self._key(state)
        state = dict(state, memory_ids=sorted(state["memory_ids"]))
        self.elite[key] = (score, state)
        self.elite = diverse_elites(self.elite)
        stats = self._team_stats(members(state))
        if stats["best_search_score"] is None or score > stats["best_search_score"]:
            stats["best_search_score"] = score
        if self.best_search is None or score > self.best_search:
            self.best, self.best_search = state, score
            self.best_mean, self.best_validation_count = None, 0

    def _fresh_score(self, state):
        key = self._key(state)
        if all((key, seed) in self.cache for seed in self.search_seed_list):
            self.duplicate_candidates += 1
            self.duplicate_cache_pairs_skipped += len(self.search_seed_list)
            return None
        score = self.estimate(state, self.search_seed_list)
        self._retain(state, score)
        return score

    def _track_stagnation(self, team, score):
        self._duplicate_streaks[team] = self._duplicate_streaks.get(team, 0) + 1 if score is None else 0
        if self._duplicate_streaks[team] >= 64:
            self.stagnant_teams.add(team)

    def _candidate(self, parent, settings, restart=False):
        try:
            return mutate(parent, self.constraints, settings, self.rng, restart,
                          loader=getattr(self.evaluator, "loader", None),
                          diagnostics=self.candidate_diagnostics)
        except AffixValidationError as exc:
            # Preserve the existing recovery contract for affix-only failures;
            # fixed-data errors and combat exceptions still propagate to worker.
            record_diagnostic(self.candidate_diagnostics, action="恢复候选词条错误",
                              operation=self.current_operation,
                              fifth_replacement=members(exc.state) != members(parent), **exc.details)
            candidate = copy.deepcopy(exc.state)
            loader = getattr(self.evaluator, "loader", None)
            for cid in members(candidate):
                initialize_character(candidate, cid, loader, self.candidate_diagnostics,
                                     operation=self.current_operation,
                                     fifth_replacement=members(candidate) != members(parent),
                                     optimize_affixes=self.settings.change_affixes)
            validate_snapshot(candidate, loader, affixes=self.settings.change_affixes)
            validate_constraints(candidate, self.constraints, loader)
            return candidate

    def run(self):
        s = self.settings
        s.validate()
        loader = getattr(self.evaluator, "loader", None)
        validate_snapshot(self.original, loader, affixes=False)
        validate_constraints(self.original, self.constraints, loader, require_current=False)
        try:
            validate_constraints(self.original, self.constraints, loader)
            self.baseline_satisfies_constraints = True
        except ValueError:
            # Pool and IDs were validated above: only the old lineup may differ.
            self.baseline_satisfies_constraints = False
        if not s.automatic:
            self.search_mode = "仅评价人工阵容"
            # Evaluation-only must not repair gear or change the user's manual lineup.
            self.search_start = copy.deepcopy(self.original)
            self.current_operation = "仅评价人工基线"
            try:
                self.best_search = self.baseline_search = self.estimate(self.original, self.search_seed_list)
                self.best_mean = self.baseline_mean = self.estimate(self.original, self.validation_seed_list)
                self.best_validation_count = len(self.validation_seed_list)
                self.baseline_validation_seeds = list(self.validation_seed_list)
                self.termination_reason = "仅评价人工阵容"
                return self.report("仅评价人工阵容；未执行自动搜索", final=True)
            except Stopped as exc:
                return self.finish("用户主动停止" if self.stop() else "战斗预算不足以完成当前种子集合",
                                   str(exc) or "保留人工阵容", stopped=True)

        self.validation_seed_list = []
        if s.search_kind == 'layered':
            from src.optimizer.layered_search import run_layered_search
            return run_layered_search(self)
        if s.search_kind == "positions":
            from src.optimizer.position_search import PositionSpace, run_position_search
            space = PositionSpace(self.original, self.constraints)
            space.require_budget(s)
            self.search_start = copy.deepcopy(self.original)
            return run_position_search(self, space)
        self.search_start = prepare_search_snapshot(
            self.original, self.constraints, loader, self.initialization_notes,
            change_fifth=s.change_fifth, change_memories=s.change_memories,
            change_affixes=s.change_affixes)
        self.best = copy.deepcopy(self.search_start)
        self.combination_total, _ = plan_combinations(
            self.search_start, self.constraints, s.change_fifth, 0, self.rng)
        if s.search_kind in ("legacy", "memory") and s.change_memories and not any((s.change_fifth, s.change_positions, s.change_affixes)):
            space = MemorySpace(self.search_start, self.constraints)
            return run_memory_search(self, space, bool(s.memory_exhaustive_limit and
                                                     space.total <= s.memory_exhaustive_limit))
        baseline_eligible = self.baseline_satisfies_constraints
        try:
            validate_snapshot(self.original, loader, affixes=s.change_affixes)
        except AffixValidationError:
            baseline_eligible = False  # Illegal manual affixes remain a comparison only.
        try:
            # Small budgets degrade seed counts explicitly, rather than rejecting.
            self.search_seed_list = self.search_seed_list[:min(s.search_seeds, s.budget)]
            self.current_operation = "人工基线评分"
            self.baseline_search = self.estimate(self.original, self.search_seed_list)
            start_score = self.estimate(self.search_start, self.search_seed_list)
            self._retain(self.search_start, start_score)
            if baseline_eligible:
                self._retain(self.original, self.baseline_search)
                if self._key(self.original) == self._key(self.best):
                    self.best = self.original
            remaining = s.budget - self.done
            # Keep roughly two thirds for exploration. Review and holdout share
            # the remainder; never pre-spend the baseline validation cohort.
            from src.optimizer.budget import recommendation
            budget_advice=recommendation(self.search_start,self.constraints,s,loader)
            reserve = (budget_advice['review_cost_estimate']+budget_advice['initial_cost']+budget_advice['extra_cost']
                       if s.budget>=budget_advice['recommended_budget'] else remaining // 3)
            reserve=min(reserve,remaining)
            search_end = s.budget - reserve
            available_requests = max(0, (search_end - self.done) // len(self.search_seed_list))
            inner = replace(s, change_fifth=False)
            mutable = any((s.change_affixes, s.change_positions, s.change_memories))
            # Three initial requests per admitted team where possible, regardless
            # of its first score. Budget-constrained pools are sampled explicitly.
            basic_requests = max(1, int(available_requests * .6)) if available_requests else 0
            full_team_requests = self.combination_total * (3 if mutable else 1)
            if full_team_requests <= available_requests:
                basic_requests = max(basic_requests, full_team_requests)
            capacity = max(1, basic_requests // (3 if mutable else 1)) if basic_requests else 0
            self.combination_total, teams = plan_combinations(
                self.search_start, self.constraints, s.change_fifth, capacity, self.rng)
            if teams:
                quotient, extra = divmod(basic_requests, len(teams))
                for index, team in enumerate(teams):
                    stats = self._team_stats(team)
                    stats["planned"] = True
                    stats["basic_target"] = (quotient + (index < extra)) * len(self.search_seed_list)
            self.budget_plan = dict(total=s.budget, baseline_spent=self.done,
                                    basic_requests=basic_requests,
                                    basic_simulation_target=basic_requests * len(self.search_seed_list),
                                    refinement_simulation_target=max(0, search_end - self.done - basic_requests * len(self.search_seed_list)),
                                    validation_reserved=reserve,
                                    policy="保留当前组合，其余组合无放回抽样；基础轮询不按首次分数淘汰；随后竞争加轮询")
            self.report("正在搜索", force=True)
            roots, walks = {}, {}
            for team in teams:
                roots[team] = combination_start(self.search_start, team, self.constraints,
                                                 loader, self.initialization_notes, optimize_affixes=s.change_affixes)
                walks[team] = []
            self.budget_phase = "basic"
            limit = max(50, s.budget * 20)
            # Round robin: one bad first evaluation cannot exclude a team.
            while teams and self.attempts < limit:
                pending = [team for team in teams if team not in self.stagnant_teams and self._team_stats(team)["basic_simulations"]
                           < self._team_stats(team)["basic_target"]]
                if not pending or self.done + len(self.search_seed_list) > search_end:
                    break
                for team in pending:
                    if self.stop():
                        raise Stopped()
                    if self.done + len(self.search_seed_list) > search_end or self.attempts >= limit:
                        break
                    stats = self._team_stats(team)
                    attempt = stats["attempts"]
                    self.current_operation = "组合基础探索/多起点" + str(team)
                    if attempt == 0:
                        candidate = roots[team]
                    elif mutable:
                        # The second starting point is a joint perturbation of ALL
                        # eligible modules, not merely the newly entered role.
                        restart = attempt == 1 or attempt % 12 == 11
                        if restart:
                            candidate = self._candidate(roots[team], inner, True)
                            self.restarts += 1
                        else:
                            parent = walks[team][attempt % len(walks[team])][1] if walks[team] else roots[team]
                            candidate = self._candidate(parent, inner)
                    else:
                        # No legal mutable dimension: don't spin through cached roots.
                        stats["basic_target"] = stats["basic_simulations"]
                        continue
                    self.attempts += 1
                    stats["attempts"] += 1
                    score = self._fresh_score(candidate)
                    self._track_stagnation(team, score)
                    if score is None and attempt == 0:
                        key = self._key(candidate)
                        score = self._rank_value(key, self.search_seed_list)
                        self._retain(candidate, score)
                    if score is not None:
                        if len(walks[team]) < 2:
                            walks[team].append((score, candidate))
                            stats["starts"] += 1
                        else:
                            slot = attempt % 2
                            if score >= walks[team][slot][0]:
                                walks[team][slot] = (score, candidate)
                    self.report("基础组合探索")
            self.budget_phase = "refinement"
            refinement_step = 0
            teams = [team for team in teams if team not in self.stagnant_teams]
            while (teams and mutable and self.done + len(self.search_seed_list) <= search_end
                   and self.attempts < limit):
                if self.stop():
                    raise Stopped()
                # Two competitive visits, then a rotating exploration visit.
                if refinement_step % 3 == 2:
                    team = teams[(refinement_step // 3) % len(teams)]
                else:
                    ordered = sorted(teams, key=lambda team: self._team_stats(team)["best_search_score"]
                                     if self._team_stats(team)["best_search_score"] is not None else -math.inf,
                                     reverse=True)
                    team = ordered[refinement_step % min(3, len(ordered))]
                restart = refinement_step % 12 == 11
                parent = roots[team] if restart or not walks[team] else walks[team][refinement_step % len(walks[team])][1]
                self.current_operation = "组合内精细优化" + str(team)
                candidate = self._candidate(parent, inner, restart)
                self.attempts += 1
                self._team_stats(team)["attempts"] += 1
                refinement_step += 1
                if restart:
                    self.restarts += 1
                score = self._fresh_score(candidate)
                self._track_stagnation(team, score)
                if team in self.stagnant_teams:
                    teams.remove(team)
                if score is not None:
                    if not walks[team]:
                        walks[team].append((score, candidate))
                    else:
                        slot = refinement_step % len(walks[team])
                        if score >= walks[team][slot][0] or restart:
                            walks[team][slot] = (score, candidate)
                self.report("组合内精细优化")
            from src.optimizer.statistical_review import review, reserve_independent
            finalists = dict(self.elite)
            review(self, finalists, baseline_eligible, reserve_independent(s.budget,self._budget_spent(),len(finalists),self._key(self.original) in finalists))
            validation_seeds = self.validation_seed_list
            validate_snapshot(self.best, loader, affixes=s.change_affixes)
            validate_constraints(self.best, self.constraints, loader)
            reason = ("战斗预算已耗尽" if self.done == s.budget else
                      "候选尝试安全上限已达到" if self.attempts >= limit else
                      "候选生成停滞（未证明穷举）" if self.stagnant_teams else
                      "启发式搜索计划已完成（未证明穷举）")
            detail = (self.independent_validation or {}).get("status", "预算不足，最佳候选未独立验证") + "；保留最后完整评估；剩余预算未强制用于重复模拟"
            return self.finish(reason, detail)
        except Stopped as exc:
            # An unverified search leader is preserved, but never labeled stable.
            return self.finish("用户主动停止" if self.stop() else "战斗预算不足以完成当前种子集合",
                               str(exc) or "保留当前最佳候选", stopped=True)
