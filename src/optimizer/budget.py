"""Explicit planning assumptions shared by recommendation and staged validation."""
import itertools
import math
from src.optimizer.model import AFFIXES, validate_constraints, validate_snapshot

INITIAL_SEEDS=50
EXTRA_SEEDS=100

def space_diagnostics(state, constraints, settings):
    """Display-only cardinalities; never changes scheduling or search constraints.

    The experimental mutator does not apply V2.5 per-role position rules. Do
    not describe those rules as shrinking its actual search space. Affix and
    member searches also have repair/neighbourhood semantics, so their full
    reachable cardinality is deliberately left unknown.
    """
    required = {int(mid) for mid, mark in constraints['memories'].items() if mark == '必选'}
    pool = {int(mid) for mid in constraints['memories']} - required
    memory_count = math.comb(len(pool), 6-len(required)) if settings.change_memories else 1
    kind = settings.search_kind
    if kind in ('positions','layered'):
        from src.optimizer.position_search import PositionSpace
        if kind=='layered':
            from src.optimizer.model import prepare_search_snapshot
            state=prepare_search_snapshot(state,constraints,change_fifth=False,change_memories=True,change_affixes=False)
        position_count = PositionSpace(state, constraints).total
        applied = True
    else:
        position_count = 720 if settings.change_positions else 1
        applied = False
    known = not settings.change_fifth and not settings.change_affixes
    theoretical = memory_count * position_count if known else None
    return dict(legal_memory_combinations=memory_count,
        legal_position_configurations=position_count,
        theoretical_joint_configurations=theoretical,
        theoretical_space_status='已按固定角色/词条与实际搜索范围计算' if known else '未统计：角色或词条可变，无法安全计算完整联合空间',
        position_hard_constraints_applied=applied,
        position_constraint_note=('独立站位模式按硬约束过滤。' if applied else
            '联合启发式搜索不执行独立站位硬约束；站位可变时按720种排列计数。' if kind in ('joint','legacy') else
            '本模式固定站位。'))

def _annotate_plan(plan, state, constraints, settings):
    if settings.search_kind in ('memory','positions') and settings.review_strategy=='quick':
        from src.optimizer.quick_review import plan as quick_plan,planned_cost
        target=settings.quick_max_seeds
        plan.update(review_strategy='quick',review_target=target,
            review_looks=[n for n,_,_ in quick_plan(target)],
            review_cost_estimate=planned_cost(plan['review_candidate_estimate'],target))
        plan['recommended_budget']=plan['basic_cost']+plan['review_cost_estimate']+plan['initial_cost']+plan['extra_cost']
        plan['notes']=plan['notes']+['全部基础候选先进入8种子；随后经验分差/3SE波动保护和名额上限逐轮缩减，非统计证明。预算为增量上限估算，可能提前进入决赛。']
    # Existing independent-mode result JSON is a V2.4 regression contract.
    # Keep its planner dict byte-for-byte compatible; only joint/heuristic plans
    # need new transparency fields. Independent UI can derive exact counts from
    # its already recorded counts without changing the saved planner.
    if plan['mode']!='启发式搜索' and settings.search_kind!='joint':
        return plan
    plan.update(space_diagnostics(state, constraints, settings))
    plan['planning_semantics'] = '完整基础覆盖规划' if plan['guarantees_exhaustive'] else '有限启发式探索规划；计划值并非实际覆盖保证'
    plan['unique_configuration_semantics'] = '完成至少一次真实战斗的不同完整配置；同配置多种子仍只计1套'
    return plan

def review_target(reference=10):
    target=4
    while target<max(32,reference):target*=2
    return target

def finalist_capacity(legal_count,baseline_included=True):
    return min(legal_count,4) if baseline_included else min(legal_count,3)+1

def final_cost(capacity):
    return capacity*INITIAL_SEEDS+(capacity*EXTRA_SEEDS if capacity>1 else 0)

def reserve_for_final(budget,coverage_cost,candidate_count,baseline_included=True):
    """Coverage first, then leave one full 4-seed review before reserving finals."""
    controls=candidate_count+(not baseline_included)
    return min(final_cost(finalist_capacity(candidate_count,baseline_included)),
               max(0,budget-coverage_cost-controls*4))

def recommendation(state,constraints,settings,loader=None):
    settings.validate();validate_snapshot(state,loader,affixes=False)
    validate_constraints(state,constraints,loader,require_current=False)
    if not settings.automatic:raise ValueError('当前是仅评价模式；请先选择自动寻找更优阵容')
    if settings.search_kind=='layered':
        from src.optimizer.layered_search import layered_recommendation
        return layered_recommendation(state,constraints,settings,loader)
    if settings.search_kind == 'positions':
        from src.optimizer.position_search import PositionSpace
        space = PositionSpace(state, constraints)
        total = space.total
        baseline_included = space.contains(state['friend_positions'])
        controls = total + (not baseline_included)
        capacity = finalist_capacity(total, baseline_included)
        target = review_target(settings.validation_seeds)
        basic = total * settings.search_seeds
        initial = capacity * INITIAL_SEEDS
        extra = capacity * EXTRA_SEEDS if capacity > 1 else 0
        return _annotate_plan(dict(mode='站位穷举', exact_position_configurations=total,
            exact_memory_combinations=1, space_upper_bound=total, basic_exhaustive_minimum=basic,
            basic_planned_configurations=total, basic_cost=basic, review_candidate_estimate=controls,
            review_target=target, review_looks=[4*2**i for i in range(int(math.log2(target//4))+1)],
            review_cost_estimate=controls*target, initial_finalist_capacity=capacity,
            initial_cost=initial, extra_cost=extra, recommended_budget=basic+controls*target+initial+extra,
            baseline_included=baseline_included, guarantees_exhaustive=True,
            notes=['只调整站位；角色、词条、装备、六张回忆和Boss保持原值。',
                   '复评按所有候选不提前淘汰估算，嵌套种子仅按新增量计入；实际可能更少。',
                   '决赛前三合法候选加去重人工基线，50新种子初评，必要时追加100新种子。',
                   '完整基础覆盖不代表统计意义的全局最优证明；回忆穷举阈值不适用于站位模式。']), state, constraints, settings)
    memory_required={int(mid) for mid,mark in constraints['memories'].items() if mark=='必选'}
    memory_pool={int(mid) for mid in constraints['memories']}-memory_required
    required=len(memory_required);candidates=len(memory_pool)
    if not 0<=required<=6 or candidates<6-required:raise ValueError('回忆约束无法补齐六张不同回忆')
    memories=math.comb(candidates,6-required) if settings.change_memories else 1
    required_roles={int(cid) for cid,mark in constraints['characters'].items() if mark=='必选'}
    candidate_roles={int(cid) for cid in constraints['characters']}-required_roles
    role_required=len(required_roles);role_candidates=len(candidate_roles)
    if not 0<=role_required<=5 or role_candidates<5-role_required:raise ValueError('角色约束无法组成五人阵容')
    roles=math.comb(role_candidates,5-role_required) if settings.change_fifth else 1
    memory_only=settings.search_kind in ("legacy","memory") and not any((settings.change_fifth,settings.change_positions,settings.change_affixes))
    exhaustive=memory_only and (not settings.change_memories or bool(settings.memory_exhaustive_limit and memories<=settings.memory_exhaustive_limit))
    try:validate_constraints(state,constraints,loader);baseline_included=True
    except ValueError:baseline_included=False
    notes=[]
    if memory_only:
        total=memories;planned=total if exhaustive else min(total,max(100,settings.memory_exhaustive_limit or 100))
        basic_minimum=total*settings.search_seeds
        if not exhaustive:notes.append('当前穷举阈值为0或低于组合数，将无放回抽样；仅增加预算不会触发穷举，可自行提高阈值。')
    else:
        affix_space=sum(math.prod(len(AFFIXES[k]) for k in kinds)*6 for kinds in itertools.combinations(AFFIXES,3))**15 if settings.change_affixes else 1
        total=roles*memories*(720 if settings.change_positions else 1)*affix_space
        planned=min(total,100);basic_minimum=None
        notes.append('联合搜索仅按最多100套探索配置规划，不保证穷举；空间数为上界，未证明所有等价类。')
    basic=planned*settings.search_seeds
    # Heuristic retains <=8 diverse elites plus possible baseline. Fixed-memory
    # coverage can send every covered candidate into its first statistical look.
    review_candidates=planned if memory_only else min(8,planned)
    control_count=review_candidates+(not baseline_included if memory_only else 1)
    capacity=finalist_capacity(review_candidates,baseline_included if memory_only else False)
    target=review_target(settings.validation_seeds)
    review=control_count*target
    initial=capacity*INITIAL_SEEDS;extra=capacity*EXTRA_SEEDS if capacity>1 else 0
    return _annotate_plan(dict(mode='回忆穷举' if exhaustive and settings.change_memories else '固定配置' if exhaustive else '启发式搜索',
        exact_memory_combinations=memories,space_upper_bound=total,basic_exhaustive_minimum=basic_minimum,
        basic_planned_configurations=planned,basic_cost=basic,review_candidate_estimate=control_count,
        review_target=target,review_looks=[4*2**i for i in range(int(math.log2(target//4))+1)],
        review_cost_estimate=review,initial_finalist_capacity=capacity,initial_cost=initial,extra_cost=extra,
        recommended_budget=basic+review+initial+extra,baseline_included=baseline_included,
        guarantees_exhaustive=exhaustive,notes=notes+['复评假设候选不提前淘汰，嵌套种子增量合计等于最终目标，不重复相加各轮。',
        '决赛按前三名加人工基线最多4套规划；50新种子初评，必要时再追加100新共同种子。实际消耗可能更低。']), state, constraints, settings)

def recommendation_text(plan, throughput=None):
    if plan['mode']=='分层联合穷举':
        from src.optimizer.layered_search import layered_recommendation_text
        return layered_recommendation_text(plan,throughput)
    minimum=plan['basic_exhaustive_minimum']
    theoretical=plan.get('theoretical_joint_configurations',plan['space_upper_bound'] if plan['guarantees_exhaustive'] else None)
    extra=[f"合法回忆组合：{plan.get('legal_memory_combinations',plan['exact_memory_combinations'])}套",
        f"{'合法站位排列' if plan.get('mode')=='站位穷举' else '合法站位'}：{plan.get('legal_position_configurations',plan.get('exact_position_configurations',1))}种",
        f"理论合法联合空间：{theoretical:,}套配置" if theoretical is not None else '理论合法联合空间：未统计',
        plan.get('theoretical_space_status','独立模式固定其余参数；计数按原有合法性规则计算。'),plan.get('position_constraint_note',''),
        plan.get('planning_semantics','完整基础覆盖规划' if plan['guarantees_exhaustive'] else '旧版本未记录')]
    if not plan['guarantees_exhaustive']:
        extra.append(f"该预算不覆盖全部{theoretical:,}套配置，不保证穷举或全局最优。" if theoretical is not None and theoretical>plan['basic_planned_configurations'] else
                     '该预算属于有限探索计划，不保证完整覆盖、穷举或全局最优。')
    if isinstance(throughput,(int,float)) and math.isfinite(throughput) and throughput>0:
        extra.append(f"预计耗时：约{plan['recommended_budget']/throughput:.1f}秒（按{throughput:.2f}场/秒；不含额外启动/统计开销）")
    else:extra.append('预计耗时：未统计；可填写吞吐量，或使用本机已测吞吐量。')
    return '\n'.join([f"搜索模式：{plan['mode']}",*extra,
        f"基础穷举最低预算：{minimum if minimum is not None else '无法精确计算（联合搜索不保证穷举）'}",
        f"基础探索规划：{plan['basic_planned_configurations']}套 / {plan['basic_cost']}场",
        (f"快速复评预留（嵌套共同种子增量＋名额上限估算）：{plan['review_cost_estimate']}场；最大{plan['review_target']}种子" if plan.get('review_strategy')=='quick' else
         f"统计复评预留（估算）：{plan['review_candidate_estimate']}套 × {plan['review_target']}种子 = {plan['review_cost_estimate']}场"),
        f"决赛初评预留：{plan['initial_cost']}场；决赛加赛预留：{plan['extra_cost']}场",
        f"推荐可靠总预算（规划，非可靠性保证）：{plan['recommended_budget']}场",*plan['notes']])
