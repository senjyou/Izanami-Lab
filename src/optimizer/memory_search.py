"""Unordered shared-memory combinations and unchanged common-seed racing."""
import copy
import math
from src.optimizer.model import validate_constraints, validate_snapshot
from src.optimizer.scheduling import _rank, _unrank


class MemorySpace:
    """Six unique shared cards, enumerated by set and filled in stable ID order."""
    def __init__(self, state, constraints):
        validate_snapshot(state,affixes=False)
        validate_constraints(state,constraints)
        self.template=tuple(sorted(state['memory_ids']))
        self.required={int(mid) for mid,mark in constraints['memories'].items() if mark=='必选'}
        self.pool=sorted({int(mid) for mid,mark in constraints['memories'].items() if mark=='候选'}-self.required)
        self.count=6-len(self.required)
        if len(self.pool)<self.count:
            raise ValueError('回忆约束无法补齐六张不同回忆')
        self.total=self.set_total=math.comb(len(self.pool),self.count)
        current=tuple(mid for mid in self.template if mid not in self.required)
        self.initial_rank=_rank(self.pool,current)

    def at(self, rank):
        return tuple(sorted(self.required.union(_unrank(self.pool,self.count,rank))))

    def ranks(self, capacity, rng):
        capacity=min(self.total,max(0,capacity))
        if not capacity:
            return []
        # Floyd sampling: no replacement, no expansion of the huge full space.
        ranks=set()
        for j in range(self.total-capacity,self.total-1):
            picked=rng.randrange(j+1)
            ranks.add(j if picked in ranks else picked)
        other=[rank+(rank>=self.initial_rank) for rank in sorted(ranks)]
        rng.shuffle(other)
        return [self.initial_rank]+other


def run_memory_search(search, space, exhaustive):
    """Cover first, then halve cohorts with additional common independent seeds.

    A round is published only after every member has the same complete seed set.
    Baseline is retained for comparison, never given an artificial score bonus.
    """
    from src.optimizer.search import Stopped
    s=search.settings
    search.search_mode='回忆穷举' if exhaustive else '启发式搜索'
    search.memory_total=space.total
    search.memory_set_total=space.set_total
    search.memory_order_policy='无序集合（共享回忆不依赖槽位）'
    if exhaustive:
        seed_count=min(s.search_seeds,max(1,s.budget//space.total))
        capacity=min(space.total,s.budget//seed_count)
    else:
        seed_count=min(s.search_seeds,s.budget)
        capacity=min(space.total,max(1,int(s.budget*.6)//seed_count))
        from src.optimizer.budget import recommendation
        advice=recommendation(search.search_start,search.constraints,s,getattr(search.evaluator,'loader',None))
        if s.budget>=advice['recommended_budget']:
            capacity=min(capacity,advice['basic_planned_configurations'])
    search.search_seed_list=search.search_seed_list[:seed_count]
    search.validation_seed_list=[]
    ranks=space.ranks(capacity,search.rng)
    search.budget_plan=dict(total=s.budget,policy='先无放回基础覆盖，后共同种子分层复评；不预占基础覆盖预算',
                           memory_planned=len(ranks),basic_seed_count=seed_count,
                           basic_simulation_target=len(ranks)*seed_count,
                           exhaustive_limit=s.memory_exhaustive_limit)
    records={}
    baseline_key=search._key(search.original)
    loader=getattr(search.evaluator,'loader',None)
    try:
        search.budget_phase='basic'
        search._team_stats(tuple(sorted(c for c in search.search_start['friend_positions'] if c)))['planned']=True
        search.begin_stage('正在基础覆盖',len(ranks),len(ranks)*seed_count)
        def jobs():
            for rank in ranks:
                state=copy.deepcopy(search.search_start)
                state['memory_ids']=list(space.at(rank))
                validate_snapshot(state,loader,affixes=False)
                validate_constraints(state,search.constraints,loader)
                key=search._key(state)
                # Use the unchanged manual baseline when this is its valid class.
                if key==baseline_key and search.baseline_satisfies_constraints:
                    state=copy.deepcopy(search.original)
                    state['memory_ids']=sorted(state['memory_ids'])
                search.current_operation='回忆组合无放回基础覆盖'
                search.attempts+=1
                yield (key,state),state,search.search_seed_list
        def completed(token,score):
            key,state=token
            records[key]=dict(state=state,basic_mean=score,eligible=True,basic_seeds=list(search.search_seed_list),validation_mean=None,validation_seeds=[])
            search.memory_covered+=1
            search.stage_progress["completed_candidates"]+=1
            if key==baseline_key:
                search.baseline_search=score
            search._retain(state,score)
            search.memory_evaluations.append(_record_summaries({key:records[key]})[0])
            search.report('回忆组合基础覆盖')
        search.evaluate_cohorts(jobs(),completed)
        complete=search.memory_covered==space.total
        if not complete and exhaustive:
            return search.finish('战斗预算已耗尽','预算不足：回忆基础覆盖未完成；未进行优先于覆盖的复评')
        from src.optimizer.statistical_review import reserve_independent
        from src.optimizer.review_dispatch import review
        finalists={key:(row['basic_mean'],row['state']) for key,row in records.items()}
        review(search,finalists,search.baseline_satisfies_constraints,
               reserve_independent(s.budget,search._budget_spent(),len(finalists),baseline_key in finalists))
        reason='战斗预算已耗尽' if search.done==s.budget else (
            '搜索空间已完整覆盖' if complete else '无放回抽样计划已完成（未完整覆盖）')
        detail=('基础覆盖完成；已执行预算内公平复评及独立验证' if complete else
                '超过穷举阈值，已完成预算内无放回抽样；未证明全部空间耗尽')
        detail += '；'+(search.independent_validation or {}).get('status','独立验证样本不足')+'；剩余预算未强制用于重复模拟'
        return search.finish(reason,detail)
    except Stopped as exc:
        if search.statistical_review is None:search.memory_evaluations=_record_summaries(records)
        reason='用户主动停止' if search.stop() else '战斗预算不足以完成当前种子集合'
        return search.finish(reason,str(exc) or '保留最后完整轮次的最佳结果',stopped=True)


def _record_summaries(records):
    return [dict(configuration_key=key,memory_ids=sorted(row['state']['memory_ids']),
                 basic_mean=row['basic_mean'],basic_seeds=row['basic_seeds'],eligible=row['eligible'],
                 validation_mean=row['validation_mean'],validation_seeds=row['validation_seeds'])
            for key,row in records.items()]
