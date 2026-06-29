#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
战斗流程主控制器 v2
src/combat_v2/battle_flow_controller.py

职责：
- 严格按照游戏流程执行战斗
- 协调各Service工作
- 管理行动阶段状态
"""

import sys
import re
from typing import Optional, Dict, Any, List, Tuple, Set

from ..entities_v2.battlefield_state import BattlefieldState
from ..entities_v2.unit_state import UnitState, BuffState
from ..entities_v2.enums import UnitActionPhase, TriggerTiming, Position, SkillEffectType, AuraUpdateTiming

from .services.resource_service import ResourceService
from .services.skill_service import SkillService
from .services.damage_service import DamageService
from .services.aura_service import AuraService
from .services.status_service import StatusService
from .services.target_service import TargetService
from .services.trigger_service import TriggerService, TriggerContext
from .services.action_axis_service import ActionAxisService
from .services.element_synergy import apply_element_synergy
from .battle_logger import battle_logger
from .battle_narrative import BattleNarrativeWriter

_log = battle_logger()


class BattleConfig:
    def __init__(self, max_turns: int = 15):
        self.max_turns = max_turns


class BattleFlowController:

    def __init__(self, battlefield: BattlefieldState, config: Optional[BattleConfig] = None,
                 data_loader: Any = None, narrative: Optional[BattleNarrativeWriter] = None):
        self.battlefield = battlefield
        self.config = config or BattleConfig()
        self.narrative = narrative

        # 初始化计分追踪器（常规战斗也追踪伤害/治疗统计）
        from .scoring_tracker import ScoringTracker
        self._scoring_tracker = ScoringTracker()
        self.battlefield.scoring_tracker = self._scoring_tracker

        if data_loader:
            self.data_loader = data_loader
        else:
            from ..data.data_loader import DataLoader
            self.data_loader = DataLoader()

        self.resource_service = ResourceService()
        self.target_service = TargetService()
        self.damage_service = DamageService()
        self.aura_service = AuraService()
        self.status_service = StatusService()

        self.trigger_service = TriggerService()
        self.trigger_service.set_data_loader(self.data_loader)
        self.trigger_service.set_damage_service(self.damage_service)

        self.skill_service = SkillService(
            data_loader=self.data_loader,
            resource_service=self.resource_service,
            target_service=self.target_service,
            damage_service=self.damage_service,
            aura_service=self.aura_service,
            status_service=self.status_service,
            trigger_service=self.trigger_service,
        )

        self.action_axis = ActionAxisService()
        self.action_axis.set_damage_service(self.damage_service)
        self._acted_this_round = set()  # 当前轮次已行动的unit_id
        self._round_eligible_ids: set = set()  # 当前轮次初始行动单位集合
        self._unit_display_names: Dict[str, str] = {}
        self._unit_id_map: Dict[str, UnitState] = {}

    def _pre_synergy_setup(self) -> None:
        """元素协同计算之前的钩子，供子类快照协同前属性（如基础max_hp）"""
        pass

    def _post_synergy_setup(self) -> None:
        """元素协同计算完成后的钩子，供子类覆写以覆盖单位初始状态（如HP/死亡）"""
        pass

    def _log_initial_state(self) -> None:
        """叙事头部输出后的钩子，供子类输出初始状态叙事（如开局即死的单位）"""
        pass

    def execute_battle(self) -> Dict[str, Any]:
        _log.info("[BATTLE] ============ 战斗开始 ============")

        self._pre_synergy_setup()
        apply_element_synergy(self.battlefield.get_all_units(), self.narrative)

        self._build_display_names()
        self._post_synergy_setup()

        _log.info("[BATTLE] 我方阵容:")
        for u in self.battlefield.friend_team:
            _log.info("[BATTLE]   %s | HP=%d/%d ATK=%d DEF=%d SPD=%d",
                      u.name, u.current_hp, u.max_hp, u.attack, u.defense, u.speed)
        _log.info("[BATTLE] 敌方阵容:")
        for u in self.battlefield.enemy_team:
            _log.info("[BATTLE]   %s | HP=%d/%d ATK=%d DEF=%d SPD=%d",
                      u.name, u.current_hp, u.max_hp, u.attack, u.defense, u.speed)
        self.skill_service.set_battlefield(self.battlefield)

        if self.narrative:
            char_count = len(self.battlefield.get_all_units())
            skills = self.data_loader.load_character_skills()
            skill_count = sum(len(v) for v in skills.values()) if skills else 0
            self.narrative.header(self.battlefield.friend_team, self.battlefield.enemy_team,
                                  char_count, skill_count)
            self.narrative.battle_start()

        self._log_initial_state()

        self.battlefield.current_trigger_phase = TriggerTiming.BATTLE_START
        battle_start_actions = self.trigger_service.trigger_battle_start(self.battlefield)
        if self.narrative and battle_start_actions:
            self.narrative.wave_start("战斗开始触发")
        self._execute_global_trigger_actions(battle_start_actions)
        self.battlefield.current_trigger_phase = None

        wave_start_actions = self.trigger_service.trigger_wave_start(self.battlefield)
        if self.narrative and wave_start_actions:
            self.narrative.wave_start("波次开始触发")
        self._execute_global_trigger_actions(wave_start_actions)

        self._apply_memory_card_effects()

        battle_result = "TIMEOUT"
        winner = None

        for turn_number in range(1, self.config.max_turns + 1):
            self.battlefield.turn_number = turn_number
            if self._execute_turn(turn_number):
                battle_result = "FINISHED"
                break

        self.trigger_service.trigger_wave_end(self.battlefield)

        alive_friends = [u for u in self.battlefield.friend_team if u.is_alive]
        alive_enemies = [u for u in self.battlefield.enemy_team if u.is_alive]
        if alive_friends and not alive_enemies:
            winner = "FRIEND"
        elif alive_enemies and not alive_friends:
            winner = "ENEMY"

        _log.info("[BATTLE] ============ 战斗结果 ============")
        _log.info("[BATTLE] 结果: %s | 回合数: %d | 胜者: %s",
                  battle_result, self.battlefield.turn_number, winner or "DRAW")
        _log.info("[BATTLE] 我方存活: %s",
                  ', '.join(u.name for u in alive_friends) if alive_friends else "全灭")
        _log.info("[BATTLE] 敌方存活: %s",
                  ', '.join(u.name for u in alive_enemies) if alive_enemies else "全灭")

        if self.narrative:
            self.narrative.battle_end(winner, self.battlefield.turn_number)

        # 构建统计结果
        battle_result_str = "UNKNOWN"
        if winner == "FRIEND":
            battle_result_str = "WIN"
        elif winner == "ENEMY":
            battle_result_str = "LOSS"

        score_result = self._scoring_tracker.build_result(
            total_turns=self.battlefield.turn_number,
            battle_result=battle_result_str,
        )

        return {
            "result": battle_result,
            "total_turns": self.battlefield.turn_number,
            "winner": winner,
            "score": score_result.to_dict(),
        }

    def _execute_turn(self, turn_number: int) -> bool:
        _log.info("[TURN] ==================================================")
        _log.info("[TURN] 回合 %d 开始", turn_number)
        # 初始化延迟暴击触发器收集器（每回合重置）
        if not hasattr(self, '_deferred_crit_triggers'):
            self._deferred_crit_triggers = []
        self._deferred_crit_triggers.clear()

        if self.narrative:
            self.narrative.turn_start(turn_number, self.config.max_turns)

        self._restore_ap_pp_for_all()

        # 快照所有存活单位的冷却（用于回合结束冷却递减判断）
        self._turn_start_cooldowns_snapshot = {
            u.unit_id: dict(u.skill_cooldowns)
            for u in self.battlefield.get_all_units() if u.is_alive
        }

        if self.narrative:
            for u in self.battlefield.get_all_units():
                if u.is_alive:
                    self.narrative.resource_restore(self._get_display_name(u), u.current_ap, u.initial_active_point,
                                                    u.current_pp, u.initial_passive_point)

        # TURN_START触发器分两阶段执行：
        # Phase 1: 先制技能（is_preemptive）优先于非先制技能，先收集并执行
        # Phase 2: 在先制技能执行后重新收集非先制技能（状态可能已因先制技能改变）
        self.battlefield.current_trigger_phase = TriggerTiming.TURN_START

        # 回忆卡 turn_start / periodic_start 触发
        self._apply_memory_card_effects_by_trigger("turn_start")
        self._apply_memory_card_effects_by_trigger("periodic_start")

        preemptive_actions = self.trigger_service.trigger_turn_start_preemptive(self.battlefield)
        if self.narrative and preemptive_actions:
            for action in preemptive_actions:
                owner = action.instance.owner
                skill_data = self.data_loader.get_skill_by_id(action.skill_id)
                skill_name = skill_data.name if skill_data else "?"
                self.narrative.global_trigger(self._get_display_name(owner), skill_name, "回合开始")
        self._execute_global_trigger_actions(preemptive_actions)

        non_preemptive_actions = self.trigger_service.trigger_turn_start_non_preemptive(self.battlefield)
        if self.narrative and non_preemptive_actions:
            for action in non_preemptive_actions:
                owner = action.instance.owner
                skill_data = self.data_loader.get_skill_by_id(action.skill_id)
                skill_name = skill_data.name if skill_data else "?"
                self.narrative.global_trigger(self._get_display_name(owner), skill_name, "回合开始")
        self._execute_global_trigger_actions(non_preemptive_actions)
        self.battlefield.current_trigger_phase = None

        # グローバル触发器（turn_start/memory_card）で付与されたbuffのjust_appliedをクリア
        # これらは行動中に付与されたものではないため、最初の行動終了時に正常に減算されるべき
        # （just_appliedは「当次行動中に付与されたbuffを递減から保護」する仕組みだが、
        #   グローバル触发器は行動中ではないため保護対象外）
        for u in self.battlefield.get_all_units():
            for b in u.buffs + u.debuffs:
                b.just_applied = False

        round_in_turn = 0
        while True:
            self.action_axis.generate_action_axis(self.battlefield)
            if self.action_axis.is_empty():
                break

            # 记录本轮初始行动单位集合，本轮内不允许添加新单位
            # 避免复活/EP满的单位在当轮被加入行动轴
            self._round_eligible_ids = {u.unit_id for u in self.action_axis.action_axis}

            round_in_turn += 1
            self._acted_this_round.clear()
            _log.info("[ROUND] 回合 %d 第 %d 轮 开始", turn_number, round_in_turn)

            if self.narrative:
                self.narrative.action_axis_display([self._get_display_name(u) for u in self.action_axis.action_axis])

            while not self.action_axis.is_empty():
                unit = self.action_axis.get_next_unit()
                if not unit:
                    break

                self._acted_this_round.add(unit.unit_id)
                self.battlefield.total_actions += 1
                self._execute_unit_action(unit, turn_number)

                if self._check_battle_end():
                    return True

                self.action_axis.resort_action_axis()
                # 本轮内不允许添加新单位（复活/EP满的单位等下一轮）
                self.action_axis.action_axis = [
                    u for u in self.action_axis.action_axis
                    if u.unit_id in self._round_eligible_ids
                ]

                if self.narrative and not self.action_axis.is_empty():
                    self.narrative.action_order(self._get_display_name(unit), [self._get_display_name(u) for u in self.action_axis.action_axis])

                self._process_aura_expiry(unit)

                all_alive = [u for u in self.battlefield.friend_team + self.battlefield.enemy_team if u.is_alive]
                hp_line = ' | '.join(f"{u.name}:{u.current_hp}/{u.max_hp}" for u in all_alive)
                _log.info("[HP] %s", hp_line)

        self.battlefield.current_trigger_phase = TriggerTiming.TURN_END

        # 回忆卡 turn_end / periodic_end 触发
        self._apply_memory_card_effects_by_trigger("turn_end")
        self._apply_memory_card_effects_by_trigger("periodic_end")

        turn_end_actions = self.trigger_service.trigger_turn_end(self.battlefield)
        if self.narrative and turn_end_actions:
            for action in turn_end_actions:
                owner = action.instance.owner
                skill_data = self.data_loader.get_skill_by_id(action.skill_id)
                skill_name = skill_data.name if skill_data else "?"
                self.narrative.global_trigger(self._get_display_name(owner), skill_name, "回合结束")
        self._execute_global_trigger_actions(turn_end_actions)
        self.battlefield.current_trigger_phase = None

        # グローバル触发器（turn_end/memory_card）で付与されたbuffのjust_appliedをクリア
        # グローバル触发器は行動中ではないため、just_applied保護は不要
        # 次ターンの最初の行動終了時に正常にdurationが減算されるようにする
        # （例: グローリーコール(130022)のatk_up buff duration=2が
        #   次ターン2行動で正常に消失するように）
        for u in self.battlefield.get_all_units():
            for b in u.buffs + u.debuffs:
                b.just_applied = False

        # 回合结束冷却递减 (cooldown_update_timing: 1)
        snapshot = getattr(self, '_turn_start_cooldowns_snapshot', {})
        for u in self.battlefield.get_all_units():
            if u.is_alive:
                self.skill_service.update_turn_end_cooldowns(u, snapshot.get(u.unit_id, {}))
                # 回合制buff/debuff持续时间递减 (duration_type="turn"，如damage_link)
                self.aura_service.process_turn_end(u)
                # 清理过期buff/debuff
                self.aura_service.check_expiration(u, self.battlefield.get_all_units())

        if self.narrative:
            all_alive = [u for u in self.battlefield.friend_team + self.battlefield.enemy_team if u.is_alive]
            self.narrative.turn_end_summary(all_alive, self._unit_display_names)

        return False

    def _execute_unit_action(self, unit: UnitState, turn: int) -> None:
        self.battlefield.round_number += 1

        # 更新所有存活单位的prev_hp_percent为当前HP百分比
        # 修复: 行动间治疗（HOT/技能治疗）后prev_hp_percent未更新，
        # 导致下次DOT降血时阈值跨越检测失效（如「再起律動」不触发）
        for u in self.battlefield.get_all_units():
            if u.is_alive and u.max_hp > 0:
                u.prev_hp_percent = (u.current_hp / u.max_hp) * 100

        _log.info("[ACT] --------------------------------------------------")
        _log.info("[ACT] T%dR%d %s (HP:%d/%d AP:%d EP:%d/%d) 开始行动",
                  turn, self.battlefield.round_number, unit.name, unit.current_hp, unit.max_hp,
                  unit.current_ap, unit.current_ep, unit.max_extra_point)

        unit.action_phase = UnitActionPhase.CHECKING_STATUS

        if self.narrative:
            self.narrative.unit_action_start_display(self._get_display_name(unit), unit.current_ap, unit.initial_active_point,
                                                      unit.current_pp, unit.initial_passive_point,
                                                      unit.current_ep, unit.max_extra_point)

        self._check_and_apply_status_effects(unit)

        # 检测DOT（炎上/毒/行動時ダメージ）导致的死亡，触发击杀触发器
        dot_killed = [u for u in self.battlefield.get_all_units()
                      if not u.is_alive and not u.is_death_notified]
        if dot_killed:
            for u in dot_killed:
                if self.narrative:
                    self.narrative.death(self._get_display_name(u))
                u.is_death_notified = True
                # 查找DOT的施法者作为击杀者
                dot_source_id = None
                for debuff in u.debuffs:
                    if debuff.effect_type in (
                        SkillEffectType.CONFLAGRATION.value,
                        SkillEffectType.POISON.value,
                        SkillEffectType.ACTION_DAMAGE.value,
                    ):
                        dot_source_id = debuff.source_unit_id
                        break
                killer = next((x for x in self.battlefield.get_all_units()
                               if x.unit_id == dot_source_id), None) if dot_source_id else None
                if killer:
                    kill_actions = self.trigger_service.trigger_pawn_killed(killer, self.battlefield)
                    self._execute_trigger_actions(kill_actions, killer)
                    any_kill_actions = self.trigger_service.trigger_pawn_any_kill(killer, self.battlefield)
                    self._execute_trigger_actions(any_kill_actions, killer)
            # 允许子类（如战术演习）在此执行复活等逻辑
            self._on_deaths_resolved(dot_killed)
            if self.narrative:
                self._on_death_narrative_complete(dot_killed)

        pre_action_cooldowns = dict(unit.skill_cooldowns)

        if not self._can_act(unit):
            reason = ""
            if not unit.is_alive:
                reason = "已阵亡"
            elif unit.is_stunned:
                reason = "眩晕"
            elif unit.is_frozen:
                reason = "冰冻"
            if self.narrative:
                self.narrative.standby(self._get_display_name(unit), reason)
            self._execute_standby(unit)
            self.skill_service.update_action_cooldowns(unit, pre_action_cooldowns)
            return

        # 蓄力完成：如果单位正在蓄力中，执行蓄力效果
        if unit.is_charging and unit.charge_skill_id:
            charge_skill_id = unit.charge_skill_id
            charge_meta = self.data_loader.get_skill_by_id(charge_skill_id)
            charge_name = charge_meta.name if charge_meta else f"Skill_{charge_skill_id}"
            _log.info("[CHARGE_EXECUTE] %s: executing charge effect [%s] (ID=%d)",
                      unit.name, charge_name, charge_skill_id)
            unit.is_charging = False
            unit.charge_skill_id = 0
            if self.narrative:
                self.narrative.charge_complete(self._get_display_name(unit), charge_name, 1)
            # 执行蓄力效果（跳过资源消耗，已在蓄力时消耗）
            skill_result = self.skill_service.execute_skill(
                caster=unit,
                skill_id=charge_skill_id,
                battlefield=self.battlefield,
                skip_cost=True,
                defer_crit_triggers=True,
            )
            # Guard cleanup: 蓄力技能执行完毕后立即清理由该攻击者触发的Guard buff
            self._cleanup_guard_buffs(unit)
            if skill_result.get("success") and self.narrative:
                self._log_narrative_effects(unit, skill_result, charge_name, 1, charge_skill_id)
            # 蓄力技能释放后进入冷却
            self.skill_service.update_cooldown_after_skill_use(unit, charge_skill_id)
            # 蓄力技能成功释放，AS技能计数+1（开始蓄力不算使用AS技能）
            unit.skill_use_count[charge_skill_id] = unit.skill_use_count.get(charge_skill_id, 0) + 1
            _log.info("[SKILL_COUNT] Charge skill_use_count updated: %s skill[%d] -> count=%d, full=%s",
                      unit.name, charge_skill_id, unit.skill_use_count[charge_skill_id], dict(unit.skill_use_count))
            skill_count_actions = self.trigger_service.trigger_skill_use_count(unit, self.battlefield)
            if skill_count_actions:
                pp_snapshot = {}
                for action in skill_count_actions:
                    owner = action.instance.owner
                    pp_snapshot[owner.unit_id] = owner.current_pp
                self._execute_trigger_actions(skill_count_actions, unit)
                if skill_count_actions:
                    any_executed = any(pp_snapshot.get(action.instance.owner.unit_id, 999) > action.instance.owner.current_pp for action in skill_count_actions)
                    if any_executed:
                        for action in skill_count_actions:
                            owner = action.instance.owner
                            if owner.skill_use_count:
                                owner.skill_use_count.clear()
                                owner.skill_use_count_pending = False
                    else:
                        for action in skill_count_actions:
                            owner = action.instance.owner
                            owner.skill_use_count_pending = True
            # 蓄力效果执行完毕，行动结束，其他技能冷却正常递减
            unit.action_phase = UnitActionPhase.AFTER_SKILL
            unit.action_count_total += 1
            self.skill_service.update_action_cooldowns(unit, pre_action_cooldowns)
            return

        selected_skill = self.skill_service.select_skill(unit)

        if selected_skill is None:
            _log.info("[ACT]   %s 无可选技能, 待机", unit.name)
            if self.narrative:
                self.narrative.standby(self._get_display_name(unit), "无可选技能")
            self._execute_standby(unit)
            self.skill_service.update_action_cooldowns(unit, pre_action_cooldowns)
            return

        meta = self.data_loader.get_skill_by_id(selected_skill)
        skill_name = meta.name if meta else f"Skill_{selected_skill}"
        resolved = self.skill_service._resolver.resolve(selected_skill, unit.skill_levels.get(selected_skill, 1))
        skill_type = resolved.skill_type if resolved else (meta.skill_type if meta else 1)

        _log.info("[ACT]   %s 使用技能 [%s] (ID=%d)", unit.name, skill_name, selected_skill)

        if not self.skill_service.check_skill_cost(unit, selected_skill):
            _log.info("[ACT]   %s 资源不足，待机", unit.name)
            if self.narrative:
                self.narrative.standby(self._get_display_name(unit), "资源不足")
            self._execute_standby(unit)
            self.skill_service.update_action_cooldowns(unit, pre_action_cooldowns)
            return

        if self.narrative:
            if skill_type == 3 and unit.current_ep >= unit.max_extra_point:
                self.narrative.ep_full(self._get_display_name(unit))
            self.narrative.unit_hp_status(unit, self._get_display_name(unit))
            self.narrative.skill_prepare(unit, skill_name, skill_type, self._get_display_name(unit))

        if not self.skill_service.deduct_skill_cost(unit, selected_skill):
            _log.info("[ACT]   %s 资源扣除失败，待机", unit.name)
            if self.narrative:
                self.narrative.standby(self._get_display_name(unit), "资源扣除失败")
            self._execute_standby(unit)
            self.skill_service.update_action_cooldowns(unit, pre_action_cooldowns)
            return

        if self.narrative:
            cost = meta.resource_cost if meta else 1
            self.narrative.resource_deduct(self._get_display_name(unit), skill_type, cost,
                                           unit.current_ap, unit.initial_active_point,
                                           unit.current_pp, unit.initial_passive_point,
                                           unit.current_ep, unit.max_extra_point)

        unit.action_phase = UnitActionPhase.BEFORE_SKILL

        if skill_type != 3:
            trigger_actions = self.trigger_service.trigger_before_skill_use(unit, selected_skill, self.battlefield)
            self._execute_trigger_actions(trigger_actions, unit)

            # before_ally_as_attack 仅在AS技能(skill_type=1)时触发
            if skill_type == 1:
                ally_trigger_actions = self.trigger_service.trigger_before_ally_as_attack(unit, selected_skill, self.battlefield)
                self._execute_trigger_actions(ally_trigger_actions, unit)

        units_before = set(u.unit_id for u in self.battlefield.get_all_units() if u.is_alive)

        # 初始化暴击触发收集器：所有crit triggers统一收集，在复活后执行
        self._deferred_crit_triggers = []

        # 蓄力技能：不立即执行效果，标记为蓄力状态，下次行动时执行
        # 检测条件：features包含32(RequiresCharging)
        # 注意：skill_kind==3表示debuff技能（如atk_down），不是蓄力技能
        is_charge_skill = skill_type == 1 and meta and (meta.features & 32)
        if is_charge_skill:
            _log.info("[CHARGE] %s: 蓄力技能 [%s] 开始蓄力，下次行动时执行效果",
                      unit.name, skill_name)
            unit.is_charging = True
            unit.charge_skill_id = selected_skill
            if self.narrative:
                self.narrative.charge_start(self._get_display_name(unit), skill_name, skill_type)
            # 触发on_ally_charge_use（友方响应蓄力）
            charge_actions = self.trigger_service.trigger_ally_charge_use(unit, self.battlefield)
            if charge_actions:
                self._execute_trigger_actions(charge_actions, unit)
            # 蓄力技能当前行动结束，其他技能冷却正常递减
            unit.action_phase = UnitActionPhase.AFTER_SKILL
            unit.action_count_total += 1
            self.skill_service.update_action_cooldowns(unit, pre_action_cooldowns)
            return

        skill_result = self.skill_service.execute_skill(
            caster=unit,
            skill_id=selected_skill,
            battlefield=self.battlefield,
            skip_cost=True,
            defer_crit_triggers=True,
        )

        # Guard cleanup: AS技能执行完毕后立即清理由该攻击者触发的Guard buff
        # Guard效果只在触发它的那次技能攻击中生效，后续PS技能不应享受Guard减伤
        self._cleanup_guard_buffs(unit)

        # 充能技能检测：如果AS技能的Features包含RequiresCharging(32)，触发on_ally_charge_use
        # 注意：蓄力技能已在上方提前处理，此处保留用于非蓄力的充能检测
        if skill_type == 1 and meta and (meta.features & 32):
            _log.info("[CHARGE] %s: 充能技能 [%s] (Features=%d, RequiresCharging=True)",
                      unit.name, skill_name, meta.features)
            charge_actions = self.trigger_service.trigger_ally_charge_use(unit, self.battlefield)
            if charge_actions:
                self._execute_trigger_actions(charge_actions, unit)

        # SAFETY: 确保所有HP<=0的单位都被标记为死亡（兜底保护）
        # 防止_pending_deaths因嵌套save/restore导致部分死亡未处理
        forced_dead = []
        for u in self.battlefield.get_all_units():
            if u.unit_id in units_before and u.current_hp <= 0 and u.is_alive:
                u.is_alive = False
                forced_dead.append(u.name)
                _log.info("[SAFETY] Forcing is_alive=False for %s (HP=%d/%d)", u.name, u.current_hp, u.max_hp)
        if forced_dead:
            _log.info("[SAFETY] Forced dead units: %s", forced_dead)

        # 1. 先输出AS技能的叙事日志（伤害、治疗等），确保AS伤害日志在PS之前
        damaged_targets = []
        if skill_result.get("success"):
            damaged_targets = self._log_narrative_effects(unit, skill_result, skill_name, skill_type, selected_skill)

        # 2. 检测新阵亡单位
        newly_dead = []
        for u in self.battlefield.get_all_units():
            if u.unit_id in units_before and not u.is_alive:
                newly_dead.append(u)

        # 3. 输出死亡通知（在复活逻辑之前，确保💀在复活叙事之前）
        if self.narrative:
            for u in newly_dead:
                if not u.is_death_notified:
                    self.narrative.death(self._get_display_name(u))
                    u.is_death_notified = True

        # 4. 死亡触发器（PAWN_DIED/PAWN_KILLED/PAWN_ANY_KILL/HP_BELOW/UNIT_COUNT_BELOW）
        if newly_dead:
            death_actions = self.trigger_service.trigger_pawn_died(newly_dead, self.battlefield)
            self._execute_trigger_actions(death_actions, unit)
            kill_actions = self.trigger_service.trigger_pawn_killed(unit, self.battlefield)
            self._execute_trigger_actions(kill_actions, unit)
            any_kill_actions = self.trigger_service.trigger_pawn_any_kill(unit, self.battlefield)
            self._execute_trigger_actions(any_kill_actions, unit)

            hp_below_actions = self.trigger_service.trigger_hp_below(self.battlefield)
            self._execute_global_trigger_actions(hp_below_actions)

            cumulative_dmg_actions = self.trigger_service.trigger_cumulative_damage(self.battlefield)
            if cumulative_dmg_actions:
                self._execute_global_trigger_actions(cumulative_dmg_actions)

            unit_count_actions = self.trigger_service.trigger_unit_count_below(self.battlefield)
            self._execute_global_trigger_actions(unit_count_actions)

            # 4.5 清除死亡单位施加的「高揚」mark及其linked debuff
            self._remove_marks_from_dead_caster(newly_dead)

            # 4.6 清除死亡单位相关的ダメージリンクbuff
            # 死亡者自身のdamage_link buffと、死亡者をsourceとするdamage_link buffを全て削除
            # トリガー検査の後に実行され、self_damage_link_active条件は死亡者のbuff残存を考慮済み
            self._remove_damage_link_from_dead(newly_dead)

            # 5. 钩子：击杀触发器处理完毕后，允许子类（如战术演习）在此执行复活等逻辑
            self._on_deaths_resolved(newly_dead)

        # 6. 输出复活叙事（在_on_deaths_resolved复活逻辑之后，确保复活叙事在死亡通知之后）
        if newly_dead and self.narrative:
            self._on_death_narrative_complete(newly_dead)

        # 7. 暴击触发PS：收集AS技能的pending_crit_triggers，与PS产生的crit triggers统一在复活后执行
        as_pending_crit = skill_result.get("pending_crit_triggers", [])
        if as_pending_crit:
            self._deferred_crit_triggers.extend(as_pending_crit)
            _log.info("[CRIT_COLLECT] AS skill: collected %d crit triggers (total=%d)",
                      len(as_pending_crit), len(self._deferred_crit_triggers))

        if skill_result.get("success"):
            had_aura = any(
                applied.get("effect_type") in ("aura", "add_status")
                for applied in skill_result.get("effects_applied", [])
            )

            # AS技能使用次数计数：无论是否造成伤害都需更新（如支援型AS技能 120111/120112）
            # 必须在收集 skill_count_actions 之前更新，以确保 on_skill_use_count 触发器（如 130119/130081）能正确匹配
            if skill_type == 1:
                unit.skill_use_count[selected_skill] = unit.skill_use_count.get(selected_skill, 0) + 1
                _log.info("[SKILL_COUNT] AS skill_use_count updated: %s skill[%d] -> count=%d, full=%s",
                          unit.name, selected_skill, unit.skill_use_count[selected_skill], dict(unit.skill_use_count))

            if damaged_targets:
                unique_damaged = list({u.unit_id: u for u in damaged_targets}.values())
                # hp_below triggers FIRST (priority over after_ally_attacked for same character,
                # e.g. ぽよぽよプロテクト(130041) before イケてる♡イケてる(130025))
                hp_below_normal = self.trigger_service.trigger_hp_below(self.battlefield, unique_damaged)
                self._execute_global_trigger_actions(hp_below_normal)
                # Track which owners had hp_below triggers fire (used to suppress after_ally_attacked)
                owners_with_hp_below = set()
                for a in hp_below_normal:
                    owners_with_hp_below.add(a.instance.owner.unit_id)

                primary_target = damaged_targets[0] if damaged_targets else None

                if skill_type == 1:
                    # AS技能执行结束后，触发器分两阶段执行：
                    # Phase 1（被攻撃反応）: after_ally_attacked, after_self_attacked,
                    #   after_as_attacked, after_as_attacked_ally
                    #   这些是对"被攻击"的反应，必须先于追撃型PS执行
                    #   （如 外殻強化 的 def_up 必须在 チェイスブレイダー 追撃前生效）
                    # Phase 2（AS攻撃後追撃）: after_ally_as_attack, after_self_as,
                    #   on_critical, skill_use_count
                    # 每阶段内部按速度→位置排序

                    # ===== 收集 Phase 1: 被攻撃反応 =====
                    phase1_actions = []

                    after_ally = self.trigger_service.trigger_after_ally_attacked(
                        damaged_targets, self.battlefield, actor=unit, primary_target=primary_target
                    )
                    # Suppress after_ally_attacked for owners who already triggered hp_below
                    # (e.g. ぽよぽよプロテクト takes priority over イケてる♡イケてる)
                    after_ally = [a for a in after_ally if a.instance.owner.unit_id not in owners_with_hp_below]
                    phase1_actions.extend(after_ally)

                    after_self = self.trigger_service.trigger_after_self_attacked(
                        damaged_targets, self.battlefield, actor=unit, primary_target=primary_target
                    )
                    phase1_actions.extend(after_self)

                    # 自身被AS攻击后触发（如フレンジーキャノン、捲土重来）
                    # 仅AS技能主目标触发
                    after_as_attacked = self.trigger_service.trigger_after_as_attacked(
                        damaged_targets, self.battlefield, actor=unit, primary_target=primary_target
                    )
                    phase1_actions.extend(after_as_attacked)

                    # 友方被AS技能攻击后触发（如ラッキー4！）
                    after_as_ally = self.trigger_service.trigger_after_as_attacked_ally(
                        damaged_targets, self.battlefield, actor=unit, primary_target=primary_target
                    )
                    phase1_actions.extend(after_as_ally)

                    # ===== 收集 Phase 2: AS攻撃後追撃 =====
                    phase2_actions = []

                    # 其他友方AS攻击后触发（如ポイズンチェイス、チェイスブレイダー）
                    # 传入primary_target使追撃型PS仅追击AS主目标，主目标阵亡时不触发
                    after_ally_as = self.trigger_service.trigger_after_ally_as_attack(
                        unit, selected_skill, damaged_targets, self.battlefield,
                        primary_target=primary_target,
                    )
                    phase2_actions.extend(after_ally_as)

                    # 暴击触发PS（ラッキー4！、ジャックポット、アンデッドリベンジ等）
                    # 暴击事件在AS执行中发生，应先于after_self_as(AS结束后触发)执行
                    # （如 アンデッドリベンジ on_critical 需先于 ハロウィン・オブ・ザ・デッド after_as_attack）
                    if self._deferred_crit_triggers:
                        for entry in list(self._deferred_crit_triggers):
                            c, bf = entry[0], entry[1]
                            crit_count = entry[2] if len(entry) > 2 else 1
                            crit_actions = self.trigger_service.trigger_pawn_caused_critical(c, bf, count=crit_count)
                            phase2_actions.extend(crit_actions)
                        self._deferred_crit_triggers = []

                    # 自身AS攻击后触发（如諸元修正、ファイティングブースト）也属于同时机
                    # 传递primary_target给after_self_as触发器，使PS技能（如アーマー・ジャム）能获取AS攻击目标
                    _as_primary_target = getattr(self.skill_service, '_last_primary_target', None)
                    after_self_as = self.trigger_service.trigger_after_skill_use(
                        unit, selected_skill, skill_result, self.battlefield,
                        primary_target=_as_primary_target
                    )
                    phase2_actions.extend(after_self_as)

                    # 技能使用次数触发PS（おまけで、えいっ！等）也属于同时机
                    # skill_use_count已在上方统一更新（含非伤害型AS技能）
                    skill_count_actions = self.trigger_service.trigger_skill_use_count(unit, self.battlefield)
                    if skill_count_actions:
                        phase2_actions.extend(skill_count_actions)

                    # 记录PP快照（两阶段合并），用于后续判断PS是否实际执行
                    all_for_snapshot = phase1_actions + phase2_actions
                    self._pp_snapshot_before_as_triggers = {}
                    for a in all_for_snapshot:
                        o = a.instance.owner
                        self._pp_snapshot_before_as_triggers[o.unit_id] = o.current_pp

                    # ===== 执行 Phase 1: 被攻撃反応 =====
                    if phase1_actions:
                        phase1_actions.sort(
                            key=lambda a: self.trigger_service.calculate_priority(a.instance.owner)
                        )
                        _log.info("[POST_AS_TRIGGERS] Phase1 (被攻撃反応): %d actions sorted by speed→position",
                                  len(phase1_actions))
                    self._execute_trigger_actions(phase1_actions, unit)
                    # Phase 1 可能产生新的暴击触发器
                    self._flush_deferred_crit_triggers(unit)

                    # ===== 执行 Phase 2: AS攻撃後追撃 =====
                    if phase2_actions:
                        phase2_actions.sort(
                            key=lambda a: self.trigger_service.calculate_priority(a.instance.owner)
                        )
                        _log.info("[POST_AS_TRIGGERS] Phase2 (AS攻撃後追撃): %d actions sorted by speed→position",
                                  len(phase2_actions))
                    self._execute_trigger_actions(phase2_actions, unit)
                    # PS技能可能产生新的暴击触发器，继续处理
                    self._flush_deferred_crit_triggers(unit)
                else:
                    # 非AS技能：先执行暴击触发器，再执行其他触发器
                    self._flush_deferred_crit_triggers(unit)

                    after_ally = self.trigger_service.trigger_after_ally_attacked(
                        damaged_targets, self.battlefield, actor=unit, primary_target=primary_target
                    )
                    # Suppress after_ally_attacked for owners who already triggered hp_below
                    after_ally = [a for a in after_ally if a.instance.owner.unit_id not in owners_with_hp_below]
                    self._execute_trigger_actions(after_ally, unit)
                    after_self = self.trigger_service.trigger_after_self_attacked(
                        damaged_targets, self.battlefield, actor=unit, primary_target=primary_target
                    )
                    self._execute_trigger_actions(after_self, unit)

                # 累计伤害触发器检查
                cumulative_dmg_actions = self.trigger_service.trigger_cumulative_damage(self.battlefield, unique_damaged)
                if cumulative_dmg_actions:
                    self._execute_global_trigger_actions(cumulative_dmg_actions)
            else:
                # 非伤害型AS技能（如支援型AS 120111/120112）：damaged_targets为空，跳过伤害相关触发器
                # 但仍需处理 after_self_as、暴击触发器、skill_count_actions
                if skill_type == 1:
                    all_post_as_actions = []

                    # 自身AS攻击后触发（如諸元修正）
                    _as_primary_target = getattr(self.skill_service, '_last_primary_target', None)
                    after_self_as = self.trigger_service.trigger_after_skill_use(
                        unit, selected_skill, skill_result, self.battlefield,
                        primary_target=_as_primary_target
                    )
                    all_post_as_actions.extend(after_self_as)

                    # 暴击触发PS（ラッキー4！、ジャックポット等）也属于同时机
                    if self._deferred_crit_triggers:
                        for entry in list(self._deferred_crit_triggers):
                            c, bf = entry[0], entry[1]
                            crit_count = entry[2] if len(entry) > 2 else 1
                            crit_actions = self.trigger_service.trigger_pawn_caused_critical(c, bf, count=crit_count)
                            all_post_as_actions.extend(crit_actions)
                        self._deferred_crit_triggers = []

                    # 技能使用次数触发PS（skill_use_count已在上方统一更新）
                    skill_count_actions = self.trigger_service.trigger_skill_use_count(unit, self.battlefield)
                    if skill_count_actions:
                        all_post_as_actions.extend(skill_count_actions)

                    # 按速度降序→位置升序排序
                    if all_post_as_actions:
                        all_post_as_actions.sort(
                            key=lambda a: self.trigger_service.calculate_priority(a.instance.owner)
                        )
                        _log.info("[POST_AS_TRIGGERS] non-damage AS: %d same-timing PS actions collected",
                                  len(all_post_as_actions))

                    # 记录PP快照，用于后续判断PS是否实际执行
                    self._pp_snapshot_before_as_triggers = {}
                    for a in all_post_as_actions:
                        o = a.instance.owner
                        self._pp_snapshot_before_as_triggers[o.unit_id] = o.current_pp

                    self._execute_trigger_actions(all_post_as_actions, unit)

                    # PS技能可能产生新的暴击触发器，继续处理
                    self._flush_deferred_crit_triggers(unit)

            if had_aura:
                aura_target_ids, new_knockout_target_ids, applied_debuff_types = \
                    self._collect_debuff_trigger_data(skill_result)
                _log.info("[AURA_TRIGGER] aura_target_ids=%s new_knockout_target_ids=%s applied_debuff_types=%s",
                          aura_target_ids, new_knockout_target_ids, applied_debuff_types)
                if aura_target_ids:
                    aura_actions = self.trigger_service.trigger_pawn_received_aura(
                        self.battlefield, aura_target_ids, actor=unit,
                        new_knockout_target_ids=new_knockout_target_ids,
                        applied_debuff_types=applied_debuff_types)
                    _log.info("[AURA_TRIGGER] aura_actions=%d, primary_targets=%s",
                              len(aura_actions),
                              [a.parameters.get('primary_target').name if hasattr(a, 'parameters') and a.parameters.get('primary_target') else None for a in aura_actions])
                    self._execute_trigger_actions(aura_actions, unit)

        self.skill_service.update_cooldown_after_skill_use(unit, selected_skill)

        # AS技能的skill_use_count更新和skill_count_actions已在all_post_as_actions中合并处理
        # 非AS技能仍在此处独立处理
        if skill_type != 1:
            unit.skill_use_count[selected_skill] = unit.skill_use_count.get(selected_skill, 0) + 1
            _log.info("[SKILL_COUNT] non-AS skill_use_count updated: %s skill[%d] -> count=%d, full=%s",
                      unit.name, selected_skill, unit.skill_use_count[selected_skill], dict(unit.skill_use_count))

        skill_count_actions = self.trigger_service.trigger_skill_use_count(unit, self.battlefield)

        # AS技能的skill_count_actions已在all_post_as_actions中合并执行，此处仅处理清理逻辑
        # 非AS技能在此处独立执行
        if skill_type == 1:
            # AS技能：skill_count_actions已在all_post_as_actions中执行
            # 此处仅处理skill_use_count清理
            # 需要检查PS是否实际执行了（PP是否足够），避免PP不足时错误清除计数器
            if skill_count_actions:
                # 检查PS是否实际执行了（通过PP快照判断）
                any_executed = False
                pp_snap = getattr(self, '_pp_snapshot_before_as_triggers', {})
                for action in skill_count_actions:
                    owner = action.instance.owner
                    pp_before = pp_snap.get(owner.unit_id, owner.current_pp)
                    if owner.current_pp < pp_before:
                        # PP已被消耗，说明PS实际执行了
                        any_executed = True
                        break

                if any_executed:
                    for action in skill_count_actions:
                        owner = action.instance.owner
                        if owner.skill_use_count:
                            parsed = self.data_loader.get_parsed_skill_data(action.skill_id) if hasattr(self.data_loader, 'get_parsed_skill_data') else None
                            gc = parsed.get('global_condition') if parsed else None
                            if gc and isinstance(gc, dict) and gc.get('type') == 'skill_use_count_modulo':
                                count_skill_types = gc.get('count_skill_types', [1])
                                is_ps_modulo_trigger = (count_skill_types == [2])
                                if is_ps_modulo_trigger:
                                    continue
                                exclude_skill_ids = gc.get('exclude_skill_ids', [])
                                cleared_ids = []
                                for sid in list(owner.skill_use_count.keys()):
                                    if sid in exclude_skill_ids:
                                        continue
                                    sd = self.data_loader.get_skill_by_id(sid) if self.data_loader else None
                                    if sd and sd.skill_type in count_skill_types:
                                        del owner.skill_use_count[sid]
                                        cleared_ids.append(sid)
                                _log.info("[SKILL_COUNT] %s skill_use_count selective reset: cleared=%s, remaining=%s",
                                          owner.name, cleared_ids, dict(owner.skill_use_count))
                            else:
                                owner.skill_use_count.clear()
                        owner.skill_use_count_pending = False
                else:
                    # PS因PP不足未执行，保留skill_use_count，设置pending
                    for action in skill_count_actions:
                        owner = action.instance.owner
                        _log.info("[SKILL_COUNT] %s PP insufficient for count trigger, preserving skill_use_count=%s, setting pending",
                                  owner.name, dict(owner.skill_use_count))
                        owner.skill_use_count_pending = True
        else:
            # 非AS技能：独立执行skill_count_actions
            if skill_count_actions:
                pp_snapshot = {}
                for action in skill_count_actions:
                    owner = action.instance.owner
                    pp_snapshot[owner.unit_id] = owner.current_pp

            self._execute_trigger_actions(skill_count_actions, unit)

            if skill_count_actions:
                any_executed = False
                for action in skill_count_actions:
                    owner = action.instance.owner
                    if pp_snapshot.get(owner.unit_id, 999) > owner.current_pp:
                        any_executed = True
                        break

                if any_executed:
                    for action in skill_count_actions:
                        owner = action.instance.owner
                        if owner.skill_use_count:
                            skill_data_for_action = self.data_loader.get_skill_by_id(action.skill_id)
                            parsed = self.data_loader.get_parsed_skill_data(action.skill_id) if hasattr(self.data_loader, 'get_parsed_skill_data') else None
                            gc = parsed.get('global_condition') if parsed else None
                            if gc and isinstance(gc, dict) and gc.get('type') == 'skill_use_count_modulo':
                                count_skill_types = gc.get('count_skill_types', [1])
                                exclude_skill_ids = gc.get('exclude_skill_ids', [])
                                is_ps_modulo_trigger = (count_skill_types == [2])
                                if is_ps_modulo_trigger:
                                    _log.info("[SKILL_COUNT] %s is PS-modulo trigger, NOT clearing counts (handled in PS execution)",
                                              owner.name)
                                    continue
                                cleared_ids = []
                                for sid in list(owner.skill_use_count.keys()):
                                    if sid in exclude_skill_ids:
                                        continue
                                    sd = self.data_loader.get_skill_by_id(sid) if self.data_loader else None
                                    if sd and sd.skill_type in count_skill_types:
                                        del owner.skill_use_count[sid]
                                        cleared_ids.append(sid)
                                _log.info("[SKILL_COUNT] %s skill_use_count selective reset after trigger: cleared skill_ids=%s, remaining=%s",
                                          owner.name, cleared_ids, dict(owner.skill_use_count))
                            else:
                                _log.info("[SKILL_COUNT] %s skill_use_count full reset after trigger: %s -> {}",
                                          owner.name, dict(owner.skill_use_count))
                                owner.skill_use_count.clear()
                            owner.skill_use_count_pending = False
                else:
                    for action in skill_count_actions:
                        owner = action.instance.owner
                        parsed = self.data_loader.get_parsed_skill_data(action.skill_id) if hasattr(self.data_loader, 'get_parsed_skill_data') else None
                        gc = parsed.get('global_condition') if parsed else None
                        is_ps_modulo_trigger = (gc and isinstance(gc, dict)
                                                and gc.get('type') == 'skill_use_count_modulo'
                                                and gc.get('count_skill_types') == [2])

                        if is_ps_modulo_trigger:
                            _log.info("[SKILL_COUNT] %s is PS-modulo trigger, pending handled in PS execution",
                                      owner.name)
                        else:
                            _log.info("[SKILL_COUNT] %s PP insufficient for count trigger, pending for next AS use",
                                      owner.name)
                            owner.skill_use_count_pending = True

        unit.action_phase = UnitActionPhase.AFTER_SKILL

        # AS技能的after_skill_use触发器已在all_post_as_actions中合并处理，此处仅对非AS技能调用
        if skill_type != 1:
            trigger_actions = self.trigger_service.trigger_after_skill_use(unit, selected_skill, skill_result, self.battlefield)
            self._execute_trigger_actions(trigger_actions, unit)

        # 处理后续触发器（after_ally_attacked等）产生的crit triggers
        # 这些触发器在复活后执行，其crit triggers可以立即执行
        self._flush_deferred_crit_triggers(unit)

        unit.action_phase = UnitActionPhase.IDLE
        unit.action_count_total += 1
        self.skill_service.update_action_cooldowns(unit, pre_action_cooldowns)

        # Guard cleanup: remove guard buffs triggered by this unit's action
        self._cleanup_guard_buffs(unit)

    def _cleanup_guard_buffs(self, attacker: UnitState) -> None:
        """清理由指定攻击者触发的guard buff和attacker_action类型的debuff/buff。

        Guard效果只在触发它的那次技能攻击中生效，技能执行完毕后立即清理。
        attacker_action类型的debuff/buff持续到攻击发起者的该次行动结束。
        同时清理新版cover/guard特殊机制状态。
        """
        for unit in self.battlefield.get_all_units():
            if not unit.is_alive:
                continue
            to_remove = []
            # Guard cleanup (旧版buff机制)
            for buff in unit.buffs:
                if (buff.effect_type == SkillEffectType.GUARD.value
                        and buff.triggered_by_attacker == attacker.unit_id):
                    to_remove.append(buff.buff_id)
                    _log.info("[GUARD_CLEANUP] %s: guard buff removed (attacker %s action ended)",
                              unit.name, attacker.name)
            # attacker_action duration_type cleanup: 攻击者行动结束时清除由攻击者施加的临时debuff/buff
            for buff in unit.buffs + unit.debuffs:
                if (buff.source_unit_id == attacker.unit_id
                        and getattr(buff, 'original_duration_type', '') == 'attacker_action'):
                    to_remove.append(buff.buff_id)
                    _log.info("[ATTACKER_ACTION_CLEANUP] %s: %s %s removed (attacker %s action ended)",
                              unit.name, 'debuff' if buff.is_debuff else 'buff',
                              buff.effect_type, attacker.name)

            # 新版cover/guard特殊机制清理：清理所有设置了cover_target的单位
            # cover/guard在攻击者行动结束时全部清理（不分来源，因为cover的持续时间就是攻击者行动）
            if unit.cover_target is not None:
                unit.cover_target = None
                unit.cover_skill_id = 0
                unit.guard_rate = 0.0
                unit.guard_active = False
                _log.info("[COVER_CLEANUP] %s: cover/guard state cleared (attacker %s action ended)",
                          unit.name, attacker.name)

            if to_remove:
                unit.buffs = [b for b in unit.buffs if b.buff_id not in to_remove]
                unit.debuffs = [b for b in unit.debuffs if b.buff_id not in to_remove]

    def _flush_deferred_crit_triggers(self, source_unit: UnitState) -> None:
        """执行所有收集的暴击触发PS，循环处理直到没有新的crit triggers产生。

        确保所有crit-triggered PS都在复活后执行，且PS自身产生的crit triggers也能被正确处理。
        """
        max_iterations = 10  # 防止无限循环
        iteration = 0
        while self._deferred_crit_triggers and self.trigger_service and iteration < max_iterations:
            iteration += 1
            triggers_to_execute = list(self._deferred_crit_triggers)
            self._deferred_crit_triggers = []
            _log.info("[CRIT_EXEC] Iteration %d: executing %d deferred crit triggers",
                      iteration, len(triggers_to_execute))
            for entry in triggers_to_execute:
                c, bf = entry[0], entry[1]
                crit_count = entry[2] if len(entry) > 2 else 1
                # 一个技能内即使多hit暴击，PS也只触发1次
                # 但crit_counter按暴击hit数累加（影响crit_count_mod条件判断）
                crit_actions = self.trigger_service.trigger_pawn_caused_critical(c, bf, count=crit_count)
                self._execute_trigger_actions(crit_actions, source_unit)

    def _on_deaths_resolved(self, newly_dead: list) -> None:
        """击杀触发器处理完毕后的钩子。子类可覆写此方法执行复活等逻辑。

        此方法在 PAWN_DIED/PAWN_KILLED/HP_BELOW/UNIT_COUNT_BELOW 触发器之后、
        AFTER_ALLY_ATTACKED 触发器之前调用，确保复活后的单位能正常响应后续触发器。

        Args:
            newly_dead: 本次行动中新阵亡的单位列表
        """
        pass

    def _remove_marks_from_dead_caster(self, newly_dead: list) -> None:
        """清除死亡单位施加的「高揚」mark及其linked debuff。
        当施加者被击败时，其施加的所有「高揚」mark及绑定的debuff应立即消失。
        """
        dead_ids = {u.unit_id for u in newly_dead}
        all_units = self.battlefield.get_all_units()
        for alive_unit in all_units:
            if alive_unit.unit_id in dead_ids:
                continue
            # 查找由死亡单位施加的「高揚」mark
            marks_to_remove = [
                d for d in alive_unit.debuffs
                if d.effect_type == SkillEffectType.MARK.value
                and getattr(d, 'name', '') == '高揚'
                and getattr(d, 'source_unit_id', None) in dead_ids
            ]
            for mark in marks_to_remove:
                mark_name = mark.name
                # 移除linked debuff
                linked_debuffs = [
                    d for d in alive_unit.debuffs
                    if getattr(d, 'linked_buff_id', '') == mark_name
                    and getattr(d, 'source_unit_id', None) in dead_ids
                ]
                for ld in linked_debuffs:
                    alive_unit.debuffs.remove(ld)
                    _log.info("[MARK_DEATH] %s: linked debuff '%s' removed (caster %d died)",
                              alive_unit.name, ld.name, mark.source_unit_id)
                alive_unit.debuffs.remove(mark)
                _log.info("[MARK_DEATH] %s: mark '高揚' removed (caster %d died)",
                          alive_unit.name, mark.source_unit_id)

    def _remove_damage_link_from_dead(self, newly_dead: list) -> None:
        """清除死亡单位相关的ダメージリンクbuff。
        - 死亡者自身のdamage_link buffを削除
        - 死亡者をsource_unit_idとするdamage_link buffを全ユニットから削除（双方向リンクの片側解除）
        """
        dead_ids = {u.unit_id for u in newly_dead}
        all_units = self.battlefield.get_all_units()
        for unit in all_units:
            # 死亡者自身のbuff削除（死亡者はaliveでない可能性があるが、buffリストは残っている）
            to_remove = []
            for buff in unit.buffs + unit.debuffs:
                if buff.effect_type != "damage_link":
                    continue
                # 死亡者自身のbuff、または死亡者をsourceとするbuffを削除
                if unit.unit_id in dead_ids or buff.source_unit_id in dead_ids:
                    to_remove.append(buff.buff_id)
                    _log.info("[DAMAGE_LINK_DEATH] %s: damage_link buff removed (buff_id=%s, source=%s, unit_dead=%s)",
                              unit.name, buff.buff_id, buff.source_unit_id,
                              unit.unit_id in dead_ids)
            if to_remove:
                unit.buffs = [b for b in unit.buffs if b.buff_id not in to_remove]
                unit.debuffs = [b for b in unit.debuffs if b.buff_id not in to_remove]

    def _trigger_damage_link_for_dot(self, unit: UnitState, dot_damage: int) -> None:
        """DoT（炎上/毒）ダメージに対するダメージリンク転送。
        公式仕様: DoTリンクダメージはシールドで吸収不可、直接HPに適用。
        リンクダメージは再度リンクされない（再帰防止）。
        """
        if dot_damage <= 0:
            return
        damage_link_buffs = [b for b in unit.buffs + unit.debuffs if b.effect_type == "damage_link"]
        if not damage_link_buffs:
            return
        all_units = self.battlefield.get_all_units()
        for dl in damage_link_buffs:
            linker = next((u for u in all_units if u.unit_id == dl.source_unit_id), None)
            if linker and linker.is_alive and linker.unit_id != unit.unit_id:
                transfer_dmg = int(dot_damage * dl.value / 100)
                if transfer_dmg <= 0:
                    continue
                # DoTリンクダメージはシールド吸収不可、直接HP減少
                linker.current_hp = max(0, linker.current_hp - transfer_dmg)
                linker.damage_taken_total += transfer_dmg
                _log.info("[DAMAGE_LINK_DOT] %s -> %s: transferred %d dmg (DoT, %.0f%% of %d), linker hp %d->%d",
                          unit.name, linker.name, transfer_dmg, dl.value,
                          dot_damage, linker.current_hp + transfer_dmg, linker.current_hp)

    def _on_death_narrative_complete(self, newly_dead: list) -> None:
        """死亡通知叙事输出完毕后的钩子。子类可覆写此方法输出复活等叙事。

        此方法在死亡通知（💀【阵亡】）输出之后调用，确保复活叙事出现在死亡通知之后。

        Args:
            newly_dead: 本次行动中新阵亡的单位列表
        """
        pass

    @staticmethod
    def _is_element_advantage(caster_elem: int, target_elem: int) -> bool:
        advantages = {1: 3, 2: 1, 3: 4, 4: 2, 5: 6, 6: 5}
        return advantages.get(caster_elem) == target_elem

    def _check_and_apply_status_effects(self, unit: UnitState) -> None:
        # 始终从debuff列表同步标志位，确保与实际状态一致
        # 避免因aura过期/移除时_sync_stun_freeze_flags未被调用导致标志位不同步
        unit.is_stunned = self.status_service.is_stunned(unit)
        if unit.is_stunned:
            _log.info("[ACT]   %s 眩晕中", unit.name)
            if self.narrative:
                self.narrative.stunned(self._get_display_name(unit))

        unit.is_frozen = self.status_service.is_frozen(unit)
        if unit.is_frozen:
            _log.info("[ACT]   %s 冰冻中", unit.name)
            if self.narrative:
                self.narrative.frozen(self._get_display_name(unit))

        # DoT结算顺序: 毒 → 炎上（按游戏内表现）
        # 毒伤害依赖当前HP（current_hp * pct），必须先结算，否则炎上先扣HP会导致毒伤害亏损
        poison_dmg, poison_calc = self.status_service.apply_poison_damage(unit)
        if poison_dmg > 0:
            unit.damage_taken_total += poison_dmg
            poison_sources = [b for b in unit.debuffs if b.effect_type == SkillEffectType.POISON.value]
            if poison_sources:
                source_id = poison_sources[0].source_unit_id
                source_unit = next((u for u in self.battlefield.get_all_units() if u.unit_id == source_id), None)
                if source_unit:
                    source_unit.damage_dealt_total += poison_dmg
                tracker = getattr(self.battlefield, 'scoring_tracker', None)
                if tracker is not None:
                    source_side = "ally" if source_unit and source_unit.side.value == "ally" else "enemy"
                    target_side = "ally" if unit.side.value == "ally" else "enemy"
                    source_name = source_unit.name if source_unit else source_id
                    tracker.record_damage(
                        source_id=source_id, source_name=source_name, source_side=source_side,
                        target_id=unit.unit_id, target_name=unit.name, target_side=target_side,
                        actual_damage=poison_dmg, shield_absorbed=0,
                    )
            if self.narrative:
                self.narrative.poison_damage(self._get_display_name(unit), poison_dmg, unit.current_hp, unit.max_hp, poison_calc)

        burn_dmg, burn_stacks, burn_calc = self.status_service.apply_burn_damage(unit)
        if burn_dmg > 0:
            unit.damage_taken_total += burn_dmg
            # Find burn source and update their damage_dealt_total + tracker
            burn_sources = [b for b in unit.debuffs if b.effect_type == SkillEffectType.CONFLAGRATION.value]
            if burn_sources:
                source_id = burn_sources[0].source_unit_id
                source_unit = next((u for u in self.battlefield.get_all_units() if u.unit_id == source_id), None)
                if source_unit:
                    source_unit.damage_dealt_total += burn_dmg
                tracker = getattr(self.battlefield, 'scoring_tracker', None)
                if tracker is not None:
                    source_side = "ally" if source_unit and source_unit.side.value == "ally" else "enemy"
                    target_side = "ally" if unit.side.value == "ally" else "enemy"
                    source_name = source_unit.name if source_unit else source_id
                    tracker.record_damage(
                        source_id=source_id, source_name=source_name, source_side=source_side,
                        target_id=unit.unit_id, target_name=unit.name, target_side=target_side,
                        actual_damage=burn_dmg, shield_absorbed=0,
                    )
            if self.narrative:
                self.narrative.burn_damage(self._get_display_name(unit), burn_dmg, unit.current_hp, unit.max_hp, burn_stacks, burn_calc)

        # ダメージリンク転送（DoT用）: 炎上/毒のダメージもリンク対象
        # ただしDoTリンクダメージはシールドで吸収不可（公式仕様）
        if (burn_dmg > 0 or poison_dmg > 0) and unit.is_alive:
            self._trigger_damage_link_for_dot(unit, burn_dmg + poison_dmg)

        # 行動時ダメージ：行动时受到施法者攻击力x%的EN伤害
        action_dmg, action_shield_absorbed = self.status_service.apply_action_damage(unit)
        if action_dmg > 0 or action_shield_absorbed > 0:
            unit.damage_taken_total += action_dmg
            action_dmg_sources = [b for b in unit.debuffs if b.effect_type == SkillEffectType.ACTION_DAMAGE.value]
            if action_dmg_sources:
                source_id = action_dmg_sources[0].source_unit_id
                source_unit = next((u for u in self.battlefield.get_all_units() if u.unit_id == source_id), None)
                if source_unit:
                    source_unit.damage_dealt_total += action_dmg
            if self.narrative:
                self.narrative.action_damage(self._get_display_name(unit), action_dmg, unit.current_hp, unit.max_hp,
                                             shield_absorbed=action_shield_absorbed)

        # DOT/行動時ダメージ处理后、HOT回復前にHP阈值触发器检查（如再起律動、リカバリーブースト）
        # 必须在HOT回復前检查，否则DOT将HP打到阈值以下后HOT又把HP拉回阈值以上，
        # trigger_hp_below会因prev和current都高于阈值而检测不到跨越（如技能「再起律動」bug）
        if burn_dmg > 0 or poison_dmg > 0 or action_dmg > 0:
            hp_below_actions = self.trigger_service.trigger_hp_below(self.battlefield, [unit])
            if hp_below_actions:
                self._execute_global_trigger_actions(hp_below_actions)

            # 累计伤害触发器检查
            cumulative_dmg_actions = self.trigger_service.trigger_cumulative_damage(self.battlefield, [unit])
            if cumulative_dmg_actions:
                self._execute_global_trigger_actions(cumulative_dmg_actions)

        regen_amount, regen_details = self.status_service.apply_regen(unit, self.damage_service, self.battlefield)
        if regen_amount > 0:
            # 计分追踪：按HOT来源分别记录回复（敌方回复需要从得分中扣除）
            # 修复: 之前source/target都填被治疗者，导致hp_healed错误累加到被治疗者
            tracker = getattr(self.battlefield, 'scoring_tracker', None)
            if tracker is not None:
                unit_side = "ally" if unit.side.value == "ally" else "enemy"
                all_units = self.battlefield.get_all_units()
                for rd in regen_details:
                    source_id = rd.get('source_unit_id') or unit.unit_id
                    source_unit = next((u for u in all_units if u.unit_id == source_id), None)
                    if source_unit:
                        source_name = source_unit.name
                        source_side = "ally" if source_unit.side.value == "ally" else "enemy"
                    else:
                        # 施法者已不在战场，回退到自身（保持兼容）
                        source_name = unit.name
                        source_side = unit_side
                    tracker.record_heal(
                        source_id=source_id, source_name=source_name, source_side=source_side,
                        target_id=unit.unit_id, target_name=unit.name, target_side=unit_side,
                        heal_amount=rd['amount'],
                    )
            if self.narrative:
                # HOT可能有多个来源，每个来源单独输出
                for rd in regen_details:
                    self.narrative.heal(source_name=self._get_display_name(unit),
                                       target_name=self._get_display_name(unit),
                                       amount=rd['amount'],
                                       source_hp=f"HP:{unit.current_hp}/{unit.max_hp}",
                                       hp_before=unit.current_hp - regen_amount if len(regen_details) == 1 else unit.current_hp - rd['amount'],
                                       target_max_hp=unit.max_hp)

    def _collect_debuff_trigger_data(self, skill_result: Dict) -> Tuple[List[str], Set[str], Set[str]]:
        """从技能结果中收集debuff触发器数据（同时处理aura和add_status两种类型）"""
        aura_target_ids = []
        new_knockout_target_ids = set()
        applied_debuff_types = set()
        for applied in skill_result.get("effects_applied", []):
            et = applied.get("effect_type")
            is_debuff = applied.get("is_debuff")
            if not is_debuff:
                continue
            if et == "aura":
                for aura_detail in applied.get("auras", []):
                    aura_target_ids.append(aura_detail["target_id"])
                    if aura_detail.get("is_new_knockout"):
                        new_knockout_target_ids.add(aura_detail["target_id"])
                    effect_type = aura_detail.get("effect", "")
                    if effect_type:
                        applied_debuff_types.add(effect_type)
            elif et == "add_status":
                for status_detail in applied.get("statuses", []):
                    aura_target_ids.append(status_detail["target_id"])
                    effect_type = status_detail.get("effect", "")
                    if effect_type:
                        applied_debuff_types.add(effect_type)
                        if effect_type.lower() == "knockout":
                            new_knockout_target_ids.add(status_detail["target_id"])
        return aura_target_ids, new_knockout_target_ids, applied_debuff_types

    # 主动攻击型 PS trigger_type 集合：这些 PS 的伤害应触发被攻撃反応（after_self_attacked 等）。
    # 反应型 PS（after_self_attacked/after_ally_attacked/after_as_attacked 等）不在集合中，
    # 避免反应链递归。全局型 PS（on_turn_end/on_cumulative_damage/on_hp_below/on_unit_count_below）
    # 走 _execute_global_trigger_actions 路径，已自带被攻撃反応处理，也不在此集合中。
    _ACTIVE_ATTACK_TRIGGER_TYPES = {
        'on_skill_use_count', 'on_critical',
        'after_as_attack', 'after_own_action', 'after_ally_as_attack',
    }

    def _trigger_being_attacked_reactions(self, attacker: UnitState,
                                          damaged_targets: list,
                                          skill_name: str) -> None:
        """对 PS 攻击的 damaged_targets 触发被攻撃反応触发器。

        顺序：hp_below → after_self_attacked → after_ally_attacked（hp_below owner 抑制 after_ally_attacked）。
        必须在死亡处理前执行，确保被攻击方的 PS（如「外殻強化」230029 的 def_up）
        在被击杀前能反应。

        与 AS 路径不同，PS 攻击不触发 after_as_attacked/after_as_attacked_ally
        （仅 AS 主目标）和 after_ally_as_attack/after_self_as（AS 攻撃後追撃型PS）。
        """
        if not damaged_targets:
            return
        unique_damaged = list({u.unit_id: u for u in damaged_targets}.values())
        primary_target = damaged_targets[0]

        # hp_below 优先于 after_self_attacked（与 AS 路径保持一致）
        hp_below_actions = self.trigger_service.trigger_hp_below(
            self.battlefield, unique_damaged)
        self._execute_trigger_actions(hp_below_actions, attacker)
        owners_with_hp_below = set(
            a.instance.owner.unit_id for a in hp_below_actions)

        # after_self_attacked: 被攻击方自身的 PS（如「外殻強化」def_up）
        after_self_actions = self.trigger_service.trigger_after_self_attacked(
            unique_damaged, self.battlefield,
            actor=attacker, primary_target=primary_target)
        if after_self_actions:
            _log.info("[POST_PS_ATTACK] after_self_attacked triggers: %d (from PS[%s] by %s)",
                      len(after_self_actions), skill_name, attacker.name)
        self._execute_trigger_actions(after_self_actions, attacker)

        # after_ally_attacked: 被攻击方友方的 PS（hp_below owner 抑制）
        after_ally_actions = self.trigger_service.trigger_after_ally_attacked(
            unique_damaged, self.battlefield,
            actor=attacker, primary_target=primary_target)
        after_ally_actions = [
            a for a in after_ally_actions
            if a.instance.owner.unit_id not in owners_with_hp_below]
        if after_ally_actions:
            _log.info("[POST_PS_ATTACK] after_ally_attacked triggers: %d (from PS[%s] by %s)",
                      len(after_ally_actions), skill_name, attacker.name)
        self._execute_trigger_actions(after_ally_actions, attacker)

        # 被攻撃反応 PS 可能产生新的暴击触发器
        self._flush_deferred_crit_triggers(attacker)

    def _execute_trigger_actions(self, actions, source_unit: UnitState) -> None:
        if not actions:
            return
        _log.info("[TRIGGER_EXEC] _execute_trigger_actions called with %d actions, source=%s",
                  len(actions), source_unit.name)
        for i, action in enumerate(actions):
            owner = action.instance.owner
            skill_data = self.data_loader.get_skill_by_id(action.skill_id)
            skill_name = skill_data.name if skill_data else "?"
            _log.info("[PS_EXEC] %s triggers %s PS[%s] (id=%d)",
                      source_unit.name, owner.name,
                      skill_name, action.skill_id)

            if not owner.is_alive:
                continue
            if owner.is_stunned or owner.is_frozen or owner.is_charging:
                _log.info("[PS_EXEC] %s: SKIPPED PS[%s] (stunned=%s frozen=%s charging=%s)",
                          owner.name, skill_name, owner.is_stunned, owner.is_frozen, owner.is_charging)
                continue

            if not self.skill_service.check_skill_cost(owner, action.skill_id):
                _log.info("[PS_EXEC] PS[%s] insufficient resources for %s", skill_name, owner.name)
                continue

            if self.narrative:
                self.narrative.ps_trigger(self._get_display_name(owner), skill_name, self._get_display_name(source_unit))
                self.narrative.skill_prepare(owner, skill_name, 2, self._get_display_name(owner))

            self.skill_service.deduct_skill_cost(owner, action.skill_id)

            if self.narrative:
                cost = skill_data.resource_cost if skill_data else 1
                self.narrative.resource_deduct(self._get_display_name(owner), 2, cost,
                                               owner.current_ap, owner.initial_active_point,
                                               owner.current_pp, owner.initial_passive_point,
                                               owner.current_ep, owner.max_extra_point)

            units_before = set(u.unit_id for u in self.battlefield.get_all_units() if u.is_alive)

            trigger_attacker = action.parameters.get('trigger_attacker') if hasattr(action, 'parameters') else None
            primary_target = action.parameters.get('primary_target') if hasattr(action, 'parameters') else None
            damaged_targets = action.parameters.get('targets') if hasattr(action, 'parameters') else None
            total_damage = action.parameters.get('total_damage') if hasattr(action, 'parameters') else None
            if trigger_attacker:
                self.skill_service._trigger_attacker = trigger_attacker
            if primary_target:
                self.skill_service._primary_target = primary_target
            if damaged_targets:
                self.skill_service._damaged_targets = damaged_targets
            if total_damage is not None:
                self.skill_service._trigger_total_damage = total_damage
            else:
                self.skill_service._trigger_total_damage = 0

            skill_result = self.skill_service.execute_skill(
                caster=owner,
                skill_id=action.skill_id,
                battlefield=self.battlefield,
                skip_cost=True,
                defer_crit_triggers=True,
            )

            if trigger_attacker:
                self.skill_service._trigger_attacker = None
            if primary_target:
                self.skill_service._primary_target = None
            if damaged_targets:
                self.skill_service._damaged_targets = None

            # Guard cleanup: PS技能执行完毕后立即清理由该施法者触发的Guard buff
            # Guard效果只在触发它的那次技能攻击中生效，后续技能不应享受Guard减伤
            self._cleanup_guard_buffs(owner)

            if skill_result.get("success"):
                damaged_targets_reaction = self._log_narrative_effects(owner, skill_result, skill_name, 2, action.skill_id)
                self.skill_service.update_cooldown_after_skill_use(owner, action.skill_id)

                # crit_count_mod触发器：PS技能执行成功后清空暴击计数器
                # 延迟清空确保PP不足时计数器保持不变，下次暴击仍可触发
                parsed = self.data_loader.get_parsed_skill_data(action.skill_id) if self.data_loader else None
                trigger_type = None
                if parsed:
                    gc = parsed.get('global_condition', {})
                    if gc and gc.get('type') == 'crit_count_mod':
                        owner.crit_counter = 0
                        _log.info("[CRIT_RESET] %s: crit_counter reset to 0 after PS[%s] executed successfully",
                                  owner.name, skill_name)

                    # on_cumulative_damage触发器：PS技能执行成功后清空累计伤害计数器
                    # PP不足时PS未执行，计数器保持不变
                    trigger_type = parsed.get('trigger_type')
                    if trigger_type == 'on_cumulative_damage':
                        owner.cumulative_hp_damage = 0
                        _log.info("[CUMULATIVE_DMG_RESET] %s: cumulative_hp_damage reset to 0 after PS[%s] executed successfully",
                                  owner.name, skill_name)

                # Update skill_use_count for PS skills (needed for skill_use_count_modulo triggers)
                owner.skill_use_count[action.skill_id] = owner.skill_use_count.get(action.skill_id, 0) + 1
                _log.info("[SKILL_COUNT] PS skill_use_count updated (_execute_trigger_actions): %s skill[%d] -> count=%d, full=%s",
                          owner.name, action.skill_id, owner.skill_use_count[action.skill_id], dict(owner.skill_use_count))

                # 检查PS技能触发的skill_use_count_modulo触发器（如「お母様、見ててください……！」）
                # 如果PP足够，立即执行；PP不足则设置pending，等待下一次PS技能执行后再检查
                self._check_and_execute_ps_skill_count_triggers(owner)

                # 触发被攻撃反応触发器：主动攻击型 PS（如 on_skill_use_count 的「期待に応えたい」、
                # on_critical、after_as_attack、after_ally_as_attack）的攻击应触发被攻击方的 PS
                # （如「外殻強化」after_self_attacked 的 def_up），与全局 PS 攻击路径一致。
                # 必须在死亡处理前触发，确保被攻击方的 PS 在被击杀前能反应。
                # 反应型 PS（after_self_attacked/after_ally_attacked 等）不再触发被攻撃反応，避免递归。
                if trigger_type in self._ACTIVE_ATTACK_TRIGGER_TYPES and damaged_targets_reaction:
                    self._trigger_being_attacked_reactions(owner, damaged_targets_reaction, skill_name)

                # 收集debuff触发数据（但延迟到复活后执行，确保被击杀的目标复活后能触发自身PS）
                ps_deferred_aura_data = None
                had_aura = any(
                    applied.get("effect_type") in ("aura", "add_status")
                    for applied in skill_result.get("effects_applied", [])
                )
                if had_aura:
                    aura_target_ids, new_ko_ids, applied_debuff_types = \
                        self._collect_debuff_trigger_data(skill_result)
                    if aura_target_ids:
                        ps_deferred_aura_data = (aura_target_ids, new_ko_ids, applied_debuff_types)

                ps_newly_dead = []
                for u in self.battlefield.get_all_units():
                    if u.unit_id in units_before and not u.is_alive:
                        ps_newly_dead.append(u)

                if self.narrative:
                    for u in ps_newly_dead:
                        if not u.is_death_notified:
                            self.narrative.death(self._get_display_name(u))
                            u.is_death_notified = True

                if ps_newly_dead:
                    death_actions = self.trigger_service.trigger_pawn_died(ps_newly_dead, self.battlefield)
                    self._execute_trigger_actions(death_actions, owner)
                    kill_actions = self.trigger_service.trigger_pawn_killed(owner, self.battlefield)
                    self._execute_trigger_actions(kill_actions, owner)
                    any_kill_actions = self.trigger_service.trigger_pawn_any_kill(owner, self.battlefield)
                    self._execute_trigger_actions(any_kill_actions, owner)
                    # 钩子：PS击杀后也执行复活逻辑
                    self._on_deaths_resolved(ps_newly_dead)
                    if self.narrative:
                        self._on_death_narrative_complete(ps_newly_dead)

                # 复活后执行debuff触发检查（确保被击杀的目标复活后能触发自身PS）
                if ps_deferred_aura_data:
                    aura_target_ids, new_ko_ids, applied_debuff_types = ps_deferred_aura_data
                    aura_actions = self.trigger_service.trigger_pawn_received_aura(
                        self.battlefield, aura_target_ids, actor=owner,
                        new_knockout_target_ids=new_ko_ids,
                        applied_debuff_types=applied_debuff_types)
                    self._execute_trigger_actions(aura_actions, owner)

                # PS技能的暴击触发：收集到_deferred_crit_triggers，由_execute_unit_action统一在复活后执行
                ps_pending_crit = skill_result.get("pending_crit_triggers", [])
                if ps_pending_crit:
                    self._deferred_crit_triggers.extend(ps_pending_crit)
                    _log.info("[CRIT_COLLECT] PS %s: collected %d crit triggers (total=%d)",
                              skill_name, len(ps_pending_crit), len(self._deferred_crit_triggers))
            else:
                _log.info("[PS_EXEC] PS[%s] execution failed: %s", skill_name, skill_result.get("error", "unknown"))

    def _check_and_execute_ps_skill_count_triggers(self, ps_owner: UnitState) -> None:
        """PS技能执行后，立即检查skill_use_count_modulo触发器。

        用于「お母様、見ててください……！」等PS技能：
        - 当PS技能触发并更新skill_use_count后，立即检查是否有满足条件的计数触发器
        - 如果PP足够，立即执行触发的技能
        - 如果PP不足，设置pending，等待下一次PS技能执行后再检查
        """
        ctx = TriggerContext(
            TriggerTiming.SKILL_USE_COUNT,
            self.battlefield,
            actor=ps_owner,
        )
        ps_count_actions = self.trigger_service.check_triggers(
            TriggerTiming.SKILL_USE_COUNT, ctx)

        if not ps_count_actions:
            return

        # 过滤出属于ps_owner的触发器（确保是owner自己的技能触发）
        ps_owner_actions = [a for a in ps_count_actions if a.instance.owner.unit_id == ps_owner.unit_id]
        if not ps_owner_actions:
            return

        _log.info("[PS_COUNT] Checking PS skill_use_count triggers for %s: %d actions",
                  ps_owner.name, len(ps_owner_actions))

        # 检查每个触发器
        for action in ps_owner_actions:
            owner = action.instance.owner
            skill_data = self.data_loader.get_skill_by_id(action.skill_id)
            skill_name = skill_data.name if skill_data else "?"
            parsed = self.data_loader.get_parsed_skill_data(action.skill_id) if hasattr(self.data_loader, 'get_parsed_skill_data') else None
            gc = parsed.get('global_condition') if parsed else None

            # 检查是否为skill_use_count_modulo条件
            is_modulo_trigger = (gc and isinstance(gc, dict) and gc.get('type') == 'skill_use_count_modulo')
            if not is_modulo_trigger:
                continue

            # 检查是否为PS-modulo触发器（count_skill_types=[2]）
            count_skill_types = gc.get('count_skill_types', [1]) if isinstance(gc, dict) else [1]
            is_ps_modulo_trigger = (count_skill_types == [2])

            # 只处理PS-modulo触发器，AS-modulo触发器由AS技能执行后处理
            if not is_ps_modulo_trigger:
                _log.info("[PS_COUNT] %s is AS-modulo trigger, skipping in PS check",
                          owner.name)
                continue

            if not self.skill_service.check_skill_cost(owner, action.skill_id):
                # PP不足，设置pending，等待下一次PS技能执行后再检查
                _log.info("[PS_COUNT] %s PP insufficient for %s, setting pending for next PS",
                          owner.name, skill_name)
                owner.skill_use_count_pending = True
                continue

            # PP足够，立即执行
            _log.info("[PS_COUNT] %s PP sufficient, executing %s immediately",
                      owner.name, skill_name)

            # 执行触发的技能
            self._execute_single_ps_action(action, ps_owner)

            # 执行后清除skill_use_count中贡献的计数
            if owner.skill_use_count:
                exclude_skill_ids = gc.get('exclude_skill_ids', [])
                cleared_ids = []
                for sid in list(owner.skill_use_count.keys()):
                    if sid in exclude_skill_ids:
                        continue
                    sd = self.data_loader.get_skill_by_id(sid) if self.data_loader else None
                    if sd and sd.skill_type in count_skill_types:
                        del owner.skill_use_count[sid]
                        cleared_ids.append(sid)
                _log.info("[PS_COUNT] %s skill_use_count cleared after immediate execution: %s",
                          owner.name, cleared_ids)
                owner.skill_use_count_pending = False

    def _execute_single_ps_action(self, action, source_unit: UnitState) -> None:
        """执行单个PS技能动作（用于PS技能触发的计数触发器）"""
        owner = action.instance.owner
        skill_data = self.data_loader.get_skill_by_id(action.skill_id)
        skill_name = skill_data.name if skill_data else "?"
        _log.info("[PS_IMMEDIATE] %s triggers %s PS[%s] (id=%d) immediately",
                  source_unit.name, owner.name, skill_name, action.skill_id)

        if not owner.is_alive:
            return
        if owner.is_stunned or owner.is_frozen or owner.is_charging:
            _log.info("[PS_IMMEDIATE] %s: SKIPPED %s (stunned=%s frozen=%s charging=%s)",
                      owner.name, skill_name, owner.is_stunned, owner.is_frozen, owner.is_charging)
            return

        self.skill_service.deduct_skill_cost(owner, action.skill_id)

        if self.narrative:
            cost = skill_data.resource_cost if skill_data else 1
            self.narrative.ps_trigger(self._get_display_name(owner), skill_name, self._get_display_name(source_unit))
            self.narrative.skill_prepare(owner, skill_name, 2, self._get_display_name(owner))
            self.narrative.resource_deduct(self._get_display_name(owner), 2, cost,
                                           owner.current_ap, owner.initial_active_point,
                                           owner.current_pp, owner.initial_passive_point,
                                           owner.current_ep, owner.max_extra_point)

        trigger_attacker = action.parameters.get('trigger_attacker') if hasattr(action, 'parameters') else None
        primary_target = action.parameters.get('primary_target') if hasattr(action, 'parameters') else None
        if trigger_attacker:
            self.skill_service._trigger_attacker = trigger_attacker
        if primary_target:
            self.skill_service._primary_target = primary_target

        skill_result = self.skill_service.execute_skill(
            caster=owner,
            skill_id=action.skill_id,
            battlefield=self.battlefield,
            skip_cost=True,
            defer_crit_triggers=True,
        )

        if trigger_attacker:
            self.skill_service._trigger_attacker = None
        if primary_target:
            self.skill_service._primary_target = None

        # Guard cleanup: PS技能执行完毕后立即清理由该施法者触发的Guard buff
        self._cleanup_guard_buffs(owner)

        if skill_result.get("success"):
            self._log_narrative_effects(owner, skill_result, skill_name, 2, action.skill_id)
            self.skill_service.update_cooldown_after_skill_use(owner, action.skill_id)

    def _execute_global_trigger_actions(self, actions: list) -> None:
        if not actions:
            return
        for action in actions:
            owner = action.instance.owner
            skill_name = "?"
            skill_data = self.data_loader.get_skill_by_id(action.skill_id)
            if skill_data:
                skill_name = skill_data.name
            _log.info("[PS_EXEC] Global trigger: %s PS[%s] (id=%d)",
                      owner.name, skill_name, action.skill_id)

            if not owner.is_alive:
                continue
            if owner.is_stunned or owner.is_frozen or owner.is_charging:
                _log.info("[PS_EXEC] %s: SKIPPED global PS[%s] (stunned=%s frozen=%s charging=%s)",
                          owner.name, skill_name, owner.is_stunned, owner.is_frozen, owner.is_charging)
                continue

            if not self.skill_service.check_skill_cost(owner, action.skill_id):
                _log.info("[PS_EXEC] Global PS[%s] insufficient resources for %s", skill_name, owner.name)
                continue

            if self.narrative:
                self.narrative.ps_trigger(self._get_display_name(owner), skill_name, "全局")
                self.narrative.skill_prepare(owner, skill_name, 2, self._get_display_name(owner))

            self.skill_service.deduct_skill_cost(owner, action.skill_id)

            if self.narrative:
                cost = skill_data.resource_cost if skill_data else 1
                self.narrative.resource_deduct(self._get_display_name(owner), 2, cost,
                                               owner.current_ap, owner.initial_active_point,
                                               owner.current_pp, owner.initial_passive_point,
                                               owner.current_ep, owner.max_extra_point)

            units_before = set(u.unit_id for u in self.battlefield.get_all_units() if u.is_alive)

            # Set trigger context on skill_service (primary_target from action params)
            params = getattr(action, 'parameters', {}) or {}
            if params.get('primary_target'):
                self.skill_service._primary_target = params['primary_target']
            if params.get('trigger_attacker'):
                self.skill_service._trigger_attacker = params['trigger_attacker']
            if params.get('targets'):
                self.skill_service._damaged_targets = params['targets']

            skill_result = self.skill_service.execute_skill(
                caster=owner,
                skill_id=action.skill_id,
                battlefield=self.battlefield,
                skip_cost=True,
                defer_crit_triggers=True,
            )

            # Guard cleanup: PS技能执行完毕后立即清理由该施法者触发的Guard buff
            self._cleanup_guard_buffs(owner)

            # Clean up trigger context
            if params.get('primary_target'):
                self.skill_service._primary_target = None
            if params.get('trigger_attacker'):
                self.skill_service._trigger_attacker = None
            if params.get('targets'):
                self.skill_service._damaged_targets = None

            if skill_result.get("success"):
                damaged_targets_reaction = self._log_narrative_effects(owner, skill_result, skill_name, 2, action.skill_id)
                self.skill_service.update_cooldown_after_skill_use(owner, action.skill_id)

                # crit_count_mod触发器：PS技能执行成功后清空暴击计数器
                parsed = self.data_loader.get_parsed_skill_data(action.skill_id) if self.data_loader else None
                if parsed:
                    gc = parsed.get('global_condition', {})
                    if gc and gc.get('type') == 'crit_count_mod':
                        owner.crit_counter = 0
                        _log.info("[CRIT_RESET] %s: crit_counter reset to 0 after global PS[%s] executed successfully",
                                  owner.name, skill_name)

                    # on_cumulative_damage触发器：PS技能执行成功后清空累计伤害计数器
                    trigger_type = parsed.get('trigger_type')
                    if trigger_type == 'on_cumulative_damage':
                        owner.cumulative_hp_damage = 0
                        _log.info("[CUMULATIVE_DMG_RESET] %s: cumulative_hp_damage reset to 0 after global PS[%s] executed successfully",
                                  owner.name, skill_name)

                # Update skill_use_count for PS skills (needed for skill_use_count_modulo triggers)
                owner.skill_use_count[action.skill_id] = owner.skill_use_count.get(action.skill_id, 0) + 1

                # 触发被攻撃反応触发器：on_turn_end 等全局PS攻击技能（如「リストリクションエッジ」）
                # 的攻击应触发被攻击方的 PS（如「外殻強化」after_self_attacked）
                # 必须在死亡处理前触发，确保被攻击方的 PS 在被击杀前能反应
                # 注意：与 AS 路径不同，全局PS攻击不触发 after_as_attacked/after_as_attacked_ally
                #       （那两个仅 AS 主目标触发），也不触发 after_ally_as_attack/after_self_as
                #       （那两个是 AS 攻击后的追撃型PS）
                if damaged_targets_reaction:
                    self._trigger_being_attacked_reactions(owner, damaged_targets_reaction, skill_name)

                # 收集debuff触发数据（但延迟到复活后执行，确保被击杀的目标复活后能触发自身PS）
                global_deferred_aura_data = None
                had_aura = any(
                    applied.get("effect_type") in ("aura", "add_status")
                    for applied in skill_result.get("effects_applied", [])
                )
                if had_aura:
                    aura_target_ids, new_ko_ids, applied_debuff_types = \
                        self._collect_debuff_trigger_data(skill_result)
                    if aura_target_ids:
                        global_deferred_aura_data = (aura_target_ids, new_ko_ids, applied_debuff_types)

                global_newly_dead = []
                for u in self.battlefield.get_all_units():
                    if u.unit_id in units_before and not u.is_alive:
                        global_newly_dead.append(u)

                if self.narrative:
                    for u in global_newly_dead:
                        if not u.is_death_notified:
                            self.narrative.death(self._get_display_name(u))
                            u.is_death_notified = True

                if global_newly_dead:
                    death_actions = self.trigger_service.trigger_pawn_died(global_newly_dead, self.battlefield)
                    self._execute_trigger_actions(death_actions, owner)
                    kill_actions = self.trigger_service.trigger_pawn_killed(owner, self.battlefield)
                    self._execute_trigger_actions(kill_actions, owner)
                    any_kill_actions = self.trigger_service.trigger_pawn_any_kill(owner, self.battlefield)
                    self._execute_trigger_actions(any_kill_actions, owner)
                    # 钩子：全局PS击杀后也执行复活逻辑
                    self._on_deaths_resolved(global_newly_dead)
                    if self.narrative:
                        self._on_death_narrative_complete(global_newly_dead)

                # 复活后执行debuff触发检查（确保被击杀的目标复活后能触发自身PS）
                if global_deferred_aura_data:
                    aura_target_ids, new_ko_ids, applied_debuff_types = global_deferred_aura_data
                    aura_actions = self.trigger_service.trigger_pawn_received_aura(
                        self.battlefield, aura_target_ids, actor=owner,
                        new_knockout_target_ids=new_ko_ids,
                        applied_debuff_types=applied_debuff_types)
                    self._execute_trigger_actions(aura_actions, owner)

                # 全局PS技能的暴击触发：收集到_deferred_crit_triggers，由_execute_unit_action统一在复活后执行
                global_pending_crit = skill_result.get("pending_crit_triggers", [])
                if global_pending_crit:
                    self._deferred_crit_triggers.extend(global_pending_crit)
                    _log.info("[CRIT_COLLECT] Global PS %s: collected %d crit triggers (total=%d)",
                              skill_name, len(global_pending_crit), len(self._deferred_crit_triggers))
            else:
                _log.info("[PS_EXEC] PS[%s] execution failed: %s", skill_name, skill_result.get("error", "unknown"))

    def _log_narrative_effects(self, caster: UnitState, skill_result: dict,
                                skill_name: str, skill_type: int, skill_id: int = 0) -> List[str]:
        damaged_targets = []

        # 始终从skill_result中提取damaged_targets（触发器逻辑依赖此返回值）
        for applied in skill_result.get("effects_applied", []):
            if applied.get("effect_type") == "damage":
                for t in applied.get("targets", []):
                    target_unit = self._find_unit(t)
                    if target_unit:
                        damaged_targets.append(target_unit)

        if not self.narrative:
            return damaged_targets

        _dmg_type_map = {1: "物理", 2: "能量", 3: "物理"}
        dmg_type = _dmg_type_map.get(caster.character_type, "物理")

        primary_target = None
        all_target_names = []
        for applied in skill_result.get("effects_applied", []):
            if applied.get("effect_type") == "damage":
                for t in applied.get("targets", []):
                    dname = self._get_display_name(t.get('target_id', t['target']))
                    if primary_target is None:
                        primary_target = dname
                    all_target_names.append(dname)
            elif applied.get("effect_type") == "heal":
                for h in applied.get("heals", []):
                    dname = self._get_display_name(h.get('target_id', h['target']))
                    if primary_target is None:
                        primary_target = dname
                    all_target_names.append(dname)
            elif applied.get("effect_type") in ("aura", "add_status"):
                for a in (applied.get("auras", []) or applied.get("statuses", [])):
                    dname = self._get_display_name(a.get('target_id', a['target']))
                    if primary_target is None:
                        primary_target = dname
                    all_target_names.append(dname)

        if not primary_target:
            primary_target = self._get_display_name(caster)
            all_target_names = [primary_target]

        caster_dname = self._get_display_name(caster)
        self.narrative.skill_use(caster_dname, primary_target, skill_name, skill_type)
        self.narrative.skill_targets(caster_dname, skill_name, list(dict.fromkeys(all_target_names)))

        # 先输出 before_* 类型的 inline PS 日志（在伤害之前触发）
        for ps_result in skill_result.get("inline_ps_results", []):
            trigger_timing = ps_result.get("trigger_timing", "")
            if trigger_timing and trigger_timing.startswith("before_"):
                ps_owner = ps_result["owner"]
                ps_name = ps_result["skill_name"]
                ps_dname = self._get_display_name(ps_owner)
                if self.narrative:
                    self.narrative.ps_trigger(ps_dname, ps_name, caster_dname)
                    self.narrative.skill_prepare(ps_owner, ps_name, 2, ps_dname)
                for applied in ps_result["result"].get("effects_applied", []):
                    self._log_narrative_aura_status(applied, ps_dname)

        for applied in skill_result.get("effects_applied", []):
            if applied.get("effect_type") == "damage":
                # 输出条件暴击率上升信息
                bonus_crit = applied.get("bonus_crit_applied", 0)
                if bonus_crit > 0:
                    self.narrative.bonus_crit(caster_dname, bonus_crit)
                for t in applied.get("targets", []):
                    # SubUnit追加伤害使用专门的叙事方法
                    sub_unit_name = t.get("sub_unit_name")
                    if sub_unit_name:
                        target_unit = self._find_unit(t)
                        max_hp = target_unit.max_hp if target_unit else t['hp_before']
                        target_dname = self._get_display_name(t.get('target_id', t['target']))
                        shield_abs = t.get('shield_absorbed', 0)
                        self.narrative.sub_unit_damage(
                            sub_unit_name, target_dname,
                            t.get('actual_damage', t['damage']),
                            t['hp_after'], max_hp, t.get('crit', False),
                            shield_absorbed=shield_abs,
                            calc_detail=t.get('calc_detail'))
                        continue

                    # 附魔伤害使用专门的叙事方法
                    is_enchant = "附魔" in (t.get("modifiers") or [])
                    if is_enchant:
                        target_unit = self._find_unit(t)
                        max_hp = target_unit.max_hp if target_unit else t.get('hp_before', 0)
                        target_dname = self._get_display_name(t.get('target_id', t['target']))
                        modifiers = list(t.get("modifiers", []))
                        if t.get("crit"):
                            modifiers.append("Critical")
                        self.narrative.enchant_damage(
                            attacker_name=caster_dname,
                            attacker_hp=f"HP:{caster.current_hp}/{caster.max_hp}",
                            target_name=target_dname,
                            hp_before=t['hp_before'],
                            hp_after=t['hp_after'],
                            damage=t.get('actual_damage', t['damage']),
                            damage_type=dmg_type,
                            modifiers=modifiers,
                            calc_detail=t.get('calc_detail'),
                            max_hp=max_hp,
                        )
                        continue

                    target_unit = self._find_unit(t)
                    max_hp = target_unit.max_hp if target_unit else t['hp_before']
                    hit_details = t.get("hits", [t.get('actual_damage', t['damage'])])
                    hit_crits = t.get("hit_crits", [t.get("crit")])
                    hit_evades = t.get("hit_evades", [])
                    hit_shield_list = t.get("hit_shield_absorbed", [])
                    hit_count = len(hit_details)
                    if hit_count > 1 and len(hit_crits) == hit_count:
                        running_hp = t['hp_before']
                        for i, hit_dmg in enumerate(hit_details):
                            hp_before_hit = running_hp
                            hit_shield = hit_shield_list[i] if i < len(hit_shield_list) else 0
                            is_evaded = hit_evades[i] if i < len(hit_evades) else False
                            if is_evaded:
                                modifiers = ["Miss"]
                                actual_hp_loss = 0
                            else:
                                actual_hp_loss = max(0, hit_dmg - hit_shield)
                                running_hp = max(0, running_hp - actual_hp_loss)
                                modifiers = []
                                if hit_crits[i]:
                                    modifiers.append("Critical")
                                if target_unit:
                                    target_elem = target_unit.element if hasattr(target_unit, 'element') else 0
                                    if self._is_element_advantage(caster.element, target_elem):
                                        modifiers.append("Effective")
                            self.narrative.damage(
                                attacker_name=caster_dname,
                                attacker_hp=f"HP:{caster.current_hp}/{caster.max_hp}",
                                target_name=self._get_display_name(t.get('target_id', t['target'])),
                                hp_before=hp_before_hit,
                                hp_after=running_hp,
                                damage=actual_hp_loss,
                                damage_type=dmg_type,
                                modifiers=modifiers,
                                shield_absorbed=hit_shield,
                                max_hp=max_hp,
                                calc_detail=t.get('calc_detail') if i == 0 else None,
                            )
                    else:
                        is_evaded = hit_evades[0] if hit_evades else False
                        if is_evaded:
                            modifiers = ["Miss"]
                        else:
                            modifiers = list(t.get("modifiers", []))
                            if t.get("crit"):
                                modifiers.append("Critical")
                            if target_unit:
                                target_elem = target_unit.element if hasattr(target_unit, 'element') else 0
                                if self._is_element_advantage(caster.element, target_elem):
                                    modifiers.append("Effective")
                        hit_shield = hit_shield_list[0] if hit_shield_list else t.get('shield_absorbed', 0)
                        self.narrative.damage(
                            attacker_name=caster_dname,
                            attacker_hp=f"HP:{caster.current_hp}/{caster.max_hp}",
                            target_name=self._get_display_name(t.get('target_id', t['target'])),
                            hp_before=t['hp_before'],
                            hp_after=t['hp_after'],
                            damage=t.get('actual_damage', t['damage']),
                            damage_type=dmg_type,
                            modifiers=modifiers,
                            shield_absorbed=hit_shield,
                            max_hp=max_hp,
                            calc_detail=t.get('calc_detail'),
                        )
                    # SubUnit吸收伤害叙事
                    for sa in t.get("sub_unit_absorbs", []):
                        target_dname = self._get_display_name(t.get('target_id', t['target']))
                        self.narrative.sub_unit_absorb(
                            target_dname, sa['sub_unit_name'], sa['absorbed'],
                            sa['sub_unit_hp_after'], sa['sub_unit_max_hp'])
                    # 护盾消失叙事（按次数/按攻击次数消耗的盾）
                    shield_expired = t.get("shield_expired")
                    if shield_expired:
                        target_dname = self._get_display_name(t.get('target_id', t['target']))
                        self.narrative.effect_expired(target_dname, shield_expired, is_debuff=False)
                # ダメージリンク転送叙事ログ出力
                for dl_transfer in applied.get("damage_link_transfers", []):
                    source_dname = self._get_display_name(dl_transfer["source_target_id"])
                    linker_dname = self._get_display_name(dl_transfer["linker_id"])
                    self.narrative.damage_link_transfer(
                        source_target_name=source_dname,
                        linker_name=linker_dname,
                        transfer_dmg=dl_transfer["transfer_dmg"],
                        hp_before=dl_transfer["hp_before"],
                        hp_after=dl_transfer["hp_after"],
                        max_hp=dl_transfer["max_hp"],
                        damage_type=dl_transfer["damage_type"],
                        link_value=dl_transfer["link_value"],
                        source_actual_damage=dl_transfer["source_actual_damage"],
                        shield_absorbed=dl_transfer["shield_absorbed"],
                    )
            elif applied.get("effect_type") == "heal":
                for h in applied.get("heals", []):
                    target_unit = self._find_unit(h)
                    target_max = target_unit.max_hp if target_unit else 0
                    hp_before_heal = h['hp_after'] - h['amount']
                    self.narrative.heal(
                        source_name=caster_dname,
                        source_hp=f"HP:{caster.current_hp}/{caster.max_hp}",
                        target_name=self._get_display_name(h.get('target_id', h['target'])),
                        hp_before=hp_before_heal,
                        amount=h['amount'],
                        target_max_hp=target_max,
                        is_crit=h.get('is_crit', False),
                        formula=h.get('heal_formula', ''),
                    )
            elif applied.get("effect_type") == "aura":
                for a in applied.get("auras", []):
                    target_unit = self._find_unit(a)
                    detail = a.get('detail', '')
                    if target_unit and not detail:
                        detail = self._get_buff_debuff_detail(target_unit, a['effect'])
                    target_dname = self._get_display_name(a.get('target_id', a['target']))
                    source_dname = self._get_display_name(a.get('source_id', a['source']))
                    if applied.get("is_debuff"):
                        self.narrative.debuff_applied(target_dname, a['effect'], source_dname, a.get('duration', 0), a.get('dur_type', 'turn'), detail)
                    else:
                        self.narrative.buff_applied(target_dname, a['effect'], source_dname, a.get('duration', 0), a.get('dur_type', 'turn'), detail)
                    # 眩晕打断蓄力叙事
                    if a.get("charge_cancelled"):
                        self.narrative.charge_cancelled(target_dname, a["charge_skill_name"], "眩晕")
                # 输出被免疫/闪避的debuff叙事
                for b in applied.get("blocked", []):
                    target_dname = self._get_display_name(b.get('target_id', b['target']))
                    source_dname = self._get_display_name(b.get('source_id', b['source']))
                    self.narrative.debuff_blocked(target_dname, b['effect'], source_dname, b.get('reason', 'debuff_immune'))
            elif applied.get("effect_type") == "hp_ratio_damage":
                for t in applied.get("targets", []):
                    target_unit = self._find_unit(t)
                    max_hp = target_unit.max_hp if target_unit else t.get('hp_before', 0)
                    target_dname = self._get_display_name(t.get('target_id', t['target']))
                    self.narrative.damage(
                        attacker_name=caster_dname,
                        attacker_hp=f"HP:{caster.current_hp}/{caster.max_hp}",
                        target_name=target_dname,
                        hp_before=t['hp_before'],
                        hp_after=t['hp_after'],
                        damage=t.get('actual_damage', t['damage']),
                        damage_type=dmg_type,
                        modifiers=["追加"],
                        shield_absorbed=t.get('shield_absorbed', 0),
                        max_hp=max_hp,
                    )
            elif applied.get("effect_type") == "damage_special":
                for t in applied.get("targets", []):
                    if isinstance(t, dict):
                        target_dname = self._get_display_name(t.get('target_id', t['target']))
                        target_unit = self._find_unit(t)
                        max_hp = target_unit.max_hp if target_unit else t.get('hp_before', 0)
                        if t.get('evaded'):
                            self.narrative.evade(target_dname, caster_dname)
                        else:
                            self.narrative.damage(
                                attacker_name=caster_dname,
                                attacker_hp=f"HP:{caster.current_hp}/{caster.max_hp}",
                                target_name=target_dname,
                                hp_before=t['hp_before'],
                                hp_after=t['hp_after'],
                                damage=t.get('actual_damage', t['damage']),
                                damage_type=dmg_type,
                                modifiers=["特殊"],
                                shield_absorbed=t.get('shield_absorbed', 0),
                                max_hp=max_hp,
                            )
            elif applied.get("effect_type") == "lifesteal":
                heal_amount = applied.get("heal_amount", 0)
                if heal_amount > 0:
                    self.narrative.lifesteal(
                        source_name=caster_dname,
                        heal_amount=heal_amount,
                        damage_based_on=applied.get("damage_based_on", 0),
                        hp_before=applied.get("hp_before", caster.current_hp - heal_amount),
                        hp_after=applied.get("hp_after", caster.current_hp),
                        max_hp=caster.max_hp,
                        cure_pct=applied.get("cure_pct", 0),
                    )
            elif applied.get("effect_type") == "add_fury":
                fc = applied.get("fury_count", 0)
                self.narrative.fury_add(self._get_display_name(caster), fc)
            elif applied.get("effect_type") == "add_status":
                for s in applied.get("statuses", []):
                    target_unit = self._find_unit(s)
                    detail = ""
                    if target_unit:
                        detail = self._get_buff_debuff_detail(target_unit, s['effect'])
                    target_dname = self._get_display_name(s.get('target_id', s['target']))
                    source_dname = self._get_display_name(s.get('source_id', s['source']))
                    if applied.get("is_debuff"):
                        self.narrative.debuff_applied(target_dname, s['effect'], source_dname, s.get('duration', 0), s.get('dur_type', 'turn'), detail)
                    else:
                        self.narrative.buff_applied(target_dname, s['effect'], source_dname, s.get('duration', 0), s.get('dur_type', 'turn'), detail)
                    # 眩晕打断蓄力叙事
                    if s.get("charge_cancelled"):
                        self.narrative.charge_cancelled(target_dname, s["charge_skill_name"], "眩晕")
            elif applied.get("effect_type") == "reset_cooldown":
                if applied.get("was_on_cd"):
                    sk_name = applied.get("skill_name", f"技能ID:{applied.get('skill_id', '?')}")
                    self.narrative.reset_cooldown(caster_dname, sk_name)
            elif applied.get("effect_type") == "remove_debuff":
                for rd in applied.get("removed_details", []):
                    target_dname = self._get_display_name(rd.get('target_id', rd.get('target')))
                    self.narrative.debuff_removed(target_dname, rd['removed_count'], rd['removed_names'], caster_dname)
            elif applied.get("effect_type") == "remove_buff":
                for rd in applied.get("removed_details", []):
                    target_dname = self._get_display_name(rd.get('target_id', rd.get('target')))
                    self.narrative.buff_removed(target_dname, rd['removed_count'], rd['removed_names'], caster_dname)
            elif applied.get("effect_type") == "remove_shield":
                for rd in applied.get("targets", []):
                    target_dname = self._get_display_name(rd.get('target_id', rd.get('target')))
                    self.narrative.shield_removed(target_dname, rd.get('removed_count', 0), rd.get('removed_names', []), caster_dname)
            elif applied.get("effect_type") == "remove_sub_unit":
                for rd in applied.get("targets", []):
                    target_dname = self._get_display_name(rd.get('target_id', rd.get('target')))
                    self.narrative.sub_unit_removed(target_dname, rd.get('removed_count', 0), rd.get('removed_names', []), caster_dname)
            elif applied.get("effect_type") == "sub_unit":
                for su in applied.get("targets", []):
                    target_dname = self._get_display_name(su.get('target_id', su.get('target')))
                    self.narrative.sub_unit_applied(
                        target_dname, su.get('sub_unit_name', 'SubUnit'),
                        su.get('sub_unit_hp', 0), su.get('sub_unit_max_hp', 0),
                        su.get('atk_dmg_pct', 0), su.get('duration', 1),
                        su.get('dur_type', 'action'), caster_dname)
            elif applied.get("effect_type") in ("add_ap", "add_ep", "remove_ap"):
                if not applied.get("skipped"):
                    rtype = applied["effect_type"]
                    if rtype == "add_ap":
                        ap_targets = applied.get("targets", [])
                        if ap_targets:
                            for at in ap_targets:
                                target_dname = self._get_display_name(at.get('target_id', at.get('target')))
                                self.narrative.resource_restore(target_dname, at['ap_after'], at['ap_max'])
                        else:
                            self.narrative.resource_restore(caster_dname, caster.current_ap, caster.initial_active_point)
                    elif rtype == "add_ep":
                        # add_ep 可能有多个目标，逐个显示
                        ep_targets = applied.get("targets", [])
                        if ep_targets:
                            for et in ep_targets:
                                target_dname = self._get_display_name(et.get('target_id', et.get('target')))
                                self.narrative.resource_restore_ep(
                                    target_dname, et['amount'], et['ep_after'], et['ep_max'])
                        else:
                            self.narrative.resource_restore_ep(caster_dname, 0, caster.current_ep, caster.max_extra_point)
                    elif rtype == "remove_ap":
                        ap_targets = applied.get("targets", [])
                        for at in ap_targets:
                            target_dname = self._get_display_name(at.get('target_id', at.get('target')))
                            cover_for = at.get('cover_replaced_for')
                            if cover_for:
                                self.narrative.ap_removed(target_dname, at['amount'], at['ap_after'], at['ap_max'], caster_dname, cover_for)
                            else:
                                self.narrative.ap_removed(target_dname, at['amount'], at['ap_after'], at['ap_max'], caster_dname)
            elif applied.get("effect_type") == "remove_pp":
                pp_targets = applied.get("targets", [])
                for pt in pp_targets:
                    target_dname = self._get_display_name(pt.get('target_id', pt.get('target')))
                    cover_for = pt.get('cover_replaced_for')
                    if cover_for:
                        self.narrative.pp_removed(target_dname, pt['amount'], pt['pp_after'], pt['pp_max'], caster_dname, cover_for)
                    else:
                        self.narrative.pp_removed(target_dname, pt['amount'], pt['pp_after'], pt['pp_max'], caster_dname)
            elif applied.get("effect_type") == "remove_ep":
                ep_targets = applied.get("targets", [])
                for et in ep_targets:
                    target_dname = self._get_display_name(et.get('target_id', et.get('target')))
                    cover_for = et.get('cover_replaced_for')
                    if cover_for:
                        self.narrative.ep_removed(target_dname, et['amount'], et['ep_after'], et['ep_max'], caster_dname, cover_for)
                    else:
                        self.narrative.ep_removed(target_dname, et['amount'], et['ep_after'], et['ep_max'], caster_dname)
            elif applied.get("effect_type") == "remove_mark":
                for rm in applied.get("targets", []):
                    target_dname = self._get_display_name(rm.get('target_id', rm.get('target')))
                    self.narrative.mark_removed(target_dname, rm['mark_name'], rm['removed_count'], caster_dname)

        for ps_result in skill_result.get("inline_ps_results", []):
            trigger_timing = ps_result.get("trigger_timing", "")
            # before_* 类型的PS已在伤害前输出，此处跳过
            if trigger_timing and trigger_timing.startswith("before_"):
                continue
            ps_owner = ps_result["owner"]
            ps_name = ps_result["skill_name"]
            ps_dname = self._get_display_name(ps_owner)

            if self.narrative:
                self.narrative.ps_trigger(ps_dname, ps_name, caster_dname)
                self.narrative.skill_prepare(ps_owner, ps_name, 2, ps_dname)

            for applied in ps_result["result"].get("effects_applied", []):
                self._log_narrative_aura_status(applied, ps_dname)

        self.narrative.skill_cast(caster_dname, primary_target, skill_name, skill_type)

        return damaged_targets

    def _log_narrative_aura_status(self, applied: dict, source_dname: str) -> None:
        """输出PS技能的aura/add_status效果日志"""
        if not self.narrative:
            return
        if applied.get("effect_type") == "aura":
            for a in applied.get("auras", []):
                target_unit = self._find_unit(a)
                target_dname = self._get_display_name(a.get('target_id', a['target']))
                detail = a.get('detail', '')
                if target_unit and not detail:
                    detail = self._get_buff_debuff_detail(target_unit, a['effect'])
                if applied.get("is_debuff"):
                    self.narrative.debuff_applied(target_dname, a['effect'], source_dname,
                                                a.get('duration', 0), a.get('dur_type', 'turn'), detail)
                else:
                    self.narrative.buff_applied(target_dname, a['effect'], source_dname,
                                               a.get('duration', 0), a.get('dur_type', 'turn'), detail)
        elif applied.get("effect_type") == "add_status":
            for s in applied.get("statuses", []):
                target_unit = self._find_unit(s)
                target_dname = self._get_display_name(s.get('target_id', s['target']))
                detail = s.get('detail', '')
                if target_unit and not detail:
                    detail = self._get_buff_debuff_detail(target_unit, s['effect'])
                if applied.get("is_debuff"):
                    self.narrative.debuff_applied(target_dname, s['effect'], source_dname,
                                                s.get('duration', 0), s.get('dur_type', 'turn'), detail)
                else:
                    self.narrative.buff_applied(target_dname, s['effect'], source_dname,
                                               s.get('duration', 0), s.get('dur_type', 'turn'), detail)

    _POSITION_BITMASK_MAP = {
        Position.ALLY_LEFT_FRONT: 1,
        Position.ALLY_CENTER_FRONT: 2,
        Position.ALLY_RIGHT_FRONT: 4,
        Position.ALLY_LEFT_BACK: 8,
        Position.ALLY_CENTER_BACK: 16,
        Position.ALLY_RIGHT_BACK: 32,
        Position.ENEMY_LEFT_FRONT: 1,
        Position.ENEMY_CENTER_FRONT: 2,
        Position.ENEMY_RIGHT_FRONT: 4,
        Position.ENEMY_LEFT_BACK: 8,
        Position.ENEMY_CENTER_BACK: 16,
        Position.ENEMY_RIGHT_BACK: 32,
    }

    def _apply_memory_card_effects(self) -> None:
        if not self.battlefield.memory_cards:
            return

        _log.info("[MEMORY] ============ 回忆卡效果处理 ============")

        for card in self.battlefield.memory_cards:
            card_name = getattr(card, 'name', f"回忆卡#{getattr(card, 'card_id', '?')}")
            _log.info("[MEMORY] 处理回忆卡: %s (ID=%d)", card_name,
                      getattr(card, 'card_id', 0))

            for highlight in card.highlights:
                skill_id = highlight.skill_master_id
                if not skill_id:
                    continue

                skill_name = self.data_loader.get_skill_name(skill_id)

                # 优先尝试结构化效果路径（新路径，从 memory_effects.json 读取）
                applied = self._apply_memory_card_structured_effect(
                    card_name, highlight, skill_id, skill_name,
                    expected_trigger="battle_start"
                )
                if applied:
                    continue

                # 检查是否有其他trigger类型的结构化数据，有则跳过旧路径
                effect_data = self.data_loader.get_memory_effect(skill_id)
                if effect_data:
                    other_trigger = effect_data.get("trigger", {}).get("type", "")
                    if other_trigger in ("turn_start", "turn_end", "periodic_start", "periodic_end"):
                        continue  # 由回合开始/结束逻辑处理，不走旧路径

                # 回退到旧路径（正则解析 + execute_skill）
                matched_units = self._resolve_memory_card_targets(highlight)
                if not matched_units:
                    _log.info("[MEMORY]   highlight skill=%d -> 无匹配单位", skill_id)
                    continue

                _log.info("[MEMORY]   skill=%d [%s] -> 旧路径 %d 个单位匹配",
                          skill_id, skill_name, len(matched_units))

                for target_unit in matched_units:
                    if not target_unit.is_alive:
                        continue

                    _log.info("[MEMORY]     -> %s (position=%s)", target_unit.name,
                              target_unit.position)

                    self.skill_service._is_memory_card_execution = True
                    skill_result = self.skill_service.execute_skill(
                        caster=target_unit,
                        skill_id=skill_id,
                        battlefield=self.battlefield,
                        skip_cost=True,
                    )
                    self.skill_service._is_memory_card_execution = False

                    if not skill_result.get("success"):
                        _log.info("[MEMORY]     skill=%d execute_skill failed: %s, trying direct effect",
                                  skill_id, skill_result.get("error", "unknown"))
                        self._apply_memory_card_direct_effect(card_name, target_unit, skill_id, skill_name)

                    if self.narrative and skill_result.get("success"):
                        self._log_memory_skill_effects(card_name, skill_name, target_unit, skill_result)

        _log.info("[MEMORY] ============ 回忆卡效果处理完成 ============")

    def _apply_memory_card_effects_by_trigger(self, trigger_type: str) -> None:
        """根据trigger类型应用回忆卡结构化效果（用于turn_start/turn_end/periodic_start/periodic_end）

        Args:
            trigger_type: 要处理的trigger类型（turn_start/turn_end/periodic_start/periodic_end）
        """
        if not self.battlefield.memory_cards:
            return

        _log.info("[MEMORY] ============ 回忆卡效果处理 (trigger=%s, turn=%d) ============",
                  trigger_type, self.battlefield.turn_number)

        for card in self.battlefield.memory_cards:
            card_name = getattr(card, 'name', f"回忆卡#{getattr(card, 'card_id', '?')}")

            for highlight in card.highlights:
                skill_id = highlight.skill_master_id
                if not skill_id:
                    continue

                skill_name = self.data_loader.get_skill_name(skill_id)

                # 只处理匹配trigger类型的结构化效果
                self._apply_memory_card_structured_effect(
                    card_name, highlight, skill_id, skill_name,
                    expected_trigger=trigger_type
                )

        _log.info("[MEMORY] ============ 回忆卡效果处理完成 (trigger=%s) ============", trigger_type)

    def _resolve_memory_card_targets(self, highlight) -> list:
        targets = []

        team = self.battlefield.friend_team if highlight.is_targeting_friendly_party else self.battlefield.enemy_team

        for unit in team:
            if not unit.is_alive:
                continue

            if not self._match_memory_card_unit(unit, highlight):
                continue

            targets.append(unit)

        return targets

    def _resolve_memory_card_targets_with_position(self, highlight,
                                                     block_party_position: int) -> list:
        """使用block级别的位置位掩码过滤目标

        与 _resolve_memory_card_targets 类似，但使用 block_party_position
        覆盖 highlight 的 party_position 进行位置过滤。
        用于"変動"类技能对不同位置施加不同效果。
        """
        targets = []

        team = self.battlefield.friend_team if highlight.is_targeting_friendly_party else self.battlefield.enemy_team

        for unit in team:
            if not unit.is_alive:
                continue

            # 复用highlight的其他过滤条件（角色/属性/队伍等），但位置过滤使用block级别
            if not self._match_memory_card_unit_with_position(unit, highlight, block_party_position):
                continue

            targets.append(unit)

        return targets

    def _match_memory_card_unit_with_position(self, unit: UnitState, highlight,
                                                block_party_position: int) -> bool:
        """与 _match_memory_card_unit 类似，但位置过滤使用 block_party_position"""
        if highlight.character_master_id is not None:
            if unit.character_id != highlight.character_master_id:
                return False

        if highlight.character_base_master_id is not None:
            char_data = self.data_loader.get_character(unit.character_id)
            if char_data:
                if char_data.character_base_id != highlight.character_base_master_id:
                    return False
            else:
                _log.info("[MEMORY]     无法获取角色数据 unit=%d, 跳过 base_master_id 检查", unit.character_id)
                return False

        if highlight.character_attribute is not None:
            if unit.element != highlight.character_attribute:
                return False

        if highlight.character_role is not None:
            if unit.role_type != highlight.character_role:
                return False

        if highlight.character_type is not None:
            if unit.character_type != highlight.character_type:
                return False

        if highlight.character_team_master_id is not None:
            if not self._check_character_team(unit, highlight.character_team_master_id):
                return False

        # 使用block级别的位置过滤
        pos_bit = self._POSITION_BITMASK_MAP.get(unit.position, 0)
        if pos_bit == 0 or (block_party_position & pos_bit) == 0:
            return False

        return True

    def _match_memory_card_unit(self, unit: UnitState, highlight) -> bool:
        if highlight.character_master_id is not None:
            if unit.character_id != highlight.character_master_id:
                return False

        if highlight.character_base_master_id is not None:
            char_data = self.data_loader.get_character(unit.character_id)
            if char_data:
                if char_data.character_base_id != highlight.character_base_master_id:
                    return False
            else:
                _log.info("[MEMORY]     无法获取角色数据 unit=%d, 跳过 base_master_id 检查", unit.character_id)
                return False

        if highlight.character_attribute is not None:
            if unit.element != highlight.character_attribute:
                return False

        if highlight.character_role is not None:
            if unit.role_type != highlight.character_role:
                return False

        if highlight.character_type is not None:
            if unit.character_type != highlight.character_type:
                return False

        if highlight.character_team_master_id is not None:
            if not self._check_character_team(unit, highlight.character_team_master_id):
                return False

        if highlight.party_position is not None:
            pos_bit = self._POSITION_BITMASK_MAP.get(unit.position, 0)
            if pos_bit == 0 or (highlight.party_position & pos_bit) == 0:
                return False

        return True

    def _check_character_team(self, unit: UnitState, team_master_id: int) -> bool:
        char_data = self.data_loader.get_character(unit.character_id)
        if not char_data:
            _log.info("[MEMORY]     团队检查: %s -> 团队%d(无角色数据, 不匹配)", unit.name, team_master_id)
            return False
        unit_team_id = self.data_loader.get_character_team_id(char_data.character_base_id)
        if unit_team_id is None:
            _log.info("[MEMORY]     团队检查: %s(base=%d) -> 团队%d(该角色无团队数据, 不匹配)",
                      unit.name, char_data.character_base_id, team_master_id)
            return False
        if unit_team_id == team_master_id:
            _log.info("[MEMORY]     团队检查: %s(base=%d) -> 团队%d(匹配)",
                      unit.name, char_data.character_base_id, team_master_id)
            return True
        _log.info("[MEMORY]     团队检查: %s(base=%d) -> 团队%d(角色团队=%d, 不匹配)",
                  unit.name, char_data.character_base_id, team_master_id, unit_team_id)
        return False

    def _log_memory_skill_effects(self, card_name: str, skill_name: str,
                                   target_unit: UnitState, skill_result: dict) -> None:
        target_dname = self._get_display_name(target_unit)

        for applied in skill_result.get("effects_applied", []):
            if applied.get("effect_type") == "heal":
                for h in applied.get("heals", []):
                    target_u = self._find_unit(h)
                    target_max = target_u.max_hp if target_u else 0
                    self.narrative.memory_effect(
                        card_name, target_dname,
                        f"回复 {h['amount']} HP (HP:{h['hp_after']}/{target_max})"
                    )
            elif applied.get("effect_type") == "aura":
                for a in applied.get("auras", []):
                    aura_target = self._find_unit(a)
                    detail = ""
                    if aura_target:
                        detail = self._get_buff_debuff_detail(aura_target, a['effect'])
                    aura_target_dname = self._get_display_name(a.get('target_id', a['target']))
                    effect_text = f"获得 «{a['effect']}»"
                    if a.get('duration', 0) > 0:
                        dur_type = a.get('dur_type', 'turn')
                        effect_text += f" 持续{a['duration']}{'行动' if dur_type == 'action' else '回合'}"
                    if detail:
                        effect_text += f" [{detail}]"
                    self.narrative.memory_effect(card_name, aura_target_dname, effect_text)
            elif applied.get("effect_type") == "add_status":
                for s in applied.get("statuses", []):
                    status_target = self._find_unit(s)
                    detail = ""
                    if status_target:
                        detail = self._get_buff_debuff_detail(status_target, s['effect'])
                    status_target_dname = self._get_display_name(s.get('target_id', s['target']))
                    effect_text = f"获得 «{s['effect']}»"
                    if s.get('duration', 0) > 0:
                        dur_type = s.get('dur_type', 'turn')
                        effect_text += f" 持续{s['duration']}{'行动' if dur_type == 'action' else '回合'}"
                    if detail:
                        effect_text += f" [{detail}]"
                    self.narrative.memory_effect(card_name, status_target_dname, effect_text)

    def _parse_memory_skill_value(self, skill_id: int, effect_type: str) -> tuple:
        desc = self.data_loader.get_skill_description(skill_id)
        if not desc:
            # Fallback: 从skills.json获取描述文本
            skill_data = self.data_loader.get_skill_by_id(skill_id)
            if skill_data and hasattr(skill_data, 'get_description_at_level'):
                desc = skill_data.get_description_at_level(1)
        if not desc:
            if effect_type == SkillEffectType.STATUS_MAX_HP.value:
                return 10.0, 0
            return 5.0, 0

        pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', desc)
        if pct_match:
            return float(pct_match.group(1)), 0

        fixed_match = re.search(r'(\d+)\s*(?:上昇|下降|低下)', desc)
        if fixed_match:
            return float(fixed_match.group(1)), 1

        if effect_type == SkillEffectType.STATUS_MAX_HP.value:
            return 10.0, 0
        return 5.0, 0

    def _apply_memory_card_structured_effect(self, card_name: str, highlight,
                                              skill_id: int, skill_name: str,
                                              expected_trigger: str = "battle_start") -> bool:
        """应用回忆卡结构化效果（新路径）

        从 memory_effects.json 读取结构化数据，独立施加效果，不经过 skill_service.execute_skill。

        Args:
            expected_trigger: 期望的trigger类型，只处理匹配的trigger

        Returns:
            True if 成功应用结构化效果；False if 无结构化数据需回退旧路径
        """
        effect_data = self.data_loader.get_memory_effect(skill_id)
        if not effect_data:
            return False  # 无结构化数据，回退到旧路径

        trigger = effect_data.get("trigger", {})
        trigger_type = trigger.get("type", "battle_start")

        # 只处理匹配的trigger类型
        if trigger_type != expected_trigger:
            return False  # 不匹配，不处理也不回退（由调用方决定）

        # 周期触发检查：判断当前回合是否是触发周期
        if trigger_type in ("periodic_start", "periodic_end"):
            periodic_turn = trigger.get("periodic_turn", 1)
            if self.battlefield.turn_number % periodic_turn != 0:
                return True  # 本回合不触发，但算作已处理（不回退旧路径）

        blocks = effect_data.get("blocks", [])
        if not blocks:
            _log.info("[MEMORY]     skill=%d 无blocks定义，回退旧路径", skill_id)
            return False

        _log.info("[MEMORY]   skill=%d [%s] -> 结构化路径 (trigger=%s)", skill_id, skill_name, trigger_type)

        for block in blocks:
            target_type = block.get("target_type", "highlight_targets")
            effects = block.get("effects", [])
            block_party_position = block.get("party_position")

            targets = self._select_memory_card_targets(highlight, target_type, block_party_position)
            if not targets:
                _log.info("[MEMORY]     target_type=%s 无匹配单位", target_type)
                continue

            _log.info("[MEMORY]     target_type=%s -> %d 个单位", target_type, len(targets))

            for target_unit in targets:
                if not target_unit.is_alive:
                    continue
                _log.info("[MEMORY]       -> %s (position=%s)", target_unit.name, target_unit.position)
                for effect in effects:
                    self._apply_structured_effect_to_unit(
                        card_name, target_unit, skill_id, skill_name, effect
                    )

        return True

    def _select_memory_card_targets(self, highlight, target_type: str,
                                      block_party_position: int = None) -> list:
        """根据 target_type 选取目标单位

        highlight_targets / ally_position / enemy_position 使用 highlight 条件过滤；
        其他类型按描述语义直接选取。

        Args:
            block_party_position: block级别的位置位掩码，当target_type=ally_position且
                                  此值不为None时，覆盖highlight的party_position进行位置过滤。
                                  用于"変動"类技能对不同位置施加不同效果。
        """
        if target_type in ("highlight_targets", "ally_position", "enemy_position"):
            if block_party_position is not None and target_type == "ally_position":
                return self._resolve_memory_card_targets_with_position(
                    highlight, block_party_position
                )
            return self._resolve_memory_card_targets(highlight)

        if target_type == "ally_all":
            return [u for u in self.battlefield.friend_team if u.is_alive]

        if target_type == "ally_front_row":
            front = {Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT, Position.ALLY_RIGHT_FRONT}
            return [u for u in self.battlefield.friend_team if u.is_alive and u.position in front]

        if target_type == "ally_back_row":
            back = {Position.ALLY_LEFT_BACK, Position.ALLY_CENTER_BACK, Position.ALLY_RIGHT_BACK}
            return [u for u in self.battlefield.friend_team if u.is_alive and u.position in back]

        if target_type == "enemy_front_row":
            front = {Position.ENEMY_LEFT_FRONT, Position.ENEMY_CENTER_FRONT, Position.ENEMY_RIGHT_FRONT}
            return [u for u in self.battlefield.enemy_team if u.is_alive and u.position in front]

        if target_type == "enemy_back_row":
            back = {Position.ENEMY_LEFT_BACK, Position.ENEMY_CENTER_BACK, Position.ENEMY_RIGHT_BACK}
            return [u for u in self.battlefield.enemy_team if u.is_alive and u.position in back]

        # 动态单目标选取
        enemies = [u for u in self.battlefield.enemy_team if u.is_alive]
        if not enemies:
            return []

        if target_type == "enemy_single_highest_hp":
            return [max(enemies, key=lambda u: u.max_hp)]
        if target_type == "enemy_single_lowest_hp":
            return [min(enemies, key=lambda u: u.max_hp)]
        if target_type == "enemy_single_highest_atk":
            return [max(enemies, key=lambda u: u.attack)]
        if target_type == "enemy_single_highest_spd":
            return [max(enemies, key=lambda u: u.speed)]
        if target_type == "enemy_single_lowest_hp_ratio":
            return [min(enemies, key=lambda u: (u.current_hp / u.max_hp) if u.max_hp > 0 else 0)]
        if target_type == "enemy_single_highest_ep":
            return [max(enemies, key=lambda u: u.current_ep)]

        # 未知 target_type，回退到 highlight 条件
        _log.info("[MEMORY]     未知 target_type=%s，回退 highlight_targets", target_type)
        return self._resolve_memory_card_targets(highlight)

    def _apply_structured_effect_to_unit(self, card_name: str, target_unit: UnitState,
                                          skill_id: int, skill_name: str, effect: dict) -> None:
        """对单个单位施加一个结构化效果"""
        effect_type = effect.get("effect_type")
        value = effect.get("value", 0)
        value_tag = effect.get("value_tag", 0)
        is_buff = effect.get("is_buff", True)
        duration = effect.get("duration", -1)
        timing_type = effect.get("timing_type", 3)
        damage_element = effect.get("damage_element", 0)
        value_source = effect.get("value_source", "")
        attack_limited = effect.get("attack_limited", 0)

        # AcquireMark 类型：获得mark标记
        if effect_type == "AcquireMark":
            mark_name = effect.get("mark_name", "")
            if not mark_name:
                _log.info("[MEMORY]       AcquireMark 缺少 mark_name，跳过")
                return
            mark_buff = BuffState(
                buff_id=f"memory_{skill_id}_{target_unit.unit_id}_{mark_name}",
                name=mark_name,
                effect_type=SkillEffectType.MARK.value,
                value=0,
                duration=-1,
                timing_type=3,
                stack_count=1,
                source_unit_id=target_unit.unit_id,
                is_debuff=False,
                is_memory_buff=True,
            )
            success = self.aura_service.add_aura(target_unit, mark_buff)
            _log.info("[MEMORY]       acquire_mark: %s -> %s mark=%s ok=%s",
                      card_name, target_unit.name, mark_name, success)
            if self.narrative:
                target_dname = self._get_display_name(target_unit)
                self.narrative.memory_effect(card_name, target_dname, f"获得标记「{mark_name}」")
            return

        # Heal 类型：直接治疗，不创建 buff
        if effect_type == SkillEffectType.HEAL.value:
            heal_amount = self._calculate_memory_heal(target_unit, value, value_tag, value_source)
            if heal_amount > 0:
                actual_heal = min(heal_amount, target_unit.max_hp - target_unit.current_hp)
                target_unit.current_hp += actual_heal
                _log.info("[MEMORY]       heal: %s -> %s val=%d (actual=%d)",
                          card_name, target_unit.name, heal_amount, actual_heal)
                if self.narrative:
                    target_dname = self._get_display_name(target_unit)
                    self.narrative.memory_effect(card_name, target_dname, f"HP回复 {actual_heal}")
            return

        # buff/debuff 类型：创建 BuffState 施加
        is_debuff = not is_buff
        final_value = -abs(value) if is_debuff else abs(value)

        buff = BuffState(
            buff_id=f"memory_{skill_id}_{target_unit.unit_id}",
            name=skill_name,
            effect_type=effect_type,
            value=final_value,
            duration=duration,
            timing_type=timing_type,
            stack_count=1,
            value_tag=value_tag,
            source_unit_id=target_unit.unit_id,
            is_debuff=is_debuff,
            is_memory_buff=True,
            damage_element=damage_element,
            attack_limited=attack_limited,
        )

        success = self.aura_service.add_aura(target_unit, buff)

        if value_tag == 1:
            _log.info("[MEMORY]       structured: %s -> %s type=%s val=%d(fixed) buff=%s ok=%s",
                      card_name, target_unit.name, effect_type, int(abs(final_value)), is_buff, success)
        else:
            _log.info("[MEMORY]       structured: %s -> %s type=%s val=%.1f%% buff=%s ok=%s",
                      card_name, target_unit.name, effect_type, abs(final_value), is_buff, success)

        if self.narrative:
            target_dname = self._get_display_name(target_unit)
            effect_label = "减益" if is_debuff else "增益"
            self.narrative.memory_effect(card_name, target_dname,
                                         f"获得 «{skill_name}» [{effect_label}]")

    def _calculate_memory_heal(self, target_unit: UnitState, value: float,
                                value_tag: int, value_source: str) -> int:
        """计算回忆卡治疗量"""
        if value_source == "target_max_hp":
            # 基于目标最大HP的百分比治疗（如"最大HPの10.5%回復"）
            return int(target_unit.max_hp * value / 100)
        if value_tag == 0:
            # 百分比治疗（基于最大HP）
            return int(target_unit.max_hp * value / 100)
        # 固定值治疗
        return int(value)

    def _apply_memory_card_direct_effect(self, card_name: str, target_unit: UnitState,
                                          skill_id: int, skill_name: str) -> None:
        name = skill_name
        skill_kind = 0
        skill_data = self.data_loader.get_skill_by_id(skill_id)
        if skill_data:
            skill_kind = skill_data.skill_kind

        is_debuff = skill_kind == 3
        if skill_kind == 0:
            if "減少" in name or "ダウン" in name:
                is_debuff = True
            elif "上昇" in name or "アップ" in name:
                is_debuff = False

        effect_type = self._infer_memory_effect_type(name)
        if not effect_type:
            _log.info("[MEMORY]     skill=%d effect_type unknown for '%s'", skill_id, name)
            return

        buff_value, value_tag = self._parse_memory_skill_value(skill_id, effect_type)

        # 判断DealtDamage的属性过滤
        damage_element = 0  # 0=全属性
        if effect_type == SkillEffectType.DEALT_DAMAGE.value:
            if "物理" in name:
                damage_element = 1  # 仅物理
            elif "EN" in name or "エナジー" in name:
                damage_element = 2  # 仅能量

        buff_duration = -1  # 永续buff，不随时间衰减

        delayed_turn = 0
        if "3T開始" in name:
            delayed_turn = 3
            _log.info("[MEMORY]     skill=%d delayed activation: turn %d", skill_id, delayed_turn)
        elif "4T終了" in name:
            _log.info("[MEMORY]     skill=%d periodic heal, turn 4 only", skill_id)

        final_value = -buff_value if is_debuff else buff_value

        buff = BuffState(
            buff_id=f"memory_{skill_id}_{target_unit.unit_id}",
            name=skill_name,
            effect_type=effect_type,
            value=final_value,
            duration=buff_duration,
            timing_type=3,  # DURABLE_SOURCE_MANEUVER_END: 永续buff，随施法者行动结束计时
            stack_count=1,
            value_tag=value_tag,
            source_unit_id=target_unit.unit_id,
            is_debuff=is_debuff,
            is_memory_buff=True,
            damage_element=damage_element,
        )

        success = self.aura_service.add_aura(target_unit, buff)

        if value_tag == 1:
            _log.info("[MEMORY]     direct effect: %s -> %s type=%s val=%d(fixed) debuff=%s ok=%s",
                      card_name, target_unit.name, effect_type, int(abs(final_value)), is_debuff, success)
        else:
            _log.info("[MEMORY]     direct effect: %s -> %s type=%s val=%.1f%% debuff=%s ok=%s",
                      card_name, target_unit.name, effect_type, abs(final_value), is_debuff, success)

        if self.narrative:
            target_dname = self._get_display_name(target_unit)
            effect_label = "减益" if is_debuff else "增益"
            self.narrative.memory_effect(card_name, target_dname,
                                         f"获得 «{skill_name}» [{effect_label}]")

    def _infer_memory_effect_type(self, skill_name: str) -> Optional[str]:
        if "攻撃" in skill_name:
            return SkillEffectType.STATUS_ATTACK.value
        elif "防御" in skill_name:
            return SkillEffectType.STATUS_DEFENSE.value
        elif "速度" in skill_name or "素早さ" in skill_name:
            return SkillEffectType.STATUS_SPEED.value
        elif "HP" in skill_name:
            return SkillEffectType.STATUS_MAX_HP.value
        elif "会心率" in skill_name:
            return SkillEffectType.STATUS_CRITICAL_CHANCE.value
        elif "会心ダメージ" in skill_name or "クリティカルダメージ" in skill_name:
            return SkillEffectType.CRITICAL_BONUS_MODIFICATION.value
        elif "与ダメージ" in skill_name:
            return SkillEffectType.DEALT_DAMAGE.value
        elif "物理ダメージ" in skill_name or "ENダメージ" in skill_name:
            return SkillEffectType.DEALT_DAMAGE.value
        elif "ダメージ" in skill_name:
            return SkillEffectType.DEALT_DAMAGE.value
        elif "回復量" in skill_name:
            return SkillEffectType.RECEIVED_HEALING.value
        elif "回復" in skill_name:
            return SkillEffectType.HEAL.value
        return None

    def _can_act(self, unit: UnitState) -> bool:
        if not unit.is_alive:
            return False
        if unit.is_stunned or unit.is_frozen:
            return False
        return True

    def _execute_standby(self, unit: UnitState) -> None:
        unit.action_phase = UnitActionPhase.STANDBY
        _log.info("[ACT]   %s 待机", unit.name)
        if unit.current_ap > 0:
            self.resource_service.consume_ap(unit, 1)
        elif unit.max_extra_point > 0 and unit.current_ep > 0:
            # AP=0且因眩晕而待机时，清空所有EP（冻结不清空EP，只待机）
            if unit.is_stunned:
                ep_before = unit.current_ep
                self.resource_service.consume_ep(unit, ep_before)
                _log.info("[STANDBY] %s AP=0 + 眩晕, EP清空: %d -> 0", unit.name, ep_before)
            elif unit.is_frozen:
                _log.info("[STANDBY] %s AP=0 + 冻结, EP不变: %d (冻结不清空EP)", unit.name, unit.current_ep)
            else:
                _log.info("[STANDBY] %s AP=0 (非眩晕/冻结), EP不变: %d", unit.name, unit.current_ep)
        unit.action_phase = UnitActionPhase.IDLE

    def _check_battle_end(self) -> bool:
        alive_friends = [u for u in self.battlefield.friend_team if u.is_alive]
        alive_enemies = [u for u in self.battlefield.enemy_team if u.is_alive]

        if not alive_friends:
            _log.info("[BATTLE] ============ 战斗结束：我方全灭 ============")
            return True
        if not alive_enemies:
            _log.info("[BATTLE] ============ 战斗结束：敌方全灭 ============")
            return True
        return False

    def _build_display_names(self) -> None:
        all_units = self.battlefield.get_all_units()
        self._unit_id_map = {u.unit_id: u for u in all_units}
        name_counts: Dict[str, int] = {}
        for u in all_units:
            name_counts[u.name] = name_counts.get(u.name, 0) + 1
        from .battle_narrative import POSITION_DISPLAY
        name_indices: Dict[str, int] = {}
        for u in all_units:
            if name_counts.get(u.name, 1) > 1:
                pos_str = POSITION_DISPLAY.get(u.position, "?")
                self._unit_display_names[u.unit_id] = f"{u.name}({pos_str})"
            else:
                self._unit_display_names[u.unit_id] = u.name

    def _get_display_name(self, target_id_or_unit: Any) -> str:
        if isinstance(target_id_or_unit, UnitState):
            uid = target_id_or_unit.unit_id
        elif isinstance(target_id_or_unit, str):
            uid = target_id_or_unit
            if uid in self._unit_id_map:
                unit = self._unit_id_map[uid]
                return self._unit_display_names.get(uid, unit.name)
        else:
            return str(target_id_or_unit)
        return self._unit_display_names.get(uid, str(target_id_or_unit))

    def _find_unit(self, target_dict_or_name: Any) -> Optional[UnitState]:
        if isinstance(target_dict_or_name, dict):
            target_id = target_dict_or_name.get('target_id')
            if target_id and target_id in self._unit_id_map:
                return self._unit_id_map[target_id]
            target_name = target_dict_or_name.get('target', target_dict_or_name)
        else:
            target_name = target_dict_or_name
        return next((u for u in self.battlefield.get_all_units() if u.name == target_name), None)

    def _restore_ap_pp_for_all(self):
        for unit in self.battlefield.friend_team + self.battlefield.enemy_team:
            if not unit.is_alive:
                continue
            self.resource_service.restore_ap_pp(unit)

    def _generate_ep_for_all(self):
        for unit in self.battlefield.friend_team + self.battlefield.enemy_team:
            if not unit.is_alive:
                continue
            if unit.max_extra_point > 0:
                self.resource_service.generate_ep(unit, 1)
                _log.info("[EP] %s generate_ep: %d/%d", unit.name, unit.current_ep, unit.max_extra_point)

    def _process_aura_expiry(self, unit: UnitState):
        if not unit.is_alive:
            return
        # 记录递减前存活的buff/debuff（用于过期叙事日志）
        prev_alive = {}
        for b in unit.buffs:
            if b.duration > 0:
                prev_alive[id(b)] = (b, "buff", b.effect_type)
        for b in unit.debuffs:
            if b.duration > 0:
                prev_alive[id(b)] = (b, "debuff", b.effect_type)
        # narrative日志：输出duration变化（just_applied的buff跳过，不递减也不输出）
        if self.narrative:
            for b in unit.buffs:
                if b.duration > 0 and not (getattr(b, 'just_applied', False) and not getattr(b, 'skip_restore', False)):
                    dur_after = b.duration - 1
                    if dur_after > 0:
                        dur_type = "action" if b.timing_type == AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value else "turn"
                        self.narrative.effect_update(unit.name, b.effect_type, dur_after, dur_type)
            for b in unit.debuffs:
                if b.duration > 0 and not (getattr(b, 'just_applied', False) and not getattr(b, 'skip_restore', False)):
                    dur_after = b.duration - 1
                    if dur_after > 0:
                        dur_type = "action" if b.timing_type == AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value else "turn"
                        self.narrative.effect_update(unit.name, b.effect_type, dur_after, dur_type)
        # process_maneuver_end 内部跳过 just_applied 的buff
        self.aura_service.process_maneuver_end(unit)
        # 施法者行动结束时，递减其他单位上由该施法者施加的DURABLE_SOURCE_MANEUVER_END buff
        _other_units_buff_ids_before = {}
        if self.narrative:
            for u in self.battlefield.get_all_units():
                if u.unit_id != unit.unit_id and u.is_alive:
                    _other_units_buff_ids_before[u.unit_id] = set()
                    for b in u.buffs + u.debuffs:
                        if hasattr(b, 'buff_id'):
                            _other_units_buff_ids_before[u.unit_id].add((id(b), b.effect_type, getattr(b, 'is_debuff', False)))
        self.aura_service.process_source_maneuver_end(unit, self.battlefield.get_all_units())
        if self.narrative:
            for u in self.battlefield.get_all_units():
                if u.unit_id == unit.unit_id or not u.is_alive:
                    continue
                before_set = _other_units_buff_ids_before.get(u.unit_id, set())
                curr_ids = set(id(b) for b in u.buffs + u.debuffs)
                for bid, etype, is_debuff in before_set:
                    if bid not in curr_ids:
                        self.narrative.effect_expired(u.name, etype, is_debuff=is_debuff)
        # 衰减型盾
        decay_details = self.aura_service.process_shield_decay(unit)
        if decay_details and self.narrative:
            display_name = self._get_display_name(unit)
            for buff_name, reduction, old_amt, new_amt, initial, expired in decay_details:
                self.narrative.shield_decay(
                    display_name, buff_name, reduction, old_amt, new_amt, initial, expired
                )
        # 过期叙事日志
        for buff_obj, kind, etype in prev_alive.values():
            if buff_obj.duration <= 0:
                if self.narrative:
                    if etype == "SubUnit":
                        self.narrative.sub_unit_expired(unit.name, getattr(buff_obj, 'name', 'SubUnit'))
                    else:
                        self.narrative.effect_expired(unit.name, etype, is_debuff=(kind == "debuff"))
        # 清除 just_applied 标记（所有单位）
        for u in self.battlefield.get_all_units():
            for b in u.buffs + u.debuffs:
                b.just_applied = False
        # 统一清理已过期的buff/debuff
        self.aura_service.check_expiration(unit, self.battlefield.get_all_units())

    def _log(self, message: str) -> None:
        _log.info(message)

    def _get_buff_debuff_detail(self, unit: UnitState, effect: str) -> str:
        # Check if this is a carried_debuff payload - show payload info instead of stat change
        if effect in ("spd_up", "spd_down", "StatusSpeed", "speed"):
            for b in unit.buffs + unit.debuffs:
                if b.effect_type == SkillEffectType.STATUS_SPEED.value and getattr(b, 'hit_limited_flags', {}).get('carried_debuff'):
                    payload_val = b.hit_limited_flags.get('carried_debuff_value', 0)
                    return f"携带式减速载荷(SPD-{int(payload_val)})"

        atk_related = {"atk_up", "atk_down", "StatusAttack", "attack"}
        def_related = {"def_up", "def_down", "StatusDefense", "defense"}
        spd_related = {"spd_up", "spd_down", "StatusSpeed", "speed"}
        dealt_related = {"dmg_dealt_up", "dmg_dealt_down", "DealtDamage"}
        taken_related = {"dmg_taken_up", "dmg_taken_down", "ReceivedDamage"}

        if effect in atk_related:
            final_atk = self.damage_service._calculate_final_stat(unit, "attack")
            return f"ATK→{final_atk}"
        elif effect in def_related:
            final_def = self.damage_service._calculate_final_stat(unit, "defense")
            return f"DEF→{final_def}"
        elif effect in spd_related:
            final_spd = self.damage_service._calculate_final_stat(unit, "speed")
            return f"SPD→{final_spd}"
        elif effect in dealt_related:
            total = 0.0
            for b in unit.buffs:
                if b.effect_type == SkillEffectType.DEALT_DAMAGE.value:
                    total += self.damage_service._normalize_buff_value(b)
            for b in unit.debuffs:
                if b.effect_type == SkillEffectType.DEALT_DAMAGE.value:
                    total -= self.damage_service._normalize_buff_value(b)
            pct = int(total * 100)
            sign = "+" if pct >= 0 else ""
            return f"造成伤害{sign}{pct}%"
        elif effect in taken_related:
            total = 0.0
            for b in unit.buffs:
                if b.effect_type == SkillEffectType.RECEIVED_DAMAGE.value:
                    total -= self.damage_service._normalize_buff_value(b)  # buffs (dmg_taken_down) REDUCE damage
            for b in unit.debuffs:
                if b.effect_type == SkillEffectType.RECEIVED_DAMAGE.value:
                    total += self.damage_service._normalize_buff_value(b)  # debuffs (dmg_taken_up) INCREASE damage
            pct = int(total * 100)
            sign = "+" if pct >= 0 else ""
            return f"受到伤害{sign}{pct}%"
        elif effect == SkillEffectType.STATUS_CRITICAL_CHANCE.value:
            # 使用与计算一致的_calculate_crit_rate，而非简单求和
            total = self.damage_service._calculate_crit_rate(unit)
            return f"暴击率→{total * 100:.1f}%"
        elif effect == SkillEffectType.CRITICAL_BONUS_MODIFICATION.value:
            total = 1.5 + self.damage_service._get_crit_damage_bonus(unit)
            return f"暴击伤害→{total * 100:.2f}%"
        return ""