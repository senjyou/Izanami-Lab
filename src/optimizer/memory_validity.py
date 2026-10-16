"""Conservative static memory audit, using the loader's structured game data.

This is a possible-effect test, never a prediction of score improvement. Only
fully understood battle-start effects with no eligible target can be excluded.
Unsupported/dynamic semantics are UNKNOWN, even when their initial target is empty.
"""
import math
import random
from dataclasses import asdict

from src.optimizer.scheduling import _unrank

EFFECTIVE = 'EFFECTIVE'
INEFFECTIVE = 'INEFFECTIVE'
UNKNOWN = 'UNKNOWN'

# Supported engine effect semantics, NOT a table of cards or descriptions.
STATIC_EFFECTS = {'StatusAttack', 'StatusMaxHp', 'StatusDefense', 'StatusSpeed',
                  'StatusCriticalChance', 'CriticalBonusModification',
                  'ReceivedHealing', 'ReceivedDamage', 'DealtDamage'}
EFFECT_FIELDS = {'effect_type', 'value', 'value_tag', 'is_buff', 'duration',
                 'duration_type', 'timing_type', 'is_memory_buff', 'damage_element'}
HIGHLIGHT_FIELDS = {'character_attribute', 'character_base_master_id', 'character_master_id',
                    'character_role', 'character_team_master_id', 'character_type',
                    'is_targeting_friendly_party', 'party_position', 'skill_master_id'}


def damage_kind(character_type):
    """Agility uses physical damage; true damage is not inferred from type."""
    return {1: 1, 2: 2, 3: 1}.get(character_type)


def _dict(value):
    return dict(value) if isinstance(value, dict) else asdict(value)


class MemoryValidity:
    def __init__(self, loader, state, enemy=None):
        """``enemy`` overrides where the reference enemy comes from.

        Memory-validity pruning asks "can this card possibly matter?" against the
        enemy the lineup actually has to beat. The tactical exercise has exactly one
        such enemy, so the default looks it up by ``state['enemy_id']``. A circle
        stage fields a whole lineup, and its evaluator supplies the boss-position
        enemy through this argument so pruning judges against the right unit instead
        of the wrong one -- which would silently exclude cards the stage needs.
        """
        self.loader = loader
        self.characters = {}
        if loader is not None:
            for cid in state['friend_positions']:
                if cid is not None:
                    char = loader.get_character(cid)
                    if char is not None:
                        self.characters[cid] = _dict(char)
        candidate = enemy
        if candidate is None and loader is not None:
            candidate = loader.get_tactical_exercise_enemies().get(state['enemy_id'])
        self.enemy = None
        if candidate is not None:
            self.enemy = dict(character_id=candidate.get('enemy_id'),
                character_type=candidate.get('type'),
                attribute=candidate.get('attribute'),
                role_type=candidate.get('role_type', 0),
                position=candidate.get('position', 2))

    def units(self, positions):
        allies = [dict(self.characters.get(cid, {}), character_id=cid, position=i+1)
                  for i, cid in enumerate(positions) if cid is not None]
        return allies, [self.enemy] if self.enemy else None

    def _match(self, unit, highlight, mask):
        unknown = False
        for key, field in (('character_master_id', 'character_id'),
                           ('character_base_master_id', 'character_base_id'),
                           ('character_role', 'role_type'), ('character_type', 'character_type')):
            if highlight.get(key) is not None:
                if unit.get(field) is None: unknown = True
                elif unit[field] != highlight[key]: return False
        attr = highlight.get('character_attribute')
        if attr is not None:
            if unit.get('attribute') is None: unknown = True
            elif attr not in (unit['attribute'], unit.get('sub_attribute', 0)): return False
        team = highlight.get('character_team_master_id')
        if team is not None:
            base = unit.get('character_base_id')
            actual = self.loader.get_character_team_id(base) if base is not None else None
            if actual is None: unknown = True
            elif actual != team: return False
        if mask is not None:
            pos = unit.get('position')
            if pos not in range(1, 7): unknown = True
            elif not (mask & (1 << (pos-1))): return False
        return None if unknown else True

    def _targets(self, highlight, block, allies, enemies):
        kind = block.get('target_type', 'highlight_targets')
        if kind in ('highlight_targets', 'ally_position', 'enemy_position'):
            units = allies if highlight.get('is_targeting_friendly_party', True) else enemies
            if units is None: return None
            mask = (block.get('party_position', highlight.get('party_position'))
                    if kind == 'ally_position' else highlight.get('party_position'))
            if mask is not None and (type(mask) is not int or not 0 <= mask <= 63): return None
            matched = [self._match(unit, highlight, mask) for unit in units]
            if None in matched: return None
            return [unit for unit, yes in zip(units, matched) if yes]
        if kind in ('ally_all', 'ally_front_row', 'ally_back_row',
                    'enemy_front_row', 'enemy_back_row'):
            units = allies if kind.startswith('ally') else enemies
            if units is None: return None
            if kind.endswith('front_row'): return [u for u in units if u['position'] in (1, 2, 3)]
            if kind.endswith('back_row'): return [u for u in units if u['position'] in (4, 5, 6)]
            return units
        return None  # Dynamic ranking, exclude-self, future targets: retain.

    def _skill(self, highlight, allies, enemies):
        skill = highlight.get('skill_master_id')
        data = self.loader.get_memory_effect(skill) if skill else None
        if not data or set(highlight) - HIGHLIGHT_FIELDS:
            return dict(skill_id=skill, status=UNKNOWN, reason='缺少结构化效果或未知筛选字段')
        trigger = data.get('trigger', {})
        blocks = data.get('blocks')
        if (trigger.get('type', 'battle_start') != 'battle_start'
                or set(trigger) - {'type', 'require_highlight_match'} or not blocks
                or set(data) - {'skill_id', 'name', 'description', 'trigger', 'blocks'}):
            return dict(skill_id=skill, status=UNKNOWN, reason='动态触发、条件或未支持机制，保守保留')
        if trigger.get('require_highlight_match'):
            return dict(skill_id=skill, status=UNKNOWN, reason='含整技能触发条件，第一版保守保留')
        outcomes = []; checks = []
        for block in blocks:
            effects = block.get('effects')
            targets = self._targets(highlight, block, allies, enemies)
            if not effects or set(block) - {'block_id', 'target_type', 'party_position', 'effects'}:
                outcomes.append(UNKNOWN)
                checks.append(dict(block_id=block.get('block_id'),status=UNKNOWN,reason='缺少效果或未知块字段'))
                continue
            for effect in effects:
                typ = effect.get('effect_type')
                if (typ not in STATIC_EFFECTS or set(effect) - EFFECT_FIELDS
                        or targets is None):
                    status = UNKNOWN
                elif typ == 'DealtDamage' and effect.get('damage_element', 0) not in (0, 1, 2):
                    status = UNKNOWN  # True/other damage needs skill analysis.
                elif typ == 'DealtDamage' and effect.get('damage_element', 0):
                    kinds = [damage_kind(u.get('character_type')) for u in targets]
                    status = EFFECTIVE if effect['damage_element'] in kinds else UNKNOWN if None in kinds else INEFFECTIVE
                else:
                    status = EFFECTIVE if targets else INEFFECTIVE
                outcomes.append(status)
                checks.append(dict(block_id=block.get('block_id'),effect_type=typ,
                    damage_element=effect.get('damage_element',0),target_type=block.get('target_type','highlight_targets'),
                    party_position=block.get('party_position',highlight.get('party_position')),
                    matching_target_ids=[u['character_id'] for u in targets] if targets is not None else None,
                    status=status))
        status = EFFECTIVE if EFFECTIVE in outcomes else UNKNOWN if UNKNOWN in outcomes else INEFFECTIVE
        return dict(skill_id=skill, status=status, effect_checks=checks,reason='存在可能生效目标' if status == EFFECTIVE else
                    '未支持效果或目标无法确认' if status == UNKNOWN else '所有已支持效果均无适用目标')

    def check(self, memory_id, positions):
        card = self.loader.get_memory(memory_id) if self.loader is not None else None
        if card is None:
            return dict(memory_id=memory_id, status=UNKNOWN, reason='缺少回忆数据', skills=[])
        highlights = _dict(card).get('highlights', [])
        if not highlights:
            return dict(memory_id=memory_id, status=UNKNOWN, reason='缺少技能列表', skills=[])
        allies, enemies = self.units(positions)
        skills = [self._skill(_dict(h), allies, enemies) for h in highlights]
        statuses = [s['status'] for s in skills]
        status = EFFECTIVE if EFFECTIVE in statuses else UNKNOWN if UNKNOWN in statuses else INEFFECTIVE
        return dict(memory_id=memory_id, status=status, skills=skills,
                    reason='至少一项可能有效' if status == EFFECTIVE else
                           '未知效果保守保留' if status == UNKNOWN else '全部技能确定无适用目标')


class PrunedMemorySpace:
    """Rank/unrank without materializing combinations; retain six unique cards."""
    def __init__(self, original, audit):
        self.required = original.required
        self.count = original.count
        self.excluded = [r['memory_id'] for r in audit
                         if r['status'] == INEFFECTIVE and r['memory_id'] not in self.required]
        pool = [mid for mid in original.pool if mid not in self.excluded]
        self.fallback = len(pool) < self.count
        self.pool = original.pool if self.fallback else pool
        self.total = math.comb(len(self.pool), self.count)

    def at(self, rank):
        return tuple(sorted(self.required.union(_unrank(self.pool, self.count, rank))))


def ragged_indices(counts, seed):
    """Balanced lazy affine sweeps; one candidate per active position each round."""
    rng = random.Random(seed)
    order = list(range(len(counts))); rng.shuffle(order)
    active = []
    for index, p in enumerate(order):
        count = counts[p]
        if not count: continue
        offset = rng.randrange(count)
        stride = rng.randrange(1, count) if count > 1 else 1
        while math.gcd(stride, count) != 1: stride += 1
        active.append((p, count, (offset+index*stride) % count, stride))
    step = 0
    while active:
        for p, count, offset, stride in active:
            yield p, (offset+step*stride) % count
        step += 1
        active = [row for row in active if step < row[1]]
