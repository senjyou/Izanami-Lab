"""V2.9 layered/quick-only bare-position screening; no combat rules live here.

Two-seed early protection is deliberately permissive. Potential grants a test,
never admission. Every later decision uses a complete common 4/8-seed cohort.
"""
import math
import statistics
from src.optimizer import objective as obj
from src.optimizer.search import Stopped


class PreselectionBudgetError(Stopped):
    def __init__(self,count,cost,available):
        self.preselection_reason=f'预算不足以完成{count}种子站位筛选'
        super().__init__(f'{self.preselection_reason}：需要新增{cost}场，可用{available}场；'
                         '保留真实评分，未进入联合穷举，不使用不完整共同种子排名')


def enabled(settings):
    return settings.search_kind=='layered' and settings.review_strategy=='quick' and settings.layered_filter


def validate_seed_settings(settings):
    if enabled(settings) and (settings.layered_base_seeds!=2 or settings.layered_max_seeds!=4):
        raise ValueError('V2.9分层快速裸装预选固定采用2→4→8共同种子；'
                         '当前自定义基础/最大种子数不兼容。请将原裸装设置改为2/4，'
                         '或选择严谨复评；旧设置不会自动覆盖。')


def same_score(a,b):
    # No rounded display scores. Eight ULPs permit arithmetic noise only.
    return abs(a-b)<=max(1e-12,8*max(math.ulp(a),math.ulp(b)))


def at_least(score,line):
    return score>=line or same_score(score,line)


def four_qualification(scores,reference,drop_percent=3,objective="mean"):
    if len(scores)!=4 or set(scores)!=set(reference):
        raise ValueError('四种子资格必须使用完整相同的4个共同种子')
    # The rank value, not necessarily the mean: for objective="mean" rank_key IS
    # statistics.mean, so the validated V3.2 behaviour is unchanged.
    mean=obj.rank_key(list(scores.values()),objective)
    ref=obj.rank_key(list(reference.values()),objective)
    direct=at_least(mean,ref*(1-drop_percent/100))
    above=[s for s in sorted(scores) if scores[s]>reference[s]]  # Strict, same seed, never cross-seed maxima.
    return dict(four_mean=mean,four_reference_mean=ref,
        four_reference_gap=(ref-mean)/abs(ref) if ref else None,
        four_direct_qualified=direct,four_potential_qualified=not direct and bool(above),
        potential_above_reference_seeds=above,eight_review_qualified=direct or bool(above))


def eight_qualification(scores,reference,drop_percent=3,objective="mean"):
    if len(scores)!=8 or set(scores)!=set(reference):
        raise ValueError('八种子资格必须使用完整相同的8个共同种子')
    mean=obj.rank_key(list(scores.values()),objective)
    ref=obj.rank_key(list(reference.values()),objective)
    return dict(eight_mean=mean,eight_reference_mean=ref,
        eight_reference_gap=(ref-mean)/abs(ref) if ref else None,
        eight_qualified=at_least(mean,ref*(1-drop_percent/100)))


def competitive_selection(rows,top_count=12,drop_percent=5,rank_limit=60):
    ranked=sorted(rows,key=lambda row:(-row['eight_mean'],row['configuration_key']))
    top=ranked[:top_count]
    reference=statistics.mean(r['eight_mean'] for r in top) if top else None
    line=reference*(1-drop_percent/100) if reference is not None else None
    qualified=[r for r in ranked if at_least(r['eight_mean'],line)]
    cutoff=qualified[rank_limit-1]['eight_mean'] if len(qualified)>=rank_limit else None
    retained=qualified if len(qualified)<=rank_limit else [r for r in qualified if at_least(r['eight_mean'],cutoff)]
    kept={r['configuration_key'] for r in retained};passed={r['configuration_key'] for r in qualified}
    for row in ranked:
        row.update(final_line_qualified=row['configuration_key'] in passed,
                   admitted=row['configuration_key'] in kept,
                   final_reference_mean=reference,final_line=line)
        row['decision']=('通过8种子均分、最终分数线及名次并列规则，晋级' if row['admitted'] else
            '通过最终分数线，但落后晋级名次且不与边界同分，淘汰' if row['final_line_qualified'] else
            '未达到前列参考均分的最终晋级分数线，淘汰')
    return retained,dict(top_reference_count=len(top),top_reference_mean=reference,final_line=line,
        final_line_count=len(qualified),rank_cutoff_score=cutoff,
        extra_tie_count=max(0,len(retained)-rank_limit),final_admitted=len(retained))


def initial_diagnostics(settings):
    return dict(version=1,mechanism='V2.9分层快速裸装预选',stage='基础2种子',completed=False,
        base_completed=0,four_eligible=None,four_completed=0,four_direct_count=None,
        four_potential_count=None,four_rejected_count=None,eight_candidate_count=None,
        eight_evaluation_count=None,eight_completed=0,eight_qualified_count=None,
        top_reference_mean=None,final_line=None,final_line_count=None,rank_cutoff_score=None,
        extra_tie_count=None,final_admitted=None,expected_joint_configurations=None,
        seed_counts=[2,4,8],elite_percent=10,four_drop_percent=settings.layered_quick_four_drop_percent,
        eight_drop_percent=settings.layered_quick_eight_drop_percent,
        final_drop_percent=settings.layered_quick_final_drop_percent,
        top_count=settings.layered_quick_top_count,rank_limit=settings.layered_quick_rank_limit,
        approximate=True,global_optimality_proven=False)


def run(run):
    from src.optimizer.layered_search import elite_reference,reference_scores,elite_gate
    search=run.search;s=search.settings;info=run.quick_preselection
    objective=getattr(s,'objective','mean') or 'mean'
    base=run.base_seeds;four=[run.seed_base+i for i in range(4)];eight=[run.seed_base+i for i in range(8)]

    def cohort(rows,seeds,label,phase):
        count=len(seeds);cost=sum((r['configuration_key'],seed) not in search.cache for r in rows for seed in seeds)
        available=max(0,s.budget-search._budget_spent())
        info.update(stage=label,next_seed_count=count,next_cohort_count=len(rows),
                    next_cost=cost,available_budget=available)
        search.budget_plan.update(bare_next_seed_count=count,bare_next_cohort_count=len(rows),
            bare_next_cost=cost,bare_remaining_budget=available)
        run.stage=label;search.report(label+'；完整共同组预算检查',force=True)
        if cost>available:
            info.update(budget_insufficient=True,interruption_reason=f'预算不足以完成{count}种子站位筛选')
            raise PreselectionBudgetError(count,cost,available)
        search.budget_phase=phase;search.begin_stage(label,len(rows),cost)
        def refreshed(targets=rows):
            for row in targets:
                if search.cross_cohorts and hasattr(search.evaluator,'evaluate_cohorts'):
                    row['scores']={seed:search.cache[row['configuration_key'],seed] for seed in seeds
                                   if (row['configuration_key'],seed) in search.cache}
                    row['mean']=(obj.rank_key(list(row['scores'].values()),objective)
                                 if len(row['scores'])==len(seeds) else None)
                    row['spread']=max(row['scores'].values())-min(row['scores'].values()) if row['scores'] else None
                if all(seed in row['scores'] for seed in four):
                    row['four_mean']=obj.rank_key([row['scores'][seed] for seed in four],objective)
                if all(seed in row['scores'] for seed in eight):
                    row['eight_mean']=obj.rank_key([row['scores'][seed] for seed in eight],objective)
            info[{2:'base_completed',4:'four_completed',8:'eight_completed'}[count]]=sum(
                all(seed in r['scores'] for seed in seeds) for r in rows)
            search.stage_progress['completed_candidates']=info[{2:'base_completed',4:'four_completed',8:'eight_completed'}[count]]
        def completed(row,mean):
            row['mean']=mean
            refreshed([row])
            search.heartbeat()
            search.report(label)
        try:
            if search.cross_cohorts and hasattr(search.evaluator,'evaluate_cohorts'):
                search.current_operation='裸装站位共同种子预选'
                search.evaluate_cohorts(((row,run.state(row['positions'],[]),seeds) for row in rows),completed)
            else:
                for row in rows:
                    try:run._score_bare(row,seeds)
                    finally:refreshed([row])
                    search.heartbeat();search.report(label)
        finally:refreshed()

    for positions in run.positions.configurations:
        run.bare.append(dict(positions=list(positions),configuration_key=search._key(run.state(positions,[])),
            scores={},decision='尚未完成完整共同种子预选',admitted=None,
            base_mean=None,four_mean=None,four_reference_gap=None,four_direct_qualified=None,
            four_potential_qualified=None,eight_review_qualified=None,eight_mean=None,
            eight_qualified=None,final_line_qualified=None,reference_only=None))
    cohort(run.bare,base,'裸装基础2种子','basic')
    run.elite=elite_reference(run.bare,base)
    elite_keys={r['configuration_key'] for r in run.elite}
    ref2=reference_scores(run.elite)
    early_threshold=s.layered_drop_percent/100
    selected=[]
    for row in run.bare:
        gate=elite_gate(row['scores'],run.elite,early_threshold,ref2)
        row.update(base_mean=row['mean'],elite_reference_member=row['configuration_key'] in elite_keys,early_gate=gate,gate=gate)
        allowed=(row['elite_reference_member'] or gate['uncertain'] or gate['gap'] is None or
                 gate['gap']<=max(.15,early_threshold+.05)+1e-12)
        row['four_review_qualified']=allowed
        if allowed:selected.append(row)
        else:row.update(admitted=False,decision='未通过宽松2种子早期复查，经验性淘汰')
    selected.sort(key=lambda row:(not row['elite_reference_member'],-row['base_mean'],row['configuration_key']))
    info.update(elite_count=len(run.elite),elite_keys=sorted(elite_keys),four_eligible=len(selected),
                early_rejected=len(run.bare)-len(selected))
    run.early=info['early_rejected']
    run.preselection_diagnostics=dict(elite_count=len(run.elite),elite_keys=sorted(elite_keys),
        initial_leader_score=max(r['base_mean'] for r in run.bare),
        initial_elite_mean=obj.rank_key(list(ref2.values()),objective))
    cohort(selected,four,'裸装完整4种子复查','refinement')
    ref4=reference_scores(run.elite)
    eligible=[]
    for row in selected:
        row.update(four_qualification(row['scores'],ref4,s.layered_quick_four_drop_percent,objective))
        if row['eight_review_qualified']:eligible.append(row)
        else:row.update(admitted=False,decision='4种子均分未达要求，且无单场严格超过同种子精英参考，淘汰')
    direct=sum(r['four_direct_qualified'] for r in selected)
    potential=sum(r['four_potential_qualified'] for r in selected)
    objects={r['configuration_key']:r for r in [*run.elite,*eligible]}
    to_evaluate=sorted(objects.values(),key=lambda row:(not row['elite_reference_member'],row['configuration_key']))
    eligible_keys={r['configuration_key'] for r in eligible}
    for row in to_evaluate:row['reference_only']=row['configuration_key'] not in eligible_keys
    info.update(four_direct_count=direct,four_potential_count=potential,four_rejected_count=len(selected)-len(eligible),
        reference_four_mean=obj.rank_key(list(ref4.values()),objective),reference_four_scores=ref4,
        eight_candidate_count=len(eligible),eight_evaluation_count=len(to_evaluate))
    search.budget_plan.update(bare_four_eligible=len(selected),bare_eight_candidates=len(eligible),
        bare_eight_reference_only=len(to_evaluate)-len(eligible),
        estimated_joint_before_final_selection=len(eligible)*run.memories.total)
    cohort(to_evaluate,eight,'裸装统一8种子评价','refinement')
    ref8=reference_scores(run.elite)
    finalists=[]
    for row in to_evaluate:
        row['eight_mean']=obj.rank_key(list(row['scores'].values()),objective)
        if not row['reference_only']:
            row.update(eight_qualification(row['scores'],ref8,s.layered_quick_eight_drop_percent,objective))
            if row['eight_qualified']:finalists.append(row)
            else:row.update(admitted=False,decision='8种子均分未达到精英参考要求，淘汰；不再保护历史单场高分')
        else:row.update(eight_qualified=False,decision='精英参考专用评价；未获4种子候选资格，不因精英身份晋级')
    kept,final_info=competitive_selection(finalists,s.layered_quick_top_count,
        s.layered_quick_final_drop_percent,s.layered_quick_rank_limit)
    run.admitted=[tuple(r['positions']) for r in kept]
    info.update(final_info,eight_qualified_count=len(finalists),
        reference_eight_mean=obj.rank_key(list(ref8.values()),objective),
        reference_eight_scores=ref8,expected_joint_configurations=len(kept)*run.memories.total,
        completed=True,stage='裸装竞争性筛选完成',next_seed_count=None,next_cohort_count=0,next_cost=0,
        available_budget=max(0,s.budget-search._budget_spent()))
    search.budget_plan.update(bare_next_seed_count=None,bare_next_cohort_count=0,bare_next_cost=0,
        bare_remaining_budget=max(0,s.budget-search._budget_spent()),
        bare_preselection_completed=True,bare_final_admitted=len(kept))
    run.preselection_complete=True
    run.preselection_diagnostics.update(reference_seeds=eight,
        final_elite_mean=obj.rank_key(list(ref8.values()),objective),actual_admitted=len(kept))
    run.stage=info['stage']
