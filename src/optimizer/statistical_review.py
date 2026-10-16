"""Frozen-candidate paired reviews; battle formulas stay in the evaluator.

Student-t intervals assume independent, approximately normal paired differences.
Bonferroni corrects ALL pairs and the finite, predeclared review looks, not just
observed winners. Heavy-tailed/non-normal battle outcomes are still a limitation.
"""
import copy
import math
import statistics
from functools import lru_cache
from src.optimizer import objective as obj


def _beta_fraction(a, b, x):
    qab, qap, qam = a+b, a+1, a-1
    c = 1.; d = 1-qab*x/qap
    d = 1/max(abs(d), 1e-300) * (1 if d >= 0 else -1)
    h = d
    for m in range(1, 201):
        aa = m*(b-m)*x/((qam+2*m)*(a+2*m))
        d = 1+aa*d; d = d if abs(d)>1e-300 else 1e-300
        c = 1+aa/c; c = c if abs(c)>1e-300 else 1e-300
        d = 1/d; h *= d*c
        aa = -(a+m)*(qab+m)*x/((a+2*m)*(qap+2*m))
        d = 1+aa*d; d = d if abs(d)>1e-300 else 1e-300
        c = 1+aa/c; c = c if abs(c)>1e-300 else 1e-300
        d = 1/d; delta = d*c; h *= delta
        if abs(delta-1)<3e-14: break
    return h


def _beta(a, b, x):
    if x <= 0: return 0.
    if x >= 1: return 1.
    scale = math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log1p(-x))
    if x < (a+1)/(a+b+2): return scale*_beta_fraction(a,b,x)/a
    return 1-scale*_beta_fraction(b,a,1-x)/b


@lru_cache(maxsize=2048)
def t_critical(df, alpha):
    lo, hi = 0., 1.
    def tail(t): return .5*_beta(df/2,.5,df/(df+t*t))
    while tail(hi)>alpha/2: hi *= 2
    for _ in range(60):
        mid = (lo+hi)/2
        if tail(mid)>alpha/2: lo = mid
        else: hi = mid
    return (lo+hi)/2


def paired_summary(left, right, alpha=.05, objective="mean"):
    if len(left)!=len(right):
        raise ValueError("配对比较必须使用相同数量的共同种子")
    diffs = [a-b for a,b in zip(left,right)]
    n = len(diffs)
    if obj.needs_resampling(objective):
        # Roll5 is a cohort statistic, so the per-seed difference is not its
        # difference. The gap and its error come from resampling the shared seeds.
        gap,se,_=obj.paired_gap(left,right,objective)
        row=dict(seed_count=n,mean_difference=gap,interval=None,
                 conclusion='独立验证样本不足' if n<8 else '暂无法区分',alpha=alpha)
        if n<8 or gap is None or not se or not math.isfinite(se):
            if n>=8 and (not se or not math.isfinite(se)):
                row['limitation']='观测差值无波动，无法可靠估计尾部风险'
            return row
        margin=t_critical(n-1,alpha)*se
        row['interval']=[gap-margin,gap+margin]
        if gap-margin>0: row['conclusion']='领先证据较充分（配对自助近似假设下）'
        return row
    mean = statistics.mean(diffs) if n else None
    row = dict(seed_count=n,mean_difference=mean,interval=None,conclusion='独立验证样本不足' if n<8 else '暂无法区分',alpha=alpha)
    if n<8: return row
    variance = statistics.variance(diffs)
    if variance <= 0:
        # A small constant sample cannot establish absence of rare outcomes.
        row['limitation']='观测差值无波动，无法可靠估计尾部风险'
        return row
    margin = t_critical(n-1,alpha)*math.sqrt(variance/n)
    row['interval']=[mean-margin,mean+margin]
    if mean-margin>0: row['conclusion']='领先证据较充分（配对t近似假设下）'
    return row


def reserve_independent(budget, coverage_cost=0, candidate_count=4, baseline_included=True):
    from src.optimizer.budget import reserve_for_final
    return reserve_for_final(budget,coverage_cost,candidate_count,baseline_included)


def review(search, candidates, baseline_eligible, reserve):
    """Both search paths call this only after candidate generation is frozen."""
    s = search.settings
    baseline_key = search._key(search.original)
    entries = dict(candidates)
    entries.setdefault(baseline_key,(search.baseline_search,copy.deepcopy(search.original)))
    eligible = {key for key in candidates if key != baseline_key or baseline_eligible}
    if not eligible: return
    # Freeze the whole shortlist before using fresh review seeds. Basic-score
    # winners do not exclude other frozen contenders on the first noisy look.
    keys = sorted(entries)
    pairs = max(1,len(keys)*(len(keys)-1)//2)
    looks = []; n = min(4,s.validation_seeds)
    maximum = max(s.validation_seeds, s.budget//max(1,len(keys)))
    while n <= maximum:
        looks.append(n); n *= 2
    if not looks: looks=[maximum]
    alpha = .05/(pairs*len(looks))
    search.evaluation_limit = s.budget-reserve
    active = list(keys)
    last = None
    search.statistical_review = dict(method='共同种子配对Student-t区间；全部配对×预定轮次Bonferroni校正',
        assumptions='独立、近似正态的配对差值；不保证重尾分布或全搜索空间最优',
        alpha_family=.05,alpha_per_comparison=alpha,planned_looks=looks,rounds=[],candidate_keys=keys)
    search.budget_plan.update(independent_reserved=reserve,
                              statistical_policy='预定共同种子轮次；只淘汰差值区间排除零的落后者；冻结前3名加人工基线独立验证')
    search.budget_phase='validation'
    for round_index,count in enumerate(looks,1):
        seeds=[s.seed+100000+i for i in range(count)]
        cost=sum((key,seed) not in search.cache for key in active for seed in seeds)
        if search._budget_spent()+cost>search.evaluation_limit:
            search.statistical_review['stopping_detail']=dict(reason='下一预定完整共同种子轮次超过复评可用预算',
                next_seed_count=count,needed_battles=cost,available_battles=search.evaluation_limit-search._budget_spent(),
                smaller_unplanned_look='未追加未预定检验轮次；保留Bonferroni校正与独立验证预留')
            break
        search.begin_stage('正在统计复评',len(active),cost,round_index)
        scores={}
        for key in active:
            scores[key]=search.estimate(entries[key][1],seeds)
            search.stage_progress['completed_candidates']+=1
            search.heartbeat()
        winners=sorted((key for key in active if key in eligible),key=lambda key:(-scores[key],key))
        if not winners: break
        leader=winners[0]
        with search.performance.measure("statistical_compute_seconds"):
            leader_values=[search.cache[leader,seed] for seed in seeds]
            _objective=getattr(search.settings,'objective','mean') or 'mean'
            comparisons={key:paired_summary(leader_values,
                                       [search.cache[key,seed] for seed in seeds],alpha,
                                       _objective)
                     for key in active if key!=leader}
        # Minimum 8 paired samples; uncertainty keeps contenders in the race.
        # The conclusion text differs by objective (t-approximation vs bootstrap),
        # so the test is on the shared prefix rather than one exact string.
        remaining=[key for key in active if key==baseline_key or key==leader or
                   not comparisons[key]['conclusion'].startswith('领先证据')]
        last=(leader,scores,seeds,list(active),comparisons)
        search.best=copy.deepcopy(entries[leader][1]); search.best_search=entries[leader][0]
        search.best_mean=scores[leader]; search.best_validation_count=count
        search.validation_seed_list=list(seeds)
        search.baseline_mean=scores[baseline_key]; search.baseline_validation_seeds=list(seeds)
        row=dict(candidate_count=len(active),seed_count=count,seeds=list(seeds),leader_key=leader,configuration_keys=list(active),
                 simulations=search.phase_simulations['validation'],comparisons=comparisons)
        search.statistical_review['rounds'].append(row)
        search.memory_rounds.append(row)
        # Preserve summaries for the image/ranking UI, with actual per-row seeds.
        for row in search.memory_evaluations:
            key=row['configuration_key']
            if key in scores: row.update(validation_mean=scores[key],validation_seeds=list(seeds))
        search.report('回忆共同种子复评轮次完成' if search.memory_total is not None else '自适应共同种子复评轮次完成',force=True)
        active=remaining
        unresolved=[key for key in active if key!=leader and key in eligible
                    and not comparisons[key]['conclusion'].startswith('领先证据')]
        if count>=8 and not unresolved:
            break # No unresolved eligible challenger; preserve budget for holdout.
    search.evaluation_limit=s.budget
    if last:
        leader,scores,seeds,active,comparisons=last
        ranking=sorted((key for key in active if key in eligible),key=lambda key:(-scores[key],key))
    else:
        ranking=sorted(eligible,key=lambda key:(-(entries[key][0] if entries[key][0] is not None else -math.inf),key))
        leader=ranking[0]
    search.search_champion=copy.deepcopy(entries[leader][1])
    search.search_champion_score=search.best_mean if last else entries[leader][0]
    search.search_champion_seeds=list(seeds) if last else list(search.search_seed_list)
    # Freeze three legal finalists plus a deduplicated baseline before holdout.
    finalists=ranking[:3]
    if baseline_key not in finalists:finalists.append(baseline_key)
    from src.optimizer.final_review import run_finals
    run_finals(search,entries,finalists,eligible,leader,baseline_key)


