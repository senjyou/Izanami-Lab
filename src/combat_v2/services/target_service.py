from typing import List, Optional
from ...entities_v2.unit_state import UnitState
from ...entities_v2.battlefield_state import BattlefieldState
from ...entities_v2.enums import (
    Side, Position,
    DisplayTargetType, DisplayTargetRange, DisplayTargetPriority,
    SkillEffectType
)
from ..battle_logger import battle_logger

_log = battle_logger()

_POS_RC = {
    Position.ALLY_LEFT_FRONT: (0, 0), Position.ALLY_CENTER_FRONT: (0, 1), Position.ALLY_RIGHT_FRONT: (0, 2),
    Position.ALLY_LEFT_BACK: (1, 0), Position.ALLY_CENTER_BACK: (1, 1), Position.ALLY_RIGHT_BACK: (1, 2),
    Position.ENEMY_LEFT_FRONT: (0, 0), Position.ENEMY_CENTER_FRONT: (0, 1), Position.ENEMY_RIGHT_FRONT: (0, 2),
    Position.ENEMY_LEFT_BACK: (1, 0), Position.ENEMY_CENTER_BACK: (1, 1), Position.ENEMY_RIGHT_BACK: (1, 2),
}

_FRONT_POSITION_MAP = {
    Position.ALLY_LEFT_BACK: Position.ALLY_LEFT_FRONT,
    Position.ALLY_CENTER_BACK: Position.ALLY_CENTER_FRONT,
    Position.ALLY_RIGHT_BACK: Position.ALLY_RIGHT_FRONT,
    Position.ENEMY_LEFT_BACK: Position.ENEMY_LEFT_FRONT,
    Position.ENEMY_CENTER_BACK: Position.ENEMY_CENTER_FRONT,
    Position.ENEMY_RIGHT_BACK: Position.ENEMY_RIGHT_FRONT,
}

class TargetService:
    """
    目标选择服务
    根据技能配置 (Type, Range, Priority) 选择目标
    距离计算基于列参考点：(0, caster_col)
    """

    def select_targets(self, skill_data, caster: UnitState, battlefield: BattlefieldState) -> List[UnitState]:
        candidates = self._get_candidates_by_type(skill_data.display_target_type, caster, battlefield)

        _log.info("[TARGET] %s selects: type=%d range=%d priority=%s | candidates=%d",
                  caster.name, skill_data.display_target_type, skill_data.display_target_range,
                  skill_data.display_target_priority, len(candidates))

        if not candidates:
            return []

        # 传递原始target_type名称，用于LINE范围时显式区分前排/后排
        target_type_name = getattr(skill_data, 'target_type_name', None)
        # mark_priority: 仅在显式设置且非None时使用
        # 注意：MagicMock的hasattr/getattr会自动创建属性，需用spec检查
        mark_priority = None
        try:
            mp = object.__getattribute__(skill_data, 'mark_priority')
            if mp is not None:
                mark_priority = mp
        except AttributeError:
            pass
        final_targets = self._select_targets(
            caster, candidates,
            skill_data.display_target_priority,
            skill_data.display_target_range,
            target_type_name,
            mark_priority
        )

        _log.info("[TARGET]   final_targets=%d: %s",
                  len(final_targets), [t.name for t in final_targets])

        return final_targets

    def _get_candidates_by_type(self, target_type: int, caster: UnitState, bf: BattlefieldState) -> List[UnitState]:
        t_type = DisplayTargetType(target_type) if isinstance(target_type, int) else target_type

        all_units = bf.get_all_units()
        ally_side = caster.side
        enemy_side = Side.ENEMY if ally_side == Side.ALLY else Side.ALLY

        if t_type == DisplayTargetType.SELF:
            return [caster]

        elif t_type == DisplayTargetType.SELF_AND_FRIENDS:
            return bf.get_alive_units(ally_side)

        elif t_type == DisplayTargetType.FRIENDS:
            return [u for u in bf.get_alive_units(ally_side) if u.unit_id != caster.unit_id]

        elif t_type == DisplayTargetType.ENEMIES:
            return bf.get_alive_units(enemy_side)

        elif t_type == DisplayTargetType.SELF_AND_FRIENDS_AND_ENEMIES:
            return [u for u in all_units if u.is_alive]

        elif t_type == DisplayTargetType.ADJACENT_ENEMIES:
            enemy_units = [u for u in all_units if u.side == Side.ENEMY and u.is_alive]
            if not enemy_units:
                return []
            return self._get_adjacent_to_closest(enemy_units, caster)

        return []

    def _select_targets(self, caster: UnitState, candidates: List[UnitState],
                        priority, range_type: int, target_type_name: str = None,
                        mark_priority: str = None) -> List[UnitState]:
        r_type = DisplayTargetRange(range_type)

        if r_type == DisplayTargetRange.ALL_PAWNS:
            return candidates

        ordered = self._order_by_priority(caster, candidates, priority)

        if not ordered:
            return []

        # enemy_nearest_and_farthest: 选取距离施法者最近和最远的两个敌方单位（如PS1ダメージリンク）
        if target_type_name == 'enemy_nearest_and_farthest':
            if len(ordered) == 1:
                _log.info("[TARGET]   enemy_nearest_and_farthest: only 1 candidate, returning single target")
                return [ordered[0]]
            nearest = ordered[0]
            # 使用_get_farthest_key正确破平局（同距离优先左列），参考カオスキャノン的furthest filter
            farthest = min(candidates, key=lambda u: self._get_farthest_key(caster.position, u))
            # 防止最近和最远是同一单位（理论上不会，但安全检查）
            if nearest.unit_id == farthest.unit_id:
                return [nearest]
            _log.info("[TARGET]   enemy_nearest_and_farthest: nearest=%s, farthest=%s",
                      nearest.name, farthest.name)
            return [nearest, farthest]

        if r_type == DisplayTargetRange.ONE_PAWN:
            return [ordered[0]]

        elif r_type == DisplayTargetRange.LINE:
            # ally_front_row: 返回所有前排友方（如さて……準備はできたわ的治疗/加攻目标）
            if target_type_name == 'ally_front_row':
                result = [u for u in candidates if self._is_front_row(u)]
                _log.info("[TARGET]   LINE: ally_front_row -> all FRONT row (%d units): %s",
                          len(result), [u.name for u in result])
                return result
            # ally_front: 仅返回正前方单一单位（如再起律動的代疗对象）
            if target_type_name == 'ally_front':
                front_pos = _FRONT_POSITION_MAP.get(caster.position)
                if front_pos:
                    result = [u for u in candidates if u.position == front_pos]
                    _log.info("[TARGET]   LINE: ally_front -> front_pos=%s => %d units: %s",
                              front_pos, len(result), [u.name for u in result])
                    return result
                _log.info("[TARGET]   LINE: ally_front -> caster at front, no front ally")
                return []
            # 如果target_type_name明确指定了前排/后排，优先使用该排
            # 否则按anchor的位置决定（保持原有逻辑兼容性）
            if target_type_name and target_type_name.endswith('_front'):
                result = [u for u in candidates if self._is_front_row(u)]
                _log.info("[TARGET]   LINE: target_type_name=%s -> force FRONT row (%d units)",
                          target_type_name, len(result))
                return result
            if target_type_name and target_type_name.endswith('_back'):
                result = [u for u in candidates if self._is_back_row(u)]
                _log.info("[TARGET]   LINE: target_type_name=%s -> force BACK row (%d units)",
                          target_type_name, len(result))
                return result
            # 显式检查 enemy_back_row（endswith在某些环境下可能不生效）
            if target_type_name == 'enemy_back_row':
                result = [u for u in candidates if self._is_back_row(u)]
                _log.info("[TARGET]   LINE: enemy_back_row explicit -> force BACK row (%d units)",
                          len(result))
                return result
            # 默认行为：按anchor所在排选择
            anchor = ordered[0]
            anchor_is_front = self._is_front_row(anchor)
            return [u for u in candidates if self._is_front_row(u) == anchor_is_front]

        elif r_type == DisplayTargetRange.COLUMN:
            if mark_priority:
                anchor = self._select_anchor_by_mark(candidates, mark_priority)
                if anchor is None:
                    anchor = ordered[0]
            else:
                anchor = ordered[0]
            anchor_col = self._get_column_index(anchor)
            return [u for u in candidates if self._get_column_index(u) == anchor_col]

        elif r_type in (DisplayTargetRange.TWO_PAWNS, DisplayTargetRange.THREE_PAWNS,
                        DisplayTargetRange.FOUR_PAWNS):
            count_map = {
                DisplayTargetRange.TWO_PAWNS: 2,
                DisplayTargetRange.THREE_PAWNS: 3,
                DisplayTargetRange.FOUR_PAWNS: 4,
            }
            count = count_map[r_type]
            primary = ordered[0]
            remaining = [u for u in ordered[1:] if u != primary]
            remaining.sort(key=lambda u: self._get_sort_key(primary.position, u))
            return [primary] + remaining[:min(count - 1, len(remaining))]

        return [ordered[0]]

    def _order_by_priority(self, caster: UnitState, candidates: List[UnitState],
                           priority) -> List[UnitState]:
        if priority is not None:
            try:
                p_type = DisplayTargetPriority(priority)
            except ValueError:
                p_type = None
        else:
            p_type = None

        if p_type is None or p_type == DisplayTargetPriority.NEAREST:
            candidates.sort(key=lambda u: self._get_sort_key(caster.position, u))
            return candidates

        if p_type == DisplayTargetPriority.FARTHEST:
            candidates.sort(key=lambda u: self._get_farthest_key(caster.position, u))
            return candidates

        if p_type == DisplayTargetPriority.LOWEST_HP_PERCENT:
            candidates.sort(key=lambda u: (u.current_hp / u.max_hp if u.max_hp > 0 else 1.0,
                                           self._get_sort_key(caster.position, u)))
            return candidates

        if p_type == DisplayTargetPriority.HIGHEST_ATK:
            candidates.sort(key=lambda u: (-u.attack, self._get_sort_key(caster.position, u)))
            return candidates

        if p_type == DisplayTargetPriority.HIGHEST_SPEED:
            candidates.sort(key=lambda u: (-u.speed, self._get_sort_key(caster.position, u)))
            return candidates

        filtered = self._filter_by_priority(candidates, priority)
        remaining = [u for u in candidates if u not in filtered]
        filtered.sort(key=lambda u: self._get_sort_key(caster.position, u))
        remaining.sort(key=lambda u: self._get_sort_key(caster.position, u))
        return filtered + remaining

    def _filter_by_priority(self, candidates: List[UnitState], priority) -> List[UnitState]:
        p_type = DisplayTargetPriority(priority)

        if p_type == DisplayTargetPriority.FRONT_LINE:
            front = [u for u in candidates if self._is_front_row(u)]
            return front if front else [u for u in candidates if self._is_back_row(u)]

        elif p_type == DisplayTargetPriority.BACK_LINE:
            back = [u for u in candidates if self._is_back_row(u)]
            return back if back else [u for u in candidates if self._is_front_row(u)]

        elif p_type == DisplayTargetPriority.LEFT_COLUMN:
            left = [u for u in candidates if self._get_column_index(u) == 0]
            if left:
                return left
            center = [u for u in candidates if self._get_column_index(u) == 1]
            if center:
                return center
            return [u for u in candidates if self._get_column_index(u) == 2]

        elif p_type == DisplayTargetPriority.CENTER_COLUMN:
            center = [u for u in candidates if self._get_column_index(u) == 1]
            if center:
                return center
            left = [u for u in candidates if self._get_column_index(u) == 0]
            right = [u for u in candidates if self._get_column_index(u) == 2]
            if left and right:
                return left + right
            return left if left else right

        elif p_type == DisplayTargetPriority.RIGHT_COLUMN:
            right = [u for u in candidates if self._get_column_index(u) == 2]
            if right:
                return right
            center = [u for u in candidates if self._get_column_index(u) == 1]
            if center:
                return center
            return [u for u in candidates if self._get_column_index(u) == 0]

        return list(candidates)

    def _get_sort_key(self, caster_pos: Position, unit: UnitState):
        _, cc = _POS_RC[caster_pos]
        tr, tc = _POS_RC[unit.position]
        # 欧几里得平方距离（含斜向距离），而非曼哈顿距离
        # 例：从左前(0,0)看，中后(1,1)距离2 < 右前(0,2)距离4，中后应优先
        dist_sq = (tr - 0) ** 2 + (tc - cc) ** 2
        return (dist_sq, tr, tc)

    def _get_farthest_key(self, caster_pos: Position, unit: UnitState):
        _, cc = _POS_RC[caster_pos]
        tr, tc = _POS_RC[unit.position]
        dist_sq = (tr - 0) ** 2 + (tc - cc) ** 2
        return (-dist_sq, tr, tc)

    def _is_front_row(self, unit: UnitState) -> bool:
        name = unit.position.name
        return "FRONT" in name

    def _is_back_row(self, unit: UnitState) -> bool:
        name = unit.position.name
        return "BACK" in name

    def _get_column_index(self, unit: UnitState) -> int:
        name = unit.position.name
        if "LEFT" in name:
            return 0
        if "RIGHT" in name:
            return 2
        return 1

    def _count_mark(self, unit: UnitState, mark_name: str) -> int:
        """统计单位身上持有指定 mark_name 的数量（同时检查 debuffs 和 buffs）"""
        count = sum(1 for b in unit.debuffs
                    if b.effect_type == SkillEffectType.MARK.value and b.name == mark_name)
        count += sum(1 for b in unit.buffs
                     if b.effect_type == SkillEffectType.MARK.value and b.name == mark_name)
        return count

    def _select_anchor_by_mark(self, candidates: List[UnitState], mark_name: str) -> Optional[UnitState]:
        """从 candidates 中选择持有指定 mark 最多的单位作为 anchor，无 mark 则返回 None"""
        best_unit = None
        best_count = 0
        for u in candidates:
            c = self._count_mark(u, mark_name)
            if c > best_count:
                best_count = c
                best_unit = u
        if best_count > 0:
            _log.info("[TARGET]   COLUMN mark_priority='%s': anchor=%s (mark_count=%d)",
                      mark_name, best_unit.name, best_count)
            return best_unit
        return None

    def select_fewest_mark_target(self, caster: UnitState, candidates: List[UnitState],
                                   mark_name: str) -> Optional[UnitState]:
        """从 candidates 中选择持有指定 mark 最少的单位（含0个），平局按距离最近优先"""
        if not candidates:
            return None
        # 按 (mark_count, distance) 排序，mark数最少+距离最近优先
        def _sort_key(u):
            c = self._count_mark(u, mark_name)
            d = self._get_sort_key(caster.position, u)
            return (c, d)
        best_unit = min(candidates, key=_sort_key)
        best_count = self._count_mark(best_unit, mark_name)
        _log.info("[TARGET]   fewest_mark_priority='%s': target=%s (mark_count=%d)",
                  mark_name, best_unit.name, best_count)
        return best_unit

    def _get_adjacent_to_closest(self, enemy_units: List[UnitState], caster: UnitState) -> List[UnitState]:
        if not enemy_units:
            return []
        closest = min(enemy_units, key=lambda u: self._get_sort_key(caster.position, u))
        adj_positions = self._get_adjacent_positions(closest.position)
        # Exclude the reference target (closest) itself — it is only a reference, not a valid adjacent target
        return [u for u in enemy_units if u.position in adj_positions and u != closest]

    def get_adjacent_to_unit(self, unit: UnitState, battlefield: BattlefieldState, caster: UnitState = None) -> List[UnitState]:
        """获取指定单位邻接位置的存活敌方单位（从施法者视角的敌方，不含主目标自身）"""
        from ...entities_v2.enums import Side
        if caster:
            enemy_side = Side.ENEMY if caster.side == Side.ALLY else Side.ALLY
        else:
            enemy_side = Side.ENEMY if unit.side == Side.ALLY else Side.ALLY
        enemies = [u for u in battlefield.get_alive_units(enemy_side) if u.unit_id != unit.unit_id]
        adj_positions = self._get_adjacent_positions(unit.position)
        return [u for u in enemies if u.position in adj_positions]

    def get_nearest_enemy(self, caster: UnitState, enemies: List[UnitState]) -> Optional[UnitState]:
        """获取距离施法者最近的敌方单位（基于列参考点的欧几里得平方距离）"""
        if not enemies:
            return None
        cr, cc = _POS_RC[caster.position]
        def _dist(e):
            er, ec = _POS_RC[e.position]
            return (er - cr) ** 2 + (ec - cc) ** 2
        return min(enemies, key=_dist)

    def get_nearest_ally(self, caster: UnitState, allies: List[UnitState]) -> Optional[UnitState]:
        """获取距离施法者最近的友方单位（基于列参考点的欧几里得平方距离）"""
        if not allies:
            return None
        cr, cc = _POS_RC[caster.position]
        def _dist(a):
            ar, ac = _POS_RC[a.position]
            return (ar - cr) ** 2 + (ac - cc) ** 2
        return min(allies, key=_dist)

    def _get_adjacent_positions(self, pos: Position) -> set:
        rc = _POS_RC.get(pos)
        if rc is None:
            return set()
        r, c = rc
        adj = set()
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            for p, (pr, pc) in _POS_RC.items():
                if (pr, pc) == (nr, nc):
                    adj.add(p)
        return adj