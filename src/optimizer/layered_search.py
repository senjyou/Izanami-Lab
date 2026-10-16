"""Position-first approximate joint coverage, on the original budget/cache ledger.

Bare scores never enter the equipped champion race. All percentages here are
declared search heuristics, not tests of true expected damage or global optimality.
"""
import copy
import math
import random
import statistics
import time
from src.optimizer import objective as obj

from src.optimizer.model import prepare_search_snapshot
from src.optimizer.position_search import PositionSpace
from src.optimizer.memory_search import MemorySpace


def crossed_indices(position_count, memory_count, seed):
    """Lazy reproducible balanced Latin sweep: no replacement, no full expansion."""
    rng=random.Random(seed)
    positions=list(range(position_count));rng.shuffle(positions)
    # A coprime affine permutation also handles enormous C(n,k) memory spaces
    # without allocating a list proportional to their cardinality.
    offset=rng.randrange(memory_count)
    stride=rng.randrange(1,memory_count) if memory_count>1 else 1
    while math.gcd(stride,memory_count)!=1:stride+=1
    for step in range(memory_count):
        for index,p in enumerate(positions):
            yield p,(offset+(step+index)*stride)%memory_count


def paired_gate(candidate, reference, threshold, objective="mean"):
    """Small-sample uncertainty guard; explicitly NOT a confidence interval.

    Every comparison uses only the same seed intersection. Positive losses mean
    outside the user threshold. Crossing or two descriptive standard errors
    protects a noisy boundary; zero/nonpositive reference disables percentage cuts.

    Under ``mean`` this is byte-for-byte the ported behaviour. Under ``roll5`` the
    per-seed loss cannot carry the comparison -- Roll5 reads the spread across seeds,
    not any single seed -- so the gap and its error come from resampling the shared
    seeds instead (:func:`objective.paired_gap`).
    """
    seeds=sorted(candidate.keys() & reference.keys())
    if len(seeds)<2:
        return dict(gap=None,uncertain=True,reason='共同样本不足，保守保留',seeds=seeds)
    a=[candidate[s] for s in seeds];b=[reference[s] for s in seeds]
    leader=obj.rank_key(b,objective)
    if leader<=0:
        return dict(gap=None,uncertain=True,reason='共同种子领先参考非正，禁用百分比淘汰',seeds=seeds)
    gap=(leader-obj.rank_key(a,objective))/leader
    if obj.needs_resampling(objective):
        gap_abs,noise,n=obj.paired_gap(b,a,objective)
        margin=gap_abs-threshold*leader if gap_abs is not None else None
        mean=margin if margin is not None else 0.0
        noise=noise if noise else 0.0
        uncertain=(mean>0 and (noise<=0 or mean<=2*noise))
        losses=[mean]
    else:
        losses=[y*(1-threshold)-x for x,y in zip(a,b)]
        mean=statistics.mean(losses)
        noise=statistics.stdev(losses)/math.sqrt(len(losses))
        # A seemingly stable lucky first two outcomes may be contradicted by the
        # leader's later samples. Restore the excluded contender's common cohort
        # instead of permanently cutting it against a stale two-seed reference.
        uncertain=mean>0 and (min(losses)<=0 or mean<=2*noise)
    reference_shift=(len(reference)>len(seeds) and
                     abs(leader-obj.rank_key(list(reference.values()),objective))>.10*abs(leader))
    uncertain=uncertain or (mean>0 and reference_shift)
    return dict(gap=gap,uncertain=uncertain,seeds=seeds,
                reference_shift_guard=reference_shift,
                paired_mean_loss=mean,descriptive_standard_error=noise,
                reason='领先者追加样本漂移，恢复共同样本，非统计证明' if reference_shift else
                       '少样本波动/临界保护，非统计证明' if uncertain else '共同种子经验阈值')


def elite_reference(rows, seeds, objective="mean"):
    """Freeze the top 10% on the identical initial cohort, never mixed means."""
    ranked=sorted(rows,key=lambda row:(-obj.rank_key([row['scores'][s] for s in seeds],objective),
                                       row['configuration_key']))
    return ranked[:max(1,math.ceil(len(rows)*.1))]


def reference_scores(elite):
    """The elite reference as a PER-SEED series.

    Deliberately still a plain mean: each entry is the elite group's average on one
    seed, so this builds a reference series rather than ranking candidates. The
    objective is applied to that series by the callers that rank with it.
    """
    common=set.intersection(*(set(row['scores']) for row in elite))
    return {seed:statistics.mean(row['scores'][seed] for row in elite) for seed in sorted(common)}


def elite_gate(candidate,elite,threshold,reference=None,objective="mean"):
    gate=paired_gate(candidate,reference if reference is not None else reference_scores(elite),
                     threshold,objective)
    incomplete=len({len(row['scores']) for row in elite})>1
    gate['elite_cohort_incomplete']=incomplete
    if incomplete:
        gate.update(uncertain=True,reason='精英追加样本未形成完整共同组，保守保留；非统计证明')
    return gate


class LayeredRun:
    def __init__(self,search):
        self.search=search;s=search.settings
        # Every stage ranks by this. "mean" reproduces the ported V3.2 ordering
        # exactly; "roll5" adds the expected-best-of-five uplift.
        self.objective=getattr(s,'objective','mean') or 'mean'
        self.template=prepare_search_snapshot(search.original,search.constraints,
            getattr(search.evaluator,'loader',None),search.initialization_notes,
            change_fifth=False,change_memories=True,change_affixes=False)
        self.positions=PositionSpace(self.template,search.constraints)
        self.memories=MemorySpace(self.template,search.constraints)
        self.bare=[];self.joint=[];self.admitted=[]
        self.stage='裸装基础初评';self.complete=False;self.preselection_complete=False
        self.seed_base=s.seed+200000000
        self.base_seeds=[self.seed_base+i for i in range(s.layered_base_seeds)]
        self.joint_seeds=[s.seed+i for i in range(s.layered_joint_seeds)]
        self.joint_total=None;self.joint_covered=0
        self.preview=[];self.review_count=0;self.early=0
        self.elite=[];self.preselection_diagnostics={}
        self.joint_admission=None
        self.position_memories=None;self.joint_basic_started=None
        self.memory_pruning=dict(version=1,enabled=s.layered_memory_pruning,
            theoretical_joint_before_preselection=self.positions.total*self.memories.total,
            planning_complete=False,original_joint_total=None,actual_joint_total=None,
            excluded_joint_configurations=None,fallback_positions=0,position_records=[])
        from src.optimizer.bare_preselection import enabled,validate_seed_settings,initial_diagnostics
        validate_seed_settings(s)
        self.quick_preselection=initial_diagnostics(s) if enabled(s) else None
        self.search.baseline_satisfies_constraints=(self.positions.contains(search.original['friend_positions'])
            and set(search.original['memory_ids'])>=self.memories.required
            and set(search.original['memory_ids'])<=set(self.memories.pool)|self.memories.required)

    def state(self,positions,memories):
        # Fixed inputs are shared read-only. Evaluators use active_snapshot before
        # constructing units; result publication deep-copies the bounded preview.
        return dict(self.template,friend_positions=list(positions),memory_ids=list(memories))

    def report_fields(self,final,heartbeat=False):
        search=self.search;s=search.settings
        cohorts={str(n):sum(len(row['scores'])>=n for row in self.bare)
                 for n in range(s.layered_base_seeds,(8 if self.quick_preselection else s.layered_max_seeds)+1)}
        spent=search._budget_spent();remaining=max(0,s.budget-spent)
        naked=sum(len(row['scores']) for row in self.bare)
        remaining_basic=(max(0,(self.joint_total or 0)-self.joint_covered)*len(self.joint_seeds)
                         if self.joint_total is not None else None)
        seconds=search.done/max(.001,time.monotonic()-search.started)
        info=dict(version=1,stage=self.stage,position_total=self.positions.total,
            bare_covered=cohorts[str(s.layered_base_seeds)],bare_seed_progress=cohorts,
            bare_actual_battles=naked,preselection_complete=self.preselection_complete,
            plan_completed=self.complete,
            early_eliminated=self.early,boundary_uncertain=sum(r.get('gate',{}).get('uncertain',False) for r in self.bare),
            admitted_positions=len(self.admitted) if self.preselection_complete else None,
            legal_memory_combinations=self.memories.total,joint_total=self.joint_total,
            joint_covered=self.joint_covered,joint_coverage=(self.joint_covered/self.joint_total if self.joint_total else None),
            joint_basic_complete=self.joint_total is not None and self.joint_covered==self.joint_total,
            joint_basic_seed_count=len(self.joint_seeds),remaining_basic_cost=remaining_basic,
            budget_spent=spent,remaining_budget=remaining,filter_enabled=s.layered_filter,
            allowed_drop_percent=s.layered_drop_percent,review_candidates=self.review_count,
            best_is_evaluated=any(row['basic_mean'] is not None for row in self.joint),
            review_percent=s.layered_review_percent,basic_seed_list=list(self.base_seeds),
            joint_seed_list=list(self.joint_seeds),resume_supported=False,
            position_filter_approximate=s.layered_filter,
            approximate=s.layered_filter or s.layered_review_percent<100,global_optimality_proven=False,
            score_semantics='原战术演习total_score：对敌伤害减敌方回复；非纯伤害',
            remaining_basic_seconds=(remaining_basic/seconds if seconds>0 and remaining_basic is not None else None),
            unused_budget_reason=('已完成预算内预定复评/决赛计划；不增加未预定检验点，不强制重复模拟' if self.complete else
                '仍有未完成阶段或共同种子组；请查看结束原因和真实覆盖数量'),
            limitation='裸装筛选和基础排名入围是经验性近似；未入围不等于统计排除；完整覆盖不证明期望分数全局最优')
        info.update(elite_reference=self.preselection_diagnostics,review_strategy=s.review_strategy,
                    quick_max_seeds=s.quick_max_seeds)
        pruning=dict(self.memory_pruning)
        pruning.update(joint_basic_actual_battles=(search.phase_simulations['basic']-self.joint_basic_started
            if self.joint_basic_started is not None else 0),
            review_actual_battles=search.phase_simulations['validation'],
            independent_actual_battles=search.phase_simulations['independent'],
            elapsed=time.monotonic()-search.started,actual_throughput=seconds,remaining_budget=remaining)
        if heartbeat:pruning.pop('position_records',None)
        info['memory_pruning']=pruning
        if self.joint_admission is not None:
            admission=dict(self.joint_admission)
            rounds=(search.statistical_review or {}).get('rounds',[])
            eight=next((row for row in rounds if row.get('seed_count')==8 and row.get('completed')),None)
            admission['first_eight_round_published']=eight is not None
            seeds=admission.get('first_eight_seeds',[])
            keys=admission.get('first_eight_configuration_keys',[])
            admission['first_eight_actual_samples']=sum((key,seed) in search.cache for key in keys for seed in seeds)
            admission['first_eight_fully_evaluated_candidates']=sum(all((key,seed) in search.cache for seed in seeds) for key in keys) if seeds else 0
            admission['first_eight_completed']=bool(keys and seeds and admission['first_eight_fully_evaluated_candidates']==len(keys))
            if heartbeat:admission.pop('extra_protected_configurations',None);admission.pop('first_eight_configuration_keys',None)
            info['joint_admission']=admission
        if self.quick_preselection is not None:info['quick_preselection']=self.quick_preselection
        if self.complete and s.review_strategy=='quick':
            info['unused_budget_reason']='快速复评与独立决赛计划完成，剩余预算未强制使用。'
        if heartbeat:return dict(layered=info)
        preview=self.preview
        if self.stage=='联合配置基础覆盖':
            preview=[dict(configuration_key=k,state=state,positions=list(state['friend_positions']),
                memory_ids=list(state['memory_ids']),basic_mean=score,basic_seeds=list(self.joint_seeds),eligible=True)
                for k,(score,state) in search.elite.items()]
        fields=dict(layered=info,joint_candidate_template=copy.deepcopy(self.template),
                    memory_evaluations=[] if final else preview)
        fields['combined_champion']=getattr(search,'combined_champion',None)
        if final:
            # Complete compact states = shared immutable template + own positions
            # and memories. This is a lossless snapshot, never winner substitution.
            fields['joint_candidate_records']=self.joint
            fields['bare_position_records']=self.bare
            keys={row['configuration_key'] for row in self.joint}
            fields['joint_seed_scores']=[dict(configuration_key=k,seed=seed,score=score)
                for (k,seed),score in search.cache.items() if k in keys]
        return fields

    def _score_bare(self,row,seeds):
        search=self.search
        search.current_operation='裸装站位共同种子预选'
        try:search.estimate(self.state(row['positions'],[]),seeds)
        finally:
            row['scores']={seed:search.cache[row['configuration_key'],seed] for seed in seeds
                           if (row['configuration_key'],seed) in search.cache}
            row['mean']=obj.rank_key(list(row['scores'].values()),self.objective) if row['scores'] else None
            row['spread']=max(row['scores'].values())-min(row['scores'].values()) if row['scores'] else None

    def _leader(self):
        # Reference is selected only inside the largest complete common cohort.
        n=max(len(row['scores']) for row in self.bare)
        cohort=[r for r in self.bare if len(r['scores'])==n]
        return min(cohort,key=lambda r:(-r['mean'],r['configuration_key']))

    def preselect(self):
        search=self.search;s=search.settings
        if self.quick_preselection is not None:
            from src.optimizer.bare_preselection import run
            run(self)
            self._plan_joint()
            return
        search.budget_phase='basic'
        search.begin_stage('裸装站位基础初评',self.positions.total,self.positions.total*len(self.base_seeds))
        for positions in self.positions.configurations:
            row=dict(positions=list(positions),configuration_key=search._key(self.state(positions,[])),scores={},decision='尚未完成初评')
            self.bare.append(row)
            self._score_bare(row,self.base_seeds)
            search.stage_progress['completed_candidates']+=1;search.heartbeat()
        threshold=s.layered_drop_percent/100
        self.elite=elite_reference(self.bare,self.base_seeds,self.objective)
        elite_keys={r['configuration_key'] for r in self.elite}
        initial_leader=self._leader()
        initial_reference=reference_scores(self.elite)
        self.preselection_diagnostics=dict(elite_keys=sorted(elite_keys),elite_count=len(self.elite),
            initial_leader_score=initial_leader['mean'],initial_elite_mean=obj.rank_key(list(initial_reference.values()),self.objective),
            initial_leader_threshold_count=sum(paired_gate(r['scores'],initial_leader['scores'],threshold)['gap'] is None or
                paired_gate(r['scores'],initial_leader['scores'],threshold)['gap']<=threshold+1e-12 for r in self.bare),
            initial_elite_threshold_count=sum(paired_gate(r['scores'],initial_reference,threshold)['gap'] is None or
                paired_gate(r['scores'],initial_reference,threshold)['gap']<=threshold+1e-12 for r in self.bare))
        for n in range(len(self.base_seeds)+1,s.layered_max_seeds+1):
            if not s.layered_filter:break  # No cut to verify, no wasted extra bare samples.
            reference=reference_scores(self.elite);selected=[]
            for row in self.bare:
                gate=elite_gate(row['scores'],self.elite,threshold,reference,self.objective);row['gate']=gate
                gap=gate['gap']
                selected_for_review=(row['configuration_key'] in elite_keys or gate['uncertain'] or gap is None or
                    (n==len(self.base_seeds)+1 and gap<=max(.15,threshold+.05)+1e-12) or
                    (n>len(self.base_seeds)+1 and gap<=threshold+.05+1e-12))
                row.setdefault('review_decisions',[]).append(dict(next_seed_count=n,reference_keys=sorted(elite_keys),
                    selected=selected_for_review,completed_seed_count=len(row['scores']),**gate))
                if selected_for_review:
                    selected.append(row)
            selected.sort(key=lambda r:(r['configuration_key'] not in elite_keys,r['gate']['gap'] if r['gate']['gap'] is not None else -math.inf,r['configuration_key']))
            self.stage=f'裸装追加第{n}共同种子'
            search.budget_phase='refinement'
            search.begin_stage(self.stage,len(selected),len(selected),n)
            seeds=[self.seed_base+i for i in range(n)]
            for row in selected:
                cost=sum((row['configuration_key'],seed) not in search.cache for seed in seeds)
                # Leave at least one equipped evaluation, never a bare winner.
                if search._budget_spent()+cost>=s.budget:
                    row['review_status']='预算不足追加，依据共同交集保守判断'
                    row['review_decisions'][-1]['budget_limited']=True;continue
                self._score_bare(row,seeds)
                row['review_decisions'][-1].update(completed_seed_count=len(row['scores']),actual_additional_samples=cost)
                search.stage_progress['completed_candidates']+=1;search.heartbeat()
        reference=reference_scores(self.elite)
        for row in self.bare:
            gate=elite_gate(row['scores'],self.elite,threshold,reference,self.objective);row['gate']=gate
            retained=(not s.layered_filter or gate['gap'] is None or gate['gap']<=threshold+1e-12 or gate['uncertain'])
            row['admitted']=retained
            row['reference_keys']=sorted(elite_keys)
            row['decision']=('关闭淘汰，全站位晋级' if not s.layered_filter else
                '非正参考/证据不足，保守晋级' if gate['gap'] is None else
                '允许落后阈值内晋级' if gate['gap']<=threshold+1e-12 else
                '波动/临界保护晋级' if retained else '预选阶段经验性淘汰，非统计证明')
            if retained:self.admitted.append(tuple(row['positions']))
            elif len(row['scores'])==len(self.base_seeds):self.early+=1
        self.preselection_complete=True
        self.preselection_diagnostics.update(reference_seeds=sorted(reference),
            final_elite_mean=obj.rank_key(list(reference.values()),self.objective),actual_admitted=len(self.admitted))
        self._plan_joint()

    def _plan_joint(self):
        search=self.search;s=search.settings
        self.joint_total=len(self.admitted)*self.memories.total
        original_total=self.joint_total
        self.memory_pruning['original_joint_total']=original_total
        if s.layered_memory_pruning:
            from src.optimizer.memory_validity import MemoryValidity,PrunedMemorySpace
            from src.optimizer.search import Stopped
            # The evaluator supplies the reference enemy, so pruning judges against
            # the unit this lineup actually fights: the single boss in a tactical
            # exercise, or the boss-slot enemy of a circle stage.
            _pruning_enemy=getattr(search.evaluator,'pruning_enemy',None)
            checker=MemoryValidity(getattr(search.evaluator,'loader',None),self.template,
                enemy=(_pruning_enemy(self.template) if _pruning_enemy else None))
            self.joint_total=None  # A stopped audit must not advertise a completed joint plan.
            self.position_memories=[]
            self.stage='入围站位回忆有效性检查'
            search.begin_stage(self.stage,len(self.admitted),0)
            for positions in self.admitted:
                if search.stop():raise Stopped('回忆剪枝规划被用户停止；未完成联合空间规划')
                audit=[checker.check(mid,positions) for mid in sorted(self.memories.required|set(self.memories.pool))]
                space=PrunedMemorySpace(self.memories,audit)
                self.position_memories.append(space)
                self.memory_pruning['position_records'].append(dict(positions=list(positions),
                    bare_configuration_key=search._key(self.state(positions,[])),cards=audit,
                    ineffective_nonrequired=space.excluded,original_combinations=self.memories.total,
                    actual_combinations=space.total,fallback=space.fallback,
                    fallback_reason='剔除后候选不足以补齐六张；回退原始完整枚举' if space.fallback else None))
                search.stage_progress['completed_candidates']+=1;search.heartbeat()
            self.joint_total=sum(space.total for space in self.position_memories)
        self.memory_pruning.update(planning_complete=True,original_joint_total=original_total,
            actual_joint_total=self.joint_total,excluded_joint_configurations=original_total-self.joint_total,
            fallback_positions=sum(r['fallback'] for r in self.memory_pruning['position_records']))
        remaining=s.budget-search._budget_spent()
        # Increase only complete common base cohorts. At most four coverage
        # seeds by default; the declared minimum is never silently reduced.
        review_size=min(self.joint_total,max(3,math.ceil(self.joint_total*s.layered_review_percent/100)))
        reserve=min(review_size*4+600,max(0,remaining-self.joint_total*s.layered_joint_seeds))
        n=max(s.layered_joint_seeds,min(4,(remaining-reserve)//max(1,self.joint_total)))
        self.joint_seeds=[s.seed+i for i in range(n)]
        self.memory_pruning.update(joint_basic_seed_count=n,
            excluded_basic_seed_evaluations=(original_total-self.joint_total)*n,
            savings_semantics='排除配置×当前完整基础种子数；相同种子成本对照，非旧版总耗时/总战斗减少保证')
        search.search_seed_list=list(self.joint_seeds)
        search.budget_plan.update(actual_admitted_positions=len(self.admitted),joint_candidate_total=self.joint_total,
            joint_basic_seed_count=n,joint_basic_minimum=self.joint_total*s.layered_joint_seeds,
            joint_basic_planned_cost=self.joint_total*n,can_cover_joint=remaining>=self.joint_total*s.layered_joint_seeds,
            policy='真实裸装完整初评，经验阈值/波动保护；均衡联合覆盖后统一统计复评与独立决赛')
        if s.layered_memory_pruning:
            search.budget_plan.update(memory_pruning_enabled=True,original_joint_total=original_total,
                excluded_joint_configurations=original_total-self.joint_total,
                fallback_positions=self.memory_pruning['fallback_positions'])
        if s.review_strategy=='quick':
            from src.optimizer.quick_review import planned_cost
            from src.optimizer.joint_admission import estimate_candidates
            review_size=estimate_candidates(self.joint_total,len(self.admitted),s.layered_review_percent)
            search.budget_plan.update(actual_quick_review_cost_estimate=planned_cost(review_size+1,s.quick_max_seeds),
                actual_final_cost_estimate=600,estimate_assumption='全局比例＋各站位至多1名补入（无额外边界同分假设）＋人工对照；同分最坏可全员；完整覆盖优先')
            search.budget_plan.update(quick_review_candidates_estimate=review_size+1,
                quick_review_all_tied_cost_estimate=planned_cost(self.joint_total+1,s.quick_max_seeds))
        search.report('裸装预选完成；已按真实入围数量更新预算',force=True)

    def cover(self):
        search=self.search;s=search.settings;self.stage='联合配置基础覆盖'
        self.joint_basic_started=search.phase_simulations['basic']
        search.budget_phase='basic';search.begin_stage(self.stage,self.joint_total,self.joint_total*len(self.joint_seeds))
        entries={}
        baseline_key=search._key(search.original)
        if self.position_memories is None:
            indices=crossed_indices(len(self.admitted),self.memories.total,s.seed)
        else:
            from src.optimizer.memory_validity import ragged_indices
            indices=ragged_indices([space.total for space in self.position_memories],s.seed)
        def jobs():
            for p,m in indices:
                space=self.memories if self.position_memories is None else self.position_memories[p]
                state=self.state(self.admitted[p],space.at(m));key=search._key(state)
                search.current_operation='入围站位×全部合法回忆均衡交叉穷举'
                search.attempts+=1
                row=dict(configuration_key=key,positions=list(state['friend_positions']),memory_ids=list(state['memory_ids']),
                         basic_mean=None,basic_seeds=[],eligible=True,validation_mean=None,validation_seeds=[])
                self.joint.append(row)
                yield (row,state),state,self.joint_seeds
        def completed(token,score):
            row,state=token;key=row['configuration_key']
            row.update(basic_mean=score,basic_seeds=list(self.joint_seeds))
            row['completed_seeds']=list(self.joint_seeds)
            entries[key]=(score,state);self.joint_covered+=1
            search.stage_progress['completed_candidates']+=1
            search._retain(state,score)
            if key==baseline_key:search.baseline_search=score
            search.heartbeat()
            search.report('联合配置基础覆盖')  # Existing wall-clock throttle; bounded snapshots only.
        try:search.evaluate_cohorts(jobs(),completed)
        finally:
            for row in self.joint:
                row['completed_seeds']=[seed for seed in self.joint_seeds if (row['configuration_key'],seed) in search.cache]
        return entries

    def run(self):
        from src.optimizer.search import Stopped
        from src.optimizer.statistical_review import reserve_independent
        from src.optimizer.review_dispatch import review
        search=self.search;s=search.settings
        search.search_mode='分层联合穷举';search.search_start=copy.deepcopy(self.template)
        search.validation_seed_list=[]
        minimum=self.positions.total*s.layered_base_seeds
        search.budget_plan=dict(total=s.budget,bare_basic_minimum=minimum,legal_positions=self.positions.total,
                               legal_memories=self.memories.total,policy='所有阶段共用正式预算账本')
        if s.budget<minimum:
            return search.finish('预算不足以开始完整裸装预选',f'至少{minimum}场；请提高预算或增加站位约束')
        try:
            self.preselect()
            if not self.admitted:
                self.stage='无站位通过裸装筛选'
                return search.finish('无站位通过裸装筛选','未进入联合穷举；请检查参考分数及筛选设置，或关闭裸装淘汰')
            entries=self.cover()
            # Fixed, user-visible screening ratio, never driven by the AI model.
            count=min(len(entries),max(3,math.ceil(len(entries)*s.layered_review_percent/100)))
            if s.review_strategy=='quick':
                from src.optimizer.joint_admission import select
                keys,self.joint_admission=select(entries,s.layered_review_percent,self.admitted)
            else:keys=sorted(entries,key=lambda k:(-entries[k][0],k))[:count]
            baseline_key=search._key(search.original)
            if baseline_key in entries and search.baseline_satisfies_constraints and baseline_key not in keys:
                keys.append(baseline_key)  # Legal admitted manual baseline remains eligible, not a forced winner.
                if self.joint_admission is not None:self.joint_admission['baseline_extra_added']=True
            if self.joint_admission is not None:
                from src.optimizer.quick_review import planned_cost
                participants=set(keys)|{baseline_key}
                seeds=[s.seed+100000+i for i in range(8)]
                cost=sum((key,seed) not in search.cache for key in participants for seed in seeds)
                self.joint_admission.update(first_eight_candidate_total=len(keys),
                    first_eight_participant_total=len(participants),baseline_control_added=baseline_key not in keys,
                    first_eight_configuration_keys=sorted(participants),first_eight_seeds=seeds,
                    first_eight_required_battles=cost,available_budget=s.budget-search._budget_spent())
                search.budget_plan.update(actual_quick_review_candidates=len(keys),
                    actual_first_eight_participants=len(participants),actual_first_eight_required_battles=cost,
                    actual_quick_review_cost_estimate=planned_cost(len(participants),s.quick_max_seeds),
                    can_complete_first_eight=cost<=s.budget-search._budget_spent())
            self.review_count=len(keys)
            admitted_keys=set(keys)
            for row in self.joint:row['review_admitted']=row['configuration_key'] in admitted_keys
            self.stage='统一联合统计复评及独立决赛'
            # Only the bounded leaderboard is sent in interim progress. Complete
            # candidate records remain in the final lossless compact result.
            self.preview=sorted(self.joint,key=lambda r:(-r['basic_mean'],r['configuration_key']))[:100]
            search.memory_evaluations=self.joint
            review(search,{k:entries[k] for k in keys},search.baseline_satisfies_constraints,
                reserve_independent(s.budget,search._budget_spent(),len(keys),search._key(search.original) in keys))
            if (search.statistical_review or {}).get('finals_skipped'):
                self.stage='复评预算不足'
                return search.finish('预算不足完整首轮8种子复评',search.statistical_review['finals_skipped'])
            self.complete=True;self.stage='结果交付'
            reason='战斗预算已耗尽' if search._budget_spent()==s.budget else ('统计决赛完成' if (search.independent_validation or {}).get('initial_completed') else '全部计划评价完成')
            if s.review_strategy=='quick' and search._budget_spent()<s.budget:
                reason='快速复评与独立决赛计划完成，剩余预算未强制使用。'
            coverage_detail=('回忆剪枝后入围联合基础空间已完整覆盖；原始'+str(self.memory_pruning['original_joint_total'])+
                '套，实际'+str(self.joint_total)+'套；未声明原始空间完整覆盖；' if s.layered_memory_pruning else
                '入围联合基础空间已完整覆盖；')
            return search.finish(reason,coverage_detail+(search.independent_validation or {}).get('status','独立验证样本不足')+
                '；10%裸装筛选/基础排名复评入围为近似搜索；不是全局最优证明')
        except Stopped as exc:
            from src.optimizer.combined_score import combine
            combine(search)  # Only completed cohorts can participate, including a completed 50-seed phase.
            self.stage+='（中断）'
            reason='用户主动停止' if search.stop() else getattr(exc,'preselection_reason','战斗预算已耗尽（不足下一完整种子集合）')
            if self.quick_preselection is not None and not self.preselection_complete:
                self.quick_preselection.update(interruption_reason=reason,completed=False)
            # Preserve completed equipped candidates, never substitute bare ones.
            self.preview=sorted((r for r in self.joint if r['basic_mean'] is not None),key=lambda r:(-r['basic_mean'],r['configuration_key']))[:100]
            search.memory_evaluations=self.preview
            return search.finish(reason,str(exc) or '保留已完成的真实评价，未完成阶段不标为完成',stopped=True)
        except Exception:
            self.stage+='（数据错误或模拟异常）'
            raise  # Worker persists completed labels/results and the full traceback.


def run_layered_search(search):
    search.layered_run=LayeredRun(search)
    return search.layered_run.run()


def layered_recommendation(state,constraints,settings,loader=None):
    from src.optimizer.budget import review_target,final_cost,finalist_capacity
    prepared=prepare_search_snapshot(state,constraints,loader,change_fifth=False,change_memories=True,change_affixes=False)
    p=PositionSpace(prepared,constraints).total;m=MemorySpace(prepared,constraints).total
    from src.optimizer.bare_preselection import enabled,validate_seed_settings
    validate_seed_settings(settings)
    v29=enabled(settings)
    naked_base=p*settings.layered_base_seeds
    naked_extra=p*((8 if v29 else settings.layered_max_seeds)-settings.layered_base_seeds) if settings.layered_filter else 0
    target=review_target(settings.validation_seeds)
    quick=settings.review_strategy=='quick'
    if quick:target=settings.quick_max_seeds
    def scenario(admitted):
        total=admitted*m
        review_count=min(total,max(3,math.ceil(total*settings.layered_review_percent/100)))+1
        if quick:
            from src.optimizer.joint_admission import estimate_candidates
            review_count=estimate_candidates(total,admitted,settings.layered_review_percent)+1
        final=final_cost(finalist_capacity(review_count,False))
        planned_seeds=max(4,settings.layered_joint_seeds)
        if quick:
            from src.optimizer.quick_review import planned_cost
            cost=planned_cost(review_count,target)
        else:cost=review_count*target
        result=dict(admitted_positions=admitted,joint_configurations=total,basic_cost=total*planned_seeds,
                    basic_minimum_cost=total*settings.layered_joint_seeds,basic_planned_seeds=planned_seeds,
                    review_candidates=review_count,review_cost=cost,final_cost=final,
                    recommended_budget=naked_base+naked_extra+total*planned_seeds+cost+final)
        if quick:
            all_tied=planned_cost(total+1,target)
            result.update(first_eight_cost_estimate=review_count*8,all_tied_review_candidates=total+1,
                all_tied_first_eight_cost=(total+1)*8,all_tied_review_cost=all_tied,
                all_tied_budget=naked_base+naked_extra+total*planned_seeds+all_tied+final)
        return result
    assumptions=sorted(set(min(p,n) for n in (20,40,80,p))) if settings.layered_filter else [p]
    if v29:assumptions=sorted(set(min(p,n) for n in (20,40,settings.layered_quick_rank_limit,settings.layered_quick_rank_limit+6,p)))
    scenarios=[scenario(n) for n in assumptions];worst=scenarios[-1]
    typical=scenario(min(p,settings.layered_quick_rank_limit if v29 else 40)) if settings.layered_filter else worst
    result=dict(mode='分层联合穷举',legal_positions=p,legal_memories=m,theoretical_joint_configurations=p*m,
        bare_basic_cost=naked_base,bare_extra_estimate=naked_extra,actual_admitted_positions=None,
        scenarios=scenarios,review_percent=settings.layered_review_percent,review_target=target,
        filter_enabled=settings.layered_filter,drop_percent=settings.layered_drop_percent,
        recommended_budget=(typical if quick else worst)['recommended_budget'],basic_exhaustive_minimum=naked_base,
        typical_budget=typical['recommended_budget'],worst_case_budget=worst['recommended_budget'],review_strategy=settings.review_strategy,
        notes=['入围数量在真实裸装预选结束前未知；快速日常推荐假设至多40站位入围，同时列出全部晋级最坏场景；严谨保持原保守规划。',
               '预算涵盖全部阶段；裸装追加按所有站位达到最大种子估算，实际通常更少。',
               '联合基础按预算充足时最多4种子（用户最低设置更高则按更高值）保守规划，最低覆盖成本另外列出。',
               ('快速按8→16→32→64→128（或256），上限64→32→16→8→4，追加共同种子增量规划；另保留人工对照，经验淘汰通常降低成本。' if quick else
                '联合覆盖后按基础共同种子均分冻结指定比例，再复用原共同种子统计与50＋100独立决赛。'),
               '未复评者未被统计排除；百分比筛选为近似，不证明全局最优；回忆穷举阈值不限制此模式。'])
    if v29:
        result.update(bare_four_extra_estimate=p*2,bare_eight_extra_estimate=p*4,
            bare_preselection_maximum=p*8,preselection_mechanism='V2.9 2→4→8',
            typical_admitted_assumption=min(p,settings.layered_quick_rank_limit),
            tie_protected=True)
        result['preselection_rules']=dict(four_drop_percent=settings.layered_quick_four_drop_percent,
            eight_drop_percent=settings.layered_quick_eight_drop_percent,
            final_percent=100-settings.layered_quick_final_drop_percent,
            top_count=settings.layered_quick_top_count,rank_limit=settings.layered_quick_rank_limit)
        result['notes'][0]=f'入围数量在真实裸装筛选结束前未知；日常推荐假设{min(p,settings.layered_quick_rank_limit)}站位，名次仅为典型假设；第{settings.layered_quick_rank_limit}名同分可全部晋级，保守场景允许全部{p}站位。'
        result['notes'].append(f'裸装基础2种子{p*2}场＋完整4种子追加最多{p*2}场＋完整8种子追加最多{p*4}场；参考组评价也占预算。')
    if settings.layered_memory_pruning:
        result['notes'].append('已启用无效回忆剪枝：预选前按未剪枝空间保守规划；晋级后按各站位实际组合数重算基础覆盖与复评成本。候选不足回退完整六卡枚举。')
    if quick:
        result['typical_budget']=typical['recommended_budget']
        result['worst_case_budget']=worst['all_tied_budget']
        result['notes'].append('V3.1快速联合入围：全局比例＋边界真实同分＋每站位至少一套代表。典型预算假设无额外边界同分；保守预算按全部联合候选同分＋人工对照估算，实际覆盖后按真实人数重算，不预先截断首轮8种子候选。')
    return result


def layered_recommendation_text(plan,throughput=None):
    lines=[f"搜索模式：{plan['mode']}",f"合法站位：{plan['legal_positions']}；合法回忆：{plan['legal_memories']}",
        f"理论完整联合空间：{plan['theoretical_joint_configurations']:,}套",
        f"裸装完整基础初评：{plan['bare_basic_cost']}场；追加种子保守预估：{plan['bare_extra_estimate']}场",
        f"裸装允许落后：{plan['drop_percent']}%；"+('启用经验淘汰，实际入围数量尚未知' if plan['filter_enabled'] else '关闭淘汰，全站位入围'),
        f"联合统计复评比例：{plan['review_percent']}%；目标参考：{plan['review_target']}共同种子"]
    if plan.get('preselection_rules'):
        r=plan['preselection_rules']
        lines[4]=f"快速裸装2→4→8；4/8种子允许落后{r['four_drop_percent']}%/{r['eight_drop_percent']}%；前{r['top_count']}均分的{r['final_percent']}%最终线；第{r['rank_limit']}名同分全保留。"
    for row in plan['scenarios']:
        lines.append(f"假设{row['admitted_positions']}站位晋级：{row['joint_configurations']:,}套联合候选；最低覆盖{row['basic_minimum_cost']}场，基础{row['basic_planned_seeds']}种子规划{row['basic_cost']}场，复评{row['review_cost']}场，决赛{row['final_cost']}场；总计{row['recommended_budget']}场")
        if 'all_tied_first_eight_cost' in row:
            lines.append(f"  无额外边界同分估算：{row['review_candidates']}名（含人工对照），完整首轮8种子{row['first_eight_cost_estimate']}场；全部同分保守场景：{row['all_tied_review_candidates']}名，首轮{row['all_tied_first_eight_cost']}场，总预算{row['all_tied_budget']}场。均为预估，非已执行场数。")
    lines.append(f"推荐总预算（{'日常假设' if plan.get('review_strategy')=='quick' else '保守规划'}，非统计可靠性保证）：{plan['recommended_budget']}场；全部晋级最坏规划：{plan.get('worst_case_budget',plan['recommended_budget'])}场")
    if isinstance(throughput,(int,float)) and math.isfinite(throughput) and throughput>0:
        lines.append(f"预计耗时：{plan['recommended_budget']/throughput:.1f}秒（按{throughput:.2f}场/秒，不含额外启动/统计开销）")
    else:lines.append('预计耗时：未统计；可填写本机吞吐量。')
    return '\n'.join(lines+plan['notes'])



