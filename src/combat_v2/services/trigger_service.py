from typing import List, Optional, Any, Dict, Set, Callable
from dataclasses import dataclass, field

from ...entities_v2.unit_state import UnitState
from ...entities_v2.battlefield_state import BattlefieldState
from ...entities_v2.enums import TriggerTiming, SkillType, Position, SkillEffectType
from ..battle_logger import battle_logger

_log = battle_logger()

TRIGGER_TYPE_MAP: Dict[str, TriggerTiming] = {
    "before_skill_use": TriggerTiming.BEFORE_SKILL_USE,
    "after_as_attack": TriggerTiming.AFTER_SKILL_USE,
    "before_as_attacked": TriggerTiming.BEFORE_AS_ATTACKED,
    "before_any_attacked": TriggerTiming.BEFORE_ANY_ATTACKED,
    "before_enemy_as_attack": TriggerTiming.BEFORE_ENEMY_AS_ATTACK,
    "before_ally_as_attack": TriggerTiming.BEFORE_ALLY_AS_ATTACK,
    "after_as_attacked": TriggerTiming.AFTER_AS_ATTACKED,
    "after_ally_attacked": TriggerTiming.AFTER_ALLY_ATTACKED,
    "after_self_attacked": TriggerTiming.AFTER_SELF_ATTACKED,
    "after_as_attacked_ally": TriggerTiming.AFTER_AS_ATTACKED_ALLY,
    "after_ally_as_attack": TriggerTiming.AFTER_ALLY_AS_ATTACK,
    "on_battle_start": TriggerTiming.BATTLE_START,
    "on_turn_start": TriggerTiming.TURN_START,
    "on_turn_end": TriggerTiming.TURN_END,
    "on_ally_killed": TriggerTiming.PAWN_DIED,
    "on_linked_enemy_killed": TriggerTiming.PAWN_DIED,
    "on_kill": TriggerTiming.PAWN_KILLED,
    "on_any_kill": TriggerTiming.PAWN_ANY_KILL,
    "on_critical": TriggerTiming.PAWN_CAUSED_CRITICAL,
    "on_debuff_applied": TriggerTiming.PAWN_RECEIVED_AURA,
    "on_hp_below": TriggerTiming.HP_BELOW,
    "on_skill_use_count": TriggerTiming.SKILL_USE_COUNT,
    "on_unit_count_below": TriggerTiming.UNIT_COUNT_BELOW,
    "on_ally_charge_use": TriggerTiming.ALLY_CHARGE_USE,
    "on_cumulative_damage": TriggerTiming.CUMULATIVE_DAMAGE,
}


@dataclass
class TriggerContext:
    """触发器上下文"""
    timing: TriggerTiming
    battlefield: BattlefieldState

    actor: Optional[UnitState] = None
    targets: List[UnitState] = field(default_factory=list)
    triggered_by: Optional[UnitState] = None
    primary_target: Optional[UnitState] = None

    skill: Optional[Any] = None
    damage_map: Dict[str, int] = field(default_factory=dict)
    heal_map: Dict[str, int] = field(default_factory=dict)

    tags: Set[str] = field(default_factory=set)
    # For on_debuff_applied: set of target_ids that received a NEW knockout (not a refresh)
    new_knockout_target_ids: Set[str] = field(default_factory=set)
    # For on_debuff_applied: set of debuff effect types applied in this trigger
    # (used when target's debuffs may have been cleared by revival, e.g. tactical exercise)
    applied_debuff_types: Set[str] = field(default_factory=set)


@dataclass
class TriggerAction:
    """触发器产生的动作"""
    skill_id: int
    owner_id: str
    action_type: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    instance: Any = None


@dataclass
class TriggerInstance:
    """待执行的触发器实例"""
    skill_id: int
    owner: UnitState
    priority: int


class TriggerService:
    """
    触发器服务
    负责全局扫描、条件检查和执行顺序排序
    """

    def __init__(self):
        self.data_loader = None
        self.skill_service = None
        self.damage_service = None

    def set_data_loader(self, loader: Any):
        self.data_loader = loader

    def set_skill_service(self, skill_svc: Any):
        self.skill_service = skill_svc

    def set_damage_service(self, damage_svc: Any):
        self.damage_service = damage_svc

    def trigger_battle_start(self, battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(TriggerTiming.BATTLE_START, battlefield)
        return self.check_triggers(TriggerTiming.BATTLE_START, ctx)

    def trigger_wave_start(self, battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(TriggerTiming.WAVE_START, battlefield)
        return self.check_triggers(TriggerTiming.WAVE_START, ctx)

    def trigger_wave_end(self, battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(TriggerTiming.WAVE_END, battlefield)
        return self.check_triggers(TriggerTiming.WAVE_END, ctx)

    def trigger_turn_start(self, battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(TriggerTiming.TURN_START, battlefield)
        return self.check_triggers(TriggerTiming.TURN_START, ctx)

    def trigger_turn_start_preemptive(self, battlefield: BattlefieldState) -> List[TriggerAction]:
        """Phase 1: 收集TURN_START先制技能（优先于非先制技能执行）"""
        ctx = TriggerContext(TriggerTiming.TURN_START, battlefield)
        return self.check_triggers(TriggerTiming.TURN_START, ctx, preemptive_filter=True)

    def trigger_turn_start_non_preemptive(self, battlefield: BattlefieldState) -> List[TriggerAction]:
        """Phase 2: 收集TURN_START非先制技能（在先制技能执行后重新检查状态）"""
        ctx = TriggerContext(TriggerTiming.TURN_START, battlefield)
        return self.check_triggers(TriggerTiming.TURN_START, ctx, preemptive_filter=False)

    def trigger_turn_end(self, battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(TriggerTiming.TURN_END, battlefield)
        return self.check_triggers(TriggerTiming.TURN_END, ctx)

    def trigger_before_skill_use(self, actor: UnitState, skill_id: int,
                                  battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.BEFORE_SKILL_USE, battlefield,
            actor=actor, skill=skill_id,
        )
        return self.check_triggers(TriggerTiming.BEFORE_SKILL_USE, ctx)

    def trigger_after_skill_use(self, actor: UnitState, skill_id: int,
                                 result: Dict, battlefield: BattlefieldState,
                                 primary_target: Optional[UnitState] = None) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.AFTER_SKILL_USE, battlefield,
            actor=actor, skill=skill_id, primary_target=primary_target,
        )
        return self.check_triggers(TriggerTiming.AFTER_SKILL_USE, ctx)

    def trigger_before_as_attacked(self, targets: List[UnitState],
                                     battlefield: BattlefieldState,
                                     attacker: Optional[UnitState] = None) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.BEFORE_AS_ATTACKED, battlefield,
            targets=targets,
            actor=attacker,
        )
        return self.check_triggers(TriggerTiming.BEFORE_AS_ATTACKED, ctx)

    def trigger_before_any_attacked(self, targets: List[UnitState],
                                      battlefield: BattlefieldState,
                                      attacker: Optional[UnitState] = None) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.BEFORE_ANY_ATTACKED, battlefield,
            targets=targets,
            actor=attacker,
        )
        return self.check_triggers(TriggerTiming.BEFORE_ANY_ATTACKED, ctx)

    def trigger_before_enemy_as_attack(self, actor: UnitState, skill_id: int,
                                        targets: List[UnitState],
                                        battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.BEFORE_ENEMY_AS_ATTACK, battlefield,
            actor=actor, skill=skill_id, targets=targets,
        )
        return self.check_triggers(TriggerTiming.BEFORE_ENEMY_AS_ATTACK, ctx)

    def trigger_before_ally_as_attack(self, actor: UnitState, skill_id: int,
                                        battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.BEFORE_ALLY_AS_ATTACK, battlefield,
            actor=actor, skill=skill_id,
        )
        return self.check_triggers(TriggerTiming.BEFORE_ALLY_AS_ATTACK, ctx)

    def trigger_after_as_attacked(self, targets: List[UnitState],
                                    battlefield: BattlefieldState,
                                    actor: Optional[UnitState] = None,
                                    primary_target: Optional[UnitState] = None) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.AFTER_AS_ATTACKED, battlefield,
            targets=targets,
            actor=actor,
            primary_target=primary_target,
        )
        return self.check_triggers(TriggerTiming.AFTER_AS_ATTACKED, ctx)

    def trigger_after_ally_attacked(self, targets: List[UnitState],
                                      battlefield: BattlefieldState,
                                      actor: Optional[UnitState] = None,
                                      primary_target: Optional[UnitState] = None) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.AFTER_ALLY_ATTACKED, battlefield,
            targets=targets,
            actor=actor,
            primary_target=primary_target,
        )
        return self.check_triggers(TriggerTiming.AFTER_ALLY_ATTACKED, ctx)

    def trigger_after_self_attacked(self, targets: List[UnitState],
                                      battlefield: BattlefieldState,
                                      actor: Optional[UnitState] = None,
                                      primary_target: Optional[UnitState] = None) -> List[TriggerAction]:
        """自身被攻击后触发：owner必须是被攻击的主目标"""
        ctx = TriggerContext(
            TriggerTiming.AFTER_SELF_ATTACKED, battlefield,
            targets=targets,
            actor=actor,
            primary_target=primary_target,
        )
        return self.check_triggers(TriggerTiming.AFTER_SELF_ATTACKED, ctx)

    def trigger_after_as_attacked_ally(self, targets: List[UnitState],
                                         battlefield: BattlefieldState,
                                         actor: Optional[UnitState] = None,
                                         primary_target: Optional[UnitState] = None) -> List[TriggerAction]:
        """友方被AS技能攻击后触发（仅AS技能+主目标条件）"""
        ctx = TriggerContext(
            TriggerTiming.AFTER_AS_ATTACKED_ALLY, battlefield,
            targets=targets,
            actor=actor,
            primary_target=primary_target,
        )
        return self.check_triggers(TriggerTiming.AFTER_AS_ATTACKED_ALLY, ctx)

    def trigger_after_ally_as_attack(self, actor: UnitState, skill_id: int,
                                       targets: List[UnitState],
                                       battlefield: BattlefieldState) -> List[TriggerAction]:
        """其他友方AS攻击后触发（同阵营、非自身、AS技能）"""
        ctx = TriggerContext(
            TriggerTiming.AFTER_ALLY_AS_ATTACK, battlefield,
            actor=actor, skill=skill_id,
            targets=targets,
        )
        return self.check_triggers(TriggerTiming.AFTER_ALLY_AS_ATTACK, ctx)

    def trigger_pawn_died(self, dead_units: List[UnitState],
                            battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.PAWN_DIED, battlefield,
            targets=dead_units,
        )
        return self.check_triggers(TriggerTiming.PAWN_DIED, ctx)

    def trigger_pawn_killed(self, killer: UnitState,
                              battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.PAWN_KILLED, battlefield,
            actor=killer,
        )
        return self.check_triggers(TriggerTiming.PAWN_KILLED, ctx)

    def trigger_pawn_any_kill(self, killer: UnitState,
                               battlefield: BattlefieldState) -> List[TriggerAction]:
        """敌方被击倒时触发：同阵营任意单位击杀均可触发（不限击杀者）"""
        ctx = TriggerContext(
            TriggerTiming.PAWN_ANY_KILL, battlefield,
            actor=killer,
        )
        return self.check_triggers(TriggerTiming.PAWN_ANY_KILL, ctx)

    def trigger_pawn_caused_critical(self, caster: UnitState,
                                     battlefield: BattlefieldState,
                                     count: int = 1) -> List[TriggerAction]:
        caster.crit_counter += count
        _log.info("[TRIGGER] %s: crit_counter += %d => %d", caster.name, count, caster.crit_counter)
        ctx = TriggerContext(
            TriggerTiming.PAWN_CAUSED_CRITICAL, battlefield,
            actor=caster,
        )
        return self.check_triggers(TriggerTiming.PAWN_CAUSED_CRITICAL, ctx)

    def trigger_hp_below(self, battlefield: BattlefieldState,
                         damaged_units: Optional[List[UnitState]] = None) -> List[TriggerAction]:
        actions = []
        units_to_check = damaged_units if damaged_units else battlefield.get_all_units()
        for unit in units_to_check:
            if not unit.is_alive:
                continue
            
            # 获取当前HP百分比
            current_hp_percent = (unit.current_hp / unit.max_hp) * 100
            
            # 收集所有同阵营PS技能的HP阈值，确保每个阈值都能被检测到
            # 例如：受伤单位自身PS阈值为40%，但友方PS（再起律動）阈值为50%
            # 如果HP从55%降到45%，只检查40%阈值不会触发，但50%阈值应该触发
            thresholds = self._get_all_hp_below_thresholds(unit, battlefield)
            
            triggered = False
            for threshold in sorted(thresholds, reverse=True):
                crossed_threshold = unit.prev_hp_percent > threshold and current_hp_percent <= threshold
                if crossed_threshold:
                    _log.info("[HP_BELOW] %s: HP从%.1f%%降至%.1f%%（阈值%.0f%%），触发阈值跨越", 
                              unit.name, unit.prev_hp_percent, current_hp_percent, threshold)
                    ctx = TriggerContext(TriggerTiming.HP_BELOW, battlefield, triggered_by=unit)
                    actions.extend(self.check_triggers(TriggerTiming.HP_BELOW, ctx))
                    triggered = True
                    break  # 每个单位每次伤害事件只触发一次
            
            # 更新prev_hp_percent为当前值（放在最后，确保日志输出正确）
            unit.prev_hp_percent = current_hp_percent
        return actions

    def _get_hp_below_threshold(self, unit: UnitState) -> float:
        """从单位拥有的PS技能配置中读取on_hp_below的HP阈值"""
        if not self.data_loader:
            return 40.0  # 默认值
        char_skills = self.data_loader.get_character_skills(unit.character_id)
        if not char_skills:
            if hasattr(unit, 'skills') and unit.skills:
                char_skills = []
                for sid in unit.skills:
                    sk = self.data_loader.get_skill_by_id(sid)
                    if sk:
                        char_skills.append(sk)
        if not char_skills:
            return 40.0
        for skill in char_skills:
            if skill.skill_type != SkillType.PS.value:
                continue
            parsed = self.data_loader.get_parsed_skill_data(skill.skill_id)
            if not parsed:
                continue
            trigger_type = parsed.get('trigger_type')
            if trigger_type == 'on_hp_below':
                condition = parsed.get('global_condition')
                if isinstance(condition, dict):
                    val = condition.get('value', 40)
                    return float(val)
        return 40.0  # 默认值

    def _get_all_hp_below_thresholds(self, unit: UnitState, battlefield: BattlefieldState) -> set:
        """收集所有同阵营PS技能的on_hp_below阈值，确保每个阈值都能被检测到跨越事件

        例如：受伤单位自身PS阈值为40%，但友方PS（再起律動）阈值为50%。
        如果HP从55%降到45%，只检查40%阈值不会触发，但50%阈值应该触发。
        """
        thresholds = set()
        same_side_units = [u for u in battlefield.get_all_units()
                           if u.side == unit.side and u.is_alive]
        for other_unit in same_side_units:
            if not self.data_loader:
                continue
            char_skills = self.data_loader.get_character_skills(other_unit.character_id)
            if not char_skills:
                if hasattr(other_unit, 'skills') and other_unit.skills:
                    char_skills = []
                    for sid in other_unit.skills:
                        sk = self.data_loader.get_skill_by_id(sid)
                        if sk:
                            char_skills.append(sk)
            if not char_skills:
                continue
            for skill in char_skills:
                if skill.skill_type != SkillType.PS.value:
                    continue
                parsed = self.data_loader.get_parsed_skill_data(skill.skill_id)
                if not parsed:
                    continue
                trigger_type = parsed.get('trigger_type')
                if trigger_type == 'on_hp_below':
                    condition = parsed.get('global_condition')
                    if isinstance(condition, dict):
                        cond_type = condition.get('type', '')
                        val = condition.get('value', 40)
                        # self_hp_percent: 仅当受伤单位就是PS持有者时才相关
                        if cond_type == 'self_hp_percent':
                            if other_unit.unit_id == unit.unit_id:
                                thresholds.add(float(val))
                        # front_ally_hp_below: 仅当受伤单位是PS持有者正前方友方时才相关
                        elif cond_type == 'front_ally_hp_below':
                            front_pos = _get_front_position(other_unit.position)
                            if front_pos and unit.position == front_pos:
                                thresholds.add(float(val))
                        else:
                            thresholds.add(float(val))
        if not thresholds:
            thresholds.add(40.0)
        return thresholds

    def trigger_skill_use_count(self, actor: UnitState,
                                  battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(
            TriggerTiming.SKILL_USE_COUNT, battlefield,
            actor=actor,
        )
        return self.check_triggers(TriggerTiming.SKILL_USE_COUNT, ctx)

    def trigger_unit_count_below(self, battlefield: BattlefieldState) -> List[TriggerAction]:
        ctx = TriggerContext(TriggerTiming.UNIT_COUNT_BELOW, battlefield)
        return self.check_triggers(TriggerTiming.UNIT_COUNT_BELOW, ctx)

    def trigger_ally_charge_use(self, charger: UnitState, battlefield: BattlefieldState) -> List[TriggerAction]:
        """友方使用充能技能时触发"""
        ctx = TriggerContext(TriggerTiming.ALLY_CHARGE_USE, battlefield)
        ctx.actor = charger
        return self.check_triggers(TriggerTiming.ALLY_CHARGE_USE, ctx)

    def trigger_cumulative_damage(self, battlefield: BattlefieldState,
                                   damaged_units: Optional[List[UnitState]] = None) -> List[TriggerAction]:
        """累计伤害达到阈值时触发

        检查指定单位（或所有单位）的累计HP伤害是否达到阈值。
        阈值从PS技能配置的global_condition.value读取（百分比形式，如10表示10%最大HP）。
        触发后计数器不在此时清除，而是在_execute_trigger_actions中PS成功执行后清除。
        """
        actions = []
        units_to_check = damaged_units if damaged_units else battlefield.get_all_units()
        for unit in units_to_check:
            if not unit.is_alive:
                continue

            # 从PS技能配置中读取累计伤害阈值
            threshold = self._get_cumulative_damage_threshold(unit)
            if threshold is None:
                continue

            # 检查累计HP伤害是否达到阈值
            threshold_value = unit.max_hp * threshold / 100
            _log.info("[CUMULATIVE_DMG_CHECK] %s: cumulative_hp_damage=%d, threshold=%.0f (max_hp=%d * %d%%), exceeded=%s",
                      unit.name, unit.cumulative_hp_damage, threshold_value, unit.max_hp, threshold,
                      unit.cumulative_hp_damage >= threshold_value)
            if unit.cumulative_hp_damage >= threshold_value:
                _log.info("[CUMULATIVE_DMG] %s: cumulative_hp_damage=%d >= threshold=%.0f (max_hp=%d * %d%%), triggering",
                          unit.name, unit.cumulative_hp_damage, threshold_value, unit.max_hp, threshold)
                ctx = TriggerContext(TriggerTiming.CUMULATIVE_DAMAGE, battlefield, triggered_by=unit)
                actions.extend(self.check_triggers(TriggerTiming.CUMULATIVE_DAMAGE, ctx))

        return actions

    def _get_cumulative_damage_threshold(self, unit: UnitState) -> Optional[float]:
        """从单位拥有的PS技能配置中读取on_cumulative_damage的阈值（百分比）"""
        if not self.data_loader:
            _log.info("[CUMULATIVE_DMG_THRESHOLD] %s: no data_loader", unit.name)
            return None
        char_skills = self.data_loader.get_character_skills(unit.character_id)
        if not char_skills:
            if hasattr(unit, 'skills') and unit.skills:
                char_skills = []
                for sid in unit.skills:
                    sk = self.data_loader.get_skill_by_id(sid)
                    if sk:
                        char_skills.append(sk)
        if not char_skills:
            _log.info("[CUMULATIVE_DMG_THRESHOLD] %s: no char_skills (character_id=%s)", unit.name, unit.character_id)
            return None
        for skill in char_skills:
            if skill.skill_type != SkillType.PS.value:
                continue
            parsed = self.data_loader.get_parsed_skill_data(skill.skill_id)
            if not parsed:
                _log.info("[CUMULATIVE_DMG_THRESHOLD] %s: no parsed data for skill %d", unit.name, skill.skill_id)
                continue
            trigger_type = parsed.get('trigger_type')
            if trigger_type == 'on_cumulative_damage':
                condition = parsed.get('global_condition')
                if isinstance(condition, dict):
                    val = condition.get('value', 10)
                    _log.info("[CUMULATIVE_DMG_THRESHOLD] %s: skill %d threshold=%s%%", unit.name, skill.skill_id, val)
                    return float(val)
        _log.info("[CUMULATIVE_DMG_THRESHOLD] %s: no on_cumulative_damage PS found among %d skills", unit.name, len(char_skills))
        return None

    def trigger_pawn_received_aura(self, battlefield: BattlefieldState,
                                   affected_unit_ids: List[str] = None,
                                   actor: Optional[UnitState] = None,
                                   new_knockout_target_ids: Set[str] = None,
                                   applied_debuff_types: Set[str] = None) -> List[TriggerAction]:
        ctx = TriggerContext(TriggerTiming.PAWN_RECEIVED_AURA, battlefield)
        if affected_unit_ids:
            ctx.targets = [u for u in battlefield.get_all_units() if u.unit_id in affected_unit_ids]
        if actor:
            ctx.actor = actor
        if new_knockout_target_ids:
            ctx.new_knockout_target_ids = new_knockout_target_ids
            # Set primary_target to the first new knockout target (for PS2 damage targeting)
            for t in ctx.targets:
                if t.unit_id in new_knockout_target_ids:
                    ctx.primary_target = t
                    break
        elif ctx.targets:
            # For on_debuff_applied (non-knockout): set primary_target to the first target
            # so debuff_applied_target can resolve correctly
            ctx.primary_target = ctx.targets[0]
        if applied_debuff_types:
            ctx.applied_debuff_types = applied_debuff_types
        return self.check_triggers(TriggerTiming.PAWN_RECEIVED_AURA, ctx)

    def check_triggers(self, timing: TriggerTiming, context: TriggerContext,
                        preemptive_filter: Optional[bool] = None) -> List[TriggerAction]:
        if not self.data_loader:
            return []

        candidates: List[TriggerInstance] = []

        for unit in context.battlefield.get_all_units():
            if not unit.is_alive:
                continue
            if unit.is_stunned or unit.is_frozen or unit.is_charging:
                continue

            char_skills = self.data_loader.get_character_skills(unit.character_id)
            if not char_skills:
                # 回退：部分敌方单位（如战术演习）的character_id不在character_skills
                # 或enemy_skills中，但unit.skills已正确填充。从unit.skills解析技能数据。
                if hasattr(unit, 'skills') and unit.skills:
                    char_skills = []
                    for sid in unit.skills:
                        sk = self.data_loader.get_skill_by_id(sid)
                        if sk:
                            char_skills.append(sk)
                if not char_skills:
                    continue

            for skill in char_skills:
                if skill.skill_type != SkillType.PS.value:
                    continue

                parsed = self.data_loader.get_parsed_skill_data(skill.skill_id)
                if not parsed:
                    continue

                if unit.skill_cooldowns.get(skill.skill_id, 0) > 0:
                    _log.info("[TRIGGER_CD] %s PS[%s](id=%d) on cooldown: %s",
                              unit.name, skill.name, skill.skill_id, dict(unit.skill_cooldowns))
                    continue

                if not self._match_trigger_timing(parsed, timing, context, unit):
                    continue

                if not self._check_condition(parsed, unit, timing, context):
                    continue

                prio = self.calculate_priority(unit)
                candidates.append(TriggerInstance(
                    skill_id=skill.skill_id,
                    owner=unit,
                    priority=prio,
                ))
                _log.info("[TRIGGER] %s PS[%s] (id=%d) matched timing=%s",
                          unit.name, skill.name, skill.skill_id, timing.name)

        # 先制效果分阶段过滤：TURN_START时，先制技能先于非先制技能分两阶段收集
        # Phase 1: 收集先制技能 → 执行 → Phase 2: 重新收集非先制技能（状态可能已变化）
        if preemptive_filter is not None and timing == TriggerTiming.TURN_START:
            filtered: List[TriggerInstance] = []
            for cand in candidates:
                parsed = self.data_loader.get_parsed_skill_data(cand.skill_id)
                is_pre = False
                if parsed:
                    for block in parsed.get('effect_blocks', []):
                        for eff in block.get('effects', []):
                            if eff.get('flags', {}).get('is_preemptive'):
                                is_pre = True
                                break
                        if is_pre:
                            break
                if is_pre == preemptive_filter:
                    filtered.append(cand)
            candidates = filtered

        return self._process_candidates(candidates, context)

    def _match_trigger_timing(self, parsed: Dict, timing: TriggerTiming,
                               context: TriggerContext, owner: UnitState) -> bool:
        trigger_type = parsed.get('trigger_type')
        if not trigger_type:
            return False

        expected = TRIGGER_TYPE_MAP.get(trigger_type)
        if expected is None:
            try:
                expected = TriggerTiming(trigger_type)
            except ValueError:
                _log.info("[TRIGGER_MATCH] %s: unknown trigger_type=%s", owner.name, trigger_type)
                return False

        if expected != timing:
            return False

        if timing == TriggerTiming.BEFORE_SKILL_USE:
            if context.actor is None:
                return False
            if owner.unit_id != context.actor.unit_id:
                return False
            # before_skill_use仅限AS技能(skill_type=1)触发，EX/PS技能不触发
            if context.skill is not None and self.data_loader:
                skill_data = self.data_loader.get_skill_by_id(context.skill)
                if skill_data and skill_data.skill_type != SkillType.AS.value:
                    _log.info("[TRIGGER_MATCH] %s: BEFORE_SKILL_USE blocked (skill %d is not AS type=%d)",
                              owner.name, context.skill, skill_data.skill_type if skill_data else -1)
                    return False
            return True

        if timing == TriggerTiming.AFTER_SKILL_USE:
            if context.actor is None:
                return False
            if owner.unit_id != context.actor.unit_id:
                return False
            # after_as_attack仅限AS技能(skill_type=1)触发，EX/PS技能不触发
            if context.skill is not None and self.data_loader:
                skill_data = self.data_loader.get_skill_by_id(context.skill)
                if skill_data and skill_data.skill_type != SkillType.AS.value:
                    _log.info("[TRIGGER_MATCH] %s: AFTER_SKILL_USE blocked (skill %d is not AS type=%d)",
                              owner.name, context.skill, skill_data.skill_type if skill_data else -1)
                    return False
            return True

        if timing == TriggerTiming.BEFORE_AS_ATTACKED:
            if not context.targets:
                return False
            # 只有敌方攻击己方时才触发：攻击者与PS owner不同阵营
            if context.actor is not None:
                if context.actor.side == owner.side:
                    _log.info("[TRIGGER_MATCH] %s: BEFORE_AS_ATTACKED blocked (attacker %s is same side)",
                              owner.name, context.actor.name)
                    return False
            # 援护类PS技能：如果攻击目标只有PS持有者本人，没有其他友方可保护，则不触发
            if self._is_cover_ps(parsed):
                has_other_ally = any(t.unit_id != owner.unit_id and t.side == owner.side
                                     for t in context.targets)
                if not has_other_ally:
                    _log.info("[TRIGGER_MATCH] %s: BEFORE_AS_ATTACKED blocked (cover PS but no ally to protect)",
                              owner.name)
                    return False
            return True

        if timing == TriggerTiming.BEFORE_ANY_ATTACKED:
            if not context.targets:
                return False
            # 只有敌方攻击己方时才触发：攻击者与PS owner不同阵营
            if context.actor is not None:
                if context.actor.side == owner.side:
                    _log.info("[TRIGGER_MATCH] %s: BEFORE_ANY_ATTACKED blocked (attacker %s is same side)",
                              owner.name, context.actor.name)
                    return False
            # 援护类PS技能：如果攻击目标只有PS持有者本人，没有其他友方可保护，则不触发
            if self._is_cover_ps(parsed):
                has_other_ally = any(t.unit_id != owner.unit_id and t.side == owner.side
                                     for t in context.targets)
                if not has_other_ally:
                    _log.info("[TRIGGER_MATCH] %s: BEFORE_ANY_ATTACKED blocked (cover PS but no ally to protect)",
                              owner.name)
                    return False
            return True

        if timing == TriggerTiming.BEFORE_ENEMY_AS_ATTACK:
            # 只有敌方带有伤害的攻击才会触发
            if context.actor is None:
                return False
            if context.actor.side == owner.side:
                return False
            # 检查攻击是否带有伤害效果
            skill_id = context.skill
            if skill_id is None:
                return False
            skill_data = self.data_loader.get_skill_by_id(skill_id)
            if skill_data is None:
                return False
            parsed = self.data_loader.get_parsed_skill_data(skill_id) if hasattr(self.data_loader, 'get_parsed_skill_data') else None
            if parsed is None:
                # Fallback: check resolved data
                resolver = getattr(self, '_resolver', None)
                if resolver is None:
                    from ..skill_data_resolver import SkillDataResolver
                    resolver = SkillDataResolver(self.data_loader)
                    self._resolver = resolver
                resolved = resolver.resolve(skill_id, 1)
                if resolved is None:
                    return False
                has_damage = any(e.effect_type == "damage" for block in resolved.effect_blocks for e in block.effects)
            else:
                has_damage = any(e.get("effect_type") == "damage" for block in parsed.get("effect_blocks", []) for e in block.get("effects", []))
            if not has_damage:
                _log.info("[TRIGGER_MATCH] %s: BEFORE_ENEMY_AS_ATTACK blocked (skill %d has no damage)", owner.name, skill_id)
                return False
            return True

        if timing == TriggerTiming.BEFORE_ALLY_AS_ATTACK:
            if context.actor is None:
                return False
            if owner.side != context.actor.side or owner.unit_id == context.actor.unit_id:
                return False
            # Check if skill targets ally_front - if so, restrict to front-position unit only
            # (e.g. 追撃符: owner in back row, actor must be same-column front row)
            effect_blocks = parsed.get('effect_blocks', [])
            has_ally_front_target = any(
                e.get('target_type') == 'ally_front'
                for block in effect_blocks
                for e in block.get('effects', [])
            )
            if has_ally_front_target:
                front_pos = _get_front_position(owner.position)
                if front_pos is None or context.actor.position != front_pos:
                    _log.info("[TRIGGER_MATCH] %s: BEFORE_ALLY_AS_ATTACK blocked (skill targets ally_front, actor %s not at front position %s)",
                              owner.name, context.actor.name, front_pos)
                    return False
            return True

        if timing == TriggerTiming.AFTER_AS_ATTACKED:
            if not context.targets:
                return False
            # 仅主目标（AS技能的第一索敌目标）触发
            primary = context.primary_target
            if primary is None and context.targets:
                primary = context.targets[0]
            if primary is None:
                return False
            if owner.unit_id != primary.unit_id:
                _log.info("[TRIGGER_MATCH] %s: AFTER_AS_ATTACKED blocked (owner is not primary target %s)",
                          owner.name, primary.name)
                return False
            return True

        if timing == TriggerTiming.AFTER_ALLY_ATTACKED:
            if context.actor is None:
                return False
            # Attacker must be an enemy (different side from the PS owner)
            if context.actor.side == owner.side:
                return False
            # Determine the primary target of the attack
            primary = context.primary_target
            if primary is None and context.targets:
                primary = context.targets[0]
            if primary is None:
                return False
            # The primary target must be an ally (same side as the PS owner)
            if primary.side != owner.side:
                return False
            return True

        if timing == TriggerTiming.AFTER_SELF_ATTACKED:
            if context.actor is None:
                return False
            # Attacker must be an enemy
            if context.actor.side == owner.side:
                return False
            # The primary target must be the PS owner itself
            primary = context.primary_target
            if primary is None and context.targets:
                primary = context.targets[0]
            if primary is None:
                return False
            return primary.unit_id == owner.unit_id

        if timing == TriggerTiming.AFTER_AS_ATTACKED_ALLY:
            # 友方被AS技能攻击后触发：攻击者是敌方 + 主要目标是友方
            # 不要求owner是主目标，只要同阵营有友方被AS攻击即可
            # （具体条件如"后排"由global_condition控制）
            if context.actor is None:
                return False
            # Attacker must be an enemy (different side from the PS owner)
            if context.actor.side == owner.side:
                return False
            # Determine the primary target of the attack
            primary = context.primary_target
            if primary is None and context.targets:
                primary = context.targets[0]
            if primary is None:
                return False
            # The primary target must be an ally (same side as the PS owner)
            if primary.side != owner.side:
                return False
            return True

        if timing == TriggerTiming.AFTER_ALLY_AS_ATTACK:
            # 其他友方AS攻击后触发：同阵营、非自身
            if context.actor is None:
                return False
            if owner.side != context.actor.side or owner.unit_id == context.actor.unit_id:
                return False
            return True

        if timing == TriggerTiming.PAWN_DIED:
            if not context.targets:
                return False
            # on_ally_killed → trigger when ally dies (owner is not the dead one)
            if trigger_type == "on_ally_killed":
                return (owner.side == context.targets[0].side and
                        owner.unit_id not in {t.unit_id for t in context.targets})
            # on_linked_enemy_killed → 敵方かつダメージリンク保持者が死亡した時
            # 双方向リンク: 死亡者がdamage_link buffを持っている、または死亡者をsourceとするdamage_link buffが存在
            if trigger_type == "on_linked_enemy_killed":
                dead_units = context.targets
                # ownerと逆陣営の死亡者のみ対象
                relevant_dead = [d for d in dead_units if d.side != owner.side]
                if not relevant_dead:
                    return False
                # 死亡者がdamage_link buffを持っているか確認
                for dead in relevant_dead:
                    dead_link_buffs = [b for b in (dead.buffs + dead.debuffs)
                                       if b.effect_type == "damage_link"]
                    if dead_link_buffs:
                        _log.info("[TRIGGER_MATCH] %s: on_linked_enemy_killed matched (dead=%s has damage_link)",
                                  owner.name, dead.name)
                        return True
                return False
            return any(t.unit_id == owner.unit_id for t in context.targets)

        if timing == TriggerTiming.PAWN_KILLED:
            if context.actor is None:
                return False
            return owner.unit_id == context.actor.unit_id

        if timing == TriggerTiming.PAWN_ANY_KILL:
            # 敌方被击倒时触发：不限击杀者，只要有敌方被击倒即可
            return True

        if timing == TriggerTiming.PAWN_CAUSED_CRITICAL:
            if context.actor is None:
                return False
            return owner.unit_id == context.actor.unit_id

        if timing == TriggerTiming.PAWN_RECEIVED_AURA:
            if not context.targets:
                return False
            # If the trigger has debuff_type condition, it fires when the specified debuff
            # is applied to an ENEMY unit (opposite faction from the PS owner).
            # Otherwise it fires when the owner receives a debuff.
            if trigger_type == "on_debuff_applied":
                gc = parsed.get('global_condition')
                if gc and isinstance(gc, dict) and gc.get('type') == 'debuff_type':
                    # Only trigger when debuff is applied to units on the opposite side
                    # AND only for NEW knockouts (not refreshes on already-stunned targets)
                    debuff_val = str(gc.get('value', '')).lower()
                    if debuff_val == 'knockout' and context.new_knockout_target_ids:
                        return any(t.side != owner.side and t.unit_id in context.new_knockout_target_ids
                                   for t in context.targets)
                    elif debuff_val == 'knockout':
                        # No new knockout targets, don't trigger
                        return False
                    return any(t.side != owner.side for t in context.targets)
                else:
                    # on_debuff_applied without debuff_type condition
                    gc = parsed.get('global_condition')
                    if gc and isinstance(gc, dict) and gc.get('type') == 'target_is_self':
                        # triggers when a debuff is applied to SELF (e.g. 明鏡止水)
                        return owner.unit_id in [t.unit_id for t in context.targets]
                    elif gc and isinstance(gc, dict) and gc.get('type') == 'is_status_ailment':
                        # triggers when SELF receives a status ailment (e.g. ヴォルコワの血脈Ω)
                        return owner.unit_id in [t.unit_id for t in context.targets]
                    else:
                        # triggers when ANY debuff is applied to an ENEMY unit
                        return any(t.side != owner.side for t in context.targets)
            return owner.unit_id in [t.unit_id for t in context.targets]

        if timing == TriggerTiming.SKILL_USE_COUNT:
            # Only the PS owner's own skill uses can trigger this
            if context.actor is None:
                return False
            return owner.unit_id == context.actor.unit_id

        if timing == TriggerTiming.ALLY_CHARGE_USE:
            if trigger_type == "on_ally_charge_use":
                # 仅友方（非自身）使用充能技能时触发
                if context.actor is None:
                    return False
                return owner.side == context.actor.side and owner.unit_id != context.actor.unit_id
            return False

        # PS skills with is_status_ailment or debuff_type condition must NOT trigger
        # on battle_start / turn_start / turn_end timing
        if timing in (TriggerTiming.BATTLE_START, TriggerTiming.TURN_START,
                       TriggerTiming.TURN_END):
            gc = parsed.get('global_condition')
            if gc and isinstance(gc, dict) and gc.get('type') in ('is_status_ailment', 'debuff_type'):
                return False

        if timing in (TriggerTiming.BATTLE_START, TriggerTiming.WAVE_START,
                       TriggerTiming.WAVE_END, TriggerTiming.TURN_START,
                       TriggerTiming.TURN_END, TriggerTiming.HP_BELOW,
                       TriggerTiming.UNIT_COUNT_BELOW,
                       TriggerTiming.CUMULATIVE_DAMAGE):
            return True

        return True

    def _is_cover_ps(self, parsed: Dict) -> bool:
        """判断PS技能是否为援护类（包含cover或guard效果）"""
        for block in parsed.get('effect_blocks', []):
            for eff in block.get('effects', []):
                if eff.get('effect_type') in ('cover', 'guard'):
                    return True
        return False

    def _check_condition(self, parsed: Dict, owner: UnitState,
                          timing: TriggerTiming, context: TriggerContext) -> bool:
        condition = parsed.get('global_condition')
        if condition is None:
            return True

        cond_type = condition.get('type') if isinstance(condition, dict) else None
        if cond_type is None:
            return True

        op = condition.get('operator', '==')
        val = condition.get('value', 0)

        if cond_type == "self_hp_percent":
            # self_hp_percent 始终检查PS持有者自身的HP，不替换为triggered_by
            hp_unit = owner
            hp_pct = hp_unit.current_hp / hp_unit.max_hp * 100 if hp_unit.max_hp > 0 else 0
            result = _eval_condition(hp_pct, op, val)
            # 仅当触发类型为on_hp_below且运算符为<=/<时，需要验证HP跨越阈值
            # 其他触发类型（before_skill_use/on_turn_start/on_battle_start等）只需检查当前状态
            if result and context.timing == TriggerTiming.HP_BELOW and op in ('<=', '<'):
                prev_pct = getattr(hp_unit, 'prev_hp_percent', 100.0)
                crossed = prev_pct > val and hp_pct <= val
                result = result and crossed
                _log.info("[TRIGGER_COND] %s: self_hp_percent %.1f%% %s %.0f%% => %s (checking %s, prev=%.1f%%, crossed=%s)",
                          owner.name, hp_pct, op, val, result, hp_unit.name, prev_pct, crossed)
            else:
                _log.info("[TRIGGER_COND] %s: self_hp_percent %.1f%% %s %.0f%% => %s (checking %s)",
                          owner.name, hp_pct, op, val, result, hp_unit.name)
            return result

        if cond_type == "cumulative_damage_percent":
            # 累计伤害百分比条件：检查owner的累计HP伤害占最大HP的百分比
            # 注意：实际阈值判断已在trigger_cumulative_damage中完成，
            # 此条件仅用于global_condition的额外过滤（如需更精细控制）
            dmg_pct = (owner.cumulative_hp_damage / owner.max_hp * 100) if owner.max_hp > 0 else 0
            result = _eval_condition(dmg_pct, op, val)
            _log.info("[TRIGGER_COND] %s: cumulative_damage_percent %.1f%% %s %.0f%% => %s",
                      owner.name, dmg_pct, op, val, result)
            return result

        if cond_type == "enemy_alive_count":
            enemies = [u for u in context.battlefield.enemy_team if u.is_alive]
            count = len(enemies)
            result = _eval_condition(count, op, val)
            _log.info("[TRIGGER_COND] %s: enemy_alive_count %d %s %d => %s",
                      owner.name, count, op, val, result)
            return result

        if cond_type == "self_damage_link_active":
            # ダメージリンク効果が場に残っているか確認（PS2触发条件）
            # 死亡单位的buff清除在触发器检查之后执行，因此死亡者的damage_link buff仍存在
            all_units = context.battlefield.get_all_units()
            has_link = False
            for u in all_units:
                link_buffs = [b for b in (u.buffs + u.debuffs) if b.effect_type == "damage_link"]
                if link_buffs:
                    has_link = True
                    break
            _log.info("[TRIGGER_COND] %s: self_damage_link_active => %s (damage_link buffs on battlefield)",
                      owner.name, has_link)
            return has_link

        if cond_type == "ally_alive_count":
            allies = [u for u in context.battlefield.friend_team if u.is_alive]
            count = len(allies)
            result = _eval_condition(count, op, val)
            _log.info("[TRIGGER_COND] %s: ally_alive_count %d %s %d => %s",
                      owner.name, count, op, val, result)
            return result

        if cond_type == "round_number":
            cur = context.battlefield.turn_number
            result = _eval_condition(cur, op, val)
            _log.info("[TRIGGER_COND] %s: round_number(turn=%d) %s %d => %s",
                      owner.name, cur, op, val, result)
            return result

        if cond_type == "round_number_modulo":
            cur = context.battlefield.turn_number
            result = cur > 0 and cur % val == 0
            _log.info("[TRIGGER_COND] %s: round_number_modulo(turn=%d) %% %d == 0 => %s",
                      owner.name, cur, val, result)
            return result

        if cond_type == "skill_use_count_modulo":
            # Filter by count_skill_types (default: [1] = AS only)
            count_skill_types = condition.get('count_skill_types', [1]) if isinstance(condition, dict) else [1]
            exclude_skill_ids = condition.get('exclude_skill_ids', []) if isinstance(condition, dict) else []
            count = 0
            if owner.skill_use_count:
                for skill_id, cnt in owner.skill_use_count.items():
                    if skill_id in exclude_skill_ids:
                        continue
                    skill_data = self.data_loader.get_skill_by_id(skill_id) if self.data_loader else None
                    if skill_data and skill_data.skill_type in count_skill_types:
                        count += cnt

            # PS-modulo触发器（如「お母様、見ててください……！」）的pending在PS技能执行后处理
            # 不在这里依赖pending标志，避免在AS技能执行后重复匹配
            is_ps_modulo_trigger = (count_skill_types == [2])
            if is_ps_modulo_trigger:
                result = count > 0 and count % val == 0
            else:
                # AS-modulo触发器（如「ぜ～～ったい負けないから！」）使用pending标志
                result = (count > 0 and count % val == 0) or owner.skill_use_count_pending
            _log.info("[TRIGGER_COND] %s: skill_use_count_modulo %d (types=%s exclude=%s) mod %d == 0 => %s (pending=%s, is_ps_modulo=%s)",
                      owner.name, count, count_skill_types, exclude_skill_ids, val, result, owner.skill_use_count_pending, is_ps_modulo_trigger)
            return result

        if cond_type == "crit_count_mod":
            count = owner.crit_counter
            result = count >= val
            _log.info("[TRIGGER_COND] %s: crit_count_mod %d >= %d => %s",
                      owner.name, count, val, result)
            # 不在此处清空crit_counter，改为在PS技能实际执行成功后清空
            # 这样PP不足时计数器保持不变，下次暴击仍可触发
            return result

        if cond_type == "enemy_hp_percent":
            enemies = [u for u in context.battlefield.enemy_team if u.is_alive]
            max_hp_pct = 0
            for e in enemies:
                pct = e.current_hp / e.max_hp * 100 if e.max_hp > 0 else 0
                max_hp_pct = max(max_hp_pct, pct)
            result = _eval_condition(max_hp_pct, op, val)
            _log.info("[TRIGGER_COND] %s: enemy_hp_percent max=%.1f%% %s %.0f%% => %s",
                      owner.name, max_hp_pct, op, val, result)
            return result

        if cond_type == "target_is_ally":
            if not context.targets:
                return True
            target = context.targets[0]
            is_ally = target.side == owner.side
            result = (is_ally == bool(val))
            _log.info("[TRIGGER_COND] %s: target_is_ally=%s expect=%s => %s",
                      owner.name, is_ally, bool(val), result)
            return result

        if cond_type == "self_skill_use_count":
            count_skill_types = condition.get('count_skill_types', [1]) if isinstance(condition, dict) else [1]
            count = 0
            if owner.skill_use_count:
                for skill_id, cnt in owner.skill_use_count.items():
                    skill_data = self.data_loader.get_skill_by_id(skill_id) if self.data_loader else None
                    if skill_data and skill_data.skill_type in count_skill_types:
                        count += cnt
            if count == 0:
                count = owner.action_count_total
            result = _eval_condition(count, op, val)
            _log.info("[TRIGGER_COND] %s: self_skill_use_count %d (types=%s) %s %d => %s",
                      owner.name, count, count_skill_types, op, val, result)
            return result

        if cond_type == "target_is_self":
            if not context.targets:
                return True
            result = any(t.unit_id == owner.unit_id for t in context.targets)
            _log.info("[TRIGGER_COND] %s: target_is_self => %s", owner.name, result)
            return result

        if cond_type == "self_has_mark":
            # 检查PS持有者自身是否持有指定mark（用于如ストイックリコイル的前置条件）
            mark_name = condition.get('mark_name', '')
            has_mark = any(
                b.effect_type == SkillEffectType.MARK.value and getattr(b, 'name', '') == mark_name
                for b in owner.buffs
            ) or any(
                d.effect_type == SkillEffectType.MARK.value and getattr(d, 'name', '') == mark_name
                for d in owner.debuffs
            )
            _log.info("[TRIGGER_COND] %s: self_has_mark '%s' => %s", owner.name, mark_name, has_mark)
            return has_mark

        if cond_type == "actor_element":
            actor = context.actor
            if actor is None:
                _log.info("[TRIGGER_COND] %s: actor_element -> no actor => False", owner.name)
                return False
            result = getattr(actor, 'element', 0) == val
            _log.info("[TRIGGER_COND] %s: actor_element=%s need=%s => %s",
                      owner.name, getattr(actor, 'element', 0), val, result)
            return result

        if cond_type == "actor_character_type":
            actor = context.actor
            if actor is None:
                _log.info("[TRIGGER_COND] %s: actor_character_type -> no actor => False", owner.name)
                return False
            result = getattr(actor, 'character_type', 0) == val
            _log.info("[TRIGGER_COND] %s: actor_character_type=%s need=%s => %s",
                      owner.name, getattr(actor, 'character_type', 0), val, result)
            return result

        if cond_type == "target_is_front_ally":
            # 对于 HP_BELOW 触发器，context.targets 可能为空，改用 context.triggered_by
            if context.timing == TriggerTiming.HP_BELOW and context.triggered_by:
                front_pos = _get_front_position(owner.position)
                if not front_pos:
                    return False
                result = (context.triggered_by.side == owner.side
                          and context.triggered_by.position == front_pos)
                _log.info("[TRIGGER_COND] %s: target_is_front_ally (HP_BELOW) triggered_by=%s pos=%s front_pos=%s => %s",
                          owner.name, context.triggered_by.name, context.triggered_by.position,
                          front_pos, result)
                return result
            if not context.targets:
                return False
            front_pos = _get_front_position(owner.position)
            if not front_pos:
                return False
            result = any(t.position == front_pos for t in context.targets if t.side == owner.side)
            return result

        if cond_type == "front_ally_hp_below":
            # 检查正前方友方单位HP是否低于阈值（用于再起律動等技能）
            # context.triggered_by: HP_BELOW时受伤的单位
            # context.targets: 其他触发器类型的目标
            hp_unit = None
            if context.timing == TriggerTiming.HP_BELOW and context.triggered_by:
                hp_unit = context.triggered_by
            elif context.targets:
                hp_unit = context.targets[0]

            if hp_unit is None:
                _log.info("[TRIGGER_COND] %s: front_ally_hp_below -> no unit to check", owner.name)
                return False

            # 必须是同阵营单位
            if hp_unit.side != owner.side:
                _log.info("[TRIGGER_COND] %s: front_ally_hp_below -> %s is not same side",
                          owner.name, hp_unit.name)
                return False

            # 必须是正前方单位
            front_pos = _get_front_position(owner.position)
            if not front_pos or hp_unit.position != front_pos:
                _log.info("[TRIGGER_COND] %s: front_ally_hp_below -> %s pos=%s not front_pos=%s",
                          owner.name, hp_unit.name, hp_unit.position, front_pos)
                return False

            # HP阈值检查 + 阈值跨越验证（仅on_hp_below + <=/<时需要跨越）
            hp_pct = hp_unit.current_hp / hp_unit.max_hp * 100 if hp_unit.max_hp > 0 else 0
            result = _eval_condition(hp_pct, op, val)
            if result and context.timing == TriggerTiming.HP_BELOW and op in ('<=', '<'):
                prev_pct = getattr(hp_unit, 'prev_hp_percent', 100.0)
                crossed = prev_pct > val and hp_pct <= val
                result = result and crossed
                _log.info("[TRIGGER_COND] %s: front_ally_hp_below %s hp=%.1f%% %s %.0f%% => %s (prev=%.1f%%, crossed=%s)",
                          owner.name, hp_unit.name, hp_pct, op, val, result, prev_pct, crossed)
            else:
                _log.info("[TRIGGER_COND] %s: front_ally_hp_below %s hp=%.1f%% %s %.0f%% => %s",
                          owner.name, hp_unit.name, hp_pct, op, val, result)
            return result

        if cond_type == "target_is_back_row":
            # 主要目标（被攻击者）必须是后排友方
            primary = context.primary_target
            if primary is None and context.targets:
                primary = context.targets[0]
            if primary is None:
                return False
            result = primary.side == owner.side and self._is_back_row(primary)
            _log.info("[TRIGGER_COND] %s: target_is_back_row primary=%s back_row=%s => %s",
                      owner.name, primary.name, self._is_back_row(primary), result)
            return result

        if cond_type == "attacker_is_back_row":
            # 攻击者必须是后排敌方
            actor = context.actor
            if actor is None:
                return False
            result = actor.side != owner.side and self._is_back_row(actor)
            _log.info("[TRIGGER_COND] %s: attacker_is_back_row actor=%s back_row=%s => %s",
                      owner.name, actor.name, self._is_back_row(actor), result)
            return result

        if cond_type == "is_debuff":
            # For PAWN_RECEIVED_AURA trigger: check if the applied aura is a debuff
            result = bool(val)
            _log.info("[TRIGGER_COND] %s: is_debuff=%s => %s", owner.name, val, result)
            return result

        if cond_type == "exclude_timing":
            # 排除特定触发时机（如战斗开始/回合开始/回合结束时不触发）
            # 检查当前触发上下文是否来自被排除的时机
            excluded_timings = val if isinstance(val, list) else [val]
            timing_map = {
                "before_battle": TriggerTiming.BATTLE_START,
                "on_turn_start": TriggerTiming.TURN_START,
                "on_turn_end": TriggerTiming.TURN_END,
                "after_own_action": TriggerTiming.AFTER_SKILL_USE,
                "before_own_action": TriggerTiming.BEFORE_SKILL_USE,
            }
            # 检查当前是否在被排除的时机中触发的
            # 通过检查battlefield的当前阶段标志判断
            current_phase = getattr(context.battlefield, 'current_trigger_phase', None)
            if current_phase:
                for et in excluded_timings:
                    mapped = timing_map.get(et)
                    if mapped and current_phase == mapped:
                        _log.info("[TRIGGER_COND] %s: exclude_timing %s matched current_phase=%s => False",
                                  owner.name, et, current_phase)
                        return False
            _log.info("[TRIGGER_COND] %s: exclude_timing %s not matched => True", owner.name, excluded_timings)
            return True

        if cond_type == "is_status_ailment":
            # Status ailment is a subset of debuff: only Knockout, Conflagration, Poison,
            # Freeze, Darkness, Confusion
            STATUS_AILMENT_TYPES = {"knockout", "conflagration", "poison", "freeze",
                                    "darkness", "confusion"}
            # 如果本次有施加debuff，只检查本次施加的类型是否为状态异常
            # 不回退到检查目标当前debuff（避免因为之前的状态异常而误触发）
            if context.applied_debuff_types:
                if any(dt.lower() in STATUS_AILMENT_TYPES for dt in context.applied_debuff_types):
                    _log.info("[TRIGGER_COND] %s: is_status_ailment found in applied_debuff_types %s => True",
                              owner.name, context.applied_debuff_types)
                    return True
                _log.info("[TRIGGER_COND] %s: is_status_ailment not found in applied_debuff_types %s => False",
                          owner.name, context.applied_debuff_types)
                return False
            # 没有本次施加的debuff信息时，才回退检查目标当前debuff
            for t in context.targets:
                if any(d.effect_type.lower() in STATUS_AILMENT_TYPES for d in t.debuffs):
                    _log.info("[TRIGGER_COND] %s: is_status_ailment found on %s => True",
                              owner.name, t.name)
                    return True
            _log.info("[TRIGGER_COND] %s: is_status_ailment not found on any target => False",
                      owner.name)
            return False

        if cond_type == "debuff_type":
            # Check if the specified debuff type was applied in this trigger event
            # Priority: use applied_debuff_types (records what was actually applied)
            # over checking target's current debuffs (which may have been cleared by revival)
            debuff_type_name = str(val).lower()
            if context.applied_debuff_types:
                if any(dt.lower() == debuff_type_name for dt in context.applied_debuff_types):
                    _log.info("[TRIGGER_COND] %s: debuff_type=%s found in applied_debuff_types %s => True",
                              owner.name, debuff_type_name, context.applied_debuff_types)
                    return True
                _log.info("[TRIGGER_COND] %s: debuff_type=%s not found in applied_debuff_types %s => False",
                          owner.name, debuff_type_name, context.applied_debuff_types)
                return False
            # Fallback: check target's current debuffs when no applied_debuff_types info
            for t in context.targets:
                if any(d.effect_type.lower() == debuff_type_name or d.name.lower() == debuff_type_name for d in t.debuffs):
                    _log.info("[TRIGGER_COND] %s: debuff_type=%s found on %s => True",
                              owner.name, debuff_type_name, t.name)
                    return True
            _log.info("[TRIGGER_COND] %s: debuff_type=%s not found on any target => False",
                      owner.name, debuff_type_name)
            return False

        _log.info("[TRIGGER_COND] %s: unknown condition type=%s → PASS (allow)", owner.name, cond_type)
        return True

    def _process_candidates(self, candidates: List[TriggerInstance],
                             context: TriggerContext) -> List[TriggerAction]:
        candidates.sort(key=lambda x: x.priority)

        # 先制效果(is_preemptive)：回合开始时，先制技能无条件优先于非先制技能
        # 多个先制技能同时触发时，按速度降序排列；同速按位置顺序
        if context.timing == TriggerTiming.TURN_START:
            preemptive = []
            non_preemptive = []
            for cand in candidates:
                parsed = self.data_loader.get_parsed_skill_data(cand.skill_id) if self.data_loader else None
                is_pre = False
                if parsed:
                    for block in parsed.get('effect_blocks', []):
                        for eff in block.get('effects', []):
                            if eff.get('flags', {}).get('is_preemptive'):
                                is_pre = True
                                break
                        if is_pre:
                            break
                if is_pre:
                    preemptive.append(cand)
                else:
                    non_preemptive.append(cand)
            if preemptive:
                _log.info("[PREEMPTIVE] %d preemptive PS matched (executed before %d non-preemptive)",
                          len(preemptive), len(non_preemptive))
                candidates = preemptive + non_preemptive

        # 同時発動制限：当多个simultaneous_limit=true的PS匹配时，只保留速度最快的1个
        simultaneous_candidates = []
        normal_candidates = []
        for cand in candidates:
            parsed = self.data_loader.get_parsed_skill_data(cand.skill_id) if self.data_loader else None
            if parsed and parsed.get('simultaneous_limit'):
                simultaneous_candidates.append(cand)
            else:
                normal_candidates.append(cand)

        if simultaneous_candidates:
            # 按优先级排序后只取第1个（优先级已按速度降序+位置先后排列）
            best_simultaneous = simultaneous_candidates[0]
            _log.info("[SIMULTANEOUS_LIMIT] %d simultaneous_limit PS matched, selecting fastest: %s PS[%d]",
                      len(simultaneous_candidates), best_simultaneous.owner.name, best_simultaneous.skill_id)
            # 被淘汰的记录日志
            for dropped in simultaneous_candidates[1:]:
                _log.info("[SIMULTANEOUS_LIMIT] dropped: %s PS[%d] (slower)",
                          dropped.owner.name, dropped.skill_id)
            normal_candidates.append(best_simultaneous)
            # 重新排序
            normal_candidates.sort(key=lambda x: x.priority)
            candidates = normal_candidates

        actions = []
        for cand in candidates:
            params = {}
            if context.actor:
                params['trigger_attacker'] = context.actor
            if context.primary_target:
                params['primary_target'] = context.primary_target
            action = TriggerAction(
                skill_id=cand.skill_id,
                owner_id=cand.owner.unit_id,
                action_type="General",
                parameters=params,
                instance=cand,
            )
            actions.append(action)

        return actions

    def calculate_priority(self, unit: UnitState) -> int:
        # 使用包含buff/debuff的即时速度，而非入场基础速度
        if self.damage_service:
            speed = self.damage_service._calculate_final_stat(unit, "speed")
        else:
            speed = unit.speed
        pos_score = self._get_position_score(unit.position)
        return (-speed * 10000) + pos_score

    def _get_position_score(self, position: Position) -> int:
        mapping = {
            Position.ALLY_LEFT_FRONT: 1,
            Position.ALLY_CENTER_FRONT: 2,
            Position.ALLY_RIGHT_FRONT: 3,
            Position.ALLY_LEFT_BACK: 4,
            Position.ALLY_CENTER_BACK: 5,
            Position.ALLY_RIGHT_BACK: 6,
            Position.ENEMY_LEFT_FRONT: 7,
            Position.ENEMY_CENTER_FRONT: 8,
            Position.ENEMY_RIGHT_FRONT: 9,
            Position.ENEMY_LEFT_BACK: 10,
            Position.ENEMY_CENTER_BACK: 11,
            Position.ENEMY_RIGHT_BACK: 12,
        }
        return mapping.get(position, 99)

    @staticmethod
    def _is_back_row(unit: UnitState) -> bool:
        name = unit.position.name
        return "BACK" in name


_FRONT_POSITION_MAP: Dict[Position, Position] = {
    Position.ALLY_LEFT_BACK: Position.ALLY_LEFT_FRONT,
    Position.ALLY_CENTER_BACK: Position.ALLY_CENTER_FRONT,
    Position.ALLY_RIGHT_BACK: Position.ALLY_RIGHT_FRONT,
    Position.ENEMY_LEFT_BACK: Position.ENEMY_LEFT_FRONT,
    Position.ENEMY_CENTER_BACK: Position.ENEMY_CENTER_FRONT,
    Position.ENEMY_RIGHT_BACK: Position.ENEMY_RIGHT_FRONT,
}


def _get_front_position(pos: Position) -> Optional[Position]:
    return _FRONT_POSITION_MAP.get(pos)


def _eval_condition(value: float, op: str, target: float) -> bool:
    if op == ">=":
        return value >= target
    if op == ">":
        return value > target
    if op == "<=":
        return value <= target
    if op == "<":
        return value < target
    if op == "==":
        return value == target
    if op == "!=":
        return value != target
    return False