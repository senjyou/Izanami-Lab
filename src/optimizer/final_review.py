"""Frozen 50 + 100 common-seed finals, Bonferroni over all frozen pairs/two looks.
No combat rules live here. Missing a complete stage never publishes its winner.
"""
import copy
import math
import time
from src.optimizer.budget import INITIAL_SEEDS, EXTRA_SEEDS


def relative_gap(leader,other):
    if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in (leader,other)) or leader==0:return None
    return abs(leader-other)/abs(leader)


def run_finals(search,entries,finalists,eligible,champion,baseline):
    from src.optimizer.statistical_review import paired_summary
    finalists=list(dict.fromkeys(finalists))
    pairs=max(1,len(finalists)*(len(finalists)-1)//2)
    alpha=.05/(pairs*2)  # fixed BEFORE seeing either independent stage
    used={seed for _,seed in search.cache}.union(search.search_seed_list)
    planned=[];seed=search.settings.seed+1000000000
    while len(planned)<INITIAL_SEEDS+EXTRA_SEEDS:
        if seed not in used:planned.append(seed)
        seed+=1
    count=min(INITIAL_SEEDS,max(0,search.settings.budget-search._budget_spent())//len(finalists))
    info=dict(version=2,status='独立验证样本不足',frozen=True,candidate_keys=finalists,
        search_champion_key=champion,initial_winner_key=None,winner_key=None,
        seeds=[],planned_seeds=planned[:count],seed_count=0,target_seed_count=count,
        initial_target=INITIAL_SEEDS,extra_target=EXTRA_SEEDS,initial_completed=False,
        extra_triggered=False,extra_executed=False,extra_candidate_keys=[],rounds=[],
        candidates=[],comparisons=[],all_candidates=[],budget_limited=count<INITIAL_SEEDS,
        limitation='预算不足50种子；在取样前冻结降级数量' if count<INITIAL_SEEDS else '',
        statistical_plan=dict(planned_looks=[50,150],effective_initial_look=count,
            alpha_family=.05,alpha_per_comparison=alpha,frozen_pair_count=pairs,
            correction='全部冻结候选配对×2观察点Bonferroni；降级初评数量在取样前固定，仍用两观察点校正'),
        all_planned_seeds=list(planned),initial_planned_seeds=planned[:count],extra_planned_seeds=planned[INITIAL_SEEDS:],
        assumptions='独立且近似正态配对差值；重尾下不保证严格有效性；未进入决赛/加赛者未被严格排除，非全局最优证明')
    search.independent_validation=info
    if not count:return
    search.budget_phase='independent'

    def phase(name,keys,seeds,new_seeds):
        start=time.monotonic()
        current=dict(name=name,candidate_keys=list(keys),seeds=[],planned_seeds=list(seeds),
            seed_count=0,target_seed_count=len(seeds),completed=False,candidates=[],comparisons=[],winner_key=None)
        info['active_phase']=current
        info.update(planned_seeds=list(seeds),target_seed_count=len(seeds))
        cost=sum((key,seed) not in search.cache for key in keys for seed in seeds)
        search.begin_stage(name,len(keys),cost)
        search.current_operation=name
        search.report(name+'；保留上一完整阶段',force=True)
        try:
            means={}
            def evaluated(key,mean):
                means[key]=mean
                search.stage_progress['completed_candidates']+=1;search.heartbeat()
            search.evaluate_cohorts(((key,entries[key][1],seeds) for key in keys),evaluated)
            valid=[key for key in keys if key in eligible]
            winner=min(valid,key=lambda key:(-means[key],key))
            with search.performance.measure('statistical_compute_seconds'):
                values=[search.cache[winner,seed] for seed in seeds]
                comparisons=[dict(configuration_key=key,eligible=key in eligible,
                    relative_gap=relative_gap(means[winner],means[key]),
                    **paired_summary(values,[search.cache[key,seed] for seed in seeds],alpha)) for key in keys if key!=winner]
            relevant=[row for row in comparisons if row['eligible']]
            status=('独立验证样本不足' if len(seeds)<8 else '仅一个合法配置，无竞争者' if len(valid)==1 else
                '领先证据较充分（配对t近似假设下）' if all(row['conclusion'].startswith('领先证据') for row in relevant) else '暂无法区分')
            candidates=[dict(configuration_key=key,state=copy.deepcopy(entries[key][1]),mean=means[key],
                seeds=list(seeds),seed_count=len(seeds),eligible=key in eligible,
                mean_gap=means[key]-means[winner],difference_percent=(100*(means[key]-means[winner])/abs(means[winner]) if means[winner] else None),relative_gap=relative_gap(means[winner],means[key])) for key in keys]
            current.update(completed=True,seeds=list(seeds),seed_count=len(seeds),winner_key=winner,
                candidates=candidates,comparisons=comparisons,status=status,
                completed_battles=sum((key,seed) in search.cache for key in keys for seed in new_seeds))
            if search.performance.enabled:
                name_key='independent_initial_wall_seconds' if name=='独立初评' else 'independent_extra_wall_seconds'
                search.performance.seconds[name_key]=time.monotonic()-start
            info['rounds'].append(copy.deepcopy(current))
            info.update(seeds=list(seeds),seed_count=len(seeds),winner_key=winner,
                candidates=candidates,comparisons=comparisons,status=status,
                search_champion_overturned=winner!=champion)
            if name=='独立初评':
                info.update(initial_winner_key=winner,initial_completed=len(seeds)==INITIAL_SEEDS)
            else:
                info.update(extra_executed=True,extra_status='100新种子加赛完成',initial_leader_overturned=winner!=info['initial_winner_key'])
            # Latest per-candidate sample records retain 50-only non-finalists.
            by_key={row['configuration_key']:row for row in info['all_candidates']}
            by_key.update({row['configuration_key']:row for row in candidates})
            info['all_candidates']=list(by_key.values())
            for row in search.memory_evaluations:
                key=row['configuration_key']
                if key in means:
                    row.setdefault('independent_stages',[]).append(dict(phase=name,mean=means[key],seeds=list(seeds)))
                    row.update(independent_mean=means[key],independent_seeds=list(seeds))
            search.best=copy.deepcopy(entries[winner][1]);search.best_search=entries[winner][0]
            search.best_mean=means[winner];search.best_validation_count=len(seeds)
            search.validation_seed_list=list(seeds)
            if baseline in means:
                search.baseline_mean=means[baseline];search.baseline_validation_seeds=list(seeds)
            else:
                search.baseline_mean=None  # never compare a 50-seed baseline with a 150-seed winner
            search.report(name+'完成；'+status,force=True)
            return winner,means,comparisons
        except Exception:
            if not current['completed']:
                current['interrupted']=True
                info['extra_status']='加赛未完成；保留初评' if name=='决赛加赛' else '初评未完成；保留统计复评结果'
            current.update(completed_battles=sum((key,seed) in search.cache for key in keys for seed in new_seeds))
            raise

    winner,means,comparisons=phase('独立初评',finalists,planned[:count],planned[:count])
    info['initial_winner_key']=winner;info['initial_completed']=count==INITIAL_SEEDS
    if count<INITIAL_SEEDS:
        info['extra_status']='初评未满50种子，不安排加赛';return
    challengers=[];reasons={}
    for row in comparisons:
        if not row['eligible']:continue
        close=row['relative_gap'] is not None and row['relative_gap']<.01
        uncertain=not row['conclusion'].startswith('领先证据')
        if close or uncertain:
            challengers.append(row['configuration_key'])
            reasons[row['configuration_key']]=dict(relative_gap_under_one_percent=close,paired_uncertain=uncertain)
    if not challengers:
        info['extra_status']='无符合加赛条件的合法竞争者';return
    extra=list(dict.fromkeys([winner,*challengers,baseline])) # baseline remains a common-seed control
    info.update(extra_triggered=True,extra_candidate_keys=extra,extra_trigger_reasons=reasons)
    needed=len(extra)*EXTRA_SEEDS
    available=search.settings.budget-search._budget_spent()
    if available<needed:
        info.update(budget_limited=True,extra_status='预算不足以追加完整100共同种子；保留初评',
            extra_needed_battles=needed,extra_available_battles=available,
            limitation='未新增非预定检验点，不把50种子结果标为150种子')
        return
    info['extra_status']='正在追加100共同种子'
    phase('决赛加赛',extra,planned,planned[INITIAL_SEEDS:])
    info.update(extra_executed=True,extra_status='100新种子加赛完成',initial_leader_overturned=info['winner_key']!=winner)
