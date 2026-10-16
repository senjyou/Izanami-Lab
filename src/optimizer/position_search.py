"""Independent fixed-team six-slot enumeration; no combat rules or pruning."""
import copy
import itertools

from src.optimizer.model import validate_constraints, validate_snapshot
from src.entities_v2.enums import Position

SLOTS = (Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT, Position.ALLY_RIGHT_FRONT,
         Position.ALLY_LEFT_BACK, Position.ALLY_CENTER_BACK, Position.ALLY_RIGHT_BACK)
SLOT_LABELS = ('1 左前', '2 中前', '3 右前', '4 左后', '5 中后', '6 右后')


class PositionSpace:
    def __init__(self, state, constraints):
        validate_snapshot(state, affixes=False)
        validate_constraints(state, constraints)
        self.original = tuple(state['friend_positions'])
        self.characters = set(self.original) - {None}
        rules = constraints.get('positions', {})
        if not isinstance(rules, dict):
            raise ValueError('站位约束必须为按角色ID保存的字典')
        self.rules, allowed = {}, {}
        for raw_id, rule in rules.items():
            try:
                cid = int(raw_id)
            except (TypeError, ValueError):
                raise ValueError(f'站位约束角色ID无效：{raw_id!r}') from None
            if cid not in self.characters:
                raise ValueError(f'站位约束角色 {cid} 不在固定五人阵容中')
            if cid in self.rules:
                raise ValueError(f'角色 {cid} 存在重复站位约束')
            if not isinstance(rule, dict) or rule.get('kind') not in ('any', 'front', 'back', 'fixed', 'keep'):
                raise ValueError(f'角色 {cid} 站位约束类型无效')
            kind = rule['kind']
            if kind in ('fixed', 'keep'):
                slot = rule.get('position')
                if type(slot) is not int or slot not in range(1, 7):
                    raise ValueError(f'角色 {cid} 的固定/保持站位须为1–6')
                choices = {slot - 1}
                self.rules[cid] = dict(kind=kind, position=slot)
            else:
                choices = {i for i, pos in enumerate(SLOTS) if kind == 'any' or
                           (kind == 'front' and pos.name.endswith('_FRONT')) or
                           (kind == 'back' and pos.name.endswith('_BACK'))}
                self.rules[cid] = dict(kind=kind)
            allowed[cid] = choices
        permutations = itertools.permutations(sorted(self.characters) + [None])
        self.configurations = [p for p in permutations if all(p.index(cid) in slots for cid, slots in allowed.items())]
        if not self.configurations:
            detail = '；'.join(f'{cid}: {rule}' for cid, rule in self.rules.items())
            raise ValueError('站位约束互相冲突，没有合法排列：' + detail)
        # Include the unchanged baseline first only when it is a legal candidate.
        if self.original in self.configurations:
            self.configurations.remove(self.original)
            self.configurations.insert(0, self.original)
        self.total = len(self.configurations)

    def contains(self, positions):
        return tuple(positions) in self.configurations

    def minimum_budget(self, settings):
        return self.total * settings.search_seeds

    def require_budget(self, settings):
        minimum = self.minimum_budget(settings)
        if settings.budget < minimum:
            raise ValueError(f'站位基础覆盖预算不足：{self.total}种合法站位 × {settings.search_seeds}种子'
                             f'至少需要{minimum}场，当前{settings.budget}场；请提高预算或增加站位约束')


def run_position_search(search, space):
    """Cover every legal position before reusing V2.4's unchanged paired review."""
    from src.optimizer.search import Stopped
    from src.optimizer.statistical_review import reserve_independent
    from src.optimizer.review_dispatch import review
    settings = search.settings
    space.require_budget(settings)
    search.search_mode = '站位穷举'
    search.position_total = space.total
    search.position_constraints = copy.deepcopy(search.constraints.get('positions', {}))
    search.position_evaluations = []
    # The existing review/finals updater uses this private collection. The public
    # result exposes it as position_evaluations, never as memory coverage.
    search.memory_evaluations = search.position_evaluations
    search.validation_seed_list = []
    search.budget_plan = dict(total=settings.budget, policy='先完整站位基础覆盖，再V2.4共同种子复评与50+100决赛',
                             position_planned=space.total, basic_seed_count=settings.search_seeds,
                             basic_simulation_target=space.minimum_budget(settings))
    search.baseline_satisfies_constraints = space.contains(search.original['friend_positions'])
    baseline_key = search._key(search.original)
    candidates = {}
    loader = getattr(search.evaluator, 'loader', None)
    try:
        search.budget_phase = 'basic'
        search._team_stats(tuple(sorted(space.characters)))['planned'] = True
        search.begin_stage('正在站位基础覆盖', space.total, space.minimum_budget(settings))
        def jobs():
            for positions in space.configurations:
                state = copy.deepcopy(search.original)
                state['friend_positions'] = list(positions)
                validate_snapshot(state, loader, affixes=False)
                validate_constraints(state, search.constraints, loader)
                key = search._key(state)
                search.current_operation = '独立站位完整枚举'
                search.attempts += 1
                yield (key,state,positions),state,search.search_seed_list
        def completed(token,score):
            key,state,positions=token
            candidates[key] = (score, state)
            search.position_evaluations.append(dict(configuration_key=key, state=state,
                positions=list(positions), memory_ids=list(state['memory_ids']), basic_mean=score,
                basic_seeds=list(search.search_seed_list), eligible=True, validation_mean=None, validation_seeds=[]))
            search.position_covered += 1
            search.stage_progress['completed_candidates'] += 1
            if key == baseline_key:
                search.baseline_search = score
            search._retain(state, score)
            search.report('站位基础覆盖')
        search.evaluate_cohorts(jobs(),completed)
        review(search, candidates, search.baseline_satisfies_constraints,
               reserve_independent(settings.budget, search._budget_spent(), len(candidates), baseline_key in candidates))
        detail = ('站位基础空间已完整覆盖；'+('快速经验复评' if settings.review_strategy=='quick' else 'V2.4严谨统计复评')+'与独立决赛；'
                  '仅为已覆盖候选的评价领先者，不是期望分数全局最优证明；' +
                  (search.independent_validation or {}).get('status', '独立验证样本不足'))
        if search.independent_validation and search.independent_validation.get('budget_limited'):
            detail += '；独立决赛受预算限制'
        return search.finish('站位搜索空间已完整覆盖', detail)
    except Stopped as exc:
        reason = '用户主动停止' if search.stop() else '战斗预算不足以完成当前种子集合'
        return search.finish(reason, str(exc) or '保留最后完整阶段；站位覆盖与统计验证分别记录', stopped=True)
