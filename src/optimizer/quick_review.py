"""Shared empirical reviews. Caps are search heuristics, never significance tests."""
import copy
import math
import statistics
from src.optimizer import objective as obj

LOOKS=(8,16,32,64,128,256)
CAPS=(64,32,16,8,4,4)
GAPS=(.05,.03,.02,.01,.005,.005)
NOISE_MULTIPLIER=3.


def plan(maximum=128):
    return [(n,cap,gap) for n,cap,gap in zip(LOOKS,CAPS,GAPS) if n<=maximum]


def planned_cost(candidate_count, maximum=128):
    """Upper cost under declared caps; no evaluations and no cardinality allocation."""
    active=candidate_count;previous=0;cost=0
    for n,cap,_ in plan(maximum):
        cost+=active*(n-previous)
        active=min(active,cap+1)  # a separate, always-retained manual control
        previous=n
    return cost


def empirical_gap(left,right,ratio,objective="mean"):
    n=len(left)
    if n!=len(right):raise ValueError('快速配对比较必须使用相同共同种子')
    if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in (*left,*right)):
        return dict(seed_count=n,mean_difference=None,descriptive_standard_error=None,
            gap_ratio=ratio,empirical_eliminated=False,interval=None,
            conclusion='分数/标准误无效，保守保留；非统计证明',uncertainty_priority=None)
    if obj.needs_resampling(objective):
        # Roll5 is a statistic over the whole cohort, so a per-seed difference cannot
        # carry it: the gap and its error come from resampling the shared seeds.
        gap_abs,se,_=obj.paired_gap(left,right,objective)
        reference=obj.rank_key(left,objective)
        mean=gap_abs
        valid=n>=8 and se is not None and math.isfinite(se) and reference>0
        cut=bool(valid and mean is not None and mean>max(ratio*reference,NOISE_MULTIPLIER*se))
        return dict(seed_count=n,mean_difference=mean,descriptive_standard_error=se,
            gap_ratio=ratio,empirical_eliminated=cut,interval=None,
            conclusion='经验分差淘汰，非统计证明' if cut else '波动/样本保护，暂无法统计区分',
            uncertainty_priority=(mean-NOISE_MULTIPLIER*se
                if (se is not None and math.isfinite(se) and mean is not None) else None))
    diff=[a-b for a,b in zip(left,right)]
    mean=statistics.mean(diff) if diff else None
    reference=statistics.mean(left) if left else None
    se=statistics.stdev(diff)/math.sqrt(n) if n>=2 else None
    valid=n>=8 and se is not None and math.isfinite(se) and reference>0
    cut=valid and mean>max(ratio*reference,NOISE_MULTIPLIER*se)
    return dict(seed_count=n,mean_difference=mean,descriptive_standard_error=se,
        gap_ratio=ratio,empirical_eliminated=cut,interval=None,
        conclusion='经验分差淘汰，非统计证明' if cut else '波动/样本保护，暂无法统计区分',
        uncertainty_priority=(mean-NOISE_MULTIPLIER*se if se is not None and math.isfinite(se) else None))


def retain(keys,eligible,leader,baseline,means,comparisons,cap):
    """75% mean / 25% plausible challengers, deterministic; leader/control survive."""
    survivors=[k for k in keys if k in eligible and (k==leader or not comparisons[k]['empirical_eliminated'])]
    ranked=sorted(survivors,key=lambda k:(-means[k],k))
    selected=ranked[:max(1,math.ceil(cap*.75))]
    uncertain=sorted((k for k in survivors if k not in selected),
                     key=lambda k:((comparisons[k]['uncertainty_priority'] if comparisons[k]['uncertainty_priority'] is not None else -math.inf),-means[k],k))
    selected+=uncertain[:max(0,cap-len(selected))]
    selected=list(dict.fromkeys([leader,*selected]))[:cap]
    if baseline in keys and baseline not in selected:selected.append(baseline)
    decisions={k:('晋级' if k in selected else '经验分差淘汰，非统计证明'
        if comparisons[k]['empirical_eliminated'] else '目标人数限制淘汰；统计上仍可能无法区分') for k in keys}
    return sorted(selected),decisions


def review(search,candidates,baseline_eligible,reserve,*,round_plan=None):
    s=search.settings;baseline=search._key(search.original)
    entries=dict(candidates)
    entries.setdefault(baseline,(search.baseline_search,copy.deepcopy(search.original)))
    eligible={k for k in candidates if k!=baseline or baseline_eligible}
    if not eligible:return
    looks=round_plan if round_plan is not None else plan(s.quick_max_seeds)
    search.statistical_review=dict(method='快速经验分差与波动保护＋目标人数限制（非统计证明）',
        strategy='quick',noise_multiplier=NOISE_MULTIPLIER,planned_looks=[x[0] for x in looks],
        caps=[x[1] for x in looks],gap_ratios=[x[2] for x in looks],rounds=[],candidate_keys=sorted(entries),
        assumptions='允许名额淘汰仍无法区分的候选；非95%置信证明，不保证全局最优')
    # Original rigorous reservation leaves four samples per participant. Quick
    # starts at eight: reserve finals only after allowing that complete cohort.
    reserve=min(reserve,max(0,s.budget-search._budget_spent()-len(entries)*looks[0][0]))
    search.budget_plan.update(independent_reserved=reserve,statistical_policy=search.statistical_review['method'])
    search.evaluation_limit=s.budget-reserve;search.budget_phase='validation'
    active=sorted(entries);last=None
    try:
        for index,(count,cap,gap) in enumerate(looks,1):
            seeds=[s.seed+100000+i for i in range(count)]
            cost=sum((k,seed) not in search.cache for k in active for seed in seeds)
            search.statistical_review['progress']=dict(round=index,seed_count=count,participants=len(active),
                next_cost=cost,remaining_budget=max(0,search.evaluation_limit-search._budget_spent()),
                ranking_basis='本轮完整共同种子均分',maximum=s.quick_max_seeds)
            if cost+search._budget_spent()>search.evaluation_limit:
                search.statistical_review['stopping_detail']=dict(reason='预算不足下一完整快速共同种子轮次',
                    next_seed_count=count,needed_battles=cost,available_battles=max(0,search.evaluation_limit-search._budget_spent()))
                break
            search.begin_stage('快速经验复评',len(active),cost,index)
            if hasattr(search,'layered_run'):search.layered_run.stage=f'快速复评 {count}共同种子'
            means={}
            def evaluated(key,mean):
                means[key]=mean
                search.stage_progress['completed_candidates']+=1;search.heartbeat()
            search.evaluate_cohorts(((key,entries[key][1],seeds) for key in active),evaluated)
            ranking=sorted((k for k in active if k in eligible),key=lambda k:(-means[k],k))
            leader=ranking[0]
            _objective=getattr(s,'objective','mean') or 'mean'
            comparisons={k:empirical_gap([search.cache[leader,x] for x in seeds],
                [search.cache[k,x] for x in seeds],gap,_objective) for k in active if k!=leader}
            remaining,decisions=retain(active,eligible,leader,baseline,means,comparisons,cap)
            row=dict(candidate_count=len(active),seed_count=count,seeds=seeds,leader_key=leader,
                configuration_keys=list(active),means=means,comparisons=comparisons,
                advanced_keys=remaining,decisions=decisions,advanced_count=len(remaining),
                eliminated_count=len(active)-len(remaining),cap=cap,gap_ratio=gap,
                simulations=search.phase_simulations['validation'],completed=True)
            search.statistical_review['rounds'].append(row);search.memory_rounds.append(row)
            search.statistical_review['progress'].update(advanced=len(remaining),eliminated=len(active)-len(remaining),
                max_reached=count==looks[-1][0],remaining_budget=max(0,search.evaluation_limit-search._budget_spent()))
            if index<len(looks):
                next_count=looks[index][0]
                search.statistical_review['progress'].update(next_seed_count=next_count,
                    next_cost=sum((k,x) not in search.cache for k in remaining for x in range(s.seed+100000,s.seed+100000+next_count)))
            else:search.statistical_review['progress'].update(next_seed_count=None,next_cost=0)
            last=(leader,means,seeds,list(active))
            search.best=copy.deepcopy(entries[leader][1]);search.best_search=entries[leader][0]
            search.best_mean=means[leader];search.best_validation_count=count;search.validation_seed_list=list(seeds)
            search.baseline_mean=means[baseline];search.baseline_validation_seeds=list(seeds)
            for record in search.memory_evaluations:
                if record['configuration_key'] in means:
                    record.update(validation_mean=means[record['configuration_key']],validation_seeds=list(seeds))
            search.report('快速复评轮次完成；经验淘汰不等于统计排除',force=True)
            active=remaining
            if len([k for k in active if k in eligible])<=4:
                search.statistical_review['stopping_detail']=dict(reason='候选较少，提前冻结进入独立决赛')
                break
    finally:
        search.evaluation_limit=s.budget
    if last:
        leader,means,seeds,_=last
        ranking=sorted((k for k in active if k in eligible),key=lambda k:(-means[k],k))
    else:
        ranking=sorted(eligible,key=lambda k:(-(entries[k][0] if entries[k][0] is not None else -math.inf),k))
        leader=ranking[0];seeds=list(search.search_seed_list)
    search.search_champion=copy.deepcopy(entries[leader][1])
    search.search_champion_score=last[1][leader] if last else entries[leader][0]
    search.search_champion_seeds=list(seeds)
    if not last:
        # Never use the two-seed base rank to quietly shrink the independent
        # modes' pool. All candidates must receive a complete first quick look.
        search.statistical_review['finals_skipped']='预算不足完整首轮8种子；保留基础覆盖，未筛选少数候选进行决赛'
        return
    finalists=ranking[:3]
    if baseline not in finalists:finalists.append(baseline)
    from src.optimizer.final_review import run_finals
    if hasattr(search,'layered_run'):search.layered_run.stage='独立决赛'
    run_finals(search,entries,finalists,eligible,leader,baseline)


