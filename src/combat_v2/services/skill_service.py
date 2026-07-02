#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
技能服务 v2
src/combat_v2/services/skill_service.py

负责:
- 技能消耗检查与扣除
- 技能效果执行 (集成 Target/Damage/Aura/Status 服务)
- 技能冷却管理
- 技能选择 AI
"""

import random
from typing import Dict, Any, Optional, List, Callable
from ...entities_v2.unit_state import UnitState, BuffState
from ...entities_v2.battlefield_state import BattlefieldState
from ...entities_v2.enums import SkillEffectType, AuraUpdateTiming, Position
from ..skill_data_resolver import ResolvedSkillData, SkillDataResolver
from ..battle_logger import battle_logger
from .damage_service import DamageResult

_log = battle_logger()

_POS_RC = {
    Position.ALLY_LEFT_FRONT: (0, 0), Position.ALLY_CENTER_FRONT: (0, 1), Position.ALLY_RIGHT_FRONT: (0, 2),
    Position.ALLY_LEFT_BACK: (1, 0), Position.ALLY_CENTER_BACK: (1, 1), Position.ALLY_RIGHT_BACK: (1, 2),
    Position.ENEMY_LEFT_FRONT: (0, 0), Position.ENEMY_CENTER_FRONT: (0, 1), Position.ENEMY_RIGHT_FRONT: (0, 2),
    Position.ENEMY_LEFT_BACK: (1, 0), Position.ENEMY_CENTER_BACK: (1, 1), Position.ENEMY_RIGHT_BACK: (1, 2),
}

_MASTERDATA_STATUS_MAP = {
    "burn": SkillEffectType.CONFLAGRATION.value,
    "stun": SkillEffectType.KNOCKOUT.value,
    "poison": SkillEffectType.POISON.value,
    "freeze": SkillEffectType.FREEZE.value,
    "凍結": SkillEffectType.FREEZE.value,
    "knockout": SkillEffectType.KNOCKOUT.value,
    "confusion": SkillEffectType.CONFUSION.value,
    "混乱": SkillEffectType.CONFUSION.value,
    "mark": SkillEffectType.MARK.value,
    "good_luck": "good_luck",
    "action_damage": SkillEffectType.ACTION_DAMAGE.value,
    "dmg": SkillEffectType.ACTION_DAMAGE.value,
    "genwaku": SkillEffectType.GENWAKU.value,
}

_JSON_EFFECT_TO_ENUM: Dict[str, str] = {
    "atk_up": SkillEffectType.STATUS_ATTACK.value,
    "atk_down": SkillEffectType.STATUS_ATTACK.value,
    "def_up": SkillEffectType.STATUS_DEFENSE.value,
    "def_down": SkillEffectType.STATUS_DEFENSE.value,
    "spd_up": SkillEffectType.STATUS_SPEED.value,
    "spd_down": SkillEffectType.STATUS_SPEED.value,
    "crit_rate_up": SkillEffectType.STATUS_CRITICAL_CHANCE.value,
    "crit_rate_down": SkillEffectType.STATUS_CRITICAL_CHANCE.value,
    "crit_dmg_up": SkillEffectType.CRITICAL_BONUS_MODIFICATION.value,
    "crit_dmg_down": SkillEffectType.CRITICAL_BONUS_MODIFICATION.value,
    "dmg_dealt_up": SkillEffectType.DEALT_DAMAGE.value,
    "dmg_dealt_down": SkillEffectType.DEALT_DAMAGE.value,
    "dmg_taken_up": SkillEffectType.RECEIVED_DAMAGE.value,
    "dmg_taken_down": SkillEffectType.RECEIVED_DAMAGE.value,
    "heal_efficacy_up": SkillEffectType.RECEIVED_HEALING.value,
    "max_hp_up": SkillEffectType.STATUS_MAX_HP.value,
    "add_max_ap": SkillEffectType.STATUS_MAX_AP.value,
    "shield": SkillEffectType.SHIELD.value,
    "guard": SkillEffectType.GUARD.value,
    "perfect_evasion": SkillEffectType.EVADE.value,
    "ignore_defense": SkillEffectType.PENETRATE_DEFENSE.value,
    "ignore_shield": SkillEffectType.SURE_HIT.value,
    "sure_hit": SkillEffectType.SURE_HIT.value,
    "add_damage_to_attack": SkillEffectType.ENCHANT_DAMAGE.value,
    "counter_stance": SkillEffectType.ENCHANT_DAMAGE.value,
    "poison": SkillEffectType.POISON.value,
    "cover": SkillEffectType.INTERCEPT.value,
    "heal_over_time": SkillEffectType.HEAL_OVER_TIME.value,
    "critical_forbidden": SkillEffectType.CRITICAL_FORBIDDEN.value,
    "sub_unit": SkillEffectType.SUB_UNIT.value,
    "dmg_invulnerable": SkillEffectType.DMG_INVULNERABLE.value,
    "block_specific_aura": SkillEffectType.BLOCK_SPECIFIC_AURA.value,
    "ep_gain_down": SkillEffectType.EP_GAIN_DOWN.value,
    "modify_pp": SkillEffectType.MODIFY_PP.value,
}


def _eval_block_condition(value, op: str, target) -> bool:
    if op == '==':
        return value == target
    if op == '!=':
        return value != target
    if op == '>':
        return value > target
    if op == '>=':
        return value >= target
    if op == '<':
        return value < target
    if op == '<=':
        return value <= target
    return False


class SkillService:

    def __init__(self, data_loader, resource_service,
                 target_service=None, damage_service=None,
                 aura_service=None, status_service=None,
                 trigger_service=None):
        self.data_loader = data_loader
        self.resource_service = resource_service
        self.target_service = target_service
        self.damage_service = damage_service
        self.aura_service = aura_service
        self.status_service = status_service
        self.trigger_service = trigger_service
        self._resolver = SkillDataResolver(data_loader)

        self._battlefield: Optional[BattlefieldState] = None
        self._recursion_guard: bool = False
        self._before_attack_triggers_fired: bool = False  # 同一技能内只触发一次before_attack触发器
        self._on_crit_blocks: list = []
        self._on_crit_applied: bool = False  # 兼容标志：整个on_crit处理是否已触发
        self._on_crit_block_executed: dict = {}  # 记录once_per_skill=true的block是否已执行
        self._on_crit_target = None  # 当前暴击目标，供crit_target target_type使用
        self._on_crit_immediate_blocks: list = []  # 即时on_crit blocks（aura效果），在hit循环中通过callback施加
        self._on_crit_immediate_applied: set = set()  # 已施加即时on_crit效果的目标unit_id集合
        self._on_crit_effects: list = []  # 收集on_crit块的效果结果
        self._deferred_on_crit_targets: list = []  # 延迟执行的on_crit目标列表
        self._block_damage_targets = None
        self._prev_block_damage_targets = {}
        self._block_damage_total: Dict[int, int] = {}  # block_id -> 该block内累计伤害总和 (供 split_heal_by_damage 读取)
        self._current_block_id: int = 0  # 当前正在执行的 block_id
        self._current_attack_targets: List[UnitState] = []  # 当前AS技能攻击的所有目标（用于PS cover效果选择）
        self._current_skill_id: int = 0
        self._trigger_total_damage: int = 0  # 触发PS的技能总伤害（用于total_damage_le条件）
        self._current_skill_priority: Optional[int] = None
        self._last_damage_hp_before: Dict[str, int] = {}
        self._newly_created_sub_unit_ids: set = set()  # SubUnit buff_ids created in current skill, skip their first attack
        self._inline_ps_results: list = []
        self._debuffs_applied_this_skill: set = set()
        self._is_memory_card_execution: bool = False
        self._pending_deaths: set = set()  # 延迟阵亡判定：技能结算完成后统一处理
        self._tactical_exercise_mode: bool = False  # 战术演习模式：敌人会复活，target_survived使用is_alive判断
        self._skill_name_cache: Dict[int, str] = {}  # skill_id -> name cache
        self._branch_override_func: Optional[Callable[[Dict], int]] = None  # 分支选择覆盖函数
        self._pending_crit_triggers: list = []  # 待处理的暴击触发器（_execute_trigger_actions_inline 直接调用时使用）

    def _get_skill_name(self, skill_id: int) -> str:
        """获取技能名称（带缓存）"""
        if skill_id in self._skill_name_cache:
            return self._skill_name_cache[skill_id]
        try:
            sd = self.data_loader.get_skill_by_id(skill_id)
            name = getattr(sd, 'name', '') or ''
        except Exception:
            name = ''
        self._skill_name_cache[skill_id] = name
        return name

    def _resolve_tag_value_for_caster(self, caster: UnitState, effect, tag_name: str):
        """解析指定tag的数值（基于当前技能等级）"""
        if not tag_name or not hasattr(self, '_resolver') or not self._resolver:
            return None
        skill_id = getattr(self, '_current_skill_id', 0) or 0
        if not skill_id:
            return None
        _skill_level = caster.skill_levels.get(skill_id, 1)
        meta = self.data_loader.get_skill_by_id(skill_id)
        if not meta:
            return None
        try:
            tag_values = self._resolver._resolve_template_tags(meta, _skill_level)
            resolved = tag_values.get(tag_name)
            return float(resolved) if resolved is not None else None
        except Exception:
            return None

    def set_battlefield(self, battlefield: BattlefieldState):
        self._battlefield = battlefield

    def set_branch_override(self, func: Optional[Callable[[Dict], int]]):
        """设置分支选择覆盖函数。func接收context dict，返回选中的block_id"""
        self._branch_override_func = func

    def clear_branch_override(self):
        """清除分支选择覆盖函数，恢复随机选择"""
        self._branch_override_func = None

    def _generate_branch_description(self, block) -> str:
        """从 block.effects 生成分支效果描述（简洁版）"""
        if not block or not hasattr(block, 'effects') or not block.effects:
            return "无效果"
        parts = []
        for eff in block.effects:
            et = getattr(eff, 'effect_type', '') or ''
            flags = getattr(eff, 'flags', None) or {}
            if et == 'damage':
                hits = getattr(eff, 'hit_count', None) or 1
                is_en = flags.get('is_en_attack', False)
                parts.append(f"{hits}hit{' EN' if is_en else ''}伤害")
            elif et == 'add_status':
                st = flags.get('status_type', '')
                dur = getattr(eff, 'duration', 0) or 0
                parts.append(f"{st}{dur}action" if dur else st)
            elif et == 'heal':
                heal_base = flags.get('heal_base', '')
                parts.append(f"回復({heal_base})" if heal_base else "回復")
            elif et == 'lifesteal':
                val = getattr(eff, 'value', 0) or 0
                parts.append(f"吸血{int(val)}%")
            elif et == 'remove_ep':
                val = getattr(eff, 'value', 1) or 1
                parts.append(f"减EP{val}")
            elif et == 'remove_pp':
                val = getattr(eff, 'value', 1) or 1
                parts.append(f"减PP{val}")
            elif et == 'dmg_dealt_down':
                parts.append("降攻")
            elif et == 'dmg_taken_down':
                parts.append("减伤")
            elif et == 'perfect_evasion':
                hits = getattr(eff, 'hit_count', 1) or 1
                parts.append(f"{hits}次回避")
            elif et == 'shield':
                parts.append("护盾")
            elif et == 'remove_all_buffs':
                parts.append("清buff")
            elif et == 'remove_all_debuffs':
                parts.append("清debuff")
            elif et == 'counter_stance':
                parts.append("反击架势")
            elif et == 'cover':
                parts.append("援护")
            else:
                parts.append(et)
        return " + ".join(parts) if parts else "无效果"

    def _execute_trigger_actions_inline(self, actions: list, battlefield: BattlefieldState,
                                          trigger_timing: str = None) -> None:
        if not actions:
            return
        _log.info("[INLINE_EXEC] _execute_trigger_actions_inline called with %d actions, timing=%s",
                  len(actions), trigger_timing)
        for action in actions:
            owner = action.instance.owner
            skill_data = self.data_loader.get_skill_by_id(action.skill_id)
            skill_name = skill_data.name if skill_data else "?"

            trigger_attacker = action.parameters.get('trigger_attacker') if hasattr(action, 'parameters') else None
            primary_target = action.parameters.get('primary_target') if hasattr(action, 'parameters') else None
            damaged_targets = action.parameters.get('targets') if hasattr(action, 'parameters') else None
            total_damage = action.parameters.get('total_damage') if hasattr(action, 'parameters') else None
            if trigger_attacker:
                self._trigger_attacker = trigger_attacker
            if primary_target:
                self._primary_target = primary_target
            if damaged_targets:
                self._damaged_targets = damaged_targets
            if total_damage is not None:
                self._trigger_total_damage = total_damage
            else:
                self._trigger_total_damage = 0

            # 保存外层技能的_current_skill_id，防止内层execute_skill覆盖
            saved_current_skill_id = self._current_skill_id

            # 保存外层技能的_before_attack_triggers_fired，防止内层execute_skill重置
            saved_before_attack_fired = self._before_attack_triggers_fired

            # 保存外层技能的pending_deaths，防止内层execute_skill提前处理
            saved_pending_deaths = set(self._pending_deaths)
            self._pending_deaths.clear()

            # 保存外层技能的_block_damage_targets，防止内层execute_skill覆盖
            saved_block_targets = self._block_damage_targets

            # 保存外层技能的_last_primary_target，防止内层execute_skill覆盖
            saved_last_primary_target = getattr(self, '_last_primary_target', None)

            # 保存外层技能的_block_evaded_targets，防止内层execute_skill清空
            saved_evaded_targets = set(getattr(self, '_block_evaded_targets', set()))

            # 保存外层技能的_skill_evaded_targets，防止内层execute_skill清空
            saved_skill_evaded_targets = set(getattr(self, '_skill_evaded_targets', set()))

            # 保存外层技能的_newly_created_sub_unit_ids，防止内层execute_skill清空
            saved_new_sub_units = set(self._newly_created_sub_unit_ids)

            # 保存外层技能的_inline_ps_results，防止内层execute_skill清空
            saved_ps_results = list(self._inline_ps_results)
            self._inline_ps_results.clear()

            # 保存外层技能的_pending_crit_triggers，防止内层execute_skill覆盖
            saved_crit_triggers = list(self._pending_crit_triggers)
            self._pending_crit_triggers = []

            # 保存外层技能的_pre_scanned_cover_candidates，防止内层execute_skill覆盖
            saved_pre_scanned_cover_candidates = list(getattr(self, '_pre_scanned_cover_candidates', []))

            # 保存外层技能的on_crit相关状态，防止内层execute_skill清空
            # （如220369紫影の斬撃的on_crit modify_pp block会被before_any_attacked PS的内层execute_skill清空）
            saved_on_crit_blocks = list(self._on_crit_blocks)
            saved_on_crit_applied = self._on_crit_applied
            saved_on_crit_block_executed = dict(self._on_crit_block_executed)
            saved_on_crit_target = self._on_crit_target
            saved_on_crit_immediate_blocks = list(self._on_crit_immediate_blocks)
            saved_on_crit_immediate_applied = set(self._on_crit_immediate_applied)
            saved_on_crit_effects = list(self._on_crit_effects)
            saved_deferred_on_crit_targets = list(self._deferred_on_crit_targets)

            skill_result = self.execute_skill(
                caster=owner,
                skill_id=action.skill_id,
                battlefield=battlefield,
                skip_cost=False,
                defer_crit_triggers=True,
            )

            # 仅在技能执行成功时设置冷却时间，避免PP不足等失败情况下冷却被错误重置
            if skill_result.get("success"):
                self.update_cooldown_after_skill_use(owner, action.skill_id)

                # crit_count_mod触发器：PS技能执行成功后清空暴击计数器
                parsed = self.data_loader.get_parsed_skill_data(action.skill_id) if self.data_loader else None
                if parsed:
                    gc = parsed.get('global_condition', {})
                    if gc and gc.get('type') == 'crit_count_mod':
                        owner.crit_counter = 0
                        _log.info("[CRIT_RESET] %s: crit_counter reset to 0 after inline PS[%s] executed successfully",
                                  owner.name, skill_name)

            # 恢复外层技能的_current_skill_id
            self._current_skill_id = saved_current_skill_id

            # 恢复外层技能的_before_attack_triggers_fired
            self._before_attack_triggers_fired = saved_before_attack_fired

            # 恢复外层技能的pending_deaths，合并内层新增的
            self._pending_deaths.update(saved_pending_deaths)

            # 恢复外层技能的_block_damage_targets
            self._block_damage_targets = saved_block_targets

            # 恢复外层技能的_last_primary_target
            self._last_primary_target = saved_last_primary_target

            # 恢复外层技能的_block_evaded_targets，合并内层新增的
            self._block_evaded_targets = saved_evaded_targets
            inner_evaded = getattr(self, '_block_evaded_targets', set())
            self._block_evaded_targets.update(inner_evaded)

            # 恢复外层技能的_skill_evaded_targets，合并内层新增的
            self._skill_evaded_targets = saved_skill_evaded_targets
            inner_skill_evaded = getattr(self, '_skill_evaded_targets', set())
            self._skill_evaded_targets.update(inner_skill_evaded)

            # 恢复外层技能的_newly_created_sub_unit_ids，合并内层新增的
            self._newly_created_sub_unit_ids.update(saved_new_sub_units)

            # 恢复外层技能的_inline_ps_results，合并内层PS结果
            inner_ps_results = list(self._inline_ps_results)
            self._inline_ps_results = saved_ps_results
            self._inline_ps_results.extend(inner_ps_results)

            # 内层PS的pending_crit_triggers也需要合并到外层
            # execute_skill不再内部执行crit triggers，改为返回在result中
            inner_crit_triggers = skill_result.get("pending_crit_triggers", [])
            self._pending_crit_triggers = saved_crit_triggers + inner_crit_triggers

            # 恢复外层技能的_pre_scanned_cover_candidates
            self._pre_scanned_cover_candidates = saved_pre_scanned_cover_candidates

            # 恢复外层技能的on_crit相关状态
            self._on_crit_blocks = saved_on_crit_blocks
            self._on_crit_applied = saved_on_crit_applied
            self._on_crit_block_executed = saved_on_crit_block_executed
            self._on_crit_target = saved_on_crit_target
            self._on_crit_immediate_blocks = saved_on_crit_immediate_blocks
            self._on_crit_immediate_applied = saved_on_crit_immediate_applied
            self._on_crit_effects = saved_on_crit_effects
            self._deferred_on_crit_targets = saved_deferred_on_crit_targets

            if skill_result.get("success") and skill_result.get("effects_applied"):
                self._inline_ps_results.append({
                    "owner": owner,
                    "skill_id": action.skill_id,
                    "skill_name": skill_name,
                    "result": skill_result,
                    "trigger_timing": trigger_timing,
                })

            if trigger_attacker:
                self._trigger_attacker = None
            if primary_target:
                self._primary_target = None

    def check_skill_cost(self, unit: UnitState, skill_id: int) -> bool:
        skill_data = self.data_loader.get_skill_by_id(skill_id)
        if not skill_data:
            return False

        cost = skill_data.resource_cost

        if skill_data.skill_type == 1:  # AS
            if unit.current_ap < cost:
                return False
        elif skill_data.skill_type == 2:  # PS
            if unit.current_pp < cost:
                return False
        elif skill_data.skill_type == 3:  # EX
            if unit.current_ep < unit.max_extra_point:
                return False
        return True

    def select_skill(self, unit: UnitState) -> Optional[int]:
        """
        技能选择AI:
        1. EP满 (current_ep == max_ep) → 选择EX技能
        2. 否则 → 第一个可用的AS技能 (AP足够 + 未冷却 + 活跃敌方)
        混乱时：EX/PS被过滤，仅含伤害效果的AS可用；无则待机。
        """

        def _is_usable(skill_id: int) -> bool:
            cd = unit.skill_cooldowns.get(skill_id, 0)
            if cd > 0:
                return False
            return self.check_skill_cost(unit, skill_id)

        # 混乱状态检查
        is_confused = getattr(unit, 'is_confused', False)

        enemies = [u for u in self._battlefield.enemy_team if u.is_alive]
        if not enemies:
            _log.info("[SKILL_SEL] %s: no alive enemies -> standby", unit.name)
            return None

        # EX技能：混乱时跳过
        if not is_confused:
            for sid in unit.skills:
                resolved = self._resolver.resolve(sid, unit.skill_levels.get(sid, 1))
                if not resolved:
                    continue

                if resolved.skill_type == 3:
                    if unit.current_ep >= unit.max_extra_point and _is_usable(sid):
                        _log.info("[SKILL_SEL] %s: EP full -> EX skill [%s] (id=%d)",
                                  unit.name, resolved.name, sid)
                        return sid

        # AS技能：混乱时仅选含伤害效果的AS
        for sid in unit.skills:
            resolved = self._resolver.resolve(sid, unit.skill_levels.get(sid, 1))
            if not resolved:
                continue
            if resolved.skill_type == 1 and _is_usable(sid):
                if is_confused and not self._skill_has_damage_effect(sid, unit.skill_levels.get(sid, 1)):
                    _log.info("[SKILL_SEL] %s: CONFUSED -> skip AS [%s] (id=%d, no damage effect)",
                              unit.name, resolved.name, sid)
                    continue
                _log.info("[SKILL_SEL] %s: AS skill [%s] (id=%d) pwr=%.1f cost=%d%s",
                          unit.name, resolved.name, sid, resolved.power, resolved.resource_cost,
                          " (CONFUSED)" if is_confused else "")
                return sid

        _log.info("[SKILL_SEL] %s: no usable skill -> standby%s",
                  unit.name, " (CONFUSED)" if is_confused else "")
        return None

    def _skill_has_damage_effect(self, skill_id: int, level: int = 1) -> bool:
        """检查技能是否包含即时伤害效果（damage/hp_ratio_damage/damage_special）"""
        parsed = self.data_loader.get_parsed_skill_data(skill_id) if hasattr(self, 'data_loader') else None
        if not parsed:
            return False
        effect_blocks = parsed.get('effect_blocks', [])
        for block in effect_blocks:
            # 检查block条件
            block_cond = block.get('condition') if isinstance(block, dict) else None
            if block_cond and isinstance(block_cond, dict):
                level_min = block_cond.get('active_level_min')
                if level_min is not None and level < level_min:
                    continue
            effects = block.get('effects', []) if isinstance(block, dict) else []
            for eff in effects:
                etype = eff.get('effect_type', '')
                if etype in ('damage', 'hp_ratio_damage', 'damage_special'):
                    return True
        return False

    def _compute_stat_display(self, unit: UnitState, mapped_effect_type: str) -> tuple:
        """计算单位当前属性值，返回 (label, value_str) 元组，如 ('ATK', '64655')。

        用于在 add_aura 前后追踪真实属性，构造 'ATK:前值→后值' 格式的叙事日志。
        关键约束：直接调用 _calculate_final_stat 获取即时属性，而非用效果量做加减法。
        返回 ("", "") 表示该效果类型无属性显示。
        """
        if not self.damage_service:
            return ("", "")
        if mapped_effect_type == SkillEffectType.STATUS_ATTACK.value:
            return ("ATK", str(self.damage_service._calculate_final_stat(unit, 'attack')))
        elif mapped_effect_type == SkillEffectType.STATUS_DEFENSE.value:
            return ("DEF", str(self.damage_service._calculate_final_stat(unit, 'defense')))
        elif mapped_effect_type == SkillEffectType.STATUS_SPEED.value:
            return ("SPD", str(self.damage_service._calculate_final_stat(unit, 'speed')))
        elif mapped_effect_type == SkillEffectType.STATUS_MAX_HP.value:
            return ("最大HP", str(self.damage_service._calculate_final_stat(unit, 'max_hp')))
        elif mapped_effect_type == SkillEffectType.DEALT_DAMAGE.value:
            total = 0.0
            for b in unit.buffs:
                if b.effect_type == SkillEffectType.DEALT_DAMAGE.value:
                    total += self.damage_service._normalize_buff_value(b)
            for b in unit.debuffs:
                if b.effect_type == SkillEffectType.DEALT_DAMAGE.value:
                    total -= self.damage_service._normalize_buff_value(b)
            pct = int(total * 100)
            sign = "+" if pct >= 0 else ""
            return ("与ダメージ", f"{sign}{pct}%")
        elif mapped_effect_type == SkillEffectType.RECEIVED_DAMAGE.value:
            total = 0.0
            for b in unit.buffs:
                if b.effect_type == SkillEffectType.RECEIVED_DAMAGE.value:
                    total -= self.damage_service._normalize_buff_value(b)
            for b in unit.debuffs:
                if b.effect_type == SkillEffectType.RECEIVED_DAMAGE.value:
                    total += self.damage_service._normalize_buff_value(b)
            pct = int(total * 100)
            sign = "+" if pct >= 0 else ""
            return ("被ダメージ", f"{sign}{pct}%")
        elif mapped_effect_type == SkillEffectType.STATUS_CRITICAL_CHANCE.value:
            total = self.damage_service._calculate_crit_rate(unit)
            return ("暴击率", f"{total * 100:.1f}%")
        elif mapped_effect_type == SkillEffectType.CRITICAL_BONUS_MODIFICATION.value:
            total = 1.5 + self.damage_service._get_crit_damage_bonus(unit)
            return ("暴击伤害", f"{total * 100:.2f}%")
        return ("", "")

    def execute_skill(self, caster: UnitState, skill_id: int,
                      battlefield: BattlefieldState, skip_cost: bool = False,
                      defer_crit_triggers: bool = False) -> Dict[str, Any]:
        result = {
            "success": False,
            "skill_id": skill_id,
            "caster_id": caster.unit_id,
            "total_damage": 0,
            "effects_applied": [],
        }

        self.set_battlefield(battlefield)

        self._on_crit_blocks = []
        self._on_crit_applied = False
        self._on_crit_block_executed = {}  # 记录once_per_skill=true的block是否已执行
        self._on_crit_target = None  # 当前暴击目标，供crit_target target_type使用
        self._on_crit_immediate_blocks = []  # 即时on_crit blocks（aura效果），在hit循环中通过callback施加
        self._on_crit_immediate_applied = set()  # 已施加即时on_crit效果的目标unit_id集合
        self._on_crit_effects = []  # 收集on_crit块的效果结果
        self._deferred_on_crit_targets = []  # 延迟执行的on_crit目标列表
        self._current_skill_id = skill_id
        self._pending_crit_triggers = []
        self._before_attack_triggers_fired = False  # 每个技能重置：只在第一个伤害效果前触发before_attack
        self._skill_evaded_targets = set()  # 技能级别：所有block中完全闪避的目标集合
        self._debuff_immune_blocked_targets = set()  # 技能级别：被debuff_immune免疫的目标集合
        self._skill_all_attacked_targets = []  # 技能级别：所有block中已攻击的目标累积（用于跨block的attacked_targets）
        self._most_recent_damage = 0  # 技能级别：累计该技能所有damage block的伤害，供lifesteal等使用

        # 快照技能执行前的mark状态（用于has_mark_at_start条件和target_has_mark条件）
        self._marks_at_start = {}
        caster_buffs = getattr(caster, 'buffs', []) or []
        caster_debuffs = getattr(caster, 'debuffs', []) or []
        for b in caster_buffs + caster_debuffs:
            if getattr(b, 'effect_type', None) == SkillEffectType.MARK.value:
                mark_name = getattr(b, 'name', '')
                if mark_name:
                    self._marks_at_start[mark_name] = self._marks_at_start.get(mark_name, 0) + 1

        # 快照所有单位的mark状态（用于target_has_mark条件，检查攻击前目标是否持有mark）
        self._marks_at_start_by_unit = {}
        for u in battlefield.get_all_units():
            unit_marks = set()
            for b in (getattr(u, 'buffs', []) or []) + (getattr(u, 'debuffs', []) or []):
                if getattr(b, 'effect_type', None) == SkillEffectType.MARK.value:
                    mname = getattr(b, 'name', '')
                    if mname:
                        unit_marks.add(mname)
            if unit_marks:
                self._marks_at_start_by_unit[u.unit_id] = unit_marks

        resolved = self._resolver.resolve(skill_id, caster.skill_levels.get(skill_id, 1))
        if not resolved:
            _log.info("[SKILL_EXEC] %s: skill_id=%d NOT FOUND in resolver", caster.name, skill_id)
            result["error"] = "Skill data not found"
            return result

        self._current_skill_priority = resolved.display_target_priority

        meta = self.data_loader.get_skill_by_id(skill_id)
        if not meta:
            _log.info("[SKILL_EXEC] %s: skill_id=%d metadata NOT FOUND", caster.name, skill_id)
            result["error"] = "Skill metadata not found"
            return result

        cd = caster.skill_cooldowns.get(skill_id, 0)
        if cd > 0:
            _log.info("[SKILL_EXEC] %s: [%s] id=%d on cooldown (%d) -> SKIP",
                      caster.name, resolved.name, skill_id, cd)
            result["error"] = "Skill on cooldown"
            return result

        _log.info("[SKILL_EXEC] %s executes [%s] (id=%d) type=%d cost=%d skip_cost=%s AP=%d EP=%d/%d",
                  caster.name, resolved.name, skill_id, resolved.skill_type,
                  resolved.resource_cost, skip_cost, caster.current_ap, caster.current_ep, caster.max_extra_point)

        if not skip_cost and not self._deduct_cost(caster, meta):
            _log.info("[SKILL_EXEC] %s: resource deduction FAILED for skill [%s]", caster.name, resolved.name)
            result["error"] = "Insufficient resources"
            return result

        # 评估global_condition（如round_number等）
        gc = getattr(resolved, 'global_condition', None)
        if gc and isinstance(gc, dict):
            gc_type = gc.get('type')
            gc_op = gc.get('operator', '==')
            gc_val = gc.get('value', 0)
            if gc_type == 'round_number':
                cur_round = battlefield.turn_number
                if not _eval_block_condition(cur_round, gc_op, gc_val):
                    _log.info("[SKILL_EXEC] %s: [%s] global_condition round_number %d %s %d failed, skipping",
                              caster.name, resolved.name, cur_round, gc_op, gc_val)
                    result["error"] = "global_condition not met"
                    return result
            elif gc_type == 'self_lacks_mark':
                # 自身持有指定mark时技能不发动（如146301 120152/130151 深慮限制）
                gc_mark_name = gc.get('mark_name', '')
                has_mark = any(
                    b.effect_type == SkillEffectType.MARK.value and getattr(b, 'name', '') == gc_mark_name
                    for b in caster.buffs
                ) or any(
                    d.effect_type == SkillEffectType.MARK.value and getattr(d, 'name', '') == gc_mark_name
                    for d in caster.debuffs
                )
                if has_mark:
                    _log.info("[SKILL_EXEC] %s: [%s] global_condition self_lacks_mark '%s': found, skipping",
                              caster.name, resolved.name, gc_mark_name)
                    result["error"] = "global_condition not met"
                    return result

        deferred_effects = []
        kills_occurred = False
        self._debuffs_applied_this_skill = set()

        # 预扫描所有damage block的索敌目标，确定cover候选
        # 仅当技能有damage效果时才重新扫描，否则保留外层技能的预扫描结果（PS技能无damage效果）
        _has_damage_effects = any(
            getattr(e, 'effect_type', None) == 'damage'
            for _pre_block in resolved.effect_blocks
            for e in _pre_block.effects
        )
        if _has_damage_effects:
            self._pre_scanned_cover_candidates = []  # 按block顺序排列的被攻击友方候选
            _seen_ids = set()
            _prescan_primary_target = None  # 用于adjacent_enemies等依赖主目标的目标类型
            for _pre_block in resolved.effect_blocks:
                for _pre_effect in _pre_block.effects:
                    if getattr(_pre_effect, 'effect_type', None) == 'damage':
                        _pre_flags = getattr(_pre_effect, 'flags', {}) or {}
                        if getattr(_pre_effect, 'target_type', None) and _pre_effect.target_type not in ('debuff_applied_target',):
                            _pre_target_type = _pre_effect.target_type
                            _pre_target_identifier = getattr(_pre_effect, 'target_identifier', None)
                            if _pre_target_identifier == "trigger_attacker":
                                # 反撃系PS: target_identifier=trigger_attacker 时，实际damage目标为_trigger_attacker
                                # prescan必须使用相同目标，否则trigger链检查的目标(NEAREST)与实际damage目标(trigger_attacker)不一致
                                # 导致before_any_attacked等触发器的target_is_self条件误判（如ブレイジングハート未触发bug）
                                _ta = getattr(self, '_trigger_attacker', None)
                                if _ta and _ta.is_alive:
                                    _pre_targets = [_ta]
                                    _log.info("[COVER_PRESCAN] %s: target_identifier=trigger_attacker -> %s",
                                              caster.name, _ta.name)
                                else:
                                    _pre_targets = []
                            # adjacent_enemies需要基于主目标选择
                            elif _pre_target_type == "adjacent_enemies":
                                if _prescan_primary_target:
                                    _pre_targets = self.target_service.get_adjacent_to_unit(
                                        _prescan_primary_target, battlefield, caster
                                    )
                                else:
                                    _pre_tso = type('obj', (object,), {
                                        'display_target_type': self._resolve_target_type(_pre_target_type),
                                        'display_target_range': self._resolve_target_range(_pre_target_type),
                                        'display_target_priority': self._current_skill_priority,
                                    })()
                                    _pre_targets = self.target_service.select_targets(_pre_tso, caster, battlefield)
                            else:
                                # 特殊索敌类型（highest_atk/highest_spd/furthest/highest_hp_ratio_back等）
                                # 实际damage执行(L1149)使用ALL_PAWNS获取所有候选再后过滤，
                                # prescan必须保持一致，否则trigger检查目标与实际damage目标不同
                                # （如ブレイジングハート误触发bug：prescan用ONE_PAWN选NEAREST=PS持有者，
                                #   实际damage用ALL_PAWNS+后过滤选了后排其他单位）
                                _SPECIAL_POSTFILTER_TYPES = {
                                    "enemy_single_highest_atk", "enemy_single_highest_spd",
                                    "enemy_single_lowest_spd", "enemy_single_furthest",
                                    "enemy_single_highest_ep",
                                    "enemy_single_highest_hp_ratio",
                                    "enemy_single_highest_current_hp",
                                    "enemy_single_highest_hp_ratio_back_priority",
                                    "enemy_single_lowest_hp_ratio",
                                    "enemy_column_furthest", "enemy_column_mark_priority",
                                }
                                if _pre_target_type in _SPECIAL_POSTFILTER_TYPES:
                                    _pre_range = self._resolve_target_range("enemies")  # ALL_PAWNS
                                else:
                                    _pre_range = self._resolve_target_range(_pre_target_type)
                                _pre_tso = type('obj', (object,), {
                                    'display_target_type': self._resolve_target_type(_pre_target_type),
                                    'display_target_range': _pre_range,
                                    'display_target_priority': self._current_skill_priority,
                                    'target_type_name': _pre_target_type,
                                    'mark_priority': _pre_flags.get('mark_priority'),
                                })()
                                _pre_targets = self.target_service.select_targets(_pre_tso, caster, battlefield)
                                # 对特殊索敌类型应用后过滤，与实际damage执行保持一致
                                # 否则trigger检查会使用与实际damage不同的目标（如ブレイジングハート误触发bug）
                                # prescan不消費ステルス（仅模拟重定向），实际消費在damage执行时
                                _pre_targets = self._postfilter_damage_targets(
                                    _pre_target_type, _pre_targets, caster, _pre_flags,
                                    consume_stealth=False
                                )
                                _pre_target_count = _pre_flags.get('target_count', 1)
                                if _pre_target_count > 1 and len(_pre_targets) > _pre_target_count:
                                    _pre_targets = _pre_targets[:_pre_target_count]
                            for _pt in _pre_targets:
                                if _pt.unit_id not in _seen_ids and _pt.is_alive:
                                    _seen_ids.add(_pt.unit_id)
                                    # 只添加与caster不同阵营的单位（即被攻击的友方）
                                    if _pt.side != caster.side:
                                        self._pre_scanned_cover_candidates.append(_pt)
                                    # 记录第一个enemy_single目标作为主目标
                                    if _prescan_primary_target is None and _pre_target_type in ("enemy_single", "enemies"):
                                        _prescan_primary_target = _pt
            if self._pre_scanned_cover_candidates:
                _log.info("[COVER_PRESCAN] %s: pre-scanned cover candidates: %s",
                          caster.name, [t.name for t in self._pre_scanned_cover_candidates])

        for block in resolved.effect_blocks:
            block_condition = getattr(block, 'condition', None)
            if block_condition and isinstance(block_condition, dict) and block_condition.get('type') == 'on_crit':
                # 检查是否为即时施加的aura block（apply_timing="immediate"）
                # 即时block在多hit伤害的hit循环中通过callback施加，使后续hit能享受易伤效果
                apply_timing = block_condition.get('apply_timing', 'deferred')
                if apply_timing == 'immediate':
                    self._on_crit_immediate_blocks.append(block)
                    _log.info("[SKILL_EXEC] %s: pre-collected on_crit IMMEDIATE block %d (effects=%d)",
                              caster.name, block.block_id, len(block.effects))
                else:
                    self._on_crit_blocks.append(block)
                    _log.info("[SKILL_EXEC] %s: pre-collected on_crit DEFERRED block %d (effects=%d)",
                              caster.name, block.block_id, len(block.effects))

        # 保存技能开始时所有敌方单位的HP快照，用于跨block的HP百分比比较（如AS1第二段攻击）
        self._pre_skill_hp = {}
        try:
            enemy_side = battlefield.enemy_team if caster.side == battlefield.friend_team[0].side else battlefield.friend_team
            for u in enemy_side:
                if u.is_alive:
                    self._pre_skill_hp[u.unit_id] = u.current_hp
        except (AttributeError, IndexError):
            pass

        # random_choice / probability 分支预选择
        # 收集所有带 random_choice 或 probability 条件的 block，按 group_id 分组
        # 每组按权重随机选 1 个执行（支持 AS1 Lv11+ 两段独立 4 选 1 的场景）
        # 注意：需过滤掉不满足 level_min/level_max 的 block
        _branch_groups = {}  # {group_id: [(block_id, weight), ...]}
        _skill_level = caster.skill_levels.get(skill_id, 1)
        for block in resolved.effect_blocks:
            bc = getattr(block, 'condition', None)
            if bc and isinstance(bc, dict):
                bt = bc.get('type')
                if bt in ('random_choice', 'probability'):
                    # 检查 level_min / level_max
                    lvl_min = bc.get('level_min')
                    lvl_max = bc.get('level_max')
                    if lvl_min is not None and _skill_level < lvl_min:
                        continue
                    if lvl_max is not None and _skill_level > lvl_max:
                        continue
                    group_id = bc.get('group_id', 0)  # 默认 group 0
                    weight = bc.get('weight', 1)
                    _branch_groups.setdefault(group_id, []).append((block.block_id, weight))
        _selected_branch_block_ids = set()
        for gid, members in _branch_groups.items():
            weights = [w for _, w in members]
            ids = [bid for bid, _ in members]
            if self._branch_override_func is not None:
                # 生成分支效果描述
                candidates_ctx = []
                for bid, w in members:
                    # 找到对应的 block 获取 effects
                    block_for_desc = next((b for b in resolved.effect_blocks if b.block_id == bid), None)
                    desc = self._generate_branch_description(block_for_desc) if block_for_desc else ""
                    candidates_ctx.append({
                        'block_id': bid,
                        'weight': w,
                        'description': desc,
                    })
                ctx = {
                    'caster_name': caster.name,
                    'caster_id': caster.unit_id,
                    'skill_name': resolved.name,
                    'skill_id': skill_id,
                    'group_id': gid,
                    'candidates': candidates_ctx,
                }
                try:
                    selected = self._branch_override_func(ctx)
                    if selected not in ids:
                        _log.warning("[BRANCH_OVERRIDE] %s: invalid block_id %s, fallback to random",
                                     caster.name, selected)
                        selected = random.choices(ids, weights=weights, k=1)[0]
                except Exception as e:
                    _log.warning("[BRANCH_OVERRIDE] %s: override error %s, fallback to random",
                                 caster.name, e)
                    selected = random.choices(ids, weights=weights, k=1)[0]
            else:
                selected = random.choices(ids, weights=weights, k=1)[0]
            _selected_branch_block_ids.add(selected)
            _log.info("[BRANCH_SELECT] %s: group=%d members=%s weights=%s selected=%s (override=%s)",
                      caster.name, gid, ids, weights, selected,
                      self._branch_override_func is not None)

        for block_idx, block in enumerate(resolved.effect_blocks):
            block_condition = getattr(block, 'condition', None)
            self._target_element_filter = None
            self._target_char_type_filter = None
            if block_condition and isinstance(block_condition, dict):
                cond_type = block_condition.get('type')
                # random_choice / probability 分支：只执行被选中的 block
                if cond_type in ('random_choice', 'probability'):
                    if block.block_id not in _selected_branch_block_ids:
                        _log.info("[BRANCH_SKIP] %s: skipping block %d (not selected, selected=%s)",
                                  caster.name, block.block_id, _selected_branch_block_ids)
                        continue
                    _log.info("[BRANCH_EXEC] %s: executing selected branch block %d",
                              caster.name, block.block_id)
                # 支持AND组合条件
                if cond_type == 'and':
                    sub_conditions = block_condition.get('conditions', [])
                    skip_block = False
                    for sub_cond in sub_conditions:
                        st = sub_cond.get('type')
                        if st == 'active_level_min':
                            _active_level = caster.skill_levels.get(skill_id, 1)
                            if _active_level < sub_cond.get('value', 0):
                                skip_block = True
                                break
                        elif st == 'target_character_type':
                            _ct_val = sub_cond.get('value')
                            self._target_char_type_filter = [_ct_val] if isinstance(_ct_val, int) else _ct_val
                        elif st == 'target_element':
                            self._target_element_filter = sub_cond.get('value')
                        elif st == 'self_has_ap':
                            if getattr(caster, 'current_ap', 0) <= 0:
                                skip_block = True
                                break
                        elif st == 'self_no_ap':
                            if getattr(caster, 'current_ap', 0) > 0:
                                skip_block = True
                                break
                    if skip_block:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (and condition not met)",
                                  caster.name, block.block_id)
                        continue
                if cond_type == 'target_survived':
                    # target_survived：只检查前序block的主目标是否存活
                    # 使用_last_primary_target（前序block的主攻击目标）
                    primary_target = getattr(self, '_last_primary_target', None)
                    if primary_target is None:
                        # 回退：检查_prev_block_damage_targets中的第一个目标类型
                        prev_targets = getattr(self, '_prev_block_damage_targets', {})
                        if prev_targets:
                            first_key = next(iter(prev_targets))
                            primary_target = prev_targets[first_key][0] if prev_targets[first_key] else None
                    if primary_target is not None:
                        if self._tactical_exercise_mode:
                            is_dead = not primary_target.is_alive
                        else:
                            is_dead = primary_target.current_hp <= 0
                        if is_dead:
                            _log.info("[SKILL_EXEC] %s: skipping block %d (target_survived: primary target %s is dead)",
                                      caster.name, block.block_id, primary_target.name)
                            continue
                elif cond_type == 'target_killed':
                    if not kills_occurred:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (target_killed condition failed, no kills)",
                                  caster.name, block.block_id)
                        continue
                elif cond_type == 'self_hp_above':
                    hp_pct = caster.current_hp / caster.max_hp * 100 if caster.max_hp > 0 else 0
                    threshold = block_condition.get('value', 0)
                    if hp_pct < threshold:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (self_hp_above: %.1f%% < %.0f%%)",
                                  caster.name, block.block_id, hp_pct, threshold)
                        continue
                elif cond_type == 'self_hp_below':
                    hp_pct = caster.current_hp / caster.max_hp * 100 if caster.max_hp > 0 else 0
                    threshold = block_condition.get('value', 0)
                    if hp_pct >= threshold:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (self_hp_below: %.1f%% >= %.0f%%)",
                                  caster.name, block.block_id, hp_pct, threshold)
                        continue
                elif cond_type == 'self_hp_full':
                    if caster.current_hp < caster.max_hp:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (self_hp_full: HP not full)",
                                  caster.name, block.block_id)
                        continue
                elif cond_type == 'fury_count_lte':
                    if caster.fury_count > block_condition.get('value', 0):
                        _log.info("[SKILL_EXEC] %s: skipping block %d (fury_count_lte: %d > %d)",
                                  caster.name, block.block_id, caster.fury_count, block_condition.get('value', 0))
                        continue
                elif cond_type == 'fury_count_eq':
                    if caster.fury_count != block_condition.get('value', 0):
                        _log.info("[SKILL_EXEC] %s: skipping block %d (fury_count_eq: %d != %d)",
                                  caster.name, block.block_id, caster.fury_count, block_condition.get('value', 0))
                        continue
                elif cond_type == 'fury_count_gte':
                    if caster.fury_count < block_condition.get('value', 0):
                        _log.info("[SKILL_EXEC] %s: skipping block %d (fury_count_gte: %d < %d)",
                                  caster.name, block.block_id, caster.fury_count, block_condition.get('value', 0))
                        continue
                elif cond_type == 'self_hp_above_not_full':
                    hp_pct = caster.current_hp / caster.max_hp * 100 if caster.max_hp > 0 else 0
                    threshold = block_condition.get('value', 0)
                    if hp_pct < threshold or hp_pct >= 100:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (self_hp_above_not_full: %.1f%%)",
                                  caster.name, block.block_id, hp_pct)
                        continue
                elif cond_type == 'target_element':
                    self._target_element_filter = block_condition.get('value')
                elif cond_type == 'target_character_type':
                    _ct_val = block_condition.get('value')
                    self._target_char_type_filter = [_ct_val] if isinstance(_ct_val, int) else _ct_val
                elif cond_type == 'self_has_status':
                    status_name = str(block_condition.get('value', ''))
                    has_status = any(
                        b.effect_type == status_name
                        for b in (getattr(caster, 'buffs', []) or [])
                    )
                    if not has_status:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (self_has_status: %s not found)",
                                  caster.name, block.block_id, status_name)
                        continue
                elif cond_type == 'self_no_status':
                    status_name = str(block_condition.get('value', ''))
                    has_status = any(
                        b.effect_type == status_name
                        for b in (getattr(caster, 'buffs', []) or [])
                    )
                    if has_status:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (self_no_status: %s found)",
                                  caster.name, block.block_id, status_name)
                        continue
                elif cond_type == 'self_has_ap':
                    if getattr(caster, 'current_ap', 0) <= 0:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (self_has_ap: AP=%d)",
                                  caster.name, block.block_id, caster.current_ap)
                        continue
                elif cond_type == 'self_no_ap':
                    if getattr(caster, 'current_ap', 0) > 0:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (self_no_ap: AP=%d)",
                                  caster.name, block.block_id, caster.current_ap)
                        continue
                elif cond_type == 'round_number':
                    cur = battlefield.turn_number
                    op = block_condition.get('operator', '==')
                    val = block_condition.get('value', 0)
                    if not _eval_block_condition(cur, op, val):
                        _log.info("[SKILL_EXEC] %s: skipping block %d (round_number: %d %s %d failed)",
                                  caster.name, block.block_id, cur, op, val)
                        continue
                elif cond_type == 'active_level_min':
                    # 直接active_level_min条件（非and组合）：技能等级 < value 时跳过
                    _active_level = caster.skill_levels.get(skill_id, 1)
                    _min_level = block_condition.get('value', 0)
                    if _active_level < _min_level:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (active_level_min: %d < %d)",
                                  caster.name, block.block_id, _active_level, _min_level)
                        continue
                elif cond_type == 'on_crit':
                    continue

                elif cond_type == 'has_mark_at_start':
                    # 检查技能执行前是否有指定mark
                    mark_name = block_condition.get('mark_name', '')
                    marks_at_start = getattr(self, '_marks_at_start', {})
                    if marks_at_start.get(mark_name, 0) <= 0:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (has_mark_at_start: no '%s' at start)",
                                  caster.name, block.block_id, mark_name)
                        continue

                elif cond_type == 'target_has_buff':
                    # 检查之前伤害块的目标是否有任意buff（不包括debuff）
                    bdt = self._block_damage_targets if hasattr(self, '_block_damage_targets') and self._block_damage_targets else {}
                    damaged_units = []
                    seen_ids = set()
                    for units in bdt.values():
                        for u in units:
                            if u.unit_id not in seen_ids and u.is_alive:
                                seen_ids.add(u.unit_id)
                                damaged_units.append(u)
                    has_buff = any(
                        any(b for b in u.buffs)
                        for u in damaged_units
                    ) if damaged_units else False
                    if not has_buff:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (target_has_buff: no target has buff)",
                                  caster.name, block.block_id)
                        continue

                elif cond_type == 'target_has_status_ailment':
                    # 检查之前伤害块的目标是否有异常状态（炎上/毒/凍結/眩暈/黑暗/混乱）
                    # 異常状態≠debuff，異常状態只是debuff的子集
                    STATUS_AILMENT_TYPES = {"knockout", "conflagration", "poison", "freeze",
                                            "darkness", "confusion"}
                    bdt = self._block_damage_targets if hasattr(self, '_block_damage_targets') and self._block_damage_targets else {}
                    damaged_units = []
                    seen_ids = set()
                    for units in bdt.values():
                        for u in units:
                            if u.unit_id not in seen_ids and u.is_alive:
                                seen_ids.add(u.unit_id)
                                damaged_units.append(u)
                    has_ailment = any(
                        any(d.effect_type.lower() in STATUS_AILMENT_TYPES for d in u.debuffs)
                        for u in damaged_units
                    )
                    if not has_ailment:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (target_has_status_ailment: no target has status ailment)",
                                  caster.name, block.block_id)
                        continue

                elif cond_type == 'self_has_mark':
                    mark_name = block_condition.get('mark_name', '')
                    has_mark = any(
                        b.effect_type == SkillEffectType.MARK.value and getattr(b, 'name', '') == mark_name
                        for b in caster.buffs
                    ) or any(
                        d.effect_type == SkillEffectType.MARK.value and getattr(d, 'name', '') == mark_name
                        for d in caster.debuffs
                    )
                    if not has_mark:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (self_has_mark '%s': not found)",
                                  caster.name, block.block_id, mark_name)
                        continue

                elif cond_type == 'self_lacks_mark':
                    mark_name = block_condition.get('mark_name', '')
                    has_mark = any(
                        b.effect_type == SkillEffectType.MARK.value and getattr(b, 'name', '') == mark_name
                        for b in caster.buffs
                    ) or any(
                        d.effect_type == SkillEffectType.MARK.value and getattr(d, 'name', '') == mark_name
                        for d in caster.debuffs
                    )
                    if has_mark:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (self_lacks_mark '%s': found, should lack)",
                                  caster.name, block.block_id, mark_name)
                        continue

                elif cond_type == 'mark_count':
                    mark_name = block_condition.get('mark_name', '')
                    op = block_condition.get('operator', '>=')
                    val = block_condition.get('value', 0)
                    # 追踪技能已攻击的所有目标单位，检查任一目标的mark数达标
                    bdt = self._block_damage_targets if hasattr(self, '_block_damage_targets') and self._block_damage_targets else {}
                    check_targets = []
                    seen_ids = set()
                    for units in bdt.values():
                        for u in units:
                            if u.unit_id not in seen_ids:
                                seen_ids.add(u.unit_id)
                                check_targets.append(u)
                    if not check_targets:
                        check_targets = [caster]
                    condition_met = False
                    for check_unit in check_targets:
                        mark_count = sum(1 for b in check_unit.debuffs
                                         if b.effect_type == SkillEffectType.MARK.value and b.name == mark_name)
                        mark_count += sum(1 for b in check_unit.buffs
                                          if b.effect_type == SkillEffectType.MARK.value and b.name == mark_name)
                        if _eval_block_condition(mark_count, op, val):
                            condition_met = True
                            self._mark_condition_target = check_unit  # 记录达标的目标，供后续效果使用
                            _log.info("[SKILL_EXEC] %s: mark_count '%s' on %s = %d %s %d -> PASS",
                                      caster.name, mark_name, check_unit.name, mark_count, op, val)
                            break
                    if not condition_met:
                        target_names = [u.name for u in check_targets]
                        _log.info("[SKILL_EXEC] %s: skipping block %d (mark_count '%s' on %s: no target met ≥%d)",
                                  caster.name, block.block_id, mark_name, target_names, val)
                        continue

                elif cond_type in ('target_has_mark', 'target_without_mark'):
                    mark_name = block_condition.get('mark_name', '')
                    # 检查已攻击的目标在技能执行前是否持有指定mark（当次攻击赋予的mark不算）
                    bdt = self._block_damage_targets if hasattr(self, '_block_damage_targets') and self._block_damage_targets else {}
                    marks_snapshot = getattr(self, '_marks_at_start_by_unit', {})
                    check_targets = []
                    seen_ids = set()
                    for units in bdt.values():
                        for u in units:
                            if u.unit_id not in seen_ids:
                                seen_ids.add(u.unit_id)
                                check_targets.append(u)
                    if not check_targets:
                        # PS 反击场景: _block_damage_targets 为空时，优先使用 _trigger_attacker
                        # (如 230386 鳴ノ硬直: after_as_attacked_ally 触发，检查攻击者是否持神鳴り mark)
                        trigger_attacker = getattr(self, '_trigger_attacker', None)
                        if trigger_attacker and trigger_attacker.is_alive:
                            check_targets = [trigger_attacker]
                            _log.info("[SKILL_EXEC] %s: %s using _trigger_attacker=%s as check target",
                                      caster.name, cond_type, trigger_attacker.name)
                        else:
                            # 缓存为空时（如PS技能执行中缓存被reset），回退到检查技能target_type对应的单位
                            # 如enemy_all → 检查所有敌方
                            first_effect = next((e for e in block.effects), None)
                            if first_effect and getattr(first_effect, 'target_type', '') == 'enemy_all':
                                check_targets = [u for u in battlefield.enemy_team if u.is_alive]
                            else:
                                check_targets = [caster]
                    condition_met = False
                    matched_targets = []
                    # target_has_mark: 至少一个目标持 mark; target_without_mark: 至少一个目标不持 mark
                    want_has = (cond_type == 'target_has_mark')
                    for check_unit in check_targets:
                        # 优先使用快照（技能执行前的mark状态），回退到当前状态
                        unit_marks_before = marks_snapshot.get(check_unit.unit_id, set())
                        has_mark = mark_name in unit_marks_before
                        if not has_mark:
                            # 回退：检查当前mark状态（兼容非当次赋予的场景）
                            has_mark = any(
                                d.effect_type == SkillEffectType.MARK.value and d.name == mark_name
                                for d in check_unit.debuffs
                            ) or any(
                                b.effect_type == SkillEffectType.MARK.value and b.name == mark_name
                                for b in check_unit.buffs
                            )
                        if has_mark == want_has:
                            condition_met = True
                            matched_targets.append(check_unit)
                            _log.info("[SKILL_EXEC] %s: %s '%s' on %s -> PASS (has_mark=%s, want_has=%s)",
                                      caster.name, cond_type, mark_name, check_unit.name, has_mark, want_has)
                    if matched_targets:
                        self._mark_condition_target = matched_targets[0]
                        self._mark_condition_targets = matched_targets
                    if not condition_met:
                        target_names = [u.name for u in check_targets]
                        _log.info("[SKILL_EXEC] %s: skipping block %d (%s '%s' on %s: no target matches)",
                                  caster.name, block.block_id, cond_type, mark_name, target_names)
                        continue

                elif cond_type == 'total_damage_le':
                    # 触发PS的技能总伤害 ≤ value 时执行（如「徹底的にやってやろうじゃん！」負けん気解除）
                    threshold = block_condition.get('value', 0)
                    total_dmg = getattr(self, '_trigger_total_damage', 0)
                    if total_dmg > threshold:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (total_damage_le: %d > %d)",
                                  caster.name, block.block_id, total_dmg, threshold)
                        continue
                    _log.info("[SKILL_EXEC] %s: block %d total_damage_le PASS (%d <= %d)",
                              caster.name, block.block_id, total_dmg, threshold)

                elif cond_type == 'caster_back_row':
                    # 施法者处于后排时执行（如「粛清です」block2: 后排时对前排友方追加伤害）
                    from ...entities_v2.enums import Position as _PosCbr
                    back_positions = {
                        _PosCbr.ALLY_LEFT_BACK, _PosCbr.ALLY_CENTER_BACK, _PosCbr.ALLY_RIGHT_BACK,
                        _PosCbr.ENEMY_LEFT_BACK, _PosCbr.ENEMY_CENTER_BACK, _PosCbr.ENEMY_RIGHT_BACK,
                    }
                    if caster.position not in back_positions:
                        _log.info("[SKILL_EXEC] %s: skipping block %d (caster_back_row: position=%s not back)",
                                  caster.name, block.block_id, caster.position)
                        continue
                    _log.info("[SKILL_EXEC] %s: block %d caster_back_row PASS (position=%s)",
                              caster.name, block.block_id, caster.position)

            level_min_val = block_condition.get('level_min') if isinstance(block_condition, dict) else None
            level_max_val = block_condition.get('level_max') if isinstance(block_condition, dict) else None
            if level_min_val is not None or level_max_val is not None:
                skill_level = caster.skill_levels.get(skill_id, 1)
                if level_min_val is not None and skill_level < level_min_val:
                    _log.info("[SKILL_EXEC] %s: skipping block %d (level %d < min %d)",
                              caster.name, block.block_id, skill_level, level_min_val)
                    continue
                if level_max_val is not None and skill_level > level_max_val:
                    _log.info("[SKILL_EXEC] %s: skipping block %d (level %d > max %d)",
                              caster.name, block.block_id, skill_level, level_max_val)
                    continue

            alive_before = set(u.unit_id for u in battlefield.get_all_units() if u.current_hp > 0)
            block_deferred = []
            block_hp_threshold_deferred = []

            self._block_damage_targets = {}
            self._block_evaded_targets = set()  # block级别重置，但伤害结算后会累积到_skill_evaded_targets
            self._pre_damage_hp = {}  # 保存伤害前HP，用于target_hp_below条件（基于伤害前HP判定）
            # 重置该block的累计伤害（供 split_heal_by_damage 读取）
            self._current_block_id = block.block_id
            self._block_damage_total[block.block_id] = 0
            # 若mark_count/target_has_mark条件命中目标，将目标填入所有效果使用的目标类型
            # 但不覆盖enemy_all/ally_all等范围型target_type（如ポストリュード：damage应打全体而非仅乱調持有者）
            mark_targets = getattr(self, '_mark_condition_targets', None)
            mark_target = getattr(self, '_mark_condition_target', None)
            if mark_targets:
                for effect in block.effects:
                    et = getattr(effect, 'target_type', None)
                    if et and et not in self._block_damage_targets:
                        if et in ('enemy_all', 'ally_all', 'enemies'):
                            continue  # 范围型不覆盖
                        self._block_damage_targets[et] = list(mark_targets)
                _log.info("[SKILL_EXEC] %s: block %d using mark_condition_targets=%s",
                          caster.name, block.block_id, [t.name for t in mark_targets])
                self._mark_condition_targets = None
                self._mark_condition_target = None
            elif mark_target is not None:
                for effect in block.effects:
                    et = getattr(effect, 'target_type', None)
                    if et and et not in self._block_damage_targets:
                        if et in ('enemy_all', 'ally_all', 'enemies'):
                            continue  # 范围型不覆盖
                        self._block_damage_targets[et] = [mark_target]
                self._mark_condition_target = None
                _log.info("[SKILL_EXEC] %s: block %d using mark_condition_target=%s",
                          caster.name, block.block_id, mark_target.name)
            block_has_damage = any(getattr(e, 'effect_type', None) == 'damage' for e in block.effects)
            for effect in block.effects:
                if getattr(effect, 'condition', None) and isinstance(effect.condition, dict):
                    if effect.condition.get('type') == 'target_killed':
                        continue
                if effect.effect_type == "damage":
                    # debuff_applied_target uses _primary_target, not select_targets; skip pre-population
                    if effect.target_type == "debuff_applied_target":
                        continue
                    # trigger_attacker uses _trigger_attacker; pre-populate with attacker instead of default targeting
                    target_identifier = getattr(effect, 'target_identifier', None)
                    if target_identifier == "trigger_attacker":
                        trigger_attacker = getattr(self, '_trigger_attacker', None)
                        if trigger_attacker and trigger_attacker.is_alive:
                            self._block_damage_targets[effect.target_type] = [trigger_attacker]
                            _log.info("[SKILL_EXEC] %s: using trigger_attacker=%s as damage target (pre-populate)",
                                      caster.name, trigger_attacker.name)
                            continue
                        # trigger_attacker not available, fall through to default targeting
                    effect_flags_block = getattr(effect, 'flags', {}) or {}
                    target_count = effect_flags_block.get('target_count', 1)

                    # is_follow_up 追撃型PS（如 チェイスブレイダー/ポイズンチェイス）：
                    # 当 _primary_target 由触发上下文传入时（PS触发场景），追击AS主目标而非重新索敌。
                    # AS技能内部的 is_follow_up（如 hp_threshold_cross 追加攻撃）不触发此分支，
                    # 因为 AS 执行时 _primary_target 为 None，会继续走下方的缓存/索敵逻辑。
                    if effect_flags_block.get('is_follow_up', False):
                        _ps_primary = getattr(self, '_primary_target', None)
                        if (_ps_primary is not None and _ps_primary.is_alive
                                and _ps_primary.side != caster.side):
                            self._block_damage_targets[effect.target_type] = [_ps_primary]
                            self._last_primary_target = _ps_primary
                            _log.info("[SKILL_EXEC] %s: is_follow_up using _primary_target=%s as damage target",
                                      caster.name, _ps_primary.name)
                            continue

                    # 如果缓存中的目标数量与当前效果需要的不同，且不是追击类效果，删除缓存重新索敌
                    if effect.target_type in self._block_damage_targets:
                        cached = self._block_damage_targets[effect.target_type]
                        is_follow_up = effect_flags_block.get('is_follow_up', False)
                        if not is_follow_up and len(cached) != target_count:
                            del self._block_damage_targets[effect.target_type]

                    if effect.target_type not in self._block_damage_targets:
                        if effect.target_type == "attacked_targets":
                            # 使用当前block中已攻击的所有目标
                            all_attacked = []
                            seen = set()
                            for units in self._block_damage_targets.values():
                                for u in units:
                                    if u.unit_id not in seen and u.is_alive:
                                        seen.add(u.unit_id)
                                        all_attacked.append(u)
                            self._block_damage_targets[effect.target_type] = all_attacked
                            _log.info("[SKILL_EXEC] %s: attacked_targets: %d targets %s",
                                      caster.name, len(all_attacked), [u.name for u in all_attacked])
                        elif effect.target_type == "enemy_all_except_last":
                            tso = type('obj', (object,), {
                                'display_target_type': self._resolve_target_type("enemies"),
                                'display_target_range': self._resolve_target_range("enemies"),
                                'display_target_priority': self._current_skill_priority,
                            })()
                            all_targets = self.target_service.select_targets(tso, caster, battlefield)
                            exclude_ids = getattr(self, '_previous_damage_target_ids', set())
                            self._block_damage_targets[effect.target_type] = [
                                t for t in all_targets if t.unit_id not in exclude_ids
                            ]
                            _log.info("[SKILL_EXEC] %s: enemy_all_except_last: all=%d exclude=%s filtered=%d",
                                      caster.name, len(all_targets), exclude_ids,
                                      len(self._block_damage_targets[effect.target_type]))
                        elif effect.target_type == "adjacent_enemies":
                            # 基于主目标(enemy_single等)的位置选择邻接敌方单位
                            # 注意：必须在target_count>1分支之前检查，否则adjacent_enemies+target_count>1会被错误地用通用多目标逻辑处理
                            # 优先使用_block_damage_targets中的enemy_single类目标，其次使用_last_primary_target（跨block引用）
                            primary_target = None
                            for _pk in ("enemy_single", "enemy_single_furthest", "enemy_single_nearest"):
                                if _pk in self._block_damage_targets:
                                    primary_list = self._block_damage_targets[_pk]
                                    if primary_list:
                                        primary_target = primary_list[0]
                                        break
                            if primary_target is None and hasattr(self, '_last_primary_target') and self._last_primary_target:
                                primary_target = self._last_primary_target
                                _log.info("[SKILL_EXEC] %s: adjacent_enemies using _last_primary_target=%s",
                                          caster.name, primary_target.name)
                            if primary_target:
                                adj_targets = self.target_service.get_adjacent_to_unit(
                                    primary_target, battlefield, caster
                                )
                            else:
                                target_skill_obj = type('obj', (object,), {
                                    'display_target_type': self._resolve_target_type(effect.target_type),
                                    'display_target_range': self._resolve_target_range(effect.target_type),
                                    'display_target_priority': self._current_skill_priority,
                                    'target_type_name': effect.target_type,
                                })()
                                adj_targets = self.target_service.select_targets(
                                    target_skill_obj, caster, battlefield
                                )
                            _adj_explicit_count = effect_flags_block.get('target_count', 0)
                            if _adj_explicit_count > 0:
                                self._block_damage_targets[effect.target_type] = adj_targets[:_adj_explicit_count]
                            else:
                                self._block_damage_targets[effect.target_type] = adj_targets
                            _log.info("[SKILL_EXEC] %s: adjacent_enemies target select: count=%d targets=%s",
                                      caster.name, len(self._block_damage_targets[effect.target_type]), [t.name for t in self._block_damage_targets[effect.target_type]])
                        elif effect.target_type == "adjacent_to_nearest_enemy":
                            # 基于"自身最近敌人"的位置选择邻接敌方单位（不同于adjacent_enemies基于攻击主目标）
                            # 注意：必须在target_count>1分支之前检查，原因同adjacent_enemies
                            # 先找到距离自身最近的敌方
                            from ...entities_v2.enums import Side
                            enemy_side = Side.ENEMY if caster.side == Side.ALLY else Side.ALLY
                            enemies = [u for u in battlefield.get_alive_units(enemy_side)]
                            if enemies:
                                nearest = self.target_service.get_nearest_enemy(caster, enemies)
                                if nearest:
                                    adj_targets = self.target_service.get_adjacent_to_unit(
                                        nearest, battlefield, caster
                                    )
                                else:
                                    adj_targets = []
                            else:
                                adj_targets = []
                            self._block_damage_targets[effect.target_type] = adj_targets[:target_count]
                            _log.info("[SKILL_EXEC] %s: adjacent_to_nearest_enemy target select: count=%d targets=%s",
                                      caster.name, target_count, [t.name for t in self._block_damage_targets[effect.target_type]])
                        elif target_count > 1 or effect_flags_block.get('lowest_hp_priority'):
                            enemy_side = battlefield.enemy_team if caster.side == battlefield.friend_team[0].side else battlefield.friend_team
                            enemies = [u for u in enemy_side if u.is_alive]
                            if effect_flags_block.get('lowest_hp_priority') and target_count > 1:
                                primary_skill_obj = type('obj', (object,), {
                                    'display_target_type': self._resolve_target_type(effect.target_type),
                                    'display_target_range': 1,
                                    'display_target_priority': 0,
                                })()
                                primary_targets = self.target_service.select_targets(
                                    primary_skill_obj, caster, battlefield
                                )
                                primary = primary_targets[0] if primary_targets else None
                                if primary:
                                    remaining = [u for u in enemies if u.unit_id != primary.unit_id]
                                    remaining.sort(key=lambda u: self._get_distance_key(primary, u))
                                    self._block_damage_targets[effect.target_type] = [primary] + remaining[:target_count - 1]
                                    _log.info("[SKILL_EXEC] %s: custom target select: primary=%s lowest_hp=True count=%d targets=%s",
                                              caster.name, primary.name, target_count,
                                              [t.name for t in self._block_damage_targets[effect.target_type]])
                                else:
                                    enemies.sort(key=lambda u: u.current_hp)
                                    self._block_damage_targets[effect.target_type] = enemies[:target_count]
                            elif effect_flags_block.get('lowest_hp_priority'):
                                # 按HP比例排序（最低优先），找到最低HP比例的敌方
                                enemies.sort(key=lambda u: u.current_hp / max(u.max_hp, 1))
                                lowest_hp_enemy = enemies[0] if enemies else None
                                if lowest_hp_enemy and effect.target_type == "enemy_row":
                                    # 根据最低HP比例敌方的位置确定横列（前排/后排）
                                    from src.entities_v2.enums import Position as _Pos
                                    lowest_pos = lowest_hp_enemy.position
                                    # 判断是前排还是后排
                                    is_front = lowest_pos in (
                                        _Pos.ENEMY_LEFT_FRONT, _Pos.ENEMY_CENTER_FRONT, _Pos.ENEMY_RIGHT_FRONT
                                    )
                                    if is_front:
                                        row_positions = {_Pos.ENEMY_LEFT_FRONT, _Pos.ENEMY_CENTER_FRONT, _Pos.ENEMY_RIGHT_FRONT}
                                    else:
                                        row_positions = {_Pos.ENEMY_LEFT_BACK, _Pos.ENEMY_CENTER_BACK, _Pos.ENEMY_RIGHT_BACK}
                                    row_enemies = [u for u in enemies if u.position in row_positions]
                                    self._block_damage_targets[effect.target_type] = row_enemies
                                    _log.info("[SKILL_EXEC] %s: custom target select: lowest_hp=%s (hp_pct=%.1f%%) row=%s targets=%s",
                                              caster.name, lowest_hp_enemy.name,
                                              lowest_hp_enemy.current_hp / max(lowest_hp_enemy.max_hp, 1) * 100,
                                              "front" if is_front else "back",
                                              [t.name for t in row_enemies])
                                else:
                                    self._block_damage_targets[effect.target_type] = enemies[:target_count]
                                _log.info("[SKILL_EXEC] %s: custom target select: lowest_hp=%s count=%d targets=%s",
                                          caster.name, effect_flags_block.get('lowest_hp_priority'),
                                          target_count, [t.name for t in self._block_damage_targets[effect.target_type]])
                            else:
                                # target_count > 1 但没有 lowest_hp_priority：先选主目标，再按距离选最近目标
                                primary_skill_obj = type('obj', (object,), {
                                    'display_target_type': self._resolve_target_type(effect.target_type),
                                    'display_target_range': 1,
                                    'display_target_priority': self._current_skill_priority,
                                })()
                                primary_targets = self.target_service.select_targets(
                                    primary_skill_obj, caster, battlefield
                                )
                                primary = primary_targets[0] if primary_targets else None
                                if primary:
                                    remaining = [u for u in enemies if u.unit_id != primary.unit_id]
                                    remaining.sort(key=lambda u: self._get_distance_key(primary, u))
                                    self._block_damage_targets[effect.target_type] = [primary] + remaining[:target_count - 1]
                                else:
                                    self._block_damage_targets[effect.target_type] = enemies[:target_count]
                                _log.info("[SKILL_EXEC] %s: multi-target select: target_count=%d targets=%s",
                                          caster.name, target_count,
                                          [t.name for t in self._block_damage_targets[effect.target_type]])
                        else:
                            # 默认索敌逻辑
                            # For highest_atk/highest_spd/furthest, get ALL candidates first then filter
                            if effect.target_type and (effect.target_type == "enemy_single_highest_atk" or effect.target_type == "enemy_single_highest_spd" or effect.target_type == "enemy_single_lowest_spd" or effect.target_type == "enemy_single_furthest" or effect.target_type == "enemy_single_highest_ep" or effect.target_type == "enemy_single_highest_hp_ratio" or effect.target_type == "enemy_single_highest_current_hp" or effect.target_type == "enemy_single_highest_hp_ratio_back_priority" or effect.target_type == "enemy_single_lowest_hp_ratio" or effect.target_type == "enemy_column_furthest" or effect.target_type == "enemy_column_mark_priority"):
                                all_candidates_skill_obj = type('obj', (object,), {
                                    'display_target_type': self._resolve_target_type(effect.target_type),
                                    'display_target_range': self._resolve_target_range("enemies"),  # get all enemies
                                    'display_target_priority': self._current_skill_priority,
                                    'target_type_name': effect.target_type,
                                })()
                                all_candidates = self.target_service.select_targets(
                                    all_candidates_skill_obj, caster, battlefield
                                )
                                self._block_damage_targets[effect.target_type] = all_candidates
                                _log.info("[SKILL_EXEC] %s: highest_atk/highest_spd/furthest candidates=%d: %s",
                                          caster.name, len(all_candidates), [t.name for t in all_candidates])
                            else:
                                # 默认索敌逻辑
                                if target_count > 1:
                                    # target_count > 1时：先选主目标，再按距离选最近目标
                                    enemy_side = battlefield.enemy_team if caster.side == battlefield.friend_team[0].side else battlefield.friend_team
                                    enemies = [u for u in enemy_side if u.is_alive]
                                    primary_skill_obj = type('obj', (object,), {
                                        'display_target_type': self._resolve_target_type(effect.target_type),
                                        'display_target_range': 1,
                                        'display_target_priority': self._current_skill_priority,
                                    })()
                                    primary_targets = self.target_service.select_targets(
                                        primary_skill_obj, caster, battlefield
                                    )
                                    primary = primary_targets[0] if primary_targets else None
                                    if primary:
                                        remaining = [u for u in enemies if u.unit_id != primary.unit_id]
                                        remaining.sort(key=lambda u: self._get_distance_key(primary, u))
                                        self._block_damage_targets[effect.target_type] = [primary] + remaining[:target_count - 1]
                                    else:
                                        self._block_damage_targets[effect.target_type] = enemies[:target_count]
                                    _log.info("[SKILL_EXEC] %s: multi-target select: target_count=%d targets=%s",
                                              caster.name, target_count,
                                              [t.name for t in self._block_damage_targets[effect.target_type]])
                                else:
                                    target_skill_obj = type('obj', (object,), {
                                        'display_target_type': self._resolve_target_type(effect.target_type),
                                        'display_target_range': self._resolve_target_range(effect.target_type),
                                        'display_target_priority': self._current_skill_priority,
                                        'target_type_name': effect.target_type,
                                        'mark_priority': effect_flags_block.get('mark_priority'),
                                    })()
                                    # fewest_mark_priority: 从所有存活敌方中選択持有指定mark最少的单位
                                    _fewest_mark_pre = effect_flags_block.get('fewest_mark_priority')
                                    if _fewest_mark_pre and effect.target_type in ("enemy_single", "enemies", "enemy"):
                                        # 获取所有存活敌方候选
                                        enemy_side = battlefield.enemy_team if caster.side == battlefield.friend_team[0].side else battlefield.friend_team
                                        _all_candidates = [u for u in enemy_side if u.is_alive]
                                        _best = self.target_service.select_fewest_mark_target(
                                            caster, _all_candidates, _fewest_mark_pre
                                        )
                                        self._block_damage_targets[effect.target_type] = [_best] if _best else []
                                        _log.info("[SKILL_EXEC] %s: fewest_mark_priority='%s' pre-populate -> %s",
                                                  caster.name, _fewest_mark_pre,
                                                  [t.name for t in self._block_damage_targets[effect.target_type]])
                                    else:
                                        self._block_damage_targets[effect.target_type] = self.target_service.select_targets(
                                            target_skill_obj, caster, battlefield
                                        )

                    # Post-filter for highest_atk/highest_spd target types
                    # ステルス消費：特殊索敌类型的第一優先対象がステルス所持時、末尾に移動してステルス消費
                    dmg_targets = self._block_damage_targets.get(effect.target_type, [])
                    if effect.target_type and "highest_atk" in effect.target_type and dmg_targets:
                        best = self.target_service.select_max_with_stealth(
                            dmg_targets,
                            key_func=lambda u: self.damage_service._calculate_final_stat(u, "attack") if self.damage_service else u.attack,
                            consume=True
                        )
                        dmg_targets = [best] if best else []
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        best_atk = self.damage_service._calculate_final_stat(best, "attack") if self.damage_service else best.attack
                        _log.info("[SKILL_EXEC] %s: highest_atk filter -> %s (atk=%d)",
                                  caster.name, best.name, best_atk)
                    elif effect.target_type and "highest_spd" in effect.target_type and dmg_targets:
                        best = self.target_service.select_max_with_stealth(
                            dmg_targets,
                            key_func=lambda u: self.damage_service._calculate_final_stat(u, "speed") if self.damage_service else u.speed,
                            consume=True
                        )
                        dmg_targets = [best] if best else []
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        best_spd = self.damage_service._calculate_final_stat(best, "speed") if self.damage_service else best.speed
                        _log.info("[SKILL_EXEC] %s: highest_spd filter -> %s (spd=%d)",
                                  caster.name, best.name, best_spd)
                    elif effect.target_type and "lowest_spd" in effect.target_type and dmg_targets:
                        best = self.target_service.select_min_with_stealth(
                            dmg_targets,
                            key_func=lambda u: self.damage_service._calculate_final_stat(u, "speed") if self.damage_service else u.speed,
                            consume=True
                        )
                        dmg_targets = [best] if best else []
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        best_spd = self.damage_service._calculate_final_stat(best, "speed") if self.damage_service else best.speed
                        _log.info("[SKILL_EXEC] %s: lowest_spd filter -> %s (spd=%d)",
                                  caster.name, best.name, best_spd)
                    elif effect.target_type and "furthest" in effect.target_type and "column_furthest" not in effect.target_type and dmg_targets:
                        # 选择距施法者最远的敌方（基于列参考点的曼哈顿距离）
                        best = self.target_service.select_min_with_stealth(
                            dmg_targets,
                            key_func=lambda u: self._get_farthest_key(caster.position, u),
                            consume=True
                        )
                        dmg_targets = [best] if best else []
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        _log.info("[SKILL_EXEC] %s: furthest filter -> %s",
                                  caster.name, best.name)
                    elif effect.target_type and "highest_ep" in effect.target_type and dmg_targets:
                        best = self.target_service.select_max_with_stealth(
                            dmg_targets,
                            key_func=lambda u: u.current_ep,
                            consume=True
                        )
                        dmg_targets = [best] if best else []
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        _log.info("[SKILL_EXEC] %s: highest_ep filter -> %s (ep=%d)",
                                  caster.name, best.name, best.current_ep)
                    elif effect.target_type == "enemy_single_highest_hp_ratio_back_priority" and dmg_targets:
                        # 後列優先でHP割合最高：先从后排选HP百分比最高，后排没人则从前排选
                        back_targets = [u for u in dmg_targets if self.target_service._is_back_row(u)]
                        search_pool = back_targets if back_targets else dmg_targets
                        best = self.target_service.select_max_with_stealth(
                            search_pool,
                            key_func=lambda u: (u.current_hp / u.max_hp) if u.max_hp > 0 else 0,
                            consume=True
                        )
                        dmg_targets = [best] if best else []
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        _log.info("[SKILL_EXEC] %s: highest_hp_ratio_back_priority filter -> %s",
                                  caster.name, best.name)
                    elif effect.target_type == "enemy_single_highest_hp_ratio" and dmg_targets:
                        best = self.target_service.select_max_with_stealth(
                            dmg_targets,
                            key_func=lambda u: (u.current_hp / u.max_hp) if u.max_hp > 0 else 0,
                            consume=True
                        )
                        dmg_targets = [best] if best else []
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        _log.info("[SKILL_EXEC] %s: highest_hp_ratio filter -> %s",
                                  caster.name, best.name)
                    elif effect.target_type == "enemy_single_highest_current_hp" and dmg_targets:
                        best = self.target_service.select_max_with_stealth(
                            dmg_targets,
                            key_func=lambda u: u.current_hp,
                            consume=True
                        )
                        dmg_targets = [best] if best else []
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        _log.info("[SKILL_EXEC] %s: highest_current_hp filter -> %s (hp=%d)",
                                  caster.name, best.name, best.current_hp)
                    elif effect.target_type == "enemy_single_lowest_hp_ratio" and dmg_targets:
                        # 使用技能开始时的HP快照计算HP百分比，确保跨block比较的是同一时刻的HP
                        pre_hp_snapshot = getattr(self, '_pre_skill_hp', {})
                        best = self.target_service.select_min_with_stealth(
                            dmg_targets,
                            key_func=lambda u: (pre_hp_snapshot.get(u.unit_id, u.current_hp) / u.max_hp) if u.max_hp > 0 else 0,
                            consume=True
                        )
                        dmg_targets = [best] if best else []
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        _log.info("[SKILL_EXEC] %s: lowest_hp_ratio filter -> %s (using pre-skill HP)",
                                  caster.name, best.name)
                    elif effect.target_type == "enemy_column_furthest" and dmg_targets:
                        # 先找最远的敌方，然后选其所在的列（前后列/纵列）
                        # ステルス重定向应用于锚点选择
                        anchor = self.target_service.select_min_with_stealth(
                            dmg_targets,
                            key_func=lambda u: self._get_farthest_key(caster.position, u),
                            consume=True
                        )
                        if anchor is None:
                            anchor_col = -1
                            dmg_targets = []
                        else:
                            anchor_col = self.target_service._get_column_index(anchor)
                            dmg_targets = [u for u in dmg_targets if self.target_service._get_column_index(u) == anchor_col]
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        _log.info("[SKILL_EXEC] %s: column_furthest filter -> col=%d targets=%s",
                                  caster.name, anchor_col, [t.name for t in dmg_targets])
                    elif effect.target_type == "enemy_column_mark_priority" and dmg_targets:
                        # 优先选择有标记的敌方所在列（前后列/纵列）
                        # 有标记时从标记单位中按默认索敌选最近，无标记时从所有敌方中选最近
                        # ステルス重定向应用于锚点选择
                        mark_name = effect_flags_block.get('mark_priority', 'サンタタグ')
                        marked_units = [u for u in dmg_targets if any(
                            getattr(b, 'name', '') == mark_name and getattr(b, 'effect_type', '').lower() == 'mark'
                            for b in ((u.buffs or []) + (u.debuffs or []))
                        )]
                        candidates = marked_units if marked_units else dmg_targets
                        anchor = self.target_service.select_min_with_stealth(
                            candidates,
                            key_func=lambda u: self._get_distance_key(caster, u),
                            consume=True
                        )
                        if anchor is None:
                            anchor_col = -1
                            dmg_targets = []
                        else:
                            anchor_col = self.target_service._get_column_index(anchor)
                            dmg_targets = [u for u in dmg_targets if self.target_service._get_column_index(u) == anchor_col]
                        self._block_damage_targets[effect.target_type] = dmg_targets
                        _log.info("[SKILL_EXEC] %s: column_mark_priority filter -> mark=%s found=%d col=%d targets=%s",
                                  caster.name, mark_name, len(marked_units), anchor_col, [t.name for t in dmg_targets])

                    # 记录enemy_single的主目标，供后续block的adjacent_enemies引用
                    if effect.target_type == "enemy_single" and effect.target_type in self._block_damage_targets:
                        es_list = self._block_damage_targets[effect.target_type]
                        if es_list:
                            self._last_primary_target = es_list[0]
                            _log.info("[SKILL_EXEC] %s: recorded _last_primary_target=%s",
                                      caster.name, es_list[0].name)

                    # 记录ally_single的主目标（如lowest_hp_priority的heal目标），供后续block引用
                    if effect.target_type == "ally_single" and effect_flags.get('lowest_hp_priority'):
                        if effect.target_type in self._block_damage_targets:
                            as_list = self._block_damage_targets[effect.target_type]
                            if as_list:
                                self._last_primary_target = as_list[0]
                                _log.info("[SKILL_EXEC] %s: recorded _last_primary_target (ally_single)=%s",
                                          caster.name, as_list[0].name)

            # 保存伤害前HP，用于target_hp_below条件（基于伤害前HP判定）
            for _tt_key, _dt_list in self._block_damage_targets.items():
                for _dt in _dt_list:
                    if _dt.unit_id not in self._pre_damage_hp:
                        self._pre_damage_hp[_dt.unit_id] = _dt.current_hp

            for effect in block.effects:
                has_kill_condition = False
                has_hp_threshold_cross = False
                if getattr(effect, 'condition', None) and isinstance(effect.condition, dict):
                    if effect.condition.get('type') == 'target_killed':
                        has_kill_condition = True
                    if effect.condition.get('type') == 'hp_threshold_cross':
                        has_hp_threshold_cross = True

                if has_kill_condition:
                    block_deferred.append(effect)
                    _log.info("[SKILL_EXEC] %s: deferring effect_type=%s (target_killed condition)",
                              caster.name, effect.effect_type)
                    continue

                # hp_threshold_cross条件的add_status效果延迟到附魔伤害结算后执行
                # 这样眩晕条件判断会基于攻击+附魔伤害后的最终HP
                if has_hp_threshold_cross and block_has_damage:
                    block_hp_threshold_deferred.append(effect)
                    _log.info("[SKILL_EXEC] %s: deferring effect_type=%s (hp_threshold_cross, after enchant)",
                              caster.name, effect.effect_type)
                    continue

                applied = self._apply_effect(caster, effect, battlefield)
                if applied:
                    result["effects_applied"].append(applied)
                    if "damage" in applied:
                        result["total_damage"] += applied["damage"]
                    # 附魔伤害+sub_unit伤害紧跟主伤害结算（绑定在一起）
                    # 主伤害全段miss时_enchant_skip标记会跳过附魔，确保miss不触发附魔
                    if applied.get("effect_type") == "damage":
                        _dmg_targets = applied.get("targets", [])
                        if _dmg_targets:
                            _enchant_results = self._apply_block_enchant_damage(
                                caster, _dmg_targets, battlefield, result["total_damage"])
                            if _enchant_results:
                                for _er in _enchant_results:
                                    result["effects_applied"].append(_er)
                                    if _er.get("effect_type") == "damage":
                                        result["total_damage"] = _er["total_damage"]

            # Note: _block_damage_targets is NOT cleared here, so that subsequent blocks
            # in the same skill can reuse the cached targets (e.g., aura effects in block 3
            # should target the same unit as damage in block 2). It will be cleared after
            # all blocks are processed.

            # 附魔伤害已紧跟每个damage效果结算，此处执行延迟的hp_threshold_cross效果
            for effect in block_hp_threshold_deferred:
                _log.info("[SKILL_EXEC] %s: applying deferred hp_threshold_cross effect_type=%s (after enchant damage)",
                          caster.name, effect.effect_type)
                applied = self._apply_effect(caster, effect, battlefield)
                if applied:
                    result["effects_applied"].append(applied)
                    if "damage" in applied:
                        result["total_damage"] += applied["damage"]

            alive_after = set(u.unit_id for u in battlefield.get_all_units() if u.current_hp > 0)
            block_kills = alive_before - alive_after
            kills_occurred = kills_occurred or len(block_kills) > 0
            _log.info("[SKILL_EXEC] %s: block kills=%d, alive_before=%d alive_after=%d",
                      caster.name, len(block_kills), len(alive_before), len(alive_after))

            # 保存当前block的攻击目标，供后续block的target_survived条件使用
            if self._block_damage_targets:
                self._prev_block_damage_targets = dict(self._block_damage_targets)
                _log.info("[SKILL_EXEC] %s: saved _prev_block_damage_targets for next block: %s",
                          caster.name, {tt: [t.name for t in ts] for tt, ts in self._prev_block_damage_targets.items()})
                # 累积技能级别所有已攻击目标（用于跨block的attacked_targets target_type）
                for _dt_list in self._block_damage_targets.values():
                    for _dt in _dt_list:
                        if _dt.unit_id not in {u.unit_id for u in self._skill_all_attacked_targets} and _dt.is_alive:
                            self._skill_all_attacked_targets.append(_dt)

            for effect in block_deferred:
                self._skill_kills = len(block_kills) > 0
                if not self._skill_kills:
                    _log.info("[SKILL_EXEC] %s: skipping deferred effect=%s (no kills in block)",
                              caster.name, effect.effect_type)
                    continue
                applied = self._apply_effect(caster, effect, battlefield)
                if applied:
                    result["effects_applied"].append(applied)
                    if "damage" in applied:
                        result["total_damage"] += applied["damage"]

        self._skill_kills = False

        # 执行延迟的on_crit块：在所有正常block执行完毕后、attack_limited cleanup之前执行
        # 这样追加伤害（如110002第6hit）能与主伤害共享同一技能内的debuff（如ふわとろのきもち的50%易伤）
        # 按target去重：同一目标多次暴击只处理一次，避免重复施加易伤/追加伤害
        if self._deferred_on_crit_targets:
            _seen_crit_targets = set()
            for entry in self._deferred_on_crit_targets:
                c, t, bf, eff = entry
                if t.unit_id in _seen_crit_targets:
                    continue
                _seen_crit_targets.add(t.unit_id)
                self._apply_on_crit_blocks(c, t, bf, eff)
            self._deferred_on_crit_targets.clear()

        # Attack-limited debuff cleanup: consumed once per skill execution (all blocks' hits affected)
        # Only consume if this skill actually dealt damage. Non-damage skills (e.g. PS buffs
        # triggered inline) should not consume attack_limited debuffs.
        if result["total_damage"] > 0:
            # Collect units that were attacked in this skill
            attacked_unit_ids = set()
            # Collect units that fully evaded all hits (attack_limited debuffs should NOT be consumed)
            fully_evaded_unit_ids = set()
            for applied in result.get("effects_applied", []):
                if applied.get("effect_type") == "damage":
                    for t in applied.get("targets", []):
                        tid = t.get("target_id")
                        if tid:
                            attacked_unit_ids.add(tid)
                            # Check if this target fully evaded all hits
                            hit_evades = t.get("hit_evades", [])
                            if hit_evades and all(hit_evades):
                                fully_evaded_unit_ids.add(tid)
                                _log.info("[ATTACK_LIMITED] %s fully evaded, attack_limited debuffs will NOT be consumed", tid)
            # Buffs with attack_limited on the caster should also be consumed
            # (e.g. 怒髪衝天's dmg_dealt_up only lasts for the current skill)
            caster_only_buff_cleanup = set()
            if caster and caster.is_alive:
                caster_only_buff_cleanup.add(caster.unit_id)
            for unit in battlefield.get_all_units():
                if not unit.is_alive:
                    continue
                # Only consume attack_limited debuffs on units that were actually attacked
                # BUT skip units that fully evaded all hits (attack missed -> debuff not consumed)
                if unit.unit_id in attacked_unit_ids and unit.unit_id not in fully_evaded_unit_ids:
                    for debuff in list(unit.debuffs):
                        if debuff.attack_limited > 0 and debuff.buff_id not in self._debuffs_applied_this_skill:
                            # dmg_dealt_down should be consumed when the unit ATTACKS (not when attacked)
                            if debuff.effect_type in (SkillEffectType.DEALT_DAMAGE.value,):
                                continue
                            debuff.attack_limited -= 1
                            _log.info("[ATTACK_LIMITED] %s: debuff %s attack_limited %d->%d",
                                      unit.name, debuff.effect_type, debuff.attack_limited + 1, debuff.attack_limited)
                            if debuff.attack_limited <= 0:
                                unit.debuffs = [d for d in unit.debuffs if d.buff_id != debuff.buff_id]
                                _log.info("[ATTACK_LIMITED] %s: debuff %s EXPIRED (attack_limited reached 0)", unit.name, debuff.effect_type)
                # Attack-limited buff cleanup: on attacked units AND caster
                # Shield buffs with attack_limited should ONLY be consumed when the unit is ATTACKED,
                # not when the unit (as caster) attacks others.
                is_attacked = unit.unit_id in attacked_unit_ids
                is_caster_only = unit.unit_id in caster_only_buff_cleanup and not is_attacked
                if is_attacked or is_caster_only:
                    for buff in list(unit.buffs):
                        if buff.attack_limited > 0:
                            # Shield buffs with attack_limited are consumed per-block in _apply_damage,
                            # skip here to avoid double consumption
                            if buff.effect_type in ("shield", "Shield"):
                                continue
                            # Shield/ReceivedDamage buffs only consume attack_limited when actually attacked
                            # (not when the unit as caster attacks others)
                            if is_caster_only and buff.effect_type in (SkillEffectType.RECEIVED_DAMAGE.value,):
                                continue
                            buff.attack_limited -= 1
                            _log.info("[ATTACK_LIMITED] %s: buff %s attack_limited %d->%d",
                                      unit.name, buff.effect_type, buff.attack_limited + 1, buff.attack_limited)
                            if buff.attack_limited <= 0:
                                unit.buffs = [b for b in unit.buffs if b.buff_id != buff.buff_id]
                                _log.info("[ATTACK_LIMITED] %s: buff %s EXPIRED (attack_limited reached 0)", unit.name, buff.effect_type)
                    # Attack-limited debuff cleanup on CASTER: dmg_dealt_down should be consumed
                    # when the caster attacks (performs an offensive action)
                    if is_caster_only:
                        for debuff in list(unit.debuffs):
                            if debuff.attack_limited > 0 and debuff.buff_id not in self._debuffs_applied_this_skill:
                                # dmg_dealt_down consumed when the unit attacks
                                if debuff.effect_type in (SkillEffectType.DEALT_DAMAGE.value,):
                                    debuff.attack_limited -= 1
                                    _log.info("[ATTACK_LIMITED] %s: caster debuff %s attack_limited %d->%d (consumed on attack)",
                                              unit.name, debuff.effect_type, debuff.attack_limited + 1, debuff.attack_limited)
                                    if debuff.attack_limited <= 0:
                                        unit.debuffs = [d for d in unit.debuffs if d.buff_id != debuff.buff_id]
                                        _log.info("[ATTACK_LIMITED] %s: caster debuff %s EXPIRED (attack_limited reached 0)", unit.name, debuff.effect_type)

        # 延迟阵亡判定：技能完整结算后，统一设置 is_alive=False
        if self._pending_deaths:
            _log.info("[SKILL_EXEC] %s: processing %d pending deaths", caster.name, len(self._pending_deaths))
            for unit in battlefield.get_all_units():
                if unit.unit_id in self._pending_deaths and unit.current_hp <= 0:
                    unit.is_alive = False
                    _log.info("[SKILL_EXEC] %s: %s is now dead (HP=%d/%d)", caster.name, unit.name, unit.current_hp, unit.max_hp)
            self._pending_deaths.clear()

        # 暴击触发：技能所有伤害结算完毕后，每技能仅触发一次PAWN_CAUSED_CRITICAL
        # defer_crit_triggers=True时，不立即执行，改为返回待执行列表
        # 由battle_flow_controller在_on_deaths_resolved（复活逻辑）之后执行
        # 确保战术演习中敌方复活后再触发暴击PS，避免对已死亡目标无效
        _log.info("[CRIT_TRIGGER] %s: pending_crit_triggers=%d, defer=%s",
                  caster.name, len(self._pending_crit_triggers), defer_crit_triggers)
        if self._pending_crit_triggers and self.trigger_service:
            if defer_crit_triggers:
                result["pending_crit_triggers"] = list(self._pending_crit_triggers)
                _log.info("[CRIT_TRIGGER] Deferring %d crit triggers to caller", len(self._pending_crit_triggers))
            else:
                if not self._recursion_guard:
                    self._recursion_guard = True
                    try:
                        for entry in self._pending_crit_triggers:
                            c, bf = entry[0], entry[1]
                            crit_count = entry[2] if len(entry) > 2 else 1
                            # 一个技能内即使多hit暴击，PS也只触发1次
                            # 但crit_counter按暴击hit数累加（影响crit_count_mod条件判断）
                            crit_actions = self.trigger_service.trigger_pawn_caused_critical(c, bf, count=crit_count)
                            self._execute_trigger_actions_inline(crit_actions, bf, trigger_timing="pawn_caused_critical")
                    finally:
                        self._recursion_guard = False
        self._pending_crit_triggers = []

        _log.info("[SKILL_EXEC] %s: [%s] complete, total_dmg=%d, effects=%d",
                  caster.name, resolved.name, result["total_damage"], len(result["effects_applied"]))
        # 将on_crit块的效果结果添加到effects_applied中（用于叙事日志）
        if self._on_crit_effects:
            result["effects_applied"].extend(self._on_crit_effects)
            _log.info("[SKILL_EXEC] %s: added %d on_crit effects to results",
                      caster.name, len(self._on_crit_effects))
        result["success"] = True
        result["inline_ps_results"] = list(self._inline_ps_results)
        self._inline_ps_results.clear()
        # Clear cached damage targets after skill execution completes
        self._block_damage_targets = None
        self._prev_block_damage_targets = {}
        self._block_damage_total = {}
        self._current_block_id = 0
        # Clear newly created SubUnit IDs (they can attack from next turn)
        self._newly_created_sub_unit_ids.clear()
        # 清理EPHEMERAL_SKILL_END类型的buff（技能内临时效果，如破衝Lv11+暴击率提升）
        if self.aura_service:
            try:
                from src.entities_v2.enums import AuraUpdateTiming
                all_units = battlefield.get_all_units() if battlefield else []
                for unit in all_units:
                    self.aura_service._update_duration(unit, [AuraUpdateTiming.EPHEMERAL_SKILL_END])
                    self.aura_service.check_expiration(unit, all_units)
            except (AttributeError, TypeError):
                pass
        return result

    def _apply_effect(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """分发效果到对应服务"""
        etype = effect.effect_type
        _log.info("[EFFECT] %s: dispatching effect_type=%s value=%s hit_count=%s duration=%s",
                  caster.name, etype, getattr(effect, 'value', None),
                  getattr(effect, 'hit_count', None), getattr(effect, 'duration', None))

        # level_min: 效果等级下限
        effect_flags = getattr(effect, 'flags', None) or {}
        level_min = effect_flags.get('level_min')
        if level_min is not None:
            skill_level = caster.skill_levels.get(self._current_skill_id, 1)
            if skill_level < level_min:
                _log.info("[SKILL_EXEC] %s: skipping effect %s (level %d < level_min %d)",
                          caster.name, etype, skill_level, level_min)
                return None

        # 混乱过滤：仅允许伤害类效果和consume_hp执行，其他效果FAIL
        if getattr(caster, 'is_confused', False):
            _CONFUSION_WHITELIST = {"damage", "hp_ratio_damage", "damage_special", "consume_hp"}
            if etype not in _CONFUSION_WHITELIST:
                _log.info("[CONFUSION] %s: effect %s FAIL (confused, only damage effects allowed)",
                          caster.name, etype)
                return None

        if etype == "damage":
            return self._apply_damage(caster, effect, battlefield)

        elif etype in ("heal", "recover"):
            return self._apply_heal(caster, effect, battlefield)

        elif etype == "add_status":
            return self._apply_add_status(caster, effect, battlefield)

        elif etype in self._get_resource_types():
            return self._apply_resource(caster, effect, battlefield)

        elif etype == "guard":
            return self._apply_guard(caster, effect, battlefield)

        elif etype in self._get_buff_types():
            return self._apply_aura(caster, effect, battlefield, is_debuff=False)

        elif etype in self._get_debuff_types():
            return self._apply_aura(caster, effect, battlefield, is_debuff=True)

        elif etype == "consume_hp":
            return self._apply_consume_hp(caster, effect, battlefield)

        elif etype == "hp_ratio_damage":
            return self._apply_hp_ratio_damage(caster, effect, battlefield)

        elif etype == "lifesteal":
            return self._apply_lifesteal(caster, effect, battlefield)

        elif etype == "shield_from_damage":
            return self._apply_shield_from_damage(caster, effect, battlefield)

        elif etype == "damage_special":
            return self._apply_damage_special(caster, effect, battlefield)

        elif etype in ("server_script_instant", "server_script_aura"):
            _log.info("[EFFECT] %s: skipped server_script type=%s", caster.name, etype)
            return None

        elif etype == "remove_debuff":
            return self._apply_remove_debuff(caster, effect, battlefield)

        elif etype == "remove_all_buffs":
            return self._apply_remove_all_buffs(caster, effect, battlefield)

        elif etype == "remove_buff":
            return self._apply_remove_buff(caster, effect, battlefield)

        elif etype == "remove_buff_by_type":
            return self._apply_remove_buff_by_type(caster, effect, battlefield)

        elif etype == "block_buff_by_type":
            return self._apply_block_buff_by_type(caster, effect, battlefield)

        elif etype == "stealth":
            return self._apply_stealth(caster, effect, battlefield)

        elif etype == "split_heal_by_damage":
            return self._apply_split_heal_by_damage(caster, effect, battlefield)

        elif etype == "skill_power_down":
            return self._apply_skill_power_down(caster, effect, battlefield)

        elif etype == "reset_cooldown":
            return self._apply_reset_cooldown(caster, effect)

        elif etype == "sub_unit":
            return self._apply_sub_unit(caster, effect, battlefield)

        elif etype == "remove_mark":
            return self._apply_remove_mark(caster, effect, battlefield)

        elif etype == "remove_shield":
            return self._apply_remove_shield(caster, effect, battlefield)

        elif etype == "remove_sub_unit":
            return self._apply_remove_sub_unit(caster, effect, battlefield)

        elif etype == "cover":
            return self._apply_cover(caster, effect, battlefield)

        elif etype == "modify_pp":
            return self._apply_modify_pp(caster, effect, battlefield)

        _log.info("[EFFECT] %s: unhandled effect_type=%s", caster.name, etype)
        return None

    def _apply_damage(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        if not self.damage_service or not self.target_service:
            _log.info("[DAMAGE_APPLY] %s: damage_service or target_service unavailable", caster.name)
            return None

        target_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': self._resolve_target_range(effect.target_type),
            'display_target_priority': self._current_skill_priority,
            'target_type_name': effect.target_type,
        })()

        cached_targets = getattr(self, '_block_damage_targets', None)
        is_using_cached = False
        if cached_targets is not None and isinstance(cached_targets, dict) and effect.target_type in cached_targets:
            targets = list(cached_targets[effect.target_type])
            is_using_cached = True
        elif cached_targets is not None and isinstance(cached_targets, list):
            targets = list(cached_targets)
            is_using_cached = True
        elif effect.target_type == "debuff_applied_target":
            # Use the primary_target from trigger context (e.g., PS2 attacking the knockout target)
            primary_target = getattr(self, '_primary_target', None)
            # 检查当前PS是否设置了exclude_self（如130125：remove_debuff应作用于被上debuff的友方而非自身）
            current_skill_id = getattr(self, '_current_skill_id', 0)
            parsed_skill = self.data_loader.get_parsed_skill_data(current_skill_id) if current_skill_id else None
            gc = parsed_skill.get('global_condition', {}) if parsed_skill else {}
            exclude_self = bool(gc.get('exclude_self', 0)) if gc else False
            if exclude_self:
                # exclude_self: 从触发上下文中找非自身的友方目标
                # 多个友方同时被上debuff时，选取距离自身最近的被上debuff的友方
                ctx_targets = getattr(self, '_damaged_targets', None) or []
                non_self_targets = [t for t in ctx_targets
                                     if t.unit_id != caster.unit_id and t.is_alive
                                     and t.side == caster.side]
                if non_self_targets:
                    nearest = self.target_service.get_nearest_ally(caster, non_self_targets)
                    if nearest:
                        primary_target = nearest
                        _log.info("[DAMAGE_APPLY] %s: debuff_applied_target exclude_self -> redirected to nearest %s",
                                  caster.name, primary_target.name)
            if primary_target and primary_target.is_alive:
                targets = [primary_target]
                _log.info("[DAMAGE_APPLY] %s: debuff_applied_target -> %s",
                          caster.name, primary_target.name)
            else:
                _log.info("[DAMAGE_APPLY] %s: debuff_applied_target FALLBACK (primary_target=%s alive=%s), using select_targets",
                          caster.name,
                          primary_target.name if primary_target else None,
                          primary_target.is_alive if primary_target else None)
                targets = self.target_service.select_targets(
                    target_skill_obj, caster, battlefield
                )
        else:
            # PS触发时通过_trigger_attacker定位攻击者（如掩撃反击攻击源）
            trigger_attacker = getattr(self, '_trigger_attacker', None)
            target_identifier = getattr(effect, 'target_identifier', None)
            if trigger_attacker and target_identifier == "trigger_attacker" and trigger_attacker.is_alive:
                targets = [trigger_attacker]
                _log.info("[DAMAGE_APPLY] %s: using trigger_attacker=%s as damage target",
                          caster.name, trigger_attacker.name)
            else:
                # fewest_mark_priority: 选择持有指定mark最少的敌方单位（如AS1「気品」循环）
                _eff_flags_early = getattr(effect, 'flags', None) or {}
                _fewest_mark = _eff_flags_early.get('fewest_mark_priority') if isinstance(_eff_flags_early, dict) else None
                if _fewest_mark and effect.target_type in ("enemy_single", "enemies", "enemy"):
                    # 先按正常逻辑选出候选目标（单目标），再从中按mark最少+距离最近选取
                    _candidates = self.target_service.select_targets(
                        target_skill_obj, caster, battlefield
                    )
                    if _candidates:
                        _best = self.target_service.select_fewest_mark_target(caster, _candidates, _fewest_mark)
                        targets = [_best] if _best else []
                        _log.info("[DAMAGE_APPLY] %s: fewest_mark_priority='%s' -> %s",
                                  caster.name, _fewest_mark,
                                  targets[0].name if targets else "none")
                    else:
                        targets = []
                else:
                    targets = self.target_service.select_targets(
                        target_skill_obj, caster, battlefield
                    )

        char_type_filter = getattr(self, '_target_char_type_filter', None)
        if char_type_filter is not None:
            if isinstance(char_type_filter, int):
                char_type_filter = [char_type_filter]
            targets = [t for t in targets if getattr(t, 'character_type', 0) in char_type_filter]
            _log.info("[DAMAGE_APPLY] %s: char_type filter=%s, filtered targets=%d",
                      caster.name, char_type_filter, len(targets))

        element_filter = getattr(self, '_target_element_filter', None)
        if element_filter is not None:
            targets = [t for t in targets if getattr(t, 'element', 0) == element_filter]
            _log.info("[DAMAGE_APPLY] %s: element filter=%d, filtered targets=%d",
                      caster.name, element_filter, len(targets))

        effect_flags = getattr(effect, 'flags', {}) or {}
        if effect_flags.get('expand_by_card'):
            card_buffs = [b for b in caster.buffs if b.effect_type in ("card_buff", "CardBuff")]
            if card_buffs:
                card_val = max(b.value for b in card_buffs)
                _log.info("[DAMAGE_APPLY] %s: card_buff detected, expanding targets from %d to %d",
                          caster.name, len(targets), card_val + 1)
                if len(targets) == 1 and card_val >= 1:
                    enemy_team = battlefield.enemy_team if caster.side == battlefield.friend_team[0].side else battlefield.friend_team
                    alive_enemies = [u for u in enemy_team if u.is_alive and u.unit_id != targets[0].unit_id]
                    alive_enemies.sort(key=lambda u: u.max_hp, reverse=True)
                    extra_count = min(card_val, len(alive_enemies))
                    targets.extend(alive_enemies[:extra_count])

        _log.info("[DAMAGE_APPLY] %s: power=%.1f hits=%d targets=%d ignore_def=%s ignore_shield=%s",
                  caster.name, effect.value or 100.0, effect.hit_count or 1, len(targets),
                  effect.ignore_defense, effect.ignore_shield)

        # hp_threshold_cross条件检查：damage效果中的HP穿越阈值判定
        effect_condition = getattr(effect, 'condition', None)
        if effect_condition and isinstance(effect_condition, dict) and effect_condition.get('type') == 'hp_threshold_cross':
            threshold = effect_condition.get('value', 70)
            # 检查每个目标是否满足穿越条件（伤害前HP > 阈值 且 伤害后HP <= 阈值）
            valid_targets = []
            for t in targets:
                hp_before = self._last_damage_hp_before.get(t.unit_id, t.current_hp)
                threshold_hp = int(t.max_hp * threshold / 100)
                if hp_before > threshold_hp and t.current_hp <= threshold_hp:
                    valid_targets.append(t)
                else:
                    _log.info("[DAMAGE_APPLY] %s -> %s: SKIPPED (hp_threshold_cross: hp_before=%d > %d=%d hp_after=%d <= %d)",
                              caster.name, t.name, hp_before, threshold_hp, threshold_hp, t.current_hp, threshold_hp)
            if not valid_targets:
                _log.info("[DAMAGE_APPLY] %s: hp_threshold_cross - no valid targets, skipping entire damage effect", caster.name)
                return None
            targets = valid_targets

        # target_is_front_row / target_is_back_row 条件过滤：按目标前后排过滤
        if effect_condition and isinstance(effect_condition, dict):
            _pos_cond_type = effect_condition.get('type')
            if _pos_cond_type in ('target_is_front_row', 'target_is_back_row'):
                _row_keyword = 'FRONT' if _pos_cond_type == 'target_is_front_row' else 'BACK'
                _filtered = []
                for t in targets:
                    _pos_name = t.position.name if hasattr(t, 'position') else ''
                    if _row_keyword in _pos_name:
                        _filtered.append(t)
                    else:
                        _log.info("[DAMAGE_APPLY] %s -> %s: SKIPPED (condition %s not met, pos=%s)",
                                  caster.name, t.name, _pos_cond_type, _pos_name)
                if not _filtered:
                    _log.info("[DAMAGE_APPLY] %s: %s - no valid targets, skipping damage effect",
                              caster.name, _pos_cond_type)
                    return None
                targets = _filtered

        if self.trigger_service and not self._recursion_guard and not self._before_attack_triggers_fired:
            self._recursion_guard = True
            self._before_attack_triggers_fired = True  # 同一技能内只触发一次
            try:
                # 收集所有攻击目标（跨damage效果/block）
                # 确保before_attack触发器能检查到技能的所有攻击目标，
                # 而非仅当前damage效果的目标（如enemy_single不含adjacent_enemies的目标）
                # 优先使用预扫描的cover候选（包含所有block的攻击目标，在技能执行前已扫描完成）
                pre_scanned = getattr(self, '_pre_scanned_cover_candidates', None)
                if pre_scanned:
                    all_block_targets = [u for u in pre_scanned if u.is_alive]
                else:
                    all_block_targets = targets  # 默认使用当前damage效果的目标
                    bdt = getattr(self, '_block_damage_targets', None)
                    if bdt and isinstance(bdt, dict):
                        seen_ids = set()
                        all_block_targets = []
                        for units in bdt.values():
                            for u in units:
                                if u.unit_id not in seen_ids and u.is_alive:
                                    seen_ids.add(u.unit_id)
                                    all_block_targets.append(u)
                        if not all_block_targets:
                            all_block_targets = targets
                before_enemy_actions = self.trigger_service.trigger_before_enemy_as_attack(caster, self._current_skill_id, all_block_targets, battlefield)
                self._execute_trigger_actions_inline(before_enemy_actions, battlefield, trigger_timing="before_enemy_as_attack")
                self._current_attack_targets = list(all_block_targets)  # 保存当前攻击目标列表，供PS cover效果使用
                before_any_actions = self.trigger_service.trigger_before_any_attacked(all_block_targets, battlefield, attacker=caster)
                self._execute_trigger_actions_inline(before_any_actions, battlefield, trigger_timing="before_any_attacked")
                before_as_actions = self.trigger_service.trigger_before_as_attacked(all_block_targets, battlefield, attacker=caster)
                self._execute_trigger_actions_inline(before_as_actions, battlefield, trigger_timing="before_as_attacked")
            finally:
                self._recursion_guard = False

        # 应用cover效果：检查是否有友方单位设置了cover_target，如果有则替换目标
        # 注意：此逻辑必须在每个damage效果中执行，因为不同damage效果有不同的目标列表
        # cover_target的设置发生在PS技能执行时（通过_apply_cover方法）
        if self._has_active_cover(battlefield):
            self._apply_cover_to_targets(caster, targets, battlefield)

        hp_scaling_flag = effect_flags.get('hp_scaling')
        hp_scaling_value = 0.0
        if hp_scaling_flag and isinstance(hp_scaling_flag, dict):
            hp_scaling_max = hp_scaling_flag.get('max', 0)
            hp_scaling_max_tag = hp_scaling_flag.get('max_tag')
            # 通过max_tag从skills.json解析最大值（如桜華の舞的up tag、レストブレイカー的range tag）
            if hp_scaling_max_tag and hp_scaling_max == 0:
                if hasattr(self, '_resolver') and self._resolver:
                    _skill_level = caster.skill_levels.get(self._current_skill_id, 1)
                    meta = self.data_loader.get_skill_by_id(self._current_skill_id)
                    if meta:
                        tag_values = self._resolver._resolve_template_tags(meta, _skill_level)
                        resolved = tag_values.get(hp_scaling_max_tag)
                        if resolved is not None:
                            hp_scaling_max = float(resolved)
            if hp_scaling_max > 0:
                # hp_scaling_enemy: 基于敌方HP比例而非施法者HP（参考一意専心）
                if effect_flags.get('hp_scaling_enemy'):
                    # 使用距离施法者最近的存活敌方单位的HP比例
                    from src.entities_v2.enums import Side as _SideHPScal
                    enemies = [u for u in battlefield.enemy_team if u.is_alive] if caster.side == _SideHPScal.ALLY else [u for u in battlefield.friend_team if u.is_alive]
                    if enemies:
                        from src.entities_v2.enums import Position as _PosHP
                        _POS_RC_HP = {
                            _PosHP.ALLY_LEFT_FRONT: (0, 0), _PosHP.ALLY_CENTER_FRONT: (0, 1), _PosHP.ALLY_RIGHT_FRONT: (0, 2),
                            _PosHP.ALLY_LEFT_BACK: (1, 0), _PosHP.ALLY_CENTER_BACK: (1, 1), _PosHP.ALLY_RIGHT_BACK: (1, 2),
                            _PosHP.ENEMY_LEFT_FRONT: (0, 0), _PosHP.ENEMY_CENTER_FRONT: (0, 1), _PosHP.ENEMY_RIGHT_FRONT: (0, 2),
                            _PosHP.ENEMY_LEFT_BACK: (1, 0), _PosHP.ENEMY_CENTER_BACK: (1, 1), _PosHP.ENEMY_RIGHT_BACK: (1, 2),
                        }
                        rc, cc = _POS_RC_HP.get(caster.position, (0, 1))
                        nearest = min(enemies, key=lambda u: (
                            (_POS_RC_HP.get(u.position, (0, 1))[0] - rc) ** 2 + (_POS_RC_HP.get(u.position, (0, 1))[1] - cc) ** 2,
                            _POS_RC_HP.get(u.position, (0, 1))[0], _POS_RC_HP.get(u.position, (0, 1))[1]
                        ))
                        hp_ratio = nearest.current_hp / nearest.max_hp if nearest.max_hp > 0 else 0
                    else:
                        hp_ratio = 0
                else:
                    hp_ratio = caster.current_hp / caster.max_hp if caster.max_hp > 0 else 0
                # hp_scaling_inverse: 反转HP比例（HP越低增幅越大，如レストブレイカー）
                if effect_flags.get('hp_scaling_inverse'):
                    hp_ratio = 1.0 - hp_ratio
                hp_scaling_value = hp_ratio * hp_scaling_max
                _log.info("[DAMAGE_APPLY] %s: HP-scaling hp_ratio=%.3f max=%.1f bonus=%.1f%% (enemy=%s inverse=%s)",
                          caster.name, hp_ratio, hp_scaling_max, hp_scaling_value,
                          effect_flags.get('hp_scaling_enemy', False), effect_flags.get('hp_scaling_inverse', False))
        elif hp_scaling_flag:
            hp_ratio = caster.current_hp / caster.max_hp if caster.max_hp > 0 else 0
            hp_scaling_value = hp_ratio * 200.0
            _log.info("[DAMAGE_APPLY] %s: HP-scaling (default) hp_ratio=%.3f bonus=%.1f%%",
                      caster.name, hp_ratio, hp_scaling_value)

        total_damage = 0
        targets_hit = []
        self._last_damage_hp_before = {}
        deferred_crit_actions = []
        # Track targets that were fully evaded (all hits missed)
        if not hasattr(self, '_block_evaded_targets'):
            self._block_evaded_targets = set()

        # kenki_power_tag: 行动开始时有剣気时切换威力tag
        kenki_power_tag = effect_flags.get('kenki_power_tag')
        if kenki_power_tag:
            # 检查行动开始时（技能执行前）是否有剣気mark，而非当前状态
            marks_at_start = getattr(self, '_marks_at_start', {})
            has_kenki = marks_at_start.get('剣気', 0) > 0
            if not has_kenki:
                # 回退：检查当前buffs（兼容旧逻辑）
                has_kenki = any(b.effect_type == SkillEffectType.MARK.value and getattr(b, 'name', '') == '剣気'
                               for b in caster.buffs)
            if has_kenki:
                _log.info("[KENKI_POWER] %s: has 剣気, switching value_tag from %s to %s",
                          caster.name, getattr(effect, 'value_tag', None), kenki_power_tag)
                effect.value_tag = kenki_power_tag
                # Re-resolve value from new tag
                if hasattr(self, '_resolver') and self._resolver:
                    _skill_level = caster.skill_levels.get(self._current_skill_id, 1)
                    meta = self.data_loader.get_skill_by_id(self._current_skill_id)
                    if meta:
                        tag_values = self._resolver._resolve_template_tags(meta, _skill_level)
                        resolved = tag_values.get(kenki_power_tag)
                        if resolved is not None:
                            effect.value = resolved
                            _log.info("[KENKI_POWER] %s: re-resolved value from tag %s = %s",
                                      caster.name, kenki_power_tag, resolved)

        # 条件性穿防穿盾：检查flags.ignore_condition，条件不满足时忽略穿防穿盾
        _ignore_def = effect.ignore_defense
        _ignore_shld = effect.ignore_shield
        _ignore_cond = effect_flags.get('ignore_condition')
        if _ignore_cond and (_ignore_def or _ignore_shld) and targets:
            _cond_type = _ignore_cond.get('type', '')
            _cond_met = False
            if _cond_type == 'target_has_burn':
                _first_target = targets[0]
                _cond_met = any(d.effect_type == SkillEffectType.CONFLAGRATION.value for d in _first_target.debuffs)
            elif _cond_type == 'target_has_status_ailment':
                _first_target = targets[0]
                _status_ailment_types = {
                    SkillEffectType.CONFLAGRATION.value,
                    SkillEffectType.POISON.value,
                    SkillEffectType.FREEZE.value,
                    SkillEffectType.KNOCKOUT.value,
                }
                _cond_met = any(d.effect_type in _status_ailment_types for d in _first_target.debuffs)
            elif _cond_type == 'target_has_poison':
                _first_target = targets[0]
                _cond_met = any(d.effect_type == SkillEffectType.POISON.value for d in _first_target.debuffs)
            if not _cond_met:
                _ignore_def = 0
                _ignore_shld = 0
                _log.info("[DAMAGE_APPLY] %s: ignore_condition(%s) not met, penetration disabled",
                          caster.name, _cond_type)

        dmg_skill_obj = type('obj', (object,), {
            'power': effect.value or 100.0,
            'hit_count': effect.hit_count or 1,
            'element': caster.element,
            'ignore_defense': _ignore_def,
            'ignore_shield': _ignore_shld,
            'hp_scaling_bonus': hp_scaling_value,
            'cannot_crit': effect_flags.get('cannot_crit', False),
            'bonus_crit_rate': 0.0,
            'skill_id': self._current_skill_id,
            'name': self._get_skill_name(self._current_skill_id),
            'base_value_source': effect_flags.get('value_source', None),
        })()

        # conditional_power_bonus: 条件满足时增伤
        # bonus_type="power"(默认): 修改skill power（独立倍率乘区）
        # bonus_type="dealt_damage": 添加dmg_dealt_up buff（造成伤害乘区）
        cond_power_bonus = effect_flags.get('conditional_power_bonus')
        if cond_power_bonus and isinstance(cond_power_bonus, dict) and targets:
            cond = cond_power_bonus.get('condition', {})
            cond_type = cond.get('type', '')
            cond_met = False
            cond_desc = ""

            if cond_type == 'target_hp_below' and targets:
                first_target = targets[0]
                pre_dmg_hp = getattr(self, '_pre_damage_hp', {}).get(first_target.unit_id, first_target.current_hp)
                hp_pct = pre_dmg_hp / first_target.max_hp * 100 if first_target.max_hp > 0 else 100
                threshold = cond.get('value', 0)
                cond_met = hp_pct <= threshold
                cond_desc = f"target_hp_below({hp_pct:.1f}%<={threshold}%)"

            elif cond_type == 'target_has_status_ailment' and targets:
                # 检查目标是否有状态异常（炎上/毒/凍結/眩暈）
                first_target = targets[0]
                status_ailment_types = {
                    SkillEffectType.CONFLAGRATION.value,
                    SkillEffectType.POISON.value,
                    SkillEffectType.FREEZE.value,
                    SkillEffectType.KNOCKOUT.value,
                }
                has_ailment = any(d.effect_type in status_ailment_types for d in first_target.debuffs)
                cond_met = has_ailment
                cond_desc = f"target_has_status_ailment({has_ailment})"

            elif cond_type == 'target_has_burn' and targets:
                # 检查目标是否处于炎上状态
                first_target = targets[0]
                has_burn = any(d.effect_type == SkillEffectType.CONFLAGRATION.value for d in first_target.debuffs)
                cond_met = has_burn
                cond_desc = f"target_has_burn({has_burn})"

            elif cond_type == 'target_has_debuff' and targets:
                # 检查目标debuffs列表是否非空（任意debuff均可）
                first_target = targets[0]
                has_debuff = len(first_target.debuffs) > 0
                cond_met = has_debuff
                cond_desc = f"target_has_debuff({has_debuff}, count={len(first_target.debuffs)})"

            if cond_met:
                value_tag = cond_power_bonus.get('value_tag', 'dmg')
                # 通过resolver解析tag值
                bonus_pct = 50.0  # 默认值
                if value_tag and hasattr(self, '_resolver') and self._resolver:
                    _skill_level = caster.skill_levels.get(self._current_skill_id, 1)
                    meta = self.data_loader.get_skill_by_id(self._current_skill_id)
                    if meta:
                        tag_values = self._resolver._resolve_template_tags(meta, _skill_level)
                        resolved = tag_values.get(value_tag)
                        if resolved is not None:
                            bonus_pct = float(resolved)
                bonus_type = cond_power_bonus.get('bonus_type', 'power')
                if bonus_type == 'dealt_damage':
                    # 造成伤害乘区：添加临时dmg_dealt_up buff（attack_limited=1，仅本次攻击生效）
                    temp_aura = BuffState(
                        buff_id=f"{caster.unit_id}_DealtDamage_{caster.unit_id}_cond",
                        name="DealtDamage",
                        effect_type=SkillEffectType.DEALT_DAMAGE.value,
                        value=bonus_pct,
                        duration=1,
                        timing_type=AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value,
                        source_unit_id=caster.unit_id,
                        source_skill_id=self._current_skill_id,
                        caster_attack=0,
                        is_debuff=False,
                        attack_limited=1,
                    )
                    caster.buffs.append(temp_aura)
                    _log.info("[CONDITIONAL_POWER_BONUS] %s: %s -> dmg_dealt_up +%.1f%% (dealt_damage乘区)",
                              caster.name, cond_desc, bonus_pct)
                elif bonus_type == 'received_damage':
                    # 易伤乘区：添加临时dmg_taken_up debuff到目标（attack_limited=1，仅本次攻击生效）
                    # 与目标已有的易伤debuff叠加（is_stackable=True），影响received_mult计算
                    first_target = targets[0]
                    import uuid
                    temp_vuln = BuffState(
                        buff_id=f"{caster.unit_id}_ReceivedDamage_{first_target.unit_id}_cond_{uuid.uuid4().hex[:8]}",
                        name="ConditionalVulnerability",
                        effect_type=SkillEffectType.RECEIVED_DAMAGE.value,
                        value=bonus_pct,
                        duration=1,
                        timing_type=AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value,
                        source_unit_id=caster.unit_id,
                        source_skill_id=self._current_skill_id,
                        caster_attack=0,
                        is_debuff=True,
                        attack_limited=1,
                        is_stackable=True,
                    )
                    first_target.debuffs.append(temp_vuln)
                    _log.info("[CONDITIONAL_POWER_BONUS] %s: %s -> dmg_taken_up +%.1f%% on %s (received_damage易伤乘区)",
                              caster.name, cond_desc, bonus_pct, first_target.name)
                elif cond_power_bonus.get('value_type') == 'percent':
                    # percent: bonus_pct是百分比值，直接作为power加成（独立倍率乘区）
                    original_power = dmg_skill_obj.power
                    dmg_skill_obj.power = original_power * (1.0 + bonus_pct / 100.0)
                    _log.info("[CONDITIONAL_POWER_BONUS] %s: %s -> power %.1f * %.2f = %.1f",
                              caster.name, cond_desc, original_power, 1.0 + bonus_pct / 100.0, dmg_skill_obj.power)

        hp_below_crit_flag = effect_flags.get('target_hp_below_crit')
        bonus_crit_applied = 0.0
        if hp_below_crit_flag and isinstance(hp_below_crit_flag, dict) and targets:
            first_target = targets[0]
            hp_pct = first_target.current_hp / first_target.max_hp * 100 if first_target.max_hp > 0 else 0
            threshold = hp_below_crit_flag.get('pct', 60)
            if hp_pct <= threshold:
                bonus = hp_below_crit_flag.get('resolved_value', 0)
                dmg_skill_obj.bonus_crit_rate = bonus
                bonus_crit_applied = bonus
                _log.info("[DAMAGE_APPLY] %s: target_hp_below_crit: target=%s hp=%.1f%% <= %.0f%% -> bonus_crit=%.1f%%",
                          caster.name, first_target.name, hp_pct, threshold, bonus)

        # per-target hp_scaling.max_bonus_pct: 基于每个目标当前HP比例计算伤害加成
        # (S6 大雷 220367: max_bonus_pct=100, HP=100%时 +100%, HP=50%时 +50%)
        # 覆盖 dmg_skill_obj.hp_scaling_bonus (单次计算的全局值) 为 per-target 值
        _hp_scaling_per_target_max = 0.0
        if hp_scaling_flag and isinstance(hp_scaling_flag, dict):
            _hp_scaling_per_target_max = float(hp_scaling_flag.get('max_bonus_pct', 0) or 0)

        for target_idx, target in enumerate(targets):
            # 判断是否是cover伤害：该target index是cover替换的位置
            is_cover_damage = target_idx in getattr(self, '_cover_replaced_indices', set())

            # 重置目标最近受到的伤害计数（用于反撃系PS，如ストイックリコイル）
            # 注意：每个damage effect开始时重置，多effect技能仅追踪最后一个effect的伤害
            target.last_received_damage = 0

            # per-target hp_scaling: 覆盖全局 hp_scaling_bonus
            if _hp_scaling_per_target_max > 0:
                _tgt_hp_ratio = (target.current_hp / target.max_hp) if target.max_hp > 0 else 0
                _per_target_bonus = _tgt_hp_ratio * _hp_scaling_per_target_max
                dmg_skill_obj.hp_scaling_bonus = _per_target_bonus
                _log.info("[HP_SCALING_PER_TARGET] %s -> %s: hp_ratio=%.3f max_bonus=%.1f%% bonus=%.1f%%",
                          caster.name, target.name, _tgt_hp_ratio, _hp_scaling_per_target_max, _per_target_bonus)

            # hp_scaling_def_penetrate: HP比例穿甲（天崩）
            # 参考Pスラスト实现：添加临时def_down debuff，而非设置ignore_defense
            if effect_flags.get('hp_scaling_def_penetrate') and target:
                hp_ratio = target.current_hp / target.max_hp if target.max_hp > 0 else 0
                penetrate_pct = min(50.0, 50.0 * hp_ratio)
                # 添加临时def_down debuff（持续到攻击者行动结束）
                temp_def_down = BuffState(
                    buff_id=f"hp_scaling_def_penetrate_{caster.unit_id}_{target.unit_id}",
                    name="HP比例穿甲",
                    effect_type=SkillEffectType.STATUS_DEFENSE.value,
                    value=penetrate_pct,
                    duration=-1,
                    timing_type=AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END.value,
                    stack_count=1,
                    value_tag=0,  # percent (0=百分比, 1=固定值)
                    source_unit_id=caster.unit_id,
                    is_debuff=True,
                )
                target.debuffs.append(temp_def_down)
                _log.info("[HP_SCALING_DEF_PENETRATE] %s: target %s HP ratio=%.2f, def_down=%.1f%%",
                          caster.name, target.name, hp_ratio, penetrate_pct)

            target_was_dead = not target.is_alive
            if target_was_dead and not is_using_cached:
                continue
            hp_before = target.current_hp
            self._last_damage_hp_before[target.unit_id] = hp_before

            # Guard: record attacker unit_id when guard buff is triggered by damage
            for buff in target.buffs:
                if buff.effect_type == SkillEffectType.GUARD.value and not buff.triggered_by_attacker:
                    buff.triggered_by_attacker = caster.unit_id
                    _log.info("[GUARD] %s: guard buff triggered by attacker %s, will expire when this skill ends",
                              target.name, caster.name)
            if target_was_dead:
                dmg_result = self.damage_service.calculate_damage(caster, target, dmg_skill_obj, is_cover_damage=is_cover_damage,
                                                                    on_crit_callback=self._make_on_crit_callback(caster, battlefield))
                actual_damage = dmg_result.total_damage
                shield_absorbed = 0
                target.current_hp = 0
                total_damage += actual_damage
                # 累计到 block_damage_total (供 split_heal_by_damage 读取)
                self._block_damage_total[self._current_block_id] = \
                    self._block_damage_total.get(self._current_block_id, 0) + actual_damage
                targets_hit.append({
                    "target": target.name,
                    "target_id": target.unit_id,
                    "hp_before": 0,
                    "hp_after": 0,
                    "damage": dmg_result.total_damage,
                    "actual_damage": actual_damage,
                    "shield_absorbed": 0,
                    "crit": dmg_result.is_critical,
                    "hits": dmg_result.hit_details,
                    "hit_crits": dmg_result.hit_crits,
                    "overkill": True,
                    "calc_detail": dmg_result.calc_detail,
                })
                caster.damage_dealt_total += actual_damage
                target.damage_taken_total += actual_damage
                _log.info("[DAMAGE_APPLY] %s -> %s (OVERKILL): hp 0→0 (-%d) crit=%s",
                          caster.name, target.name, actual_damage, dmg_result.is_critical)
                continue

            dmg_result = self.damage_service.calculate_damage(caster, target, dmg_skill_obj,
                                                                is_cover_damage=is_cover_damage,
                                                                on_crit_callback=self._make_on_crit_callback(caster, battlefield))
            actual_damage = dmg_result.total_damage
            shield_absorbed = 0

            # 幻惑 (genwaku): 攻击者持有幻惑时，伤害转为回复
            # 回复值 = 最终伤害值 × genwaku%，受目标回复量修正影响
            genwaku_buffs = [b for b in caster.debuffs if b.effect_type == SkillEffectType.GENWAKU.value]
            if genwaku_buffs:
                genwaku_pct = genwaku_buffs[0].value
                heal_amount = int(actual_damage * genwaku_pct / 100)
                heal_received_mult = self.damage_service._get_heal_received_multiplier(target)
                if heal_received_mult != 1.0:
                    heal_amount = int(heal_amount * heal_received_mult)
                target_max_hp = self.damage_service._calculate_final_stat(target, "max_hp")
                actual_heal = min(heal_amount, target_max_hp - target.current_hp)
                target.current_hp = min(target_max_hp, target.current_hp + heal_amount)
                _log.info("[GENWAKU] %s -> %s: damage %d converted to heal %d (genwaku=%.1f%%, mult=%.4f), hp %d->%d",
                          caster.name, target.name, actual_damage, actual_heal, genwaku_pct,
                          heal_received_mult, hp_before, target.current_hp)
                targets_hit.append({
                    "target": target.name,
                    "target_id": target.unit_id,
                    "hp_before": hp_before,
                    "hp_after": target.current_hp,
                    "damage": 0,
                    "actual_damage": 0,
                    "shield_absorbed": 0,
                    "crit": dmg_result.is_critical,
                    "hits": dmg_result.hit_details,
                    "hit_crits": dmg_result.hit_crits,
                    "hit_evades": dmg_result.hit_evades,
                    "genwaku_heal": actual_heal,
                    "calc_detail": dmg_result.calc_detail,
                })
                continue

            # dmg_invulnerable: 伤害无效化（实际造成1点伤害）
            # threshold_pct > 0: 現在HPのX%を超える攻撃のみダメージを無効にする
            # threshold_pct = 0: 全ての攻撃ダメージを無効にする（攻撃無効化）
            invuln_buffs = [b for b in target.buffs if b.effect_type == SkillEffectType.DMG_INVULNERABLE.value]
            invuln_nullified = False
            if invuln_buffs:
                invuln_buff = invuln_buffs[0]
                threshold = invuln_buff.threshold_pct
                if threshold > 0 or invuln_buff.hit_limited > 0:
                    threshold_value = int(target.current_hp * threshold) if threshold > 0 else 0
                    nullified_damage = 0
                    new_hit_details = []
                    new_hit_crits = []
                    new_hit_evades = []
                    for idx, hit_dmg in enumerate(dmg_result.hit_details):
                        should_nullify = False
                        if threshold > 0:
                            # 現在HPのX%を超える攻撃のみダメージを無効にする
                            should_nullify = hit_dmg > 0 and hit_dmg > threshold_value
                        else:
                            # 无阈值模式：所有伤害>0的hit都无效化
                            should_nullify = hit_dmg > 0
                        if should_nullify and invuln_buff.hit_limited > 0:
                            nullified_damage += (hit_dmg - 1)  # 差值：原伤害-1
                            new_hit_details.append(1)  # 伤害无效=1点伤害
                            new_hit_crits.append(False)  # 无效化不算暴击
                            new_hit_evades.append(False)
                            invuln_buff.hit_limited -= 1
                            invuln_nullified = True
                            _log.info("[DMG_INVULNERABLE] %s: hit[%d] %d <= threshold %d (hp*%.2f%%) -> 1 damage (nullified), hit_limited=%d",
                                      target.name, idx + 1, hit_dmg, threshold_value, threshold * 100, invuln_buff.hit_limited)
                            if invuln_buff.hit_limited <= 0:
                                # Remove linked buffs (e.g., HOT linked to dmg_invulnerable via linked_effect flag)
                                linked_hot = [b for b in target.buffs
                                              if b.effect_type == SkillEffectType.HEAL_OVER_TIME.value
                                              and b.source_skill_id == invuln_buff.source_skill_id
                                              and b.source_unit_id == invuln_buff.source_unit_id]
                                for lb in linked_hot:
                                    target.buffs = [b for b in target.buffs if b.buff_id != lb.buff_id]
                                    _log.info("[DMG_INVULNERABLE] %s: linked HOT buff also removed", target.name)
                                target.buffs = [b for b in target.buffs if b.buff_id != invuln_buff.buff_id]
                                _log.info("[DMG_INVULNERABLE] %s: buff EXPIRED (hit_limited=0)", target.name)
                                # Append remaining hits unchanged
                                for remaining_idx in range(idx + 1, len(dmg_result.hit_details)):
                                    new_hit_details.append(dmg_result.hit_details[remaining_idx])
                                    new_hit_crits.append(dmg_result.hit_crits[remaining_idx] if remaining_idx < len(dmg_result.hit_crits) else False)
                                    new_hit_evades.append(dmg_result.hit_evades[remaining_idx] if remaining_idx < len(dmg_result.hit_evades) else False)
                                break
                        else:
                            new_hit_details.append(hit_dmg)
                            new_hit_crits.append(dmg_result.hit_crits[idx] if idx < len(dmg_result.hit_crits) else False)
                            new_hit_evades.append(dmg_result.hit_evades[idx] if idx < len(dmg_result.hit_evades) else False)
                    if nullified_damage > 0:
                        actual_damage -= nullified_damage
                        dmg_result = DamageResult(
                            total_damage=actual_damage,
                            is_critical=dmg_result.is_critical,
                            attribute_factor=dmg_result.attribute_factor,
                            hit_details=new_hit_details,
                            hit_crits=new_hit_crits,
                            hit_evades=new_hit_evades,
                            calc_detail=dmg_result.calc_detail,
                        )
                        _log.info("[DMG_INVULNERABLE] %s: nullified %d damage (reduced to 1 per hit), remaining=%d",
                                  target.name, nullified_damage, actual_damage)

            # 冻结受击增伤：如果目标有冻结debuff，伤害增加冻结value%，然后解除冻结
            # 但如果目标完全闪避了所有攻击（miss），则不解除冻结
            fully_evaded = dmg_result.hit_evades and all(dmg_result.hit_evades)
            freeze_debuffs = [d for d in target.debuffs if d.effect_type == SkillEffectType.FREEZE.value]
            if freeze_debuffs and not fully_evaded:
                freeze_debuff = freeze_debuffs[0]
                freeze_dmg_up = freeze_debuff.value / 100.0 if freeze_debuff.value else 0.0
                if freeze_dmg_up > 0:
                    bonus = int(actual_damage * freeze_dmg_up)
                    actual_damage += bonus
                    _log.info("[FREEZE_BREAK] %s: freeze damage up +%.0f%%, damage %d->%d",
                              target.name, freeze_debuff.value, actual_damage - bonus, actual_damage)
                # 解除冻结
                target.debuffs = [d for d in target.debuffs if d.effect_type != SkillEffectType.FREEZE.value]
                target.is_frozen = False
                _log.info("[FREEZE_BREAK] %s: freeze removed by damage", target.name)
            elif freeze_debuffs and fully_evaded:
                _log.info("[FREEZE_KEEP] %s: attack fully evaded (miss), freeze NOT removed", target.name)

            shield_penetration = 0
            if dmg_skill_obj.ignore_shield:
                shield_penetration = min(dmg_skill_obj.ignore_shield / 100.0, 1.0)

            direct_damage = int(actual_damage * shield_penetration)
            shield_portion = actual_damage - direct_damage
            sub_unit_absorbs = []  # Track sub_unit absorption for narrative

            if shield_penetration < 1.0:
                caster_char_type = getattr(caster, 'character_type', 1)
                is_en_damage = (caster_char_type == 2)

                if is_en_damage and target.en_shield > 0:
                    if shield_portion <= target.en_shield:
                        shield_absorbed += shield_portion
                        target.en_shield -= shield_portion
                        shield_portion = 0
                    else:
                        shield_absorbed += target.en_shield
                        shield_portion -= target.en_shield
                        target.en_shield = 0

                if not is_en_damage and shield_portion > 0 and target.physical_shield > 0:
                    if shield_portion <= target.physical_shield:
                        shield_absorbed += shield_portion
                        target.physical_shield -= shield_portion
                        shield_portion = 0
                    else:
                        shield_absorbed += target.physical_shield
                        shield_portion -= target.physical_shield
                        target.physical_shield = 0

                if shield_portion > 0 and target.shield > 0:
                    if shield_portion <= target.shield:
                        shield_absorbed += shield_portion
                        target.shield -= shield_portion
                        shield_portion = 0
                    else:
                        shield_absorbed += target.shield
                        shield_portion -= target.shield
                        target.shield = 0

                # Sub-unit HP consumption: after normal shields, before HP damage
                # Only for non-piercing damage (poison/burn are handled separately)
                if shield_portion > 0:
                    sub_unit_buffs = [b for b in target.buffs if b.effect_type == SkillEffectType.SUB_UNIT.value and b.sub_unit_hp > 0]
                    for sub_buff in sub_unit_buffs:
                        if shield_portion <= 0:
                            break
                        if shield_portion <= sub_buff.sub_unit_hp:
                            absorbed_by_sub = shield_portion
                            sub_buff.sub_unit_hp -= shield_portion
                            shield_absorbed += shield_portion
                            _log.info("[SUB_UNIT_DMG] %s: sub_unit '%s' absorbs %d damage, HP %d->%d",
                                      target.name, sub_buff.name, shield_portion,
                                      sub_buff.sub_unit_hp + shield_portion, sub_buff.sub_unit_hp)
                            shield_portion = 0
                        else:
                            absorbed_by_sub = sub_buff.sub_unit_hp
                            shield_absorbed += sub_buff.sub_unit_hp
                            shield_portion -= sub_buff.sub_unit_hp
                            _log.info("[SUB_UNIT_DMG] %s: sub_unit '%s' HP depleted (absorbed %d), removing",
                                      target.name, sub_buff.name, sub_buff.sub_unit_hp)
                            sub_buff.sub_unit_hp = 0
                        sub_unit_absorbs.append({
                            "sub_unit_name": sub_buff.name,
                            "absorbed": absorbed_by_sub,
                            "sub_unit_hp_after": sub_buff.sub_unit_hp,
                            "sub_unit_max_hp": sub_buff.sub_unit_max_hp,
                        })
                        if sub_buff.sub_unit_hp <= 0:
                            target.buffs = [b for b in target.buffs if b.buff_id != sub_buff.buff_id]
                            _log.info("[SUB_UNIT_DMG] %s: sub_unit '%s' EXPIRED (HP=0)", target.name, sub_buff.name)
                            # [GAME_BUG_SIMULATION] 子機Ⅱ跨目标联动失效（HP耗尽触发）
                            # 原实现路径：sub_unit_link_group为空时_cascade_linked_sub_unit_expiry直接返回
                            self.aura_service._cascade_linked_sub_unit_expiry(
                                sub_buff, target, battlefield.get_all_units())

            actual_damage = shield_portion + direct_damage
            # 非闪避命中最低1点伤害，可作用于护盾或HP
            if actual_damage <= 0 and dmg_result.total_damage > 0:
                # 先尝试让盾吸收这1点最低伤害
                min_absorbed = False
                if shield_penetration < 1.0:
                    caster_char_type = getattr(caster, 'character_type', 1)
                    is_en_damage = (caster_char_type == 2)
                    if is_en_damage and target.en_shield > 0:
                        target.en_shield -= 1
                        shield_absorbed += 1
                        min_absorbed = True
                    elif not is_en_damage and target.physical_shield > 0:
                        target.physical_shield -= 1
                        shield_absorbed += 1
                        min_absorbed = True
                    elif target.shield > 0:
                        target.shield -= 1
                        shield_absorbed += 1
                        min_absorbed = True
                    # 子单位 HP 仍可吸收这1点最低伤害（与原伤害吸收顺序一致：盾→子单位→HP）
                    if not min_absorbed:
                        sub_unit_buffs_min = [b for b in target.buffs
                                              if b.effect_type == SkillEffectType.SUB_UNIT.value and b.sub_unit_hp > 0]
                        if sub_unit_buffs_min:
                            sub_buff_min = sub_unit_buffs_min[0]
                            sub_buff_min.sub_unit_hp -= 1
                            shield_absorbed += 1
                            min_absorbed = True
                            sub_unit_absorbs.append({
                                "sub_unit_name": sub_buff_min.name,
                                "absorbed": 1,
                                "sub_unit_hp_after": sub_buff_min.sub_unit_hp,
                                "sub_unit_max_hp": sub_buff_min.sub_unit_max_hp,
                            })
                            _log.info("[SUB_UNIT_DMG] %s: sub_unit '%s' absorbs 1 minimum damage, HP %d->%d",
                                      target.name, sub_buff_min.name,
                                      sub_buff_min.sub_unit_hp + 1, sub_buff_min.sub_unit_hp)
                            if sub_buff_min.sub_unit_hp <= 0:
                                target.buffs = [b for b in target.buffs if b.buff_id != sub_buff_min.buff_id]
                                _log.info("[SUB_UNIT_DMG] %s: sub_unit '%s' EXPIRED (HP=0) from minimum damage",
                                          target.name, sub_buff_min.name)
                                # [GAME_BUG_SIMULATION] 子機Ⅱ跨目标联动失效（最低1点伤害耗尽触发）
                                # 原实现路径：sub_unit_link_group为空时_cascade_linked_sub_unit_expiry直接返回
                                self.aura_service._cascade_linked_sub_unit_expiry(
                                    sub_buff_min, target, battlefield.get_all_units())
                if not min_absorbed:
                    actual_damage = 1
            overflow = max(0, actual_damage - hp_before)
            target.current_hp = max(0, target.current_hp - actual_damage)
            # 累计伤害计数：仅记录HP部分（不含盾吸收）
            hp_loss = hp_before - target.current_hp
            if hp_loss > 0:
                target.cumulative_hp_damage += hp_loss
            # 最近受到的伤害：用于反撃系PS（如ストイックリコイル）
            # 累计当次攻击所有hit的伤害（包括被盾吸收的部分，不含溢出）
            received_total = hp_loss + shield_absorbed
            if received_total > 0:
                target.last_received_damage += received_total
            total_damage += actual_damage
            # 累计到 block_damage_total (供 split_heal_by_damage 读取)
            self._block_damage_total[self._current_block_id] = \
                self._block_damage_total.get(self._current_block_id, 0) + actual_damage

            hit_shield_absorbed = []
            remaining_shield = shield_absorbed
            for hit_dmg in dmg_result.hit_details:
                hit_direct = int(hit_dmg * shield_penetration)
                hit_shield_portion = hit_dmg - hit_direct
                absorbed = min(hit_shield_portion, remaining_shield)
                hit_shield_absorbed.append(absorbed)
                remaining_shield -= absorbed

            targets_hit.append({
                "target": target.name,
                "target_id": target.unit_id,
                "hp_before": hp_before,
                "hp_after": target.current_hp,
                "damage": dmg_result.total_damage,
                "actual_damage": actual_damage,
                "shield_absorbed": shield_absorbed,
                "hit_shield_absorbed": hit_shield_absorbed,
                "crit": dmg_result.is_critical,
                "hits": dmg_result.hit_details,
                "hit_crits": dmg_result.hit_crits,
                "hit_evades": dmg_result.hit_evades,
                "sub_unit_absorbs": sub_unit_absorbs,
                "calc_detail": dmg_result.calc_detail,
            })
            # Track fully evaded targets (all hits evaded) so aura effects skip them
            if dmg_result.hit_evades and all(dmg_result.hit_evades):
                self._block_evaded_targets.add(target.unit_id)
                self._skill_evaded_targets.add(target.unit_id)  # 技能级别累积
                _log.info("[EVADE_FULL] %s: %s fully evaded, aura effects will skip", caster.name, target.name)
            caster.damage_dealt_total += actual_damage
            target.damage_taken_total += actual_damage

            # 计分追踪：记录伤害（actual_damage含溢出，全部计入得分）
            tracker = getattr(battlefield, 'scoring_tracker', None)
            if tracker is not None:
                caster_side = "ally" if caster.side.value == "ally" else "enemy"
                target_side = "ally" if target.side.value == "ally" else "enemy"
                tracker.record_damage(
                    source_id=caster.unit_id, source_name=caster.name, source_side=caster_side,
                    target_id=target.unit_id, target_name=target.name, target_side=target_side,
                    actual_damage=actual_damage, shield_absorbed=shield_absorbed,
                    overflow=overflow if target_side == "enemy" else 0,
                )

            if dmg_result.is_critical and self.trigger_service and not self._recursion_guard:
                # 按暴击hit数累加，而非每个目标只算1次
                crit_hit_count = sum(1 for c in dmg_result.hit_crits if c) if dmg_result.hit_crits else 1
                deferred_crit_actions.append((caster, battlefield, crit_hit_count))

            if dmg_result.is_critical and self._on_crit_blocks:
                # 延迟执行on_crit块：记录暴击目标，在所有正常block执行完毕后再执行
                # 避免on_crit块的效果被后续block（如remove_mark）错误清除
                self._deferred_on_crit_targets.append((caster, target, battlefield, effect))

            shield_info = f" [shield={shield_absorbed}]" if shield_absorbed > 0 else ""
            dead_mark = " 💀DEAD" if target.current_hp <= 0 else ""
            _log.info("[DAMAGE_APPLY] %s -> %s: hp %d→%d (-%d)%s%s crit=%s",
                      caster.name, target.name,
                      hp_before, target.current_hp,
                      actual_damage, shield_info, dead_mark,
                      dmg_result.is_critical)

            if target.current_hp <= 0:
                cheat_death_buffs = [b for b in target.buffs if b.effect_type in ("cheat_death", "CheatDeath")]
                if cheat_death_buffs:
                    heal_pct = max(b.value for b in cheat_death_buffs)
                    target.current_hp = max(1, int(target.max_hp * heal_pct / 100))
                    target.buffs = [b for b in target.buffs if b.effect_type not in ("cheat_death", "CheatDeath")]
                    _log.info("[CHEAT_DEATH] %s: survived lethal, healed to %d/%d (%.1f%%)",
                              target.name, target.current_hp, target.max_hp, heal_pct)
                else:
                    # 延迟阵亡判定：仅标记，技能完整结算后再统一设置 is_alive=False
                    self._pending_deaths.add(target.unit_id)
                    _log.info("[PENDING_DEATH] %s: HP=0, death deferred until skill end", target.name)

            for i in range(dmg_skill_obj.hit_count):
                # hit_limited消耗：跳过有attack_limited的debuff，它们由技能结束时的attack_limited清理统一处理
                hit_limited_buffs = [b for b in target.debuffs if b.hit_limited > 0 and b.attack_limited <= 0]
                for b in hit_limited_buffs:
                    b.hit_limited -= 1
                    _log.info("[HIT_LIMITED] %s: debuff %s hit_limited %d->%d",
                              target.name, b.effect_type, b.hit_limited + 1, b.hit_limited)
                    if b.hit_limited <= 0:
                        target.debuffs = [d for d in target.debuffs if d.buff_id != b.buff_id]
                        _log.info("[HIT_LIMITED] %s: debuff %s EXPIRED (hit_limited reached 0)", target.name, b.effect_type)

            if shield_absorbed > 0 and not effect_flags.get('skip_attack_limited_shield', False):
                shield_hit_limited_buffs = [b for b in target.buffs if b.effect_type in ("shield", "Shield") and b.hit_limited > 0]
                for sb in shield_hit_limited_buffs:
                    if target.shield > 0:
                        removed = target.shield
                        target.shield = 0
                        sb.hit_limited = 0
                        shield_name = getattr(sb, 'name', '') or sb.effect_type
                        target.buffs = [b for b in target.buffs if b.buff_id != sb.buff_id]
                        _log.info("[HIT_LIMITED_SHIELD] %s: one-hit shield consumed, removed %d remaining shield (abs=%d total_before=%d)",
                                  target.name, removed, shield_absorbed, removed + shield_absorbed)
                        # 记录护盾消失信息到damage结果
                        if targets_hit and targets_hit[-1].get("target_id") == target.unit_id:
                            targets_hit[-1]["shield_expired"] = shield_name

            # attack_limited shield buff: 每个damage block后立即消耗
            # "1次攻撃"=1个block的攻击，而非整个技能结束后才清理
            # 例如：スナイプリフレクター的护盾在block1攻击后消失，block2攻击直接命中HP
            # skip_attack_limited_shield: 同一block内多段damage共享盾消耗，第二段不重复消耗
            skip_shield_consume = effect_flags.get('skip_attack_limited_shield', False)
            if not skip_shield_consume and not (dmg_result.hit_evades and all(dmg_result.hit_evades)):
                for buff in list(target.buffs):
                    if buff.effect_type in ("shield", "Shield") and buff.attack_limited > 0:
                        buff.attack_limited -= 1
                        _log.info("[ATTACK_LIMITED_SHIELD] %s: shield buff attack_limited %d->%d (per-block)",
                                  target.name, buff.attack_limited + 1, buff.attack_limited)
                        if buff.attack_limited <= 0:
                            shield_to_remove = getattr(buff, 'shield_amount', target.shield)
                            if shield_to_remove > 0 and target.shield > 0:
                                actual_remove = min(shield_to_remove, target.shield)
                                target.shield -= actual_remove
                                _log.info("[ATTACK_LIMITED_SHIELD] %s: shield buff expired, removing %d shield (remaining=%d)",
                                          target.name, actual_remove, target.shield)
                            shield_name = getattr(buff, 'name', '') or buff.effect_type
                            target.buffs = [b for b in target.buffs if b.buff_id != buff.buff_id]
                            _log.info("[ATTACK_LIMITED_SHIELD] %s: shield buff EXPIRED (attack_limited reached 0)", target.name)
                            # 记录护盾消失信息到damage结果
                            if targets_hit and targets_hit[-1].get("target_id") == target.unit_id:
                                targets_hit[-1]["shield_expired"] = shield_name

        # Consume hit_limited buffs on the caster (e.g. dmg_dealt_up with hit-limited duration)
        # Skip EnchantDamage and carried_debuff StatusSpeed - they are consumed by _process_enchant_damage
        # Skip buffs with attack_limited - they are consumed by attack_limited cleanup at skill end
        # Skip Evade - its hit_limited is consumed in damage_service when actually evading a hit
        # Skip debuff_immune - its hit_limited is consumed by _consume_debuff_immune when blocking a debuff
        # Skip dmg_invulnerable - its hit_limited is consumed in the damage nullification logic above
        for b in list(caster.buffs):
            if b.hit_limited > 0:
                if b.effect_type == SkillEffectType.ENCHANT_DAMAGE.value:
                    continue
                if b.effect_type == SkillEffectType.EVADE.value:
                    continue
                if b.effect_type in ("debuff_immune", "DebuffImmune"):
                    continue
                if b.effect_type == SkillEffectType.DMG_INVULNERABLE.value:
                    continue
                if getattr(b, 'hit_limited_flags', {}).get('carried_debuff'):
                    continue
                if b.attack_limited > 0:
                    continue
                b.hit_limited -= 1
                _log.info("[HIT_LIMITED] %s: caster buff %s hit_limited %d->%d",
                          caster.name, b.effect_type, b.hit_limited + 1, b.hit_limited)
                if b.hit_limited <= 0:
                    caster.buffs = [x for x in caster.buffs if x.buff_id != b.buff_id]
                    _log.info("[HIT_LIMITED] %s: caster buff %s EXPIRED (hit_limited reached 0)", caster.name, b.effect_type)

        # ダメージリンク転送: リンクされたダメージは物理/EN区分を保持し、対応するシールドで吸収可能
        # リンクダメージは再度リンクされない（再帰防止）、ダメージ軽減/増加buffの影響を受けない
        # 叙事日志由battle_flow_controller._log_narrative_effects统一输出（skill_service无narrative访问权）
        _is_en_attack = bool(effect_flags.get('is_en_attack', False)) if effect_flags else False
        damage_link_transfers = []  # 收集链接伤害转移信息供叙事日志输出
        for target in targets_hit:
            target_unit = next((u for u in battlefield.get_all_units() if u.unit_id == target["target_id"]), None)
            if target_unit and target_unit.is_alive:
                damage_link_buffs = [b for b in target_unit.buffs if b.effect_type == "damage_link"]
                for dl in damage_link_buffs:
                    linker = next((u for u in battlefield.get_all_units() if u.unit_id == dl.source_unit_id), None)
                    if linker and linker.is_alive and linker.unit_id != target_unit.unit_id:
                        transfer_dmg = int(target["actual_damage"] * dl.value / 100)
                        if transfer_dmg <= 0:
                            continue
                        linker_hp_before = linker.current_hp
                        # 対応するシールドで吸収（物理=physical_shield, EN=en_shield）
                        shield_absorbed = 0
                        if _is_en_attack and linker.en_shield > 0:
                            shield_absorbed = min(linker.en_shield, transfer_dmg)
                            linker.en_shield -= shield_absorbed
                        elif not _is_en_attack and linker.physical_shield > 0:
                            shield_absorbed = min(linker.physical_shield, transfer_dmg)
                            linker.physical_shield -= shield_absorbed
                        elif linker.shield > 0:
                            # 汎用シールド（属性指定なし）でも吸収可能
                            shield_absorbed = min(linker.shield, transfer_dmg)
                            linker.shield -= shield_absorbed
                        hp_damage = transfer_dmg - shield_absorbed
                        if hp_damage > 0:
                            linker.current_hp = max(0, linker.current_hp - hp_damage)
                        linker.damage_taken_total += transfer_dmg
                        total_damage += transfer_dmg
                        _log.info("[DAMAGE_LINK] %s -> %s: transferred %d dmg (%s, %.0f%% of %d), shield_absorbed=%d, linker hp %d->%d",
                                  target_unit.name, linker.name, transfer_dmg,
                                  "EN" if _is_en_attack else "物理", dl.value,
                                  target["actual_damage"], shield_absorbed,
                                  linker_hp_before, linker.current_hp)
                        # 收集叙事日志信息
                        damage_link_transfers.append({
                            "source_target_id": target["target_id"],
                            "source_target_name": target_unit.name,
                            "linker_id": linker.unit_id,
                            "linker_name": linker.name,
                            "transfer_dmg": transfer_dmg,
                            "shield_absorbed": shield_absorbed,
                            "hp_before": linker_hp_before,
                            "hp_after": linker.current_hp,
                            "max_hp": linker.max_hp,
                            "damage_type": "EN" if _is_en_attack else "物理",
                            "link_value": dl.value,
                            "source_actual_damage": target["actual_damage"],
                        })

        self._most_recent_damage += total_damage

        self._previous_damage_target_ids = set(t["target_id"] for t in targets_hit)

        # after_as_attacked触发器已移至battle_flow_controller.py中处理
        # 确保反击在AS技能所有伤害结束后才触发，而非每段伤害后触发

        if deferred_crit_actions and self.trigger_service and not self._recursion_guard:
            self._recursion_guard = True
            try:
                for entry in deferred_crit_actions:
                    c, bf = entry[0], entry[1]
                    crit_count = entry[2] if len(entry) > 2 else 1
                    # 收集到技能级别的列表，延迟到execute_skill末尾统一触发
                    # 同一caster的crit_count累加（每技能仅触发一次PS，但crit_counter按hit数累加）
                    existing = next((ca for ca in self._pending_crit_triggers if ca[0].unit_id == c.unit_id), None)
                    if existing:
                        # 累加crit_count
                        updated = (existing[0], existing[1], existing[2] + crit_count)
                        self._pending_crit_triggers = [ca for ca in self._pending_crit_triggers if ca[0].unit_id != c.unit_id]
                        self._pending_crit_triggers.append(updated)
                    else:
                        self._pending_crit_triggers.append((c, bf, crit_count))
            finally:
                self._recursion_guard = False

        return {
            "effect_type": "damage",
            "targets": targets_hit,
            "total_damage": total_damage,
            "damage": total_damage,
            "bonus_crit_applied": bonus_crit_applied,
            "damage_link_transfers": damage_link_transfers,
        }

    def _process_enchant_damage(self, caster: UnitState, targets_hit: list,
                                 battlefield: BattlefieldState, total_damage: int) -> tuple:
        enchant_buffs = [b for b in caster.buffs if b.effect_type == SkillEffectType.ENCHANT_DAMAGE.value]
        sub_unit_buffs = [b for b in caster.buffs if b.effect_type == SkillEffectType.SUB_UNIT.value and b.value > 0]
        carried_debuff_buffs = [b for b in caster.buffs
                                if getattr(b, 'hit_limited_flags', {}).get('carried_debuff')]
        if not enchant_buffs and not carried_debuff_buffs and not sub_unit_buffs:
            return total_damage, [], []

        _log.info("[ENCHANT_DMG] %s: processing %d enchant_damage + %d carried_debuff + %d sub_unit buffs",
                  caster.name, len(enchant_buffs), len(carried_debuff_buffs), len(sub_unit_buffs))
        for i, sb in enumerate(sub_unit_buffs):
            _log.info("[ENCHANT_DMG] %s: sub_unit[%d] name='%s' value=%.1f hp=%d/%d source=%s",
                      caster.name, i, sb.name, sb.value, sb.sub_unit_hp, sb.sub_unit_max_hp, sb.source_unit_id)

        enchant_targets = []

        # Process sub-unit additional damage: each sub-unit adds 1 hit per target
        for sub_buff in sub_unit_buffs[:]:
            if sub_buff.sub_unit_hp <= 0:
                _log.info("[SUB_UNIT_DMG] %s: skipping sub_unit '%s' (HP=0)", caster.name, sub_buff.name)
                continue
            # Skip SubUnits created in the current skill (they should not attack on the turn they're summoned)
            if sub_buff.buff_id in self._newly_created_sub_unit_ids:
                _log.info("[SUB_UNIT_DMG] %s: skipping sub_unit '%s' (just created this turn)", caster.name, sub_buff.name)
                continue
            # Sub-unit damage formula:
            # max(0, snapshot_atk + min(0, a_atk - b_def)) * power% * 1.5(crit) * a_dealt * b_received
            # where a = source unit (main unit), b = target (enemy)
            source_unit_id = sub_buff.source_unit_id
            snapshot_atk = sub_buff.caster_attack  # ATK snapshotted when SubUnit was created
            source_unit = None
            a_atk = snapshot_atk  # fallback
            for u in battlefield.get_all_units():
                if u.unit_id == source_unit_id:
                    a_atk = self.damage_service._calculate_final_stat(u, "attack")
                    source_unit = u
                    break
            # 暴击率使用持有者(caster)的当前暴击率，与附魔伤害一致（非创建者source_unit的暴击率）
            a_crit_rate = self.damage_service._calculate_crit_rate(caster)
            power_pct = sub_buff.value / 100.0
            _log.info("[SUB_UNIT_DMG] %s: sub_unit '%s' source_id=%s snapshot_atk=%d a_atk=%d power=%.1f%% targets_hit=%d crit_rate=%.4f(from caster)",
                      caster.name, sub_buff.name, source_unit_id, snapshot_atk, a_atk, power_pct * 100, len(targets_hit), a_crit_rate)

            for target_info in targets_hit:
                target = next((u for u in battlefield.get_all_units() if u.unit_id == target_info.get("target_id")), None)
                if not target or not target.is_alive:
                    _log.info("[SUB_UNIT_DMG] %s: skipping target %s (found=%s alive=%s)",
                              caster.name, target_info.get("target_id"), target is not None,
                              target.is_alive if target else "N/A")
                    continue
                # 主伤害全段闪避的目标不触发sub_unit伤害（与附魔伤害一致）
                target_evades = target_info.get("hit_evades", [])
                if target_evades and all(target_evades):
                    _log.info("[SUB_UNIT_DMG] %s: skipping sub_unit for %s (all hits evaded)",
                              caster.name, target.name)
                    continue

                b_def = self.damage_service._calculate_final_stat(target, "defense")

                # 子单位伤害公式: max(0, snapshot_atk + min(0, a_atk - b_def)) * power%
                base = max(0, snapshot_atk + min(0, a_atk - b_def))

                dmg = base * power_pct

                # 暴击: 独立roll，使用caster(持有者)的暴击率，暴伤固定1.5倍（与附魔伤害一致）
                self.damage_service._crit_context = {
                    'source': 'sub_unit',
                    'attacker_name': caster.name,
                    'attacker_id': caster.unit_id,
                    'target_name': target.name,
                    'target_id': target.unit_id,
                    'skill_name': self._get_skill_name(self._current_skill_id),
                    'skill_id': self._current_skill_id,
                    'hit_number': 1,
                    'total_hits': 1,
                    'cannot_crit': False,
                    'sub_unit_name': sub_buff.name if hasattr(sub_buff, 'name') else '',
                }
                is_sub_crit = self.damage_service._check_crit(a_crit_rate)
                if is_sub_crit:
                    dmg *= 1.5

                # a增减伤区 (持有者的给予伤害倍率，子单位伤害应继承持有者造伤乘区)
                # 与附魔伤害一致使用caster，而非source_unit(创建者)
                target_hp_before_attack = target_info.get("hp_before", target.current_hp)
                a_dealt_mult = self.damage_service._get_damage_dealt_multiplier(
                    caster, target, defender_hp_for_condition=target_hp_before_attack)
                # b增减伤区 (被攻击对象的受击增减伤倍率，攻击时即时套用)
                b_received_mult = self.damage_service._get_damage_received_multiplier(target, attacker=caster)
                # 属性克制因子 (主单位的属性对目标的属性)
                advantage = self.damage_service._get_attribute_factor(source_unit.element if source_unit else caster.element, target.element, source_unit or caster)

                dmg *= a_dealt_mult * b_received_mult * advantage

                guard_rate = self.damage_service._aggregate_buff_value_signed(
                    target.buffs, target.debuffs, SkillEffectType.GUARD.value)
                if guard_rate > 0:
                    dmg *= (1.0 - guard_rate)

                extra_dmg = max(1, int(dmg))
                # 混乱减免：子单位追加伤害也受混乱减免影响（召唤者混乱时）
                if getattr(caster, 'is_confused', False):
                    confusion_buff = self.damage_service._get_confusion_buff(caster)
                    if confusion_buff and confusion_buff.confusion_dmg_reduction > 0:
                        orig_extra = extra_dmg
                        extra_dmg = max(1, int(extra_dmg * (1 - confusion_buff.confusion_dmg_reduction / 100.0)))
                        _log.info("[SUB_UNIT_DMG] CONFUSION reduction: %d -> %d (-%.1f%%)",
                                  orig_extra, extra_dmg, confusion_buff.confusion_dmg_reduction)
                hp_before = target.current_hp

                # Shield absorption (same logic as normal damage)
                shield_absorbed = 0
                remaining = extra_dmg

                # Determine damage type from source unit's character_type
                source_char_type = getattr(source_unit, 'character_type', 1) if source_unit else 1
                is_en_damage = (source_char_type == 2)

                if is_en_damage and target.en_shield > 0 and remaining > 0:
                    if remaining <= target.en_shield:
                        shield_absorbed += remaining
                        target.en_shield -= remaining
                        remaining = 0
                    else:
                        shield_absorbed += target.en_shield
                        remaining -= target.en_shield
                        target.en_shield = 0

                if not is_en_damage and remaining > 0 and target.physical_shield > 0:
                    if remaining <= target.physical_shield:
                        shield_absorbed += remaining
                        target.physical_shield -= remaining
                        remaining = 0
                    else:
                        shield_absorbed += target.physical_shield
                        remaining -= target.physical_shield
                        target.physical_shield = 0

                if remaining > 0 and target.shield > 0:
                    if remaining <= target.shield:
                        shield_absorbed += remaining
                        target.shield -= remaining
                        remaining = 0
                    else:
                        shield_absorbed += target.shield
                        remaining -= target.shield
                        target.shield = 0

                # Apply remaining damage to HP
                target.current_hp = max(0, target.current_hp - remaining)
                total_damage += extra_dmg
                caster.damage_dealt_total += extra_dmg
                target.damage_taken_total += extra_dmg

                # 计分追踪：记录子单位伤害
                tracker = getattr(battlefield, 'scoring_tracker', None)
                if tracker is not None:
                    source_side = "ally" if caster.side.value == "ally" else "enemy"
                    target_side = "ally" if target.side.value == "ally" else "enemy"
                    tracker.record_damage(
                        source_id=caster.unit_id, source_name=caster.name, source_side=source_side,
                        target_id=target.unit_id, target_name=target.name, target_side=target_side,
                        actual_damage=extra_dmg, shield_absorbed=shield_absorbed,
                    )

                enchant_targets.append({
                    "target_id": target.unit_id,
                    "target": target.unit_id,
                    "hp_before": hp_before,
                    "hp_after": target.current_hp,
                    "actual_damage": extra_dmg,
                    "damage": extra_dmg,
                    "shield_absorbed": shield_absorbed,
                    "crit": is_sub_crit,
                    "hits": [extra_dmg],
                    "hit_crits": [is_sub_crit],
                    "sub_unit_name": sub_buff.name,
                    "calc_detail": {
                        "snapshot_atk": snapshot_atk,
                        "a_atk": a_atk,
                        "b_def": b_def,
                        "base_diff": base,
                        "power_pct": power_pct * 100,
                        "crit_factor": 1.5 if is_sub_crit else 1.0,
                        "a_dealt_mult": a_dealt_mult,
                        "b_received_mult": b_received_mult,
                        "advantage": advantage,
                        "guard_mult": 1.0 - guard_rate if guard_rate > 0 else 1.0,
                    },
                })

                _log.info("[SUB_UNIT_DMG] %s sub_unit '%s' -> %s: extra=%d shield=%d (snapshot_atk=%d a_atk=%d b_def=%d power=%.1f%% crit=%s advantage=%.2f a_dealt=%.4f b_received=%.4f) hp: %d->%d",
                          caster.name, sub_buff.name, target.name, extra_dmg, shield_absorbed, snapshot_atk, a_atk, b_def,
                          power_pct * 100, is_sub_crit, advantage, a_dealt_mult, b_received_mult,
                          hp_before, target.current_hp)

                # add_status_to_attack: 子機追加伤害时同时施加debuff（如spd_down）
                sub_hlf = getattr(sub_buff, 'hit_limited_flags', {}) or {}
                add_status_info = sub_hlf.get('add_status_to_attack') if sub_hlf else None
                if add_status_info and target.is_alive:
                    status_name = add_status_info.get('status', 'spd_down')
                    status_value = add_status_info.get('value', 0)
                    # value=0时不施加debuff（Lv1-10时spd=0，不触发降速）
                    if status_value and status_value > 0:
                        status_duration = add_status_info.get('duration', 1)
                        # 映射status名称到effect_type
                        status_effect_map = {
                            'spd_down': SkillEffectType.STATUS_SPEED.value,
                            'atk_down': SkillEffectType.STATUS_ATTACK.value,
                            'def_down': SkillEffectType.STATUS_DEFENSE.value,
                        }
                        status_et = status_effect_map.get(status_name, SkillEffectType.STATUS_SPEED.value)
                        status_aura = BuffState(
                            buff_id=f"{caster.unit_id}_SubUnitStatus_{target.unit_id}_{sub_buff.buff_id[-8:]}",
                            name=f"SubUnit_{status_name}",
                            effect_type=status_et,
                            value=status_value,
                            duration=status_duration,
                            timing_type=AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value,
                            source_unit_id=sub_buff.source_unit_id,
                            source_skill_id=sub_buff.source_skill_id,
                            caster_attack=0,
                            is_debuff=True,
                            is_stackable=add_status_info.get('stackable', False),
                        )
                        self.aura_service.add_aura(target, status_aura)
                        _log.info("[SUB_UNIT_DMG] %s: sub_unit '%s' add_status_to_attack %s(%.1f) -> %s (dur=%d)",
                                  caster.name, sub_buff.name, status_name, status_value, target.name, status_duration)

        for eb in enchant_buffs:
            if eb.hit_limited <= 0:
                continue

            source_atk = eb.caster_attack
            power_pct = eb.value / 100.0
            source_unit_id = eb.source_unit_id
            source_unit = None
            for u in battlefield.get_all_units():
                if u.unit_id == source_unit_id:
                    source_atk = self.damage_service._calculate_final_stat(u, "attack")
                    source_unit = u
                    break

            b_atk = self.damage_service._calculate_final_stat(caster, "attack")
            b_crit_rate = self.damage_service._calculate_crit_rate(caster)

            for target_info in targets_hit:
                target = next((u for u in battlefield.get_all_units() if u.unit_id == target_info.get("target_id")), None)
                if not target:
                    continue
                # 全段闪避的目标不触发附魔伤害
                target_evades = target_info.get("hit_evades", [])
                if target_evades and all(target_evades):
                    _log.info("[ENCHANT_DMG] %s: skipping enchant for %s (all hits evaded)", caster.name, target.name)
                    continue
                # Allow enchant damage even if target died from main damage
                # (HP capped at 0, but damage is logged and counted in totals)
                if not target.is_alive and target_info.get("hp_before", 0) <= 0:
                    continue

                c_def = self.damage_service._calculate_final_stat(target, "defense")

                # 附魔伤害公式: max(0, (a攻 + min(0, b攻 - c防))) * 威力% * 1.5(套b暴击率, 暴伤固定1.5倍) * a增减伤区 * c增减伤区 * b有利伤害区
                base = max(0, source_atk + min(0, b_atk - c_def))

                dmg = base * power_pct

                # 暴击: 独立roll，使用b的暴击率，暴伤固定1.5倍
                self.damage_service._crit_context = {
                    'source': 'enchant',
                    'attacker_name': caster.name,
                    'attacker_id': caster.unit_id,
                    'target_name': target.name,
                    'target_id': target.unit_id,
                    'skill_name': self._get_skill_name(self._current_skill_id),
                    'skill_id': self._current_skill_id,
                    'hit_number': 1,
                    'total_hits': 1,
                    'cannot_crit': False,
                    'sub_unit_name': '',
                }
                is_enchant_crit = self.damage_service._check_crit(b_crit_rate)
                if is_enchant_crit:
                    dmg *= 1.5

                # 附魔伤害类型取决于附魔源的character_type: EN(2)=能量, 其他=物理
                enchant_damage_element = 2 if (source_unit and getattr(source_unit, 'character_type', 0) == 2) else 1
                # b增减伤区 (被附魔者的给予伤害倍率，按附魔伤害类型过滤)
                # 注意：附魔源(a)的造伤不参与附魔伤害计算，仅被附魔者(b)的造伤参与
                # 条件判断使用攻击前的HP（避免直伤已扣减HP导致条件判断错误）
                target_hp_before_attack = target_info.get("hp_before", target.current_hp)
                b_dealt_mult = self.damage_service._get_damage_dealt_multiplier(
                    caster, target, damage_element=enchant_damage_element,
                    defender_hp_for_condition=target_hp_before_attack)
                # c增减伤区 (被攻击对象的受击增减伤倍率)
                c_received_mult = self.damage_service._get_damage_received_multiplier(target, attacker=caster)
                # b有利伤害区 (附魔对象的属性克制因子)
                b_advantage = self.damage_service._get_attribute_factor(caster.element, target.element, caster)

                dmg *= b_dealt_mult * c_received_mult * b_advantage

                guard_rate = self.damage_service._aggregate_buff_value_signed(
                    target.buffs, target.debuffs, SkillEffectType.GUARD.value)
                if guard_rate > 0:
                    dmg *= (1.0 - guard_rate)
                    _log.info("[ENCHANT_DMG] guard reduction: rate=%.4f dmg=%.1f", guard_rate, dmg)

                extra_dmg = max(1, int(dmg))
                # 混乱减免：附魔伤害也受混乱减免影响
                if getattr(caster, 'is_confused', False):
                    confusion_buff = self.damage_service._get_confusion_buff(caster)
                    if confusion_buff and confusion_buff.confusion_dmg_reduction > 0:
                        orig_extra = extra_dmg
                        extra_dmg = max(1, int(extra_dmg * (1 - confusion_buff.confusion_dmg_reduction / 100.0)))
                        _log.info("[ENCHANT_DMG] CONFUSION reduction: %d -> %d (-%.1f%%)",
                                  orig_extra, extra_dmg, confusion_buff.confusion_dmg_reduction)
                hp_before = target.current_hp
                target.current_hp = max(0, target.current_hp - extra_dmg)
                total_damage += extra_dmg
                caster.damage_dealt_total += extra_dmg
                target.damage_taken_total += extra_dmg

                # 计分追踪：记录附魔伤害
                tracker = getattr(battlefield, 'scoring_tracker', None)
                if tracker is not None:
                    source_side = "ally" if caster.side.value == "ally" else "enemy"
                    target_side = "ally" if target.side.value == "ally" else "enemy"
                    tracker.record_damage(
                        source_id=caster.unit_id, source_name=caster.name, source_side=source_side,
                        target_id=target.unit_id, target_name=target.name, target_side=target_side,
                        actual_damage=extra_dmg, shield_absorbed=0,
                    )

                enchant_targets.append({
                    "target_id": target.unit_id,
                    "target": target.unit_id,
                    "hp_before": hp_before,
                    "hp_after": target.current_hp,
                    "actual_damage": extra_dmg,
                    "damage": extra_dmg,
                    "crit": is_enchant_crit,
                    "hits": [extra_dmg],
                    "hit_crits": [is_enchant_crit],
                    "modifiers": ["附魔"],
                    "calc_detail": {
                        "source_atk": source_atk,
                        "b_atk": b_atk,
                        "c_def": c_def,
                        "base_diff": base,
                        "power_pct": power_pct * 100,
                        "crit_factor": 1.5 if is_enchant_crit else 1.0,
                        "b_dealt_mult": b_dealt_mult,
                        "c_received_mult": c_received_mult,
                        "attr_factor": b_advantage,
                        "guard_mult": 1.0 - guard_rate if guard_rate > 0 else 1.0,
                    },
                })

                _log.info("[ENCHANT_DMG] %s enchant -> %s: extra=%d (source_atk=%d b_atk=%d c_def=%d power=%.1f%% crit=%s advantage=%.2f b_dealt=%.4f c_received=%.4f) hp: %d->%d",
                          caster.name, target.name, extra_dmg, source_atk, b_atk, c_def,
                          power_pct * 100, is_enchant_crit, b_advantage, b_dealt_mult, c_received_mult,
                          hp_before, target.current_hp)

                # add_status: 附魔伤害触发后附加状态异常（如炎上）
                _eb_hlf = getattr(eb, 'hit_limited_flags', {}) or {}
                _add_status = _eb_hlf.get('add_status')
                if _add_status and target.is_alive:
                    _status_dur = _eb_hlf.get('add_status_duration', 2)
                    if _add_status == 'burn':
                        _burn_val = source_atk * 0.30
                        _burn = BuffState(
                            buff_id=f"{eb.buff_id}_burn_{target.unit_id}",
                            name="炎上",
                            effect_type=SkillEffectType.CONFLAGRATION.value,
                            value=_burn_val,
                            duration=_status_dur,
                            timing_type=AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value,
                            source_unit_id=source_unit_id,
                            is_debuff=True,
                        )
                        target.debuffs.append(_burn)
                        _log.info("[ENCHANT_DMG] %s: add_status burn -> %s (val=%.1f dur=%d)",
                                  caster.name, target.name, _burn_val, _status_dur)

            eb.hit_limited -= 1
            _log.info("[ENCHANT_DMG] %s: enchant_damage buff hit_limited %d->%d",
                      caster.name, eb.hit_limited + 1, eb.hit_limited)
            if eb.hit_limited <= 0:
                caster.buffs = [b for b in caster.buffs if b.buff_id != eb.buff_id]
                _log.info("[ENCHANT_DMG] %s: enchant_damage buff EXPIRED", caster.name)

        carried_debuff_targets = []
        # 携带式debuff载荷：支持多种debuff类型(atk_down/def_down/spd_down/crit_rate_down等)
        # 显示标签映射: effect_type -> (stat_label, short_name)
        _CARRIED_DEBUFF_LABELS = {
            'atk_down': 'ATK',
            'def_down': 'DEF',
            'spd_down': 'SPD',
            'crit_rate_down': 'CRT',
            'poison': 'POI',
        }
        for sb in carried_debuff_buffs:
            if sb.hit_limited <= 0:
                continue
            hlf = getattr(sb, 'hit_limited_flags', {}) or {}
            debuff_type = hlf.get('carried_debuff_type', 'spd_down')
            debuff_value = hlf.get('carried_debuff_value', 200.0)
            debuff_duration = hlf.get('carried_debuff_duration', 1)
            debuff_value_tag = hlf.get('carried_debuff_value_tag', 1)
            debuff_stackable = hlf.get('carried_debuff_stackable', False)
            mapped_type = _JSON_EFFECT_TO_ENUM.get(debuff_type, SkillEffectType.STATUS_SPEED.value)
            stat_label = _CARRIED_DEBUFF_LABELS.get(debuff_type, debuff_type)
            # poison特殊处理：value是当前HP百分比(如0.10=10%)，caster_attack用于DoT伤害上限
            is_poison = (debuff_type == 'poison' or mapped_type == SkillEffectType.POISON.value)
            if is_poison:
                poison_pct = hlf.get('poison_damage_pct', 10)
                debuff_value = poison_pct / 100.0
                debuff_value_tag = 0
                value_display = f"{poison_pct}%HP"
            else:
                value_display = f"-{debuff_value:.0f}%" if debuff_value_tag == 0 else f"-{int(debuff_value)}"
            for target_info in targets_hit:
                target = next((u for u in battlefield.get_all_units() if u.unit_id == target_info.get("target_id")), None)
                if not target or not target.is_alive:
                    continue
                # 在add_aura前后各算一次属性，构造"ATK:前值→后值"格式detail（追踪真实属性，非效果量加减法）
                stat_before = self._compute_stat_display(target, mapped_type)
                carried_aura = BuffState(
                    buff_id=f"{caster.unit_id}_{mapped_type}_{target.unit_id}_enchant",
                    name=mapped_type,
                    effect_type=mapped_type,
                    value=debuff_value,
                    duration=debuff_duration,
                    timing_type=AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value,
                    source_unit_id=sb.source_unit_id,
                    source_skill_id=sb.source_skill_id,
                    caster_attack=sb.caster_attack if is_poison else 0,
                    is_debuff=True,
                    hit_limited=0,
                    value_tag=debuff_value_tag,
                    is_stackable=debuff_stackable,
                )
                added = self.aura_service.add_aura(target, carried_aura)
                if not added:
                    _log.info("[ENCHANT_DMG] %s: carried_debuff %s BLOCKED on %s (immunity/buff_block), skipping",
                              caster.name, debuff_type, target.name)
                    continue
                _log.info("[ENCHANT_DMG] %s: carried_debuff %s(%.4f, tag=%d) applied to %s (dur=%d, stackable=%s)",
                          caster.name, debuff_type, debuff_value, debuff_value_tag, target.name, debuff_duration, debuff_stackable)
                stat_after = self._compute_stat_display(target, mapped_type)
                if stat_before[0] and stat_after[0] and stat_after[1] != stat_before[1]:
                    enchant_detail = f"{stat_before[0]}:{stat_before[1]}→{stat_after[1]}"
                else:
                    enchant_detail = f"{stat_after[0]}:{stat_after[1]}" if stat_after[0] else ""
                carried_debuff_targets.append({
                    "target_id": target.unit_id,
                    "target": target.unit_id,
                    "effect": mapped_type,
                    "source_id": sb.source_unit_id,
                    "source": sb.source_unit_id,
                    "duration": debuff_duration,
                    "dur_type": "action",
                    "detail": enchant_detail,
                })

            sb.hit_limited -= 1
            _log.info("[ENCHANT_DMG] %s: carried_debuff buff hit_limited %d->%d",
                      caster.name, sb.hit_limited + 1, sb.hit_limited)
            if sb.hit_limited <= 0:
                caster.buffs = [b for b in caster.buffs if b.buff_id != sb.buff_id]
                _log.info("[ENCHANT_DMG] %s: carried_debuff buff EXPIRED", caster.name)

        return total_damage, enchant_targets, carried_debuff_targets

    def _apply_block_enchant_damage(self, caster: UnitState, targets_hit: list,
                                     battlefield: BattlefieldState, total_damage: int) -> list:
        """Apply enchant damage after a block and return a list of effect dicts for narrative."""
        _log.info("[ENCHANT_BLOCK] %s: _apply_block_enchant_damage called, targets_hit=%s, total_dmg=%d",
                  caster.name, [(t.get('target_id'), t.get('target')) for t in targets_hit], total_damage)
        new_total, enchant_targets, carried_debuff_targets = self._process_enchant_damage(caster, targets_hit, battlefield, total_damage)
        # 附魔伤害+sub_unit伤害累加到技能累计伤害，供延迟执行的lifesteal使用
        enchant_damage_delta = new_total - total_damage
        if enchant_damage_delta > 0:
            self._most_recent_damage += enchant_damage_delta
            _log.info("[ENCHANT_BLOCK] %s: enchant+sub_unit damage %d accumulated to _most_recent_damage (total=%d)",
                      caster.name, enchant_damage_delta, self._most_recent_damage)
        results = []
        if enchant_targets:
            _log.info("[ENCHANT_BLOCK] %s: enchant_targets=%s, new_total=%d", caster.name,
                      [(t.get('target_id'), t.get('target'), t.get('actual_damage')) for t in enchant_targets], new_total)
            results.append({
                "effect_type": "damage",
                "targets": enchant_targets,
                "total_damage": new_total,
                "damage": new_total - total_damage,
            })
        else:
            _log.info("[ENCHANT_BLOCK] %s: NO enchant_targets returned, skipping", caster.name)
        if carried_debuff_targets:
            _log.info("[ENCHANT_BLOCK] %s: carried_debuff_targets=%d", caster.name, len(carried_debuff_targets))
            results.append({
                "effect_type": "aura",
                "is_debuff": True,
                "auras": carried_debuff_targets,
            })
        return results if results else None

    def _make_on_crit_callback(self, caster: UnitState, battlefield: BattlefieldState):
        """创建暴击回调函数，用于在多hit伤害中暴击后立即施加即时on_crit aura效果（如易伤）。

        回调在每个hit暴击后被调用，但对同一目标只施加一次（通过_on_crit_immediate_applied集合控制）。
        施加的debuff会立即生效，使后续hit的damage_received_mult重算时能享受易伤加成。
        """
        if not self._on_crit_immediate_blocks:
            return None

        def callback(attacker, defender, hit_number):
            # 每个目标只施加一次即时on_crit效果
            if defender.unit_id in self._on_crit_immediate_applied:
                return
            self._on_crit_immediate_applied.add(defender.unit_id)
            # 设置当前暴击目标，供crit_target target_type使用
            self._on_crit_target = defender
            _log.info("[ON_CRIT_IMMEDIATE] %s -> %s: applying %d immediate on_crit blocks (hit %d)",
                      attacker.name, defender.name, len(self._on_crit_immediate_blocks), hit_number)
            for block in self._on_crit_immediate_blocks:
                # 检查level_min/level_max
                block_condition = getattr(block, 'condition', None)
                if isinstance(block_condition, dict):
                    level_min = block_condition.get('level_min')
                    level_max = block_condition.get('level_max')
                else:
                    level_min = level_max = None
                skill_level = caster.skill_levels.get(self._current_skill_id, 1)
                if level_min is not None and skill_level < level_min:
                    continue
                if level_max is not None and skill_level > level_max:
                    continue
                for effect in block.effects:
                    effect_type = effect.effect_type
                    if effect_type in ("dmg_taken_up", "crit_rate_down", "atk_down", "def_down",
                                        "spd_down", "dmg_dealt_down", "stun"):
                        self._apply_aura(caster, effect, battlefield, is_debuff=True)
                        _log.info("[ON_CRIT_IMMEDIATE] %s -> %s: applied %s",
                                  attacker.name, defender.name, effect_type)
                    elif effect_type in ("atk_up", "crit_rate_up", "crit_dmg_up", "def_up",
                                          "spd_up", "dmg_dealt_up", "dmg_taken_down", "shield"):
                        self._apply_aura(caster, effect, battlefield, is_debuff=False)
                        _log.info("[ON_CRIT_IMMEDIATE] %s -> %s: applied %s (buff)",
                                  attacker.name, defender.name, effect_type)

        return callback

    def _apply_on_crit_blocks(self, caster: UnitState, target: UnitState,
                               battlefield: BattlefieldState, damage_effect) -> None:
        # 兼容旧逻辑：_on_crit_applied标志控制整个on_crit处理只触发一次
        # 新逻辑：通过block级别once_per_skill flag控制（默认true）
        # 当所有block都是once_per_skill=true时，_on_crit_applied确保只处理第一个暴击目标
        # 当存在once_per_skill=false的block时，对每个暴击目标都处理（但once_per_skill=true的block只执行一次）
        if self._on_crit_applied:
            # 检查是否有once_per_skill=false的block需要执行
            has_per_target_block = False
            for block in self._on_crit_blocks:
                block_condition = getattr(block, 'condition', None)
                if isinstance(block_condition, dict):
                    if not block_condition.get('once_per_skill', True):
                        has_per_target_block = True
                        break
            if not has_per_target_block:
                return
        if not target.is_alive:
            return
        # 设置当前暴击目标，供crit_target target_type使用
        self._on_crit_target = target
        if not self._on_crit_applied:
            self._on_crit_applied = True
        _log.info("[ON_CRIT] %s -> %s: processing %d on_crit blocks",
                  caster.name, target.name, len(self._on_crit_blocks))
        for block in self._on_crit_blocks:
            # 检查once_per_skill flag（默认true）
            block_condition = getattr(block, 'condition', None)
            if isinstance(block_condition, dict):
                once_per_skill = block_condition.get('once_per_skill', True)
            else:
                once_per_skill = True

            # once_per_skill=true且已执行过，跳过
            if once_per_skill and self._on_crit_block_executed.get(block.block_id, False):
                _log.info("[ON_CRIT] %s: skipping block %d (once_per_skill=true, already executed)",
                          caster.name, block.block_id)
                continue
            if once_per_skill:
                self._on_crit_block_executed[block.block_id] = True

            level_min = getattr(block, 'level_min', None)
            level_max = getattr(block, 'level_max', None)
            skill_level = caster.skill_levels.get(self._current_skill_id, 1)
            if level_min is not None and skill_level < level_min:
                _log.info("[ON_CRIT] %s: skipping block %d (level %d < min %d)",
                          caster.name, block.block_id, skill_level, level_min)
                continue
            if level_max is not None and skill_level > level_max:
                _log.info("[ON_CRIT] %s: skipping block %d (level %d > max %d)",
                          caster.name, block.block_id, skill_level, level_max)
                continue
            for effect in block.effects:
                effect_type = effect.effect_type
                if effect_type == "damage":
                    eff_flags = getattr(effect, 'flags', {}) or {}
                    dmg_skill_obj = type('obj', (object,), {
                        'power': getattr(effect, 'value', None) or 100.0,
                        'hit_count': getattr(effect, 'hit_count', None) or 1,
                        'element': caster.element,
                        'ignore_defense': getattr(effect, 'ignore_defense', 0) or 0,
                        'ignore_shield': getattr(effect, 'ignore_shield', 0) or 0,
                        'hp_scaling_bonus': 0.0,
                        'cannot_crit': eff_flags.get('cannot_crit', False),
                        'bonus_crit_rate': 0.0,
                        'skill_id': self._current_skill_id,
                        'name': self._get_skill_name(self._current_skill_id),
                        'base_value_source': eff_flags.get('value_source', None),
                    })()
                    tso = type('obj', (object,), {
                        'display_target_type': self._resolve_target_type(effect.target_type),
                        'display_target_range': self._resolve_target_range(effect.target_type),
                        'display_target_priority': None,
                        'target_type_name': effect.target_type,
                    })()
                    # crit_target: 使用当前暴击目标
                    if effect.target_type == "crit_target":
                        crit_target = getattr(self, '_on_crit_target', None)
                        if crit_target and crit_target.is_alive:
                            dmg_targets = [crit_target]
                        else:
                            dmg_targets = []
                    else:
                        dmg_targets = self.target_service.select_targets(tso, caster, battlefield) if self.target_service else [target]
                    dmg_targets = [t for t in dmg_targets if t.is_alive]
                    on_crit_targets_hit = []
                    for dt in dmg_targets:
                        hp_before = dt.current_hp
                        dmg_result = self.damage_service.calculate_damage(caster, dt, dmg_skill_obj)
                        actual = dmg_result.total_damage
                        shield_absorbed = 0
                        caster_char_type = getattr(caster, 'character_type', 1)
                        is_en_dmg = (caster_char_type == 2)
                        if is_en_dmg and dt.en_shield > 0:
                            if actual <= dt.en_shield:
                                dt.en_shield -= actual
                                shield_absorbed += actual
                                actual = 0
                            else:
                                shield_absorbed += dt.en_shield
                                actual -= dt.en_shield
                                dt.en_shield = 0
                        if not is_en_dmg and actual > 0 and dt.physical_shield > 0:
                            if actual <= dt.physical_shield:
                                dt.physical_shield -= actual
                                shield_absorbed += actual
                                actual = 0
                            else:
                                shield_absorbed += dt.physical_shield
                                actual -= dt.physical_shield
                                dt.physical_shield = 0
                        if actual > 0 and dt.shield > 0:
                            if actual <= dt.shield:
                                dt.shield -= actual
                                shield_absorbed += actual
                                actual = 0
                            else:
                                shield_absorbed += dt.shield
                                actual -= dt.shield
                                dt.shield = 0
                        # 非闪避命中最低1点伤害
                        if actual <= 0 and dmg_result.total_damage > 0:
                            actual = 1
                        dt.current_hp = max(0, dt.current_hp - actual)
                        _log.info("[ON_CRIT] %s -> %s: extra damage %d (hp now %d)",
                                  caster.name, dt.name, actual, dt.current_hp)
                        # === 伤害统计累加（与主流程 _apply_damage 保持一致） ===
                        # on_crit 追加伤害必须计入统计/lifesteal基础值/scoring
                        overflow = max(0, actual - hp_before)
                        caster.damage_dealt_total += actual
                        dt.damage_taken_total += actual
                        self._most_recent_damage += actual
                        tracker = getattr(battlefield, 'scoring_tracker', None)
                        if tracker is not None:
                            caster_side = "ally" if caster.side.value == "ally" else "enemy"
                            target_side = "ally" if dt.side.value == "ally" else "enemy"
                            tracker.record_damage(
                                source_id=caster.unit_id, source_name=caster.name, source_side=caster_side,
                                target_id=dt.unit_id, target_name=dt.name, target_side=target_side,
                                actual_damage=actual, shield_absorbed=shield_absorbed,
                                overflow=overflow if target_side == "enemy" else 0,
                            )
                        # 生成叙事日志条目
                        on_crit_targets_hit.append({
                            "target": dt.name,
                            "target_id": dt.unit_id,
                            "hp_before": hp_before,
                            "hp_after": dt.current_hp,
                            "damage": dmg_result.total_damage,
                            "actual_damage": actual,
                            "shield_absorbed": shield_absorbed,
                            "hit_shield_absorbed": [shield_absorbed],
                            "crit": dmg_result.is_critical,
                            "hits": dmg_result.hit_details,
                            "hit_crits": dmg_result.hit_crits,
                            "hit_evades": dmg_result.hit_evades,
                            "sub_unit_absorbs": [],
                            "calc_detail": dmg_result.calc_detail,
                        })
                        if dt.current_hp <= 0:
                            self._pending_deaths.add(dt.unit_id)
                            _log.info("[ON_CRIT] %s -> %s: killed by on_crit damage (death deferred)", caster.name, dt.name)
                    # 将追撃伤害结果添加到_on_crit_effects，用于叙事日志显示
                    if on_crit_targets_hit:
                        self._on_crit_effects.append({
                            "effect_type": "damage",
                            "targets": on_crit_targets_hit,
                            "total_damage": sum(t["actual_damage"] for t in on_crit_targets_hit),
                            "damage": sum(t["actual_damage"] for t in on_crit_targets_hit),
                            "bonus_crit_applied": 0,
                        })
                elif effect_type in ("dmg_taken_up", "crit_rate_down", "atk_down", "def_down",
                                      "spd_down", "dmg_dealt_down", "stun"):
                    aura_result = self._apply_aura(caster, effect, battlefield, is_debuff=True)
                    if aura_result:
                        self._on_crit_effects.append(aura_result)
                elif effect_type in ("atk_up", "crit_rate_up", "crit_dmg_up", "def_up",
                                      "spd_up", "dmg_dealt_up"):
                    aura_result = self._apply_aura(caster, effect, battlefield, is_debuff=False)
                    if aura_result:
                        self._on_crit_effects.append(aura_result)
                elif effect_type == "mark":
                    aura_result = self._apply_aura(caster, effect, battlefield, is_debuff=False)
                    if aura_result:
                        self._on_crit_effects.append(aura_result)
                elif effect_type == "add_status":
                    status_result = self._apply_add_status(caster, effect, battlefield)
                    if status_result:
                        self._on_crit_effects.append(status_result)
                elif effect_type == "modify_pp":
                    pp_result = self._apply_modify_pp(caster, effect, battlefield)
                    if pp_result:
                        self._on_crit_effects.append(pp_result)
                elif effect_type == "remove_buff_by_type":
                    rbbt_result = self._apply_remove_buff_by_type(caster, effect, battlefield)
                    if rbbt_result:
                        self._on_crit_effects.append(rbbt_result)
                else:
                    _log.info("[ON_CRIT] %s: unhandled effect_type=%s in on_crit block, skip",
                              caster.name, effect_type)

    def _apply_heal(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        if not self.target_service:
            _log.info("[HEAL] %s: target_service unavailable", caster.name)
            return None

        heal_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': self._resolve_target_range(effect.target_type),
            'display_target_priority': None,
            'target_type_name': effect.target_type,
        })()

        targets = self.target_service.select_targets(
            heal_skill_obj, caster, battlefield
        )

        # target_identifier resolution for heal effects
        target_identifier = getattr(effect, 'target_identifier', None)
        if target_identifier == "trigger_attacker":
            # after_ally_attacked 等 PS: trigger_attacker 可能是敌方攻击者，
            # 若雷 230383 需治疗受击友方 → 回退到 _primary_target / _damaged_targets
            ta = getattr(self, '_trigger_attacker', None)
            if ta and ta.is_alive and ta.side == caster.side:
                targets = [ta]
                _log.info("[HEAL] %s: trigger_attacker(ally) -> %s", caster.name, ta.name)
            else:
                damaged = getattr(self, '_damaged_targets', None)
                if damaged:
                    allies = [t for t in damaged if t.is_alive and t.side == caster.side]
                    if allies:
                        targets = [allies[0]]
                        _log.info("[HEAL] %s: trigger_attacker(enemy) fallback to damaged_ally -> %s",
                                  caster.name, allies[0].name)
                elif getattr(self, '_primary_target', None):
                    pt = self._primary_target
                    if pt and pt.is_alive and pt.side == caster.side:
                        targets = [pt]
                        _log.info("[HEAL] %s: trigger_attacker(enemy) fallback to primary_target -> %s",
                                  caster.name, pt.name)
        elif target_identifier == "primary_target":
            # Find the nearest attacked ally (self has distance 0 → highest priority)
            damaged = getattr(self, '_damaged_targets', None)
            if damaged:
                allies = [t for t in damaged if t.is_alive and t.side == caster.side]
                if allies:
                    allies.sort(key=lambda u: (
                        0 if u.unit_id == caster.unit_id else 1,
                        self.target_service._get_sort_key(caster, u) if self.target_service else 0
                    ))
                    targets = [allies[0]]
                    _log.info("[HEAL] %s: nearest_attacked_ally -> %s (among %d)",
                              caster.name, targets[0].name, len(allies))
            elif getattr(self, '_primary_target', None):
                primary = self._primary_target
                if primary and primary.is_alive:
                    targets = [primary]
                    _log.info("[HEAL] %s: primary_target -> %s", caster.name, primary.name)

        heal_pct = effect.value or 0
        _log.info("[HEAL_DEBUG] %s: effect.value=%s heal_pct=%s effect.effect_type=%s",
                  caster.name, effect.value, heal_pct, getattr(effect, 'effect_type', None))
        heal_flags = getattr(effect, 'flags', {}) or {}
        heal_base = heal_flags.get('heal_base', 'atk')

        # lowest_hp_priority: 选择HP比例最低的友方作为治疗目标
        # 两层优先：1.自身以外优先 2.HP比例最低（第一层优先级 > 第二层）
        if heal_flags.get('lowest_hp_priority') and targets:
            from src.entities_v2.enums import Side as _SideH
            ally_team = battlefield.friend_team if caster.side == _SideH.ALLY else battlefield.enemy_team
            all_allies = [u for u in ally_team if u.is_alive]
            if all_allies:
                # target_count_lv15: Lv15时治疗目标数增加（如仲間想いのリカバリーLv15→2体）
                _tc_lv15 = heal_flags.get('target_count_lv15')
                _heal_count = 1
                if _tc_lv15 and _tc_lv15 > 1:
                    _skill_id_h = self._current_skill_id
                    _skill_level_h = caster.skill_levels.get(_skill_id_h, 1)
                    if _skill_level_h >= 15:
                        _heal_count = _tc_lv15
                # 先取自身以外的友方按HP比例升序排序
                # tiebreaker: HP比例相同时（如全员满血）按距离施法者最近排序
                others = [u for u in all_allies if u.unit_id != caster.unit_id]
                others.sort(key=lambda u: (u.current_hp / max(u.max_hp, 1),
                                           self.target_service._get_sort_key(caster, u)))
                if others:
                    selected = others[:_heal_count]
                    # 非自身友方不足时用自身补位
                    if len(selected) < _heal_count and caster.is_alive:
                        selected.append(caster)
                    targets = selected
                else:
                    targets = [caster] if caster.is_alive else []
                _log.info("[HEAL] %s: lowest_hp_priority -> %s (count=%d, hp_pct=%.1f%%)",
                          caster.name, [t.name for t in targets], _heal_count,
                          targets[0].current_hp / max(targets[0].max_hp, 1) * 100 if targets else 0)

        # 记录heal主目标，供后续block的lowest_hp_row_only引用
        if targets:
            self._last_primary_target = targets[0]
            _log.info("[SKILL_EXEC] %s: recorded _last_primary_target (heal)=%s",
                      caster.name, targets[0].name)
        effective_atk = self.damage_service._calculate_final_stat(caster, "attack")
        effective_max_hp = self.damage_service._calculate_final_stat(caster, "max_hp")
        _log.info("[HEAL] %s: heal_pct=%d%% base=%s atk=%d max_hp=%d targets=%d",
                  caster.name, heal_pct, heal_base, effective_atk, effective_max_hp, len(targets))

        total_heal = 0
        heal_details = []
        skill_name = self._get_skill_name(self._current_skill_id)
        for target in targets:
            if not target.is_alive:
                continue
            hp_before = target.current_hp
            target_effective_max_hp = self.damage_service._calculate_final_stat(target, "max_hp")
            if heal_base == 'max_hp':
                heal_amount = int(target_effective_max_hp * heal_pct / 100)
            elif heal_base == 'lost_hp':
                # 基于目标已损失HP计算治疗量
                lost_hp = target_effective_max_hp - target.current_hp
                heal_amount = int(lost_hp * heal_pct / 100)
                _log.info("[HEAL] %s -> %s: heal_base=lost_hp lost_hp=%d heal_pct=%d%%",
                          caster.name, target.name, lost_hp, heal_pct)
            else:
                heal_amount = int(effective_atk * heal_pct / 100)

            # debuff_heal_bonus: 目标有debuff时治疗量+100%（如イケてる♡イケてる）
            if heal_flags.get('debuff_heal_bonus') and target.debuffs:
                heal_amount = heal_amount * 2
                _log.info("[HEAL] %s -> %s: debuff_heal_bonus triggered (target has %d debuffs), heal x2=%d",
                          caster.name, target.name, len(target.debuffs), heal_amount)

            # 治疗暴击判定：暴击率引用治疗发起者，暴击时治疗量1.5倍
            # HP百分比治疗（max_hp/lost_hp）不可暴击，仅ATK基数治疗可暴击
            is_heal_crit = False
            if heal_base == 'atk':
                is_heal_crit = self.damage_service.check_heal_crit(caster, {
                    'healer_name': caster.name,
                    'target_name': target.name,
                    'target_id': target.unit_id,
                    'skill_name': skill_name,
                    'skill_id': self._current_skill_id,
                })
                if is_heal_crit:
                    heal_amount = int(heal_amount * 1.5)
                    _log.info("[HEAL_CRIT] %s -> %s: heal CRIT! heal_amount=%d (x1.5)",
                              caster.name, target.name, heal_amount)

            # 受到治疗量乘区：目标身上的ReceivedHealing buff/debuff
            heal_received_mult = self.damage_service._get_heal_received_multiplier(target)
            if heal_received_mult != 1.0:
                heal_amount = int(heal_amount * heal_received_mult)
                _log.info("[HEAL_EFFICACY] %s -> %s: heal_efficacy_mult=%.4f heal_amount=%d",
                          caster.name, target.name, heal_received_mult, heal_amount)

            # 实际回血量：不超过缺失HP
            missing_hp = target_effective_max_hp - target.current_hp
            actual_heal = min(heal_amount, missing_hp)
            target.current_hp = min(target_effective_max_hp, target.current_hp + heal_amount)
            total_heal += actual_heal
            heal_details.append({
                "target": target.name,
                "target_id": target.unit_id,
                "hp_before": hp_before,
                "hp_after": target.current_hp,
                "amount": actual_heal,
                "is_crit": is_heal_crit,
                "heal_formula": f"[ATK:{effective_atk} base:{heal_base} pct:{heal_pct}% crit:{'1.5' if is_heal_crit else '1.0'} efficacy:{heal_received_mult:.4f} raw:{heal_amount}]",
            })
            crit_tag = "【Critical】" if is_heal_crit else ""
            _log.info("[HEAL] %s -> %s: hp %d→%d (+%d, raw=%d) %s",
                      caster.name, target.name, hp_before, target.current_hp, actual_heal, heal_amount, crit_tag)

            # 计分追踪：记录实际治疗量（不含溢出）
            tracker = getattr(battlefield, 'scoring_tracker', None)
            if tracker is not None:
                caster_side = "ally" if caster.side.value == "ally" else "enemy"
                target_side = "ally" if target.side.value == "ally" else "enemy"
                tracker.record_heal(
                    source_id=caster.unit_id, source_name=caster.name, source_side=caster_side,
                    target_id=target.unit_id, target_name=target.name, target_side=target_side,
                    heal_amount=actual_heal,
                )

        return {"effect_type": "heal", "total_heal": total_heal, "heals": heal_details}

    def _apply_aura(self, caster: UnitState, effect, battlefield: BattlefieldState, is_debuff: bool) -> Optional[Dict]:
        if not self.aura_service or not self.target_service:
            _log.info("[AURA_APPLY] %s: aura_service or target_service unavailable", caster.name)
            return None

        if effect.effect_type == "add_fury":
            caster.fury_count += 1
            _log.info("[FURY] %s: fury_count=%d", caster.name, caster.fury_count)
            return {"effect_type": "add_fury", "fury_count": caster.fury_count}

        # target_count > 1时扩展目标范围（如ally_single + target_count=2 → 选择2体友方）
        _aura_flags = getattr(effect, 'flags', {}) or {}
        _aura_target_count = _aura_flags.get('target_count', 0)
        _resolved_range = self._resolve_target_range(effect.target_type)
        if _aura_target_count and _aura_target_count > 1 and _resolved_range == 1:  # ONE_PAWN
            from ...entities_v2.enums import DisplayTargetRange
            _resolved_range = (DisplayTargetRange.TWO_PAWNS.value if _aura_target_count == 2
                               else DisplayTargetRange.ALL_PAWNS.value)

        # 特殊索敌类型（highest_atk/highest_spd/highest_hp_ratio等）需用ALL_PAWNS获取全部候选再后过滤，
        # 否则ONE_PAWN会先选出最近敌方，后过滤只有1个目标可选（与damage路径保持一致）
        _AURA_SPECIAL_POSTFILTER_TYPES = {
            "enemy_single_highest_atk", "enemy_single_highest_spd",
            "enemy_single_lowest_spd", "enemy_single_furthest",
            "enemy_single_highest_ep",
            "enemy_single_highest_hp_ratio",
            "enemy_single_highest_current_hp",
            "enemy_single_highest_hp_ratio_back_priority",
            "enemy_single_lowest_hp_ratio",
            "enemy_column_furthest", "enemy_column_mark_priority",
        }
        if effect.target_type in _AURA_SPECIAL_POSTFILTER_TYPES:
            from ...entities_v2.enums import DisplayTargetRange
            _resolved_range = DisplayTargetRange.ALL_PAWNS.value

        aura_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': _resolved_range,
            'display_target_priority': self._current_skill_priority,
            'target_type_name': effect.target_type,
        })()

        # Use cached damage targets if available (ensures aura effects target the same unit as damage)
        cached_targets = getattr(self, '_block_damage_targets', None)
        if effect.target_type == "crit_target":
            # crit_target: on_crit block中使用，指向当前暴击目标
            crit_target = getattr(self, '_on_crit_target', None)
            if crit_target and crit_target.is_alive:
                targets = [crit_target]
                _log.info("[AURA_APPLY] %s: crit_target -> %s",
                          caster.name, crit_target.name)
            else:
                _log.info("[AURA_APPLY] %s: crit_target unavailable, no targets", caster.name)
                return None
        # target_identifier resolution for aura/shield effects
        elif getattr(effect, 'target_identifier', None) == "triggered_by":
            primary = getattr(self, '_primary_target', None)
            if primary and primary.is_alive:
                targets = [primary]
                _log.info("[AURA_APPLY] %s: triggered_by -> %s", caster.name, primary.name)
            else:
                _log.info("[AURA_APPLY] %s: triggered_by target not available", caster.name)
                return None
        elif effect.target_type == "attacked_targets":
            # attacked_targets: 收集技能中所有已攻击目标（跨block累积）
            all_attacked = []
            seen = set()
            # 优先使用当前block的_block_damage_targets
            if cached_targets and isinstance(cached_targets, dict):
                for units in cached_targets.values():
                    for u in units:
                        if u.unit_id not in seen and u.is_alive:
                            seen.add(u.unit_id)
                            all_attacked.append(u)
            # 补充技能级别的_skill_all_attacked_targets（跨block累积）
            skill_attacked = getattr(self, '_skill_all_attacked_targets', []) or []
            for u in skill_attacked:
                if u.unit_id not in seen and u.is_alive:
                    seen.add(u.unit_id)
                    all_attacked.append(u)
            targets = all_attacked
            _log.info("[AURA_APPLY] %s: attacked_targets -> %s",
                      caster.name, [t.name for t in targets])
        elif cached_targets is not None and isinstance(cached_targets, dict) and effect.target_type in cached_targets:
            targets = [t for t in cached_targets[effect.target_type] if t.is_alive]
            _log.info("[AURA_APPLY] %s: using cached damage targets for %s -> %s",
                      caster.name, effect.target_type, [t.name for t in targets])
        else:
            targets = self.target_service.select_targets(
                aura_skill_obj, caster, battlefield
            )

        # Handle debuff_applied_target: use primary_target from trigger context
        if effect.target_type == "debuff_applied_target":
            primary_target = getattr(self, '_primary_target', None)
            # 检查当前PS是否设置了exclude_self（如130125 気合い入れていこー！：
            # 其他友方被上debuff时触发，remove_debuff应作用于被上debuff的友方而非自身）
            current_skill_id = getattr(self, '_current_skill_id', 0)
            parsed_skill = self.data_loader.get_parsed_skill_data(current_skill_id) if current_skill_id else None
            gc = parsed_skill.get('global_condition', {}) if parsed_skill else {}
            exclude_self = bool(gc.get('exclude_self', 0)) if gc else False
            if exclude_self:
                # exclude_self: 从触发上下文中找非自身的友方目标
                # 多个友方同时被上debuff时，选取距离自身最近的被上debuff的友方
                ctx_targets = getattr(self, '_damaged_targets', None) or []
                non_self_targets = [t for t in ctx_targets
                                     if t.unit_id != caster.unit_id and t.is_alive
                                     and t.side == caster.side]
                if non_self_targets:
                    nearest = self.target_service.get_nearest_ally(caster, non_self_targets)
                    if nearest:
                        primary_target = nearest
                        _log.info("[AURA_APPLY] %s: debuff_applied_target exclude_self -> redirected to nearest %s",
                                  caster.name, primary_target.name)
            if primary_target and primary_target.is_alive:
                targets = [primary_target]
                _log.info("[AURA_APPLY] %s: debuff_applied_target -> %s",
                          caster.name, primary_target.name)

        trigger_attacker = getattr(self, '_trigger_attacker', None)
        if trigger_attacker and is_debuff and effect.target_type in ("enemy_single", "enemy", "enemies", "last_target"):
            # 仅当trigger_attacker为敌方时覆盖（反击系PS：被敌人攻击后对敌人施加debuff）
            # 自触发PS（如on_skill_use_count）的trigger_attacker是PS持有者自身，不应覆盖敌方目标
            # last_target: after_as_attacked系PS（如130007スタン・オブ・ダウン）对攻击者施加stun
            if trigger_attacker.side != caster.side and trigger_attacker.is_alive:
                targets = [trigger_attacker]
                _log.info("[AURA_APPLY] %s: using trigger_attacker=%s as target (counter-attack, target_type=%s)",
                          caster.name, trigger_attacker.name, effect.target_type)

        if trigger_attacker and effect.target_type in ("ally_single", "last_target"):
            # ally_single: 触发源指定的单个友方（如追撃符的触发者）
            # last_target: before_ally_as_attack系PS（如130057ポイズンライド）对攻击友方追加伤害/毒
            #   技能描述「当該攻撃に威力{威力}のダメージと、3行動分の毒効果を追加する」
            #   last_target在此上下文应指向触发源（即将攻击的友方），而非敌方目标
            if trigger_attacker.is_alive:
                targets = [trigger_attacker]
                _log.info("[AURA_APPLY] %s: using trigger_attacker=%s as ally/last_target (target_type=%s)",
                          caster.name, trigger_attacker.name, effect.target_type)

        # Element filter must come AFTER trigger_attacker override
        element_filter = getattr(self, '_target_element_filter', None)
        if element_filter is not None:
            targets = [t for t in targets if getattr(t, 'element', 0) == element_filter]
            _log.info("[AURA_APPLY] %s: element filter=%d, filtered targets=%d",
                      caster.name, element_filter, len(targets))

        # Character type filter (for target_character_type block condition)
        # Supports int (single type) or list (multiple types, e.g. [1,3] for physical or agile)
        char_type_filter = getattr(self, '_target_char_type_filter', None)
        if char_type_filter is not None:
            if isinstance(char_type_filter, int):
                char_type_filter = [char_type_filter]
            targets = [t for t in targets if getattr(t, 'character_type', 0) in char_type_filter]
            _log.info("[AURA_APPLY] %s: char_type filter=%s, filtered targets=%d",
                      caster.name, char_type_filter, len(targets))

        if effect.target_type == "ally_front_row":
            # ally_front_row: 所有前排友方（如さて……準備はできたわ的加攻目标）
            from src.entities_v2.enums import Side as _SideFR
            team = battlefield.friend_team if caster.side == _SideFR.ALLY else battlefield.enemy_team
            front_row_allies = [u for u in team if u.is_alive and u.position.value.endswith('_front')]
            if front_row_allies:
                targets = front_row_allies
                _log.info("[AURA_APPLY] %s: ally_front_row -> %s",
                          caster.name, [t.name for t in targets])
            else:
                _log.info("[AURA_APPLY] %s: ally_front_row -> no front-row allies", caster.name)

        if effect.target_type == "ally_front":
            # ally_front: owner正前方的友方（如代助一避的闪避buff目标）
            from src.combat_v2.services.trigger_service import _get_front_position
            front_pos = _get_front_position(caster.position)
            if front_pos:
                from src.entities_v2.enums import Side as _Side
                team = battlefield.friend_team if caster.side == _Side.ALLY else battlefield.enemy_team
                front_allies = [u for u in team if u.is_alive and u.position == front_pos]
                if front_allies:
                    targets = front_allies
                    _log.info("[AURA_APPLY] %s: ally_front -> %s (front_pos=%s)",
                              caster.name, [t.name for t in targets], front_pos.value)
                else:
                    _log.info("[AURA_APPLY] %s: ally_front -> no ally at front_pos=%s",
                              caster.name, front_pos.value)
            else:
                _log.info("[AURA_APPLY] %s: ally_front -> caster at front, no front ally", caster.name)

        if effect.target_type and "highest_atk" in effect.target_type:
            if targets:
                best = self.target_service.select_max_with_stealth(
                    targets,
                    key_func=lambda u: self.damage_service._calculate_final_stat(u, "attack") if self.damage_service else u.attack,
                    consume=True
                )
                targets = [best] if best else []
                best_atk = self.damage_service._calculate_final_stat(best, "attack") if self.damage_service else best.attack
                _log.info("[AURA_APPLY] %s: highest_atk filter -> %s (atk=%d)",
                          caster.name, best.name, best_atk)

        if effect.target_type and "highest_spd" in effect.target_type:
            if targets:
                best = self.target_service.select_max_with_stealth(
                    targets,
                    key_func=lambda u: self.damage_service._calculate_final_stat(u, "speed") if self.damage_service else u.speed,
                    consume=True
                )
                targets = [best] if best else []
                best_spd = self.damage_service._calculate_final_stat(best, "speed") if self.damage_service else best.speed
                _log.info("[AURA_APPLY] %s: highest_spd filter -> %s (spd=%d)",
                          caster.name, best.name, best_spd)

        if effect.target_type == "enemy_single_highest_hp_ratio_back_priority":
            if targets:
                back_targets = [u for u in targets if self.target_service._is_back_row(u)]
                search_pool = back_targets if back_targets else targets
                best = self.target_service.select_max_with_stealth(
                    search_pool,
                    key_func=lambda u: (u.current_hp / u.max_hp) if u.max_hp > 0 else 0,
                    consume=True
                )
                targets = [best] if best else []
                _log.info("[AURA_APPLY] %s: highest_hp_ratio_back_priority filter -> %s",
                          caster.name, best.name)

        if effect.target_type == "enemy_single_highest_hp_ratio":
            if targets:
                best = self.target_service.select_max_with_stealth(
                    targets,
                    key_func=lambda u: (u.current_hp / u.max_hp) if u.max_hp > 0 else 0,
                    consume=True
                )
                targets = [best] if best else []
                _log.info("[AURA_APPLY] %s: highest_hp_ratio filter -> %s",
                          caster.name, best.name)

        if effect.target_type == "enemy_single_highest_current_hp":
            if targets:
                best = self.target_service.select_max_with_stealth(
                    targets,
                    key_func=lambda u: u.current_hp,
                    consume=True
                )
                targets = [best] if best else []
                _log.info("[AURA_APPLY] %s: highest_current_hp filter -> %s (hp=%d)",
                          caster.name, best.name, best.current_hp)

        if effect.target_type == "enemy_single_lowest_hp_ratio":
            if targets:
                best = self.target_service.select_min_with_stealth(
                    targets,
                    key_func=lambda u: (u.current_hp / u.max_hp) if u.max_hp > 0 else 0,
                    consume=True
                )
                targets = [best] if best else []
                _log.info("[AURA_APPLY] %s: lowest_hp_ratio filter -> %s",
                          caster.name, best.name)

        if effect.target_type == "ally_back" and caster.position.name.endswith("BACK"):
            if caster.is_alive and caster not in targets:
                targets.append(caster)
                _log.info("[AURA_APPLY] %s: ally_back including self (caster in back row)", caster.name)

        # lowest_hp_priority for aura effects: select ally with lowest HP ratio
        effect_flags_aura = getattr(effect, 'flags', {}) or {}
        if effect_flags_aura.get('lowest_hp_priority'):
            # Get all alive allies as candidates (including caster, even if target_type excluded caster)
            from src.entities_v2.enums import Side as _Side2
            ally_team = battlefield.friend_team if caster.side == _Side2.ALLY else battlefield.enemy_team
            all_allies = [u for u in ally_team if u.is_alive]
            if all_allies:
                all_allies.sort(key=lambda u: u.current_hp / max(u.max_hp, 1))
                targets = [all_allies[0]]
                _log.info("[AURA_APPLY] %s: lowest_hp_priority -> %s (hp_pct=%.1f%%)",
                          caster.name, targets[0].name,
                          targets[0].current_hp / max(targets[0].max_hp, 1) * 100)

        # en_type_priority for ally aura: prioritize EN type allies, fallback to self
        # 配合 ally_single_include_self 使用：
        #   1. 先取不包括自身的EN类型友方列表，有则取离自身最近的
        #   2. 若无EN类型友方，取离自身最近的友方(自身以外)
        #   3. 若无任何自身以外友方，回退自身
        # 注意：必须在select_targets缩窄到ONE_PAWN之前对完整友方列表排序，
        #       否则最近的物理友方会先被选中而遗漏更远的EN友方
        if effect_flags_aura.get('en_type_priority') and targets:
            from src.entities_v2.enums import Side as _SideEN
            ally_team = battlefield.friend_team if caster.side == _SideEN.ALLY else battlefield.enemy_team
            others = [u for u in ally_team if u.is_alive and u.unit_id != caster.unit_id]
            if others:
                # 按距离施法者最近排序（与select_targets的NEAREST优先级一致）
                others.sort(key=lambda u: self.target_service._get_sort_key(caster, u))
                en_ordered = [u for u in others if getattr(u, 'character_type', 0) == 2]
                non_en_ordered = [u for u in others if getattr(u, 'character_type', 0) != 2]
                priority_list = en_ordered + non_en_ordered
                if priority_list:
                    targets = [priority_list[0]]
                    _log.info("[AURA_APPLY] %s: en_type_priority -> %s (character_type=%d)",
                              caster.name, targets[0].name, getattr(targets[0], 'character_type', 0))
                else:
                    targets = [caster]
                    _log.info("[AURA_APPLY] %s: en_type_priority fallback -> self (no other ally in targets)",
                              caster.name)
            else:
                targets = [caster]
                _log.info("[AURA_APPLY] %s: en_type_priority fallback -> self (no other ally)", caster.name)

        # lowest_hp_row_only for ally_row/ally_column: select allies in same row/column as primary target
        if effect_flags_aura.get('lowest_hp_row_only') and effect.target_type in ('ally_row', 'ally_column'):
            from src.entities_v2.enums import Side as _Side3
            ally_team = battlefield.friend_team if caster.side == _Side3.ALLY else battlefield.enemy_team
            all_allies = [u for u in ally_team if u.is_alive]
            if all_allies:
                # 优先使用前序block记录的主目标（如Block1的heal目标），
                # 避免因Block1治疗改变了HP比例导致重新计算得到不同目标
                if hasattr(self, '_last_primary_target') and self._last_primary_target:
                    ref_ally = self._last_primary_target
                    _log.info("[AURA_APPLY] %s: lowest_hp_row_only using _last_primary_target=%s",
                              caster.name, ref_ally.name)
                else:
                    # 回退：重新计算最低HP友方
                    all_allies.sort(key=lambda u: u.current_hp / max(u.max_hp, 1))
                    ref_ally = all_allies[0]
                # Determine row or column positions based on caster's side
                from src.entities_v2.enums import Position as _Pos
                ref_pos = ref_ally.position
                is_front = 'FRONT' in ref_pos.name
                if effect.target_type == 'ally_row':
                    # Same row (front/back)
                    if caster.side == _Side3.ALLY:
                        row_positions = {
                            _Pos.ALLY_LEFT_FRONT, _Pos.ALLY_CENTER_FRONT, _Pos.ALLY_RIGHT_FRONT
                        } if is_front else {
                            _Pos.ALLY_LEFT_BACK, _Pos.ALLY_CENTER_BACK, _Pos.ALLY_RIGHT_BACK
                        }
                    else:
                        row_positions = {
                            _Pos.ENEMY_LEFT_FRONT, _Pos.ENEMY_CENTER_FRONT, _Pos.ENEMY_RIGHT_FRONT
                        } if is_front else {
                            _Pos.ENEMY_LEFT_BACK, _Pos.ENEMY_CENTER_BACK, _Pos.ENEMY_RIGHT_BACK
                        }
                    row_allies = [u for u in all_allies if u.position in row_positions]
                    if row_allies:
                        targets = row_allies
                        _log.info("[AURA_APPLY] %s: lowest_hp_row_only -> row=%s targets=%s (ref=%s hp_pct=%.1f%%)",
                                  caster.name, "front" if is_front else "back",
                                  [t.name for t in targets], ref_ally.name,
                                  ref_ally.current_hp / max(ref_ally.max_hp, 1) * 100)
                else:  # ally_column
                    # Same column: left/center/right
                    col_index = _POS_RC.get(ref_pos, (0, 0))[1]
                    col_positions = set()
                    for pos in _POS_RC:
                        if _POS_RC[pos][1] == col_index:
                            col_positions.add(pos)
                    col_allies = [u for u in all_allies if u.position in col_positions]
                    if col_allies:
                        targets = col_allies
                        _log.info("[AURA_APPLY] %s: lowest_hp_row_only (column) -> col=%d targets=%s (ref=%s hp_pct=%.1f%%)",
                                  caster.name, col_index,
                                  [t.name for t in targets], ref_ally.name,
                                  ref_ally.current_hp / max(ref_ally.max_hp, 1) * 100)

        carried_debuff = effect_flags_aura.get('carried_debuff', False)
        if carried_debuff and is_debuff:
            _log.info("[AURA_APPLY] %s: carried_debuff flag detected (type=%s) - this debuff will be applied to attacked enemy later",
                      caster.name, effect.effect_type)
        # front_priority: 前列味方優先（如PS2 shield「前列の味方を優先し」）
        # 排序: 前排(0) < 后排(1)，同排内按距施法者最近优先
        if effect_flags_aura and effect_flags_aura.get('front_priority'):
            targets.sort(key=lambda u: (
                0 if self.target_service._is_front_row(u) else 1,
                self.target_service._get_sort_key(caster, u)
            ))
            _log.info("[AURA_APPLY] %s: front_priority sorted -> %s",
                      caster.name, [t.name for t in targets])
        # nearest_ally: 自身から最も近い味方（如120056 Lv11+ shield「自身から最も近い味方に対し」）
        # 从已选目标中筛选距离施法者最近的一个；若候选为空（如 ally_single 未命中），回退到全体友方
        target_identifier = getattr(effect, 'target_identifier', None)
        if target_identifier == "nearest_ally":
            from src.entities_v2.enums import Side as _SideNA
            team = battlefield.friend_team if caster.side == _SideNA.ALLY else battlefield.enemy_team
            candidates = [u for u in team if u.is_alive and u.unit_id != caster.unit_id]
            if candidates and self.target_service:
                nearest = self.target_service.get_nearest_ally(caster, candidates)
                if nearest:
                    targets = [nearest]
                    _log.info("[AURA_APPLY] %s: nearest_ally -> %s",
                              caster.name, nearest.name)
                else:
                    targets = []
                    _log.info("[AURA_APPLY] %s: nearest_ally -> no ally available", caster.name)
            else:
                targets = []
                _log.info("[AURA_APPLY] %s: nearest_ally -> no ally available", caster.name)
        aura_target_count = effect_flags_aura.get('target_count')
        if aura_target_count is not None and aura_target_count > 0 and len(targets) > aura_target_count:
            targets = targets[:aura_target_count]
            _log.info("[AURA_APPLY] %s: limited targets by target_count=%d -> %s",
                      caster.name, aura_target_count, [t.name for t in targets])

        # cover替换：如果cover生效，debuff目标也应替换为cover者
        if is_debuff:
            targets = self._apply_cover_debuff_replacement(caster, targets, battlefield)

        value = effect.value or 0
        hp_scaling_buff = effect_flags_aura.get('hp_scaling')
        if hp_scaling_buff and value > 0:
            if effect_flags_aura.get('hp_scaling_enemy'):
                enemies = [u for u in battlefield.enemy_team if u.is_alive]
                if enemies:
                    rc, cc = _POS_RC[caster.position]
                    nearest = min(enemies, key=lambda u: (
                        (_POS_RC[u.position][0] - rc) ** 2 + (_POS_RC[u.position][1] - cc) ** 2,
                        _POS_RC[u.position][0], _POS_RC[u.position][1]
                    ))
                    hp_ratio = nearest.current_hp / nearest.max_hp if nearest.max_hp > 0 else 0
                else:
                    hp_ratio = 0
            else:
                hp_ratio = caster.current_hp / caster.max_hp if caster.max_hp > 0 else 0
            original_value = value
            value = value * hp_ratio
            _log.info("[AURA_APPLY] %s: HP-scaling buff hp_ratio=%.3f value %.1f -> %.1f",
                      caster.name, hp_ratio, original_value, value)
        dur_type = getattr(effect, 'duration_type', None) or "action"
        original_dur_type = getattr(effect, 'duration_type', None) or ""  # 保存原始duration_type用于清理
        effect_dur = getattr(effect, 'duration', None)
        if dur_type == "hit":
            # Hit-limited effects: duration=-1 (permanent), lifespan controlled by hit_limited
            hit_limited_from_dur = effect_dur if effect_dur and effect_dur > 0 else 0
            duration = -1
        elif dur_type == "attack":
            # Attack-limited effects: duration=-1 (permanent), lifespan controlled by attack_limited
            hit_limited_from_dur = 0
            duration = -1
            # debuff_immune/dmg_invulnerable不应设置attack_limited——它们的生命周期由hit_limited控制
            # （阻挡N次后消失），而非在持有者攻击后消失
            is_hit_limited_lifecycle = effect.effect_type in ("debuff_immune", "DebuffImmune",
                                                              "dmg_invulnerable", "DmgInvulnerable")
            if not is_hit_limited_lifecycle and not (effect_flags_aura and effect_flags_aura.get('attack_limited')):
                if effect_flags_aura is None:
                    effect_flags_aura = {}
                effect_flags_aura['attack_limited'] = 1
        elif dur_type == "attacker_action":
            # Guard: duration=-1 (permanent), lifespan controlled by triggered_by_attacker
            # Cleaned up immediately after the triggering skill ends (not at attacker's action end)
            hit_limited_from_dur = 0
            duration = -1
        elif effect_dur is not None:
            hit_limited_from_dur = 0
            duration = effect_dur
        else:
            hit_limited_from_dur = 0
            duration = -1

        if dur_type == "action":
            timing = AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value
            # duration_owner: 当flags中指定duration_owner="caster"时，
            # duration在施法者行动结束时减少，而非目标行动结束时减少
            if effect_flags_aura.get('duration_owner') == 'caster':
                timing = AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END.value
                _log.info("[AURA_APPLY] %s: duration_owner=caster -> timing=DURABLE_SOURCE_MANEUVER_END", caster.name)
        elif dur_type == "hit":
            # Hit-limited: use DURABLE_WHEN_USED timing (never expires on turn/action boundaries)
            timing = AuraUpdateTiming.DURABLE_WHEN_USED.value
        elif dur_type == "attack":
            # Attack-limited: use DURABLE_WHEN_USED timing (never expires on turn/action boundaries)
            timing = AuraUpdateTiming.DURABLE_WHEN_USED.value
        elif dur_type == "skill":
            # 技能内临时效果：技能结束时立即消失
            timing = AuraUpdateTiming.EPHEMERAL_SKILL_END.value
        elif dur_type == "attacker_action":
            # Guard: use DURABLE_WHEN_USED timing (never expires on turn/action boundaries)
            # Cleaned up immediately after the triggering skill ends
            timing = AuraUpdateTiming.DURABLE_WHEN_USED.value
        elif dur_type == "turn":
            # 回合制: 不在行动结束时递减（DURABLE_WHEN_USED不被process_maneuver_end处理）
            # 由aura_service.process_turn_end在回合结束时统一递减
            timing = AuraUpdateTiming.DURABLE_WHEN_USED.value
            _log.info("[AURA_APPLY] %s: duration_type=turn -> timing=DURABLE_WHEN_USED (decrement at turn end)", caster.name)
        else:
            timing = AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END.value

        mapped_effect_type = _JSON_EFFECT_TO_ENUM.get(effect.effect_type, effect.effect_type)
        mapped_effect_type = _MASTERDATA_STATUS_MAP.get(effect.effect_type, mapped_effect_type)

        aura_type = "Debuff" if is_debuff else "Buff"
        _log.info("[AURA_APPLY] %s: type=%s effect=%s (mapped=%s) value=%d dur=%d targets=%d",
                  caster.name, aura_type, effect.effect_type, mapped_effect_type, value, duration, len(targets))

        aura_details = []
        blocked_details = []  # 被免疫/闪避的debuff记录
        actual_is_debuff = is_debuff  # default; may be overridden per-target below
        effect_condition = getattr(effect, 'condition', None)

        # 对于target_hp_below/target_hp_above等基于伤害目标的条件，
        # 当buff目标为self时，应检查伤害目标而非buff目标
        # 且应使用伤害前的HP（参考用户确认：target_hp_below基于伤害前的HP）
        _skip_per_target_condition = False
        if effect_condition and isinstance(effect_condition, dict):
            cond_type = effect_condition.get('type', '')
            if cond_type in ('target_hp_below', 'target_hp_above') and effect.target_type == "self":
                dmg_targets_cache = getattr(self, '_block_damage_targets', None)
                pre_damage_hp = getattr(self, '_pre_damage_hp', {})
                if dmg_targets_cache and isinstance(dmg_targets_cache, dict):
                    # 遍历所有缓存的伤害目标，取第一个存活的作为条件检查对象
                    cond_target = None
                    for _tt, _dt_list in dmg_targets_cache.items():
                        for _dt in _dt_list:
                            if _dt.is_alive:
                                cond_target = _dt
                                break
                        if cond_target:
                            break
                    if cond_target:
                        # 使用伤害前HP进行条件判定
                        saved_hp = cond_target.current_hp
                        pre_hp = pre_damage_hp.get(cond_target.unit_id, saved_hp)
                        cond_target.current_hp = pre_hp
                        condition_met = self._check_target_condition(cond_target, effect_condition)
                        cond_target.current_hp = saved_hp  # 恢复
                        if not condition_met:
                            _log.info("[AURA_APPLY] %s: SKIPPED entire effect (condition %s on damage target %s not met, pre_damage_hp_pct=%.1f%%)",
                                      caster.name, cond_type, cond_target.name,
                                      pre_hp / max(cond_target.max_hp, 1) * 100)
                            return None
                        # 条件已对伤害目标验证通过，跳过per-target的条件检查
                        _skip_per_target_condition = True

        # exclude_self: 排除施法者自身（如リカバリーブースト Lv11+的横排def_up排除自身）
        if effect_flags_aura.get('exclude_self'):
            targets = [t for t in targets if t.unit_id != caster.unit_id]
            _log.info("[AURA_APPLY] %s: exclude_self -> targets=%s", caster.name, [t.name for t in targets])

        # 双向ダメージリンク: enemy_nearest_and_farthest + link_mode=bidirectional
        # 每个目标的damage_link buff的source_unit_id指向配对目标（而非施法者）
        _bidir_link_map = {}  # target.unit_id -> paired_target.unit_id
        is_bidir_damage_link = (effect.effect_type == "damage_link"
                                and effect_flags_aura.get('link_mode') == 'bidirectional')
        if is_bidir_damage_link and len(targets) >= 2:
            for i in range(len(targets)):
                paired = targets[(i + 1) % len(targets)]
                _bidir_link_map[targets[i].unit_id] = paired.unit_id
            _log.info("[AURA_APPLY] %s: bidirectional damage_link pairs=%s",
                      caster.name,
                      [(t.name, next((p.name for p in targets if p.unit_id == _bidir_link_map[t.unit_id]), '?')) for t in targets])

        for target in targets:
            if not target.is_alive:
                continue

            if not _skip_per_target_condition and not self._check_target_condition(target, effect_condition):
                _log.info("[AURA_APPLY] %s -> %s: SKIPPED (condition %s not met)",
                          caster.name, target.name, effect_condition.get('type') if effect_condition else 'none')
                continue

            actual_is_debuff = is_debuff
            if carried_debuff and caster.side == target.side:
                actual_is_debuff = False
                _log.info("[AURA_APPLY] %s -> %s: carried_debuff applied as buff (payload will trigger on attack)",
                          caster.name, target.name)

            # Mark with is_buff_mark flag should be stored as buff, not debuff
            if effect.effect_type == "mark" and effect_flags_aura.get('is_buff_mark'):
                actual_is_debuff = False
                _log.info("[AURA_APPLY] %s -> %s: mark '%s' stored as buff (is_buff_mark=True)",
                          caster.name, target.name, effect_flags_aura.get('mark_name', ''))

            # skip_if_exists: 若目标已有同名mark则跳过付与（不刷新持续时间）
            if (effect.effect_type == "mark" and effect_flags_aura.get('skip_if_exists')):
                mark_name_to_check = effect_flags_aura.get('mark_name', '')
                already_has = any(
                    b.effect_type == SkillEffectType.MARK.value and getattr(b, 'name', '') == mark_name_to_check
                    for b in target.buffs
                ) or any(
                    d.effect_type == SkillEffectType.MARK.value and getattr(d, 'name', '') == mark_name_to_check
                    for d in target.debuffs
                )
                if already_has:
                    _log.info("[AURA_APPLY] %s -> %s: mark '%s' SKIPPED (skip_if_exists, already has)",
                              caster.name, target.name, mark_name_to_check)
                    continue

            # max_stacks: 若目标已持有同名mark达到上限则跳过（如「負けん気」最大持有数）
            if effect.effect_type == "mark":
                _max_stacks = effect_flags_aura.get('max_stacks')
                _max_stacks_tag = effect_flags_aura.get('max_stacks_tag')
                if _max_stacks is not None or _max_stacks_tag:
                    _actual_max = _max_stacks
                    if _max_stacks_tag:
                        _resolved = self._resolve_tag_value_for_caster(caster, effect, _max_stacks_tag)
                        if _resolved is not None:
                            _actual_max = int(_resolved)
                    if _actual_max is not None:
                        _mark_name_check = effect_flags_aura.get('mark_name', '')
                        _current_count = sum(1 for b in target.buffs
                                            if b.effect_type == SkillEffectType.MARK.value
                                            and getattr(b, 'name', '') == _mark_name_check)
                        _current_count += sum(1 for d in target.debuffs
                                             if d.effect_type == SkillEffectType.MARK.value
                                             and getattr(d, 'name', '') == _mark_name_check)
                        if _current_count >= _actual_max:
                            _log.info("[AURA_APPLY] %s -> %s: mark '%s' SKIPPED (max_stacks %d >= %d)",
                                      caster.name, target.name, _mark_name_check, _current_count, _actual_max)
                            continue

            if actual_is_debuff and self._has_debuff_immune(target):
                _log.info("[AURA_APPLY] %s -> %s: DEBUFF BLOCKED (debuff_immune active)",
                          caster.name, target.name)
                # 消费debuff_immune的hit_limited
                self._consume_debuff_immune(target)
                # 记录被免疫的目标，供linked_mark检查使用
                if not hasattr(self, '_debuff_immune_blocked_targets'):
                    self._debuff_immune_blocked_targets = set()
                self._debuff_immune_blocked_targets.add(target.unit_id)
                blocked_details.append({
                    "target": target.name,
                    "target_id": target.unit_id,
                    "effect": f"标记「{effect_flags_aura.get('mark_name', '')}」" if mapped_effect_type == SkillEffectType.MARK.value and effect_flags_aura and effect_flags_aura.get('mark_name') else mapped_effect_type,
                    "source": caster.name,
                    "source_id": caster.unit_id,
                    "reason": "debuff_immune",
                })
                continue

            # linked_mark: 如果此debuff绑定了某个mark，但该mark被免疫/闪避而未施加，则跳过此debuff
            linked_mark_name = effect_flags_aura.get('linked_mark') if effect_flags_aura else None
            if linked_mark_name and actual_is_debuff:
                # 检查目标是否拥有对应的mark（debuff形式）
                has_mark = any(
                    getattr(d, 'name', '') == linked_mark_name
                    for d in target.debuffs
                )
                # 也检查目标是否因debuff_immune而未获得mark
                blocked_targets = getattr(self, '_debuff_immune_blocked_targets', set())
                if not has_mark and target.unit_id in blocked_targets:
                    _log.info("[AURA_APPLY] %s -> %s: SKIPPED (linked_mark '%s' was blocked by debuff_immune)",
                              caster.name, target.name, linked_mark_name)
                    blocked_details.append({
                        "target": target.name,
                        "target_id": target.unit_id,
                        "effect": mapped_effect_type,
                        "source": caster.name,
                        "source_id": caster.unit_id,
                        "reason": "linked_mark_blocked",
                        "linked_mark": linked_mark_name,
                    })
                    continue

            # Skip debuff on targets that fully evaded the preceding damage
            if actual_is_debuff and target.unit_id in getattr(self, '_skill_evaded_targets', set()):
                _log.info("[AURA_APPLY] %s -> %s: DEBUFF SKIPPED (target fully evaded damage)",
                          caster.name, target.name)
                # 记录被闪避的目标，供linked_mark检查使用
                self._debuff_immune_blocked_targets.add(target.unit_id)
                blocked_details.append({
                    "target": target.name,
                    "target_id": target.unit_id,
                    "effect": f"标记「{effect_flags_aura.get('mark_name', '')}」" if mapped_effect_type == SkillEffectType.MARK.value and effect_flags_aura and effect_flags_aura.get('mark_name') else mapped_effect_type,
                    "source": caster.name,
                    "source_id": caster.unit_id,
                    "reason": "evade",
                })
                continue

            if actual_is_debuff and caster.side != target.side:
                evade_buffs = [b for b in target.buffs if b.effect_type == SkillEffectType.EVADE.value and b.hit_limited > 0]
                if evade_buffs:
                    # 必中效果优先：施法者持有sure_hit时，目标的闪避不触发且不消耗
                    sure_hit_buffs = [b for b in caster.buffs if b.effect_type == SkillEffectType.SURE_HIT.value]
                    if sure_hit_buffs:
                        _log.info("[EVADE] %s has sure_hit, %s's evade NOT triggered for debuff %s",
                                  caster.name, target.name, effect.effect_type)
                    else:
                        ev_buff = evade_buffs[0]
                        ev_buff.hit_limited -= 1
                        _log.info("[EVADE] %s evades debuff from %s (effect=%s)! hit_limited=%d",
                                  target.name, caster.name, effect.effect_type, ev_buff.hit_limited)
                        if ev_buff.hit_limited <= 0:
                            target.buffs = [b for b in target.buffs if b.buff_id != ev_buff.buff_id]
                            _log.info("[EVADE] %s: Evade buff EXPIRED", target.name)
                        # 记录被闪避的目标，供linked_mark检查使用
                        self._debuff_immune_blocked_targets.add(target.unit_id)
                        blocked_details.append({
                            "target": target.name,
                            "target_id": target.unit_id,
                            "effect": f"标记「{effect_flags_aura.get('mark_name', '')}」" if mapped_effect_type == SkillEffectType.MARK.value and effect_flags_aura and effect_flags_aura.get('mark_name') else mapped_effect_type,
                            "source": caster.name,
                            "source_id": caster.unit_id,
                            "reason": "evade",
                        })
                        continue

            if effect.effect_type == "shield":
                shield_base = effect_flags_aura.get('shield_base', 'atk')
                if shield_base == 'max_hp':
                    effective_max_hp = self.damage_service._calculate_final_stat(caster, "max_hp")
                    shield_value = int(effective_max_hp * value / 100)
                else:
                    effective_atk = self.damage_service._calculate_final_stat(caster, "attack")
                    shield_value = int(effective_atk * value / 100)
                # 根据damage_element决定添加到哪个盾
                shield_elem = effect_flags_aura.get('damage_element', '')
                if shield_elem == 'physical':
                    target.physical_shield += shield_value
                    _log.info("[AURA_APPLY] %s -> %s: +physical_shield %d (total=%d, base=%s %.0f%% × %.1f%%)",
                              caster.name, target.name, shield_value, target.physical_shield,
                              shield_base, effective_max_hp if shield_base == 'max_hp' else effective_atk, value)
                elif shield_elem == 'en':
                    target.en_shield += shield_value
                    _log.info("[AURA_APPLY] %s -> %s: +en_shield %d (total=%d, base=%s %.0f%% × %.1f%%)",
                              caster.name, target.name, shield_value, target.en_shield,
                              shield_base, effective_max_hp if shield_base == 'max_hp' else effective_atk, value)
                else:
                    target.shield += shield_value
                    _log.info("[AURA_APPLY] %s -> %s: +shield %d (total=%d, base=%s %.0f%% × %.1f%%)",
                              caster.name, target.name, shield_value, target.shield,
                              shield_base, effective_max_hp if shield_base == 'max_hp' else effective_atk, value)
                _shield_value_for_buff = shield_value  # 保存实际盾值用于BuffState

            aura_name = mapped_effect_type
            # For marks, store the mark_name from flags as the name for counting
            if effect.effect_type == "mark" and effect_flags_aura.get('mark_name'):
                aura_name = effect_flags_aura.get('mark_name')
            # 通用buff_name: 允许任意aura效果设置独特的name，用于linked_buff_id精确联动
            # （如130126 PS2的shield消失时联动移除atk_up，需要atk_up有匹配的name）
            elif effect_flags_aura and effect_flags_aura.get('buff_name'):
                aura_name = effect_flags_aura.get('buff_name')

            # 从flags中解析value_tag: 0=百分比, 1=固定值
            resolved_value_tag = 0
            if effect_flags_aura:
                vt = effect_flags_aura.get('value_type', 'percent')
                resolved_value_tag = 0 if vt == 'percent' else 1

            # Guard effects: 根据duration_type区分新旧guard
            # - 新版guard（130034 cover附带，duration_type="attacker_action"）: 使用特殊机制，不使用attack_limited
            # - 旧版guard（130009等）: 使用attack_limited=1在受攻击后消失
            attack_limited_val = int(effect_flags_aura.get('attack_limited', 0)) if effect_flags_aura else 0
            is_guard = mapped_effect_type == SkillEffectType.GUARD.value
            duration_type = getattr(effect, 'duration_type', None)
            if is_guard and duration_type == "attacker_action":
                # 新版guard使用attacker_action timing，不使用attack_limited
                # 由unit.guard_active机制处理
                attack_limited_val = 0
            # 双向ダメージリンク: source_unit_id指向配对目标而非施法者
            _aura_source_unit_id = caster.unit_id
            if is_bidir_damage_link and target.unit_id in _bidir_link_map:
                _aura_source_unit_id = _bidir_link_map[target.unit_id]
            _add_status_flag = effect_flags_aura.get('add_status') if effect_flags_aura else None
            # scale_by_target_hp_ratio: 按目标当前HP比例线性缩放value
            # （如130017「最高{def}%低下させる」「対象のHPが多いほど高い効果を発揮する」）
            final_value = value
            if effect_flags_aura and effect_flags_aura.get('scale_by_target_hp_ratio'):
                hp_ratio = (target.current_hp / target.max_hp) if target.max_hp > 0 else 0
                final_value = value * hp_ratio
                _log.info("[AURA_APPLY] %s -> %s: scale_by_target_hp_ratio hp_ratio=%.3f value %.1f -> %.1f",
                          caster.name, target.name, hp_ratio, value, final_value)
            _hlf = {}
            if carried_debuff:
                _hlf = {
                    'carried_debuff': carried_debuff,
                    'carried_debuff_type': effect.effect_type,
                    'carried_debuff_value': final_value,
                    'carried_debuff_duration': duration,
                    'carried_debuff_value_tag': resolved_value_tag,
                    'carried_debuff_stackable': bool(effect_flags_aura.get('stackable', False)) if effect_flags_aura else False,
                }
                if effect.effect_type == 'poison':
                    _hlf['poison_damage_pct'] = effect_flags_aura.get('poison_damage_pct', 10) if effect_flags_aura else 10
            if _add_status_flag:
                _hlf['add_status'] = _add_status_flag
                _hlf['add_status_duration'] = duration
            aura = BuffState(
                buff_id=f"{_aura_source_unit_id}_{self._current_skill_id}_{mapped_effect_type}_{target.unit_id}",
                name=aura_name,
                effect_type=mapped_effect_type,
                value=final_value,
                duration=duration,
                timing_type=timing,
                source_unit_id=_aura_source_unit_id,
                source_skill_id=self._current_skill_id,
                caster_attack=self.damage_service._calculate_final_stat(caster, "attack"),
                is_debuff=actual_is_debuff,
                value_tag=resolved_value_tag,
                hit_limited=int(effect_flags_aura.get('hit_limited', hit_limited_from_dur)) if effect_flags_aura else hit_limited_from_dur,
                attack_limited=attack_limited_val,
                hit_limited_flags=_hlf,
            )
            # 双向ダメージリンク: 标记link_mode
            if is_bidir_damage_link:
                aura.link_mode = "bidirectional"
            # 通用damage_element传递: dmg_taken_up/dmg_taken_down等debuff也需要物理/EN过滤
            # (如130064「2回攻撃を受けるまで物理攻撃による被ダメージ」)
            if effect.effect_type != "shield" and effect_flags_aura:
                dmg_elem_str = effect_flags_aura.get('damage_element', '')
                if dmg_elem_str == 'physical':
                    aura.damage_element = 1
                elif dmg_elem_str == 'en':
                    aura.damage_element = 2
            # 盾buff: 存储实际贡献的盾值，用于叠加盾正确扣除
            if effect.effect_type == "shield":
                aura.shield_amount = _shield_value_for_buff
                # 设置damage_element: physical=1, en=2, all=0
                shield_elem = effect_flags_aura.get('damage_element', '')
                if shield_elem == 'physical':
                    aura.damage_element = 1
                elif shield_elem == 'en':
                    aura.damage_element = 2
                # shield_decay_pct: 每行动衰减百分比（如110012「1行動に付き最大値の25%減少する」）
                decay_pct = int(effect_flags_aura.get('shield_decay_pct', 0)) if effect_flags_aura else 0
                if decay_pct > 0 and _shield_value_for_buff > 0:
                    aura.shield_decay_pct = decay_pct
                    aura.initial_shield_value = _shield_value_for_buff
                    _log.info("[AURA_APPLY] %s -> %s: shield_decay_pct=%d initial_shield_value=%d",
                              caster.name, target.name, decay_pct, _shield_value_for_buff)
            if getattr(effect, 'flags', None) and effect.flags.get('stackable'):
                import uuid
                aura.buff_id = f"{caster.unit_id}_{mapped_effect_type}_{target.unit_id}_{uuid.uuid4().hex[:8]}"
                aura.is_stackable = True
                _log.info("[AURA_APPLY] %s: stackable buff -> unique id=%s", caster.name, aura.buff_id)
            if self._is_memory_card_execution:
                aura.is_memory_buff = True
                _log.info("[AURA_APPLY] %s: memory card buff -> is_memory_buff=True", caster.name)

            # HOT不暴击，无需快照暴击率

            # dmg_invulnerable: 存储threshold_pct（伤害阈值百分比）
            if mapped_effect_type == SkillEffectType.DMG_INVULNERABLE.value:
                # threshold_pct from flags or value field
                # JSON中的值是百分比形式（如1.75表示1.75%），需除以100转为小数
                threshold = effect_flags_aura.get('threshold_pct', 0)
                if threshold > 0:
                    threshold = threshold / 100.0
                elif value and value > 0:
                    threshold = value / 100.0
                aura.threshold_pct = threshold
                _log.info("[DMG_INVULNERABLE] %s -> %s: threshold_pct=%.2f hit_limited=%d",
                          caster.name, target.name, threshold, aura.hit_limited)

            # caster_alive标记：施法者死亡时此buff自动消失
            if effect_flags_aura.get('caster_alive'):
                aura.caster_alive = True
                _log.info("[AURA_APPLY] %s: caster_alive flag set on %s", caster.name, mapped_effect_type)

            # unremovable标记：此buff不可被驱散或过期移除
            if effect_flags_aura.get('unremovable'):
                aura.unremovable = True
                _log.info("[AURA_APPLY] %s: unremovable flag set on %s", caster.name, mapped_effect_type)

            # skip_restore标记：当次行动新施加的buff在行动结束时正常递减duration（如「再起律動」）
            if effect_flags_aura.get('skip_restore'):
                aura.skip_restore = True
                _log.info("[AURA_APPLY] %s: skip_restore flag set on %s", caster.name, mapped_effect_type)

            # hp_threshold_tag: 条件性减伤，仅当HP≥阈值时减伤生效
            hp_threshold_tag = effect_flags_aura.get('hp_threshold_tag')
            if hp_threshold_tag:
                # 通过resolver解析tag值
                _skill_level = caster.skill_levels.get(self._current_skill_id, 1)
                meta = self.data_loader.get_skill_by_id(self._current_skill_id)
                if meta:
                    tag_values = self._resolver._resolve_template_tags(meta, _skill_level)
                    threshold_value = tag_values.get(hp_threshold_tag)
                else:
                    threshold_value = None
                if threshold_value is not None:
                    aura.hp_threshold = threshold_value
                    _log.info("[AURA_APPLY] %s: hp_threshold=%.1f%% on %s (only effective when HP >= threshold)",
                              caster.name, threshold_value, mapped_effect_type)

            # mark_condition: 条件性减伤，仅当攻击者持有指定mark时此buff/debuff才生效
            mark_condition_name = effect_flags_aura.get('mark_condition', '')
            if mark_condition_name:
                aura.mark_condition = mark_condition_name
                _log.info("[AURA_APPLY] %s: mark_condition='%s' on %s (only effective when attacker has the mark)",
                          caster.name, mark_condition_name, mapped_effect_type)

            # linked_mark: 当对应的mark消失时，此debuff也消失
            linked_mark = effect_flags_aura.get('linked_mark') if effect_flags_aura else None
            if linked_mark:
                aura.linked_buff_id = linked_mark
                _log.info("[AURA_APPLY] %s: linked_mark set to '%s' on %s", caster.name, linked_mark, mapped_effect_type)

            # 保存原始duration_type（如"attacker_action"），用于攻击者行动结束时精确清理
            if original_dur_type:
                aura.original_duration_type = original_dur_type

            # BlockSpecificAura: 存储被免疫的状态类型列表
            if mapped_effect_type == SkillEffectType.BLOCK_SPECIFIC_AURA.value:
                block_status = effect_flags_aura.get('block_status', []) if effect_flags_aura else []
                aura.block_status_list = list(block_status)
                _log.info("[AURA_APPLY] %s -> %s: BlockSpecificAura block_status=%s",
                          caster.name, target.name, aura.block_status_list)

            # HOT: 存储治疗基数来源（heal_base）
            if mapped_effect_type == SkillEffectType.HEAL_OVER_TIME.value:
                hot_heal_base = effect_flags_aura.get('heal_base', 'atk') if effect_flags_aura else 'atk'
                aura.heal_base = hot_heal_base
                _log.info("[AURA_APPLY] %s -> %s: HOT heal_base=%s",
                          caster.name, target.name, aura.heal_base)

            # Knockout refresh rule: if target already has a Knockout debuff,
            # keep the one with longer duration and mark whether this is a NEW knockout
            is_new_knockout = True
            if mapped_effect_type == SkillEffectType.KNOCKOUT.value:
                existing_stun = next((d for d in target.debuffs
                                      if d.effect_type == SkillEffectType.KNOCKOUT.value), None)
                if existing_stun:
                    is_new_knockout = False
                    # Keep the longer duration; refresh if new one is longer
                    if duration > existing_stun.duration:
                        existing_stun.duration = duration
                        _log.info("[AURA_APPLY] %s -> %s: knockout refreshed to longer duration=%d",
                                  caster.name, target.name, duration)
                    else:
                        _log.info("[AURA_APPLY] %s -> %s: knockout NOT refreshed (existing dur=%d >= new dur=%d)",
                                  caster.name, target.name, existing_stun.duration, duration)
                    # Skip adding a duplicate knockout debuff
                    aura_details.append({
                        "target": target.name,
                        "target_id": target.unit_id,
                        "effect": mapped_effect_type,
                        "value": value,
                        "duration": duration,
                        "dur_type": dur_type,
                        "source": caster.name,
                        "source_id": caster.unit_id,
                        "detail": "knockout_refresh",
                        "is_new_knockout": False,
                    })
                    continue

            # max_hp_up: 直接修改unit.max_hp和unit.current_hp，不添加buff（避免_calculate_final_stat重复计算）
            if effect.effect_type == "max_hp_up":
                if resolved_value_tag == 0:  # percent
                    hp_increase = int(target.max_hp * value / 100)
                else:  # fixed
                    hp_increase = int(value)
                old_max_hp = target.max_hp
                target.max_hp += hp_increase
                target.current_hp += hp_increase
                _log.info("[MAX_HP_UP] %s -> %s: max_hp %d -> %d (+%d), current_hp %d -> %d",
                          caster.name, target.name, old_max_hp, target.max_hp, hp_increase,
                          target.current_hp - hp_increase, target.current_hp)
                aura_detail_dict = {
                    "target": target.name,
                    "target_id": target.unit_id,
                    "effect": mapped_effect_type,
                    "value": value,
                    "duration": duration,
                    "dur_type": dur_type,
                    "source": caster.name,
                    "source_id": caster.unit_id,
                    "detail": f"最大HP+{hp_increase}({old_max_hp}->{target.max_hp})",
                }
                aura_details.append(aura_detail_dict)
                continue

            # 在add_aura之前计算生效前属性（追踪真实属性，非效果量加减法）
            stat_before = self._compute_stat_display(target, mapped_effect_type)
            was_charging = target.is_charging and target.charge_skill_id
            charge_skill_id = target.charge_skill_id if was_charging else 0
            charge_skill_name = ""
            if was_charging:
                charge_meta = self.data_loader.get_skill_by_id(target.charge_skill_id)
                charge_skill_name = charge_meta.name if charge_meta else f"Skill_{target.charge_skill_id}"
            self.aura_service.add_aura(target, aura)
            if actual_is_debuff:
                self._debuffs_applied_this_skill.add(aura.buff_id)
            # Build detail string for aura log
            # 关键：使用 add_aura 前后的真实属性构造"ATK:前值→后值"格式，而非用效果量做加减法
            aura_detail = ""
            if carried_debuff:
                # carried_debuff payload on ally carrier: 载荷对携带者属性无影响（_aggregate_buff_value跳过）
                # 所以只显示载荷描述，不显示"前→后"
                _CARRIED_LABELS_LOCAL = {
                    'atk_down': 'ATK', 'def_down': 'DEF', 'spd_down': 'SPD',
                    'crit_rate_down': 'CRT', 'poison': 'POI',
                }
                _cd_label = _CARRIED_LABELS_LOCAL.get(effect.effect_type, effect.effect_type)
                if effect.effect_type == 'poison':
                    _poison_pct = effect_flags_aura.get('poison_damage_pct', 10) if effect_flags_aura else 10
                    aura_detail = f"携带式{_cd_label}载荷({_cd_label}{_poison_pct}%HP)"
                else:
                    _v_disp = f"-{int(final_value)}" if resolved_value_tag == 1 else f"-{final_value:.0f}%"
                    aura_detail = f"携带式{_cd_label}载荷({_cd_label}{_v_disp})"
            elif effect.effect_type == "shield":
                aura_detail = f"护盾+{shield_value}"
            elif stat_before[0]:
                # stat类效果：构造"ATK:前值→后值"格式，使用 add_aura 前后的真实属性
                stat_after = self._compute_stat_display(target, mapped_effect_type)
                if stat_after[0] and stat_after[1] != stat_before[1]:
                    aura_detail = f"{stat_before[0]}:{stat_before[1]}→{stat_after[1]}"
                else:
                    aura_detail = f"{stat_after[0]}:{stat_after[1]}" if stat_after[0] else ""

            # mark效果：使用mark_name作为显示名称
            display_effect = mapped_effect_type
            if mapped_effect_type == SkillEffectType.MARK.value:
                mark_name = effect_flags_aura.get('mark_name', '') if effect_flags_aura else ''
                if mark_name:
                    display_effect = f"标记「{mark_name}」"

            aura_detail_dict = {
                "target": target.name,
                "target_id": target.unit_id,
                "effect": display_effect,
                "value": final_value,
                "duration": duration,
                "dur_type": dur_type,
                "source": caster.name,
                "source_id": caster.unit_id,
                "detail": aura_detail,
            }
            # Mark whether this is a new knockout (for PS2 trigger filtering)
            if mapped_effect_type == SkillEffectType.KNOCKOUT.value:
                aura_detail_dict["is_new_knockout"] = is_new_knockout
            # 眩晕打断蓄力：蓄力技能进入冷却
            if was_charging and mapped_effect_type == SkillEffectType.KNOCKOUT.value:
                aura_detail_dict["charge_cancelled"] = True
                aura_detail_dict["charge_skill_name"] = charge_skill_name
                self.update_cooldown_after_skill_use(target, charge_skill_id)
            aura_details.append(aura_detail_dict)

        result = {
            "effect_type": "aura",
            "is_debuff": actual_is_debuff,
            "target_count": len(aura_details),
            "auras": aura_details,
        }
        if blocked_details:
            result["blocked"] = blocked_details
        return result

    def _apply_add_status(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        if not self.aura_service or not self.target_service:
            _log.info("[ADD_STATUS] %s: aura_service or target_service unavailable", caster.name)
            return None

        add_status_flags = getattr(effect, 'flags', {}) or {}
        # 优先使用 flags.status_type（明确的状态类型），其次使用 value_tag
        # value_tag 可能是通用tag名（如"value"），不适合作为状态类型
        status_type = add_status_flags.get('status_type', None)
        if not status_type:
            status_type = getattr(effect, 'value_tag', None)
        if not status_type:
            _log.info("[ADD_STATUS] %s: no flags.status_type or value_tag in effect", caster.name)
            return None

        normalized = _MASTERDATA_STATUS_MAP.get(status_type, status_type)
        is_debuff = normalized in self._get_debuff_types()

        # 特殊索敌类型（furthest/highest_atk等）必须用ALL_PAWNS获取全部候选再后过滤，
        # 否则ONE_PAWN会先选出最近敌方，后过滤只有1个目标可选（如130064燃烧应打最远却打最近）
        _SPECIAL_POSTFILTER_TYPES = {
            "enemy_single_highest_atk", "enemy_single_highest_spd",
            "enemy_single_lowest_spd", "enemy_single_furthest",
            "enemy_single_highest_ep",
            "enemy_single_highest_hp_ratio",
            "enemy_single_highest_current_hp",
            "enemy_single_highest_hp_ratio_back_priority",
            "enemy_single_lowest_hp_ratio",
            "enemy_column_furthest", "enemy_column_mark_priority",
        }
        _st_range = self._resolve_target_range("enemies") if effect.target_type in _SPECIAL_POSTFILTER_TYPES \
                    else self._resolve_target_range(effect.target_type)

        st_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': _st_range,
            'display_target_priority': None,
            'target_type_name': effect.target_type,
        })()

        # Use cached damage targets if available (ensures add_status effects target the same unit as damage)
        cached_targets = getattr(self, '_block_damage_targets', None)
        if cached_targets is not None and isinstance(cached_targets, dict) and effect.target_type in cached_targets:
            targets = [t for t in cached_targets[effect.target_type] if t.is_alive]
            _log.info("[ADD_STATUS] %s: using cached damage targets for %s -> %s",
                      caster.name, effect.target_type, [t.name for t in targets])
        else:
            targets = self.target_service.select_targets(st_skill_obj, caster, battlefield)
            # 对特殊索敌类型应用后过滤，与damage执行保持一致
            if effect.target_type in _SPECIAL_POSTFILTER_TYPES and targets:
                targets = self._postfilter_damage_targets(
                    effect.target_type, targets, caster,
                    getattr(effect, 'flags', {}) or {}
                )
                _log.info("[ADD_STATUS] %s: special postfilter %s -> %s",
                          caster.name, effect.target_type, [t.name for t in targets])

        # cover替换：如果cover生效，debuff目标也应替换为cover者
        if is_debuff:
            targets = self._apply_cover_debuff_replacement(caster, targets, battlefield)

        # hp_threshold_cross: 如果目标已被击杀，target_service 会过滤掉死亡单位
        # 需要从 _last_damage_hp_before 中找到被伤害的目标来施加状态
        effect_condition = getattr(effect, 'condition', None)
        is_hp_threshold_cross = (effect_condition and isinstance(effect_condition, dict)
                                 and effect_condition.get('type') == 'hp_threshold_cross')
        if is_hp_threshold_cross and not targets and self._last_damage_hp_before:
            _log.info("[ADD_STATUS] %s: hp_threshold_cross targets empty, fallback to _last_damage_hp_before",
                      caster.name)
            for uid in self._last_damage_hp_before:
                unit = next((u for u in battlefield.get_all_units() if u.unit_id == uid), None)
                if unit:
                    targets.append(unit)
                    _log.info("[ADD_STATUS] %s: fallback target %s (is_alive=%s hp=%d/%d)",
                              caster.name, unit.name, unit.is_alive, unit.current_hp, unit.max_hp)

        element_filter = getattr(self, '_target_element_filter', None)
        if element_filter is not None:
            targets = [t for t in targets if getattr(t, 'element', 0) == element_filter]
            _log.info("[ADD_STATUS] %s: element filter=%d, filtered targets=%d",
                      caster.name, element_filter, len(targets))

        if effect.target_type and "highest_atk" in effect.target_type:
            if targets:
                targets = [max(targets, key=lambda u: self.damage_service._calculate_final_stat(u, "attack") if self.damage_service else u.attack)]
                best = targets[0]
                best_atk = self.damage_service._calculate_final_stat(best, "attack") if self.damage_service else best.attack
                _log.info("[ADD_STATUS] %s: highest_atk filter -> %s (atk=%d)",
                          caster.name, best.name, best_atk)

        if effect.target_type and "highest_spd" in effect.target_type:
            if targets:
                targets = [max(targets, key=lambda u: self.damage_service._calculate_final_stat(u, "speed") if self.damage_service else u.speed)]
                best = targets[0]
                best_spd = self.damage_service._calculate_final_stat(best, "speed") if self.damage_service else best.speed
                _log.info("[ADD_STATUS] %s: highest_spd filter -> %s (spd=%d)",
                          caster.name, best.name, best_spd)

        if effect.target_type and "furthest" in effect.target_type:
            if targets:
                targets = [min(targets, key=lambda u: self._get_farthest_key(caster.position, u))]
                best = targets[0]
                _log.info("[ADD_STATUS] %s: furthest filter -> %s",
                          caster.name, best.name)

        if effect.target_type == "ally_back" and caster.position.name.endswith("BACK"):
            if caster.is_alive and caster not in targets:
                targets.append(caster)
                _log.info("[ADD_STATUS] %s: ally_back including self (caster in back row)", caster.name)

        value = effect.value or 0
        if status_type == "burn":
            burn_damage_pct = add_status_flags.get('burn_damage_pct', 30)
            snapshot_atk = self.damage_service._calculate_final_stat(caster, "attack")
            value = snapshot_atk * burn_damage_pct / 100.0
            _log.info("[ADD_STATUS] %s: burn pct=%d atk(snapshot)=%d -> value=%.1f",
                      caster.name, burn_damage_pct, snapshot_atk, value)
        elif status_type == "poison":
            poison_damage_pct = add_status_flags.get('poison_damage_pct', 10)
            value = poison_damage_pct / 100.0
            _log.info("[ADD_STATUS] %s: poison pct=%d -> value=%.3f",
                      caster.name, poison_damage_pct, value)
        elif status_type == "confusion":
            # 混乱参数从flags读取，存入BuffState专用字段
            value = 0  # 混乱本身无value，参数在专用字段
            _log.info("[ADD_STATUS] %s: confusion params from flags: dmg_reduction=%s proxy_atk_pct=%s",
                      caster.name,
                      add_status_flags.get('confusion_dmg_reduction'),
                      add_status_flags.get('confusion_proxy_atk_pct'))
        effect_dur = getattr(effect, 'duration', None)
        if effect_dur is not None:
            duration = effect_dur
        else:
            duration = -1

        _log.info("[ADD_STATUS] %s: status=%s (normalized=%s) value=%s dur=%d targets=%d is_debuff=%s",
                  caster.name, status_type, normalized, value, duration, len(targets), is_debuff)

        dur_type = getattr(effect, 'duration_type', None) or "action"
        if dur_type == "action":
            timing = AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value
        else:
            timing = AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END.value

        status_details = []
        effect_condition = getattr(effect, 'condition', None)
        is_hp_threshold_cross = (effect_condition and isinstance(effect_condition, dict)
                                 and effect_condition.get('type') == 'hp_threshold_cross')
        for target in targets:
            if not target.is_alive and not is_hp_threshold_cross:
                # hp_threshold_cross: 即使目标被击杀，仍需施加眩晕等状态（kill phase切换后会被清除）
                continue
            # Skip debuff on targets that fully evaded the preceding damage
            if is_debuff and target.unit_id in getattr(self, '_skill_evaded_targets', set()):
                _log.info("[ADD_STATUS] %s -> %s: SKIPPED (target fully evaded damage)",
                          caster.name, target.name)
                continue
            if not self._check_target_condition(target, effect_condition):
                _log.info("[ADD_STATUS] %s -> %s: SKIPPED (condition %s not met)",
                          caster.name, target.name, effect_condition.get('type') if effect_condition else 'none')
                continue
            if is_hp_threshold_cross:
                threshold = effect_condition.get('value', 70)
                hp_before = self._last_damage_hp_before.get(target.unit_id, target.current_hp)
                threshold_hp = int(target.max_hp * threshold / 100)
                if not (hp_before > threshold_hp and target.current_hp <= threshold_hp):
                    _log.info("[ADD_STATUS] %s -> %s: SKIPPED (hp_threshold_cross: hp_before=%d > %d=%d hp_after=%d <= %d)",
                              caster.name, target.name, hp_before, threshold_hp, threshold_hp, target.current_hp, threshold_hp)
                    continue
            # knockout_upgrade: if target already has 1-action knockout, remove it and apply 2-action instead
            final_duration = duration
            if add_status_flags.get('knockout_upgrade') and normalized == SkillEffectType.KNOCKOUT.value:
                existing_knockout = None
                for d in getattr(target, 'debuffs', []) or []:
                    d_effect = getattr(d, 'effect_type', None)
                    d_dur = getattr(d, 'duration', 0)
                    _log.info("[ADD_STATUS] %s -> %s: knockout_upgrade scan: effect=%s duration=%d",
                              caster.name, target.name, d_effect, d_dur)
                    if d_effect == SkillEffectType.KNOCKOUT.value and d_dur == 1:
                        existing_knockout = d
                        break
                if existing_knockout:
                    target.debuffs = [d for d in target.debuffs if d is not existing_knockout]
                    final_duration = 2
                    _log.info("[ADD_STATUS] %s -> %s: knockout_upgrade: removed existing duration=1, applying duration=2",
                              caster.name, target.name)
                else:
                    _log.info("[ADD_STATUS] %s -> %s: knockout_upgrade: no existing duration=1 knockout found among %d debuffs",
                              caster.name, target.name, len(getattr(target, 'debuffs', []) or []))

            aura = BuffState(
                buff_id=f"{caster.unit_id}_add_status_{normalized}_{target.unit_id}",
                name=normalized,
                effect_type=normalized,
                value=value,
                duration=final_duration,
                timing_type=timing,
                source_unit_id=caster.unit_id,
                source_skill_id=self._current_skill_id,
                caster_attack=self.damage_service._calculate_final_stat(caster, "attack"),
                is_debuff=is_debuff,
            )
            # 混乱专用参数：从flags读取并写入BuffState
            if normalized == SkillEffectType.CONFUSION.value:
                aura.confusion_dmg_reduction = float(add_status_flags.get('confusion_dmg_reduction', 0.0))
                aura.confusion_proxy_atk_pct = float(add_status_flags.get('confusion_proxy_atk_pct', 10.0))
            was_charging = target.is_charging and target.charge_skill_id
            charge_skill_id = target.charge_skill_id if was_charging else 0
            charge_skill_name = ""
            if was_charging:
                charge_meta = self.data_loader.get_skill_by_id(target.charge_skill_id)
                charge_skill_name = charge_meta.name if charge_meta else f"Skill_{target.charge_skill_id}"
            self.aura_service.add_aura(target, aura)
            status_detail = {
                "target": target.name,
                "target_id": target.unit_id,
                "effect": normalized,
                "value": value,
                "duration": final_duration,
                "dur_type": dur_type,
                "source": caster.name,
                "source_id": caster.unit_id,
            }
            # 眩晕打断蓄力：蓄力技能进入冷却
            if was_charging and normalized == SkillEffectType.KNOCKOUT.value:
                status_detail["charge_cancelled"] = True
                status_detail["charge_skill_name"] = charge_skill_name
                self.update_cooldown_after_skill_use(target, charge_skill_id)
            status_details.append(status_detail)

        return {
            "effect_type": "add_status",
            "status": status_type,
            "is_debuff": is_debuff,
            "target_count": len(status_details),
            "statuses": status_details,
        }

    def _apply_remove_debuff(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        if not self.target_service:
            _log.info("[REMOVE_DEBUFF] %s: target_service unavailable", caster.name)
            return None

        # count参数：限制每个目标解除的debuff数量（LIFO：从最近施加的开始解除）
        # count <= 0 或未指定表示解除全部
        # count_tag: 通过tag解析count值（如PS1 130125的cure tag，按技能等级插值）
        effect_flags_rd = getattr(effect, 'flags', {}) or {}
        max_count = effect_flags_rd.get('count', 0)
        count_tag = effect_flags_rd.get('count_tag')
        if count_tag:
            resolved_count = self._resolve_tag_value_for_caster(caster, effect, count_tag)
            if resolved_count is not None:
                max_count = int(resolved_count)
                _log.info("[REMOVE_DEBUFF] %s: count_tag='%s' resolved to %d",
                          caster.name, count_tag, max_count)

        # lowest_hp_priority: 优先使用前序heal block记录的_last_primary_target，
        # 避免heal后HP变化导致remove_debuff选到不同友方
        if effect_flags_rd.get('lowest_hp_priority'):
            ref_target = getattr(self, '_last_primary_target', None)
            if ref_target and ref_target.is_alive:
                targets = [ref_target]
                _log.info("[REMOVE_DEBUFF] %s: lowest_hp_priority using _last_primary_target=%s",
                          caster.name, ref_target.name)
            else:
                target_skill_obj = type('obj', (object,), {
                    'display_target_type': self._resolve_target_type(effect.target_type),
                    'display_target_range': self._resolve_target_range(effect.target_type),
                    'display_target_priority': None,
                    'target_type_name': effect.target_type,
                })()
                targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)
        elif effect.target_type == "debuff_applied_target":
            # debuff_applied_target: 使用触发上下文中的primary_target
            # （如130125 気合い入れていこー！：其他友方被上debuff时触发，remove_debuff作用于被上debuff的友方）
            primary_target = getattr(self, '_primary_target', None)
            # 检查当前PS是否设置了exclude_self
            current_skill_id = getattr(self, '_current_skill_id', 0)
            parsed_skill = self.data_loader.get_parsed_skill_data(current_skill_id) if current_skill_id else None
            gc = parsed_skill.get('global_condition', {}) if parsed_skill else {}
            exclude_self = bool(gc.get('exclude_self', 0)) if gc else False
            if exclude_self:
                # exclude_self: 从触发上下文中找非自身的友方目标
                # 多个友方同时被上debuff时，选取距离自身最近的被上debuff的友方
                ctx_targets = getattr(self, '_damaged_targets', None) or []
                non_self_targets = [t for t in ctx_targets
                                     if t.unit_id != caster.unit_id and t.is_alive
                                     and t.side == caster.side]
                if non_self_targets:
                    nearest = self.target_service.get_nearest_ally(caster, non_self_targets)
                    if nearest:
                        primary_target = nearest
                        _log.info("[REMOVE_DEBUFF] %s: debuff_applied_target exclude_self -> redirected to nearest %s",
                                  caster.name, primary_target.name)
            if primary_target and primary_target.is_alive:
                targets = [primary_target]
                _log.info("[REMOVE_DEBUFF] %s: debuff_applied_target -> %s",
                          caster.name, primary_target.name)
            else:
                _log.info("[REMOVE_DEBUFF] %s: debuff_applied_target no primary_target, skip", caster.name)
                targets = []
        else:
            target_skill_obj = type('obj', (object,), {
                'display_target_type': self._resolve_target_type(effect.target_type),
                'display_target_range': self._resolve_target_range(effect.target_type),
                'display_target_priority': None,
                'target_type_name': effect.target_type,
            })()
            targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)

        total_removed = 0
        removed_details = []
        for target in targets:
            if not target.is_alive:
                continue
            if max_count and max_count > 0 and len(target.debuffs) > max_count:
                # LIFO：从列表末尾（最近施加）开始移除max_count个
                to_remove = target.debuffs[-max_count:]
                removed_names = [d.name for d in to_remove]
                for d in to_remove:
                    target.debuffs.remove(d)
                count = len(removed_names)
            else:
                removed_names = [d.name for d in target.debuffs]
                count = len(target.debuffs)
                target.debuffs.clear()
            total_removed += count
            if count > 0:
                removed_details.append({
                    "target_id": target.unit_id,
                    "target": target.name,
                    "removed_count": count,
                    "removed_names": removed_names,
                })
            _log.info("[REMOVE_DEBUFF] %s: removed %d debuffs from %s (max_count=%s)",
                      caster.name, count, target.name, max_count if max_count > 0 else 'all')

        return {
            "effect_type": "remove_debuff",
            "target_count": len(targets),
            "total_removed": total_removed,
            "removed_details": removed_details,
        }

    def _apply_remove_all_buffs(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """解除目标所有buff，排除回忆卡buff和不可解除buff"""
        if not self.target_service:
            _log.info("[REMOVE_ALL_BUFFS] %s: target_service unavailable", caster.name)
            return None

        target_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': self._resolve_target_range(effect.target_type),
            'display_target_priority': None,
            'target_type_name': effect.target_type,
        })()
        targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)

        total_removed = 0
        removed_details = []
        for target in targets:
            if not target.is_alive:
                continue
            # 排除回忆卡buff和不可解除buff
            to_remove = [b for b in target.buffs
                         if not b.is_memory_buff and not b.unremovable]
            removed_names = [b.name for b in to_remove]
            for b in to_remove:
                target.buffs.remove(b)
            count = len(to_remove)
            total_removed += count
            if count > 0:
                removed_details.append({
                    "target_id": target.unit_id,
                    "target": target.name,
                    "removed_count": count,
                    "removed_names": removed_names,
                })
            _log.info("[REMOVE_ALL_BUFFS] %s: removed %d buffs from %s (kept %d memory/unremovable)",
                      caster.name, count, target.name,
                      len([b for b in target.buffs if b.is_memory_buff or b.unremovable]))

        return {
            "effect_type": "remove_all_buffs",
            "target_count": len(targets),
            "total_removed": total_removed,
            "removed_details": removed_details,
        }

    def _apply_remove_buff(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """解除目标1个buff，排除回忆卡buff和不可解除buff"""
        if not self.target_service:
            _log.info("[REMOVE_BUFF] %s: target_service unavailable", caster.name)
            return None

        target_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': self._resolve_target_range(effect.target_type),
            'display_target_priority': None,
            'target_type_name': effect.target_type,
        })()
        targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)

        total_removed = 0
        removed_details = []
        # count: 解除buff数量，从effect.value或flags.count获取，默认1
        remove_buff_flags = getattr(effect, 'flags', {}) or {}
        count = 1
        if effect.value:
            try:
                count = int(effect.value)
            except (TypeError, ValueError):
                count = 1
        elif 'count' in remove_buff_flags:
            try:
                count = int(remove_buff_flags.get('count', 1))
            except (TypeError, ValueError):
                count = 1
        for target in targets:
            if not target.is_alive:
                continue
            # 排除回忆卡buff和不可解除buff
            removable = [b for b in target.buffs
                         if not b.is_memory_buff and not b.unremovable]
            if removable:
                # LIFO: 从列表末尾（最近施加）开始移除count个
                actual_count = min(count, len(removable))
                to_remove = removable[-actual_count:] if actual_count > 0 else []
                removed_names = []
                for b in to_remove:
                    target.buffs.remove(b)
                    removed_names.append(b.name)
                    total_removed += 1
                removed_details.append({
                    "target_id": target.unit_id,
                    "target": target.name,
                    "removed_count": len(removed_names),
                    "removed_names": removed_names,
                })
                _log.info("[REMOVE_BUFF] %s: removed %d buff(s) %s from %s (LIFO)",
                          caster.name, len(removed_names), removed_names, target.name)
            else:
                _log.info("[REMOVE_BUFF] %s: no removable buff on %s",
                          caster.name, target.name)

        return {
            "effect_type": "remove_buff",
            "target_count": len(targets),
            "total_removed": total_removed,
            "removed_details": removed_details,
        }

    def _apply_remove_buff_by_type(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """按 effect_type 列表移除目标 buff（如大雷会心時バフ全解除：filter=[atk_up, crit_rate_up]）
        排除回忆卡 buff 和 unremovable buff。
        """
        if not self.target_service:
            _log.info("[REMOVE_BUFF_BY_TYPE] %s: target_service unavailable", caster.name)
            return None

        target_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': self._resolve_target_range(effect.target_type),
            'display_target_priority': None,
            'target_type_name': effect.target_type,
        })()
        targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)

        rbbt_flags = getattr(effect, 'flags', {}) or {}
        filter_types = rbbt_flags.get('filter', [])
        if isinstance(filter_types, str):
            filter_types = [filter_types]
        # 将 JSON effect_type 名 (如 "atk_up") 映射为枚举值 (如 "StatusAttack")，
        # 以便与 buff.effect_type (枚举值) 匹配
        filter_set = set()
        for t in filter_types:
            mapped = _JSON_EFFECT_TO_ENUM.get(t, t)
            filter_set.add(mapped.lower())
            filter_set.add(t.lower())
        if not filter_set:
            _log.info("[REMOVE_BUFF_BY_TYPE] %s: empty filter, no-op", caster.name)
            return {"effect_type": "remove_buff_by_type", "target_count": 0, "total_removed": 0, "removed_details": []}

        total_removed = 0
        removed_details = []
        for target in targets:
            if not target.is_alive:
                continue
            matching = [b for b in target.buffs
                        if not b.is_memory_buff and not b.unremovable
                        and (b.effect_type or "").lower() in filter_set]
            removed_names = []
            for b in matching:
                target.buffs.remove(b)
                removed_names.append(b.name)
                total_removed += 1
            removed_details.append({
                "target_id": target.unit_id,
                "target": target.name,
                "removed_count": len(removed_names),
                "removed_names": removed_names,
            })
            _log.info("[REMOVE_BUFF_BY_TYPE] %s: removed %d buff(s) %s from %s (filter=%s)",
                      caster.name, len(removed_names), removed_names, target.name, sorted(filter_set))

        return {
            "effect_type": "remove_buff_by_type",
            "target_count": len(targets),
            "total_removed": total_removed,
            "removed_details": removed_details,
        }

    def _apply_block_buff_by_type(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """付与 debuff 阻止特定 buff 类型的新付与（土雷 buff_block）。
        通过 add_aura 登记 block_buff_by_type debuff，由 aura_service.add_aura 在付与 buff 前检查。
        duration_type="source_action" -> 施法者行动结束时-1，施法者死亡时清除。
        """
        if not self.target_service or not self.aura_service:
            _log.info("[BLOCK_BUFF_BY_TYPE] %s: services unavailable", caster.name)
            return None

        target_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': self._resolve_target_range(effect.target_type),
            'display_target_priority': None,
            'target_type_name': effect.target_type,
        })()
        targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)

        bbf_flags = getattr(effect, 'flags', {}) or {}
        blocked_types = bbf_flags.get('blocked_buff_types', [])
        if isinstance(blocked_types, str):
            blocked_types = [blocked_types]
        # 将 snake_case 名 (如 atk_up) 映射为 SkillEffectType 枚举值 (如 StatusAttack)
        # 存入 block_status_list，由 aura_service.add_aura 检查
        blocked_enum_set = set()
        for bt in blocked_types:
            enum_val = _JSON_EFFECT_TO_ENUM.get(bt, bt)
            blocked_enum_set.add(enum_val)

        duration = getattr(effect, 'duration', 1)
        duration_type = getattr(effect, 'duration_type', 'source_action')
        # source_action -> DURABLE_SOURCE_MANEUVER_END (施法者行动结束时-1)
        if duration_type == 'source_action':
            timing = AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END.value
        elif duration_type == 'action':
            timing = AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value
        else:
            timing = AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END.value

        detail_list = []
        aura_details = []
        blocked_display = "/".join(blocked_types) if blocked_types else "buff"
        # source_action 按施法者行动计数，叙事显示用 "action"（行动）
        narr_dur_type = "action" if duration_type == "source_action" else duration_type
        for target in targets:
            if not target.is_alive:
                continue
            aura = BuffState(
                buff_id=f"{caster.unit_id}_{self._current_skill_id}_BlockBuffByType_{target.unit_id}",
                name="buff_block",
                effect_type=SkillEffectType.BLOCK_BUFF_BY_TYPE.value,
                value=0,
                duration=duration,
                timing_type=timing,
                source_unit_id=caster.unit_id,
                source_skill_id=self._current_skill_id,
                is_debuff=True,
                original_duration_type=duration_type,
                block_status_list=list(blocked_enum_set),
                caster_alive=True,  # 施法者死亡时此debuff自动消失
                just_applied=True,
            )
            self.aura_service.add_aura(target, aura)
            detail_list.append({"target_id": target.unit_id, "target": target.name})
            aura_details.append({
                "target": target.name,
                "target_id": target.unit_id,
                "effect": "buff_block",
                "value": 0,
                "duration": duration,
                "dur_type": narr_dur_type,
                "source": caster.name,
                "source_id": caster.unit_id,
                "detail": f"阻止 {blocked_display}",
            })
            _log.info("[BLOCK_BUFF_BY_TYPE] %s: applied to %s blocked_types=%s (enum=%s) dur=%s dur_type=%s",
                      caster.name, target.name, blocked_types, sorted(blocked_enum_set),
                      duration, duration_type)

        return {
            "effect_type": "block_buff_by_type",
            "is_debuff": True,
            "target_count": len(targets),
            "blocked_buff_types": blocked_types,
            "details": detail_list,
            "auras": aura_details,
        }

    def _apply_stealth(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """付与自身ステルス buff（土雷 220362）。
        ステルス在 target_service.select_targets 的第一優先対象選択時消耗：将自身移到候选末尾。
        duration_type="action" -> 目标(自身)行动结束时-1。
        """
        if not self.aura_service:
            _log.info("[STEALTH] %s: aura_service unavailable", caster.name)
            return None

        duration = getattr(effect, 'duration', 2)
        duration_type = getattr(effect, 'duration_type', 'action')
        value = getattr(effect, 'value', 1)
        # action -> DURABLE_TARGET_MANEUVER_END (持有者行动结束时-1)
        if duration_type == 'action':
            timing = AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value
        else:
            timing = AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value

        aura = BuffState(
            buff_id=f"{caster.unit_id}_{self._current_skill_id}_Stealth",
            name="ステルス",
            effect_type=SkillEffectType.STEALTH.value,
            value=float(value),
            duration=duration,
            timing_type=timing,
            source_unit_id=caster.unit_id,
            source_skill_id=self._current_skill_id,
            is_debuff=False,
            original_duration_type=duration_type,
            just_applied=True,
        )
        self.aura_service.add_aura(caster, aura)
        _log.info("[STEALTH] %s: applied stealth dur=%s dur_type=%s value=%s",
                  caster.name, duration, duration_type, value)

        return {
            "effect_type": "stealth",
            "is_debuff": False,
            "target_count": 1,
            "details": [{"target_id": caster.unit_id, "target": caster.name}],
            "auras": [{
                "target": caster.name,
                "target_id": caster.unit_id,
                "effect": "ステルス",
                "value": float(value),
                "duration": duration,
                "dur_type": duration_type,
                "source": caster.name,
                "source_id": caster.unit_id,
                "detail": "隠密",
            }],
        }

    def _apply_split_heal_by_damage(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """将同 block 内前序 damage 总和按 percent 转化为 heal，均分到所有目标（若雷 220360/220361）。
        参考 _apply_shield_from_damage 的 _most_recent_damage 读取机制。
        """
        if not self.target_service:
            _log.info("[SPLIT_HEAL_BY_DAMAGE] %s: target_service unavailable", caster.name)
            return None

        shbd_flags = getattr(effect, 'flags', {}) or {}
        source_block_id = shbd_flags.get('source_block_id')
        split = bool(shbd_flags.get('split_among_targets', True))
        percent = float(getattr(effect, 'value', 100) or 100)

        # 从 _block_damage_total 取该 block 的伤害总和
        block_dmg_total_map = getattr(self, '_block_damage_total', None) or {}
        if source_block_id is None:
            # 默认使用当前 block_id
            source_block_id = getattr(self, '_current_block_id', 1)
        total_damage = block_dmg_total_map.get(source_block_id, 0)
        if total_damage <= 0:
            _log.info("[SPLIT_HEAL_BY_DAMAGE] %s: no damage in block_id=%s, skip heal",
                      caster.name, source_block_id)
            return {"effect_type": "split_heal_by_damage", "target_count": 0, "total_heal": 0,
                    "details": [], "heals": []}

        total_heal_value = int(total_damage * percent / 100)

        target_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': self._resolve_target_range(effect.target_type),
            'display_target_priority': None,
            'target_type_name': effect.target_type,
        })()
        targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)
        alive_targets = [t for t in targets if t.is_alive]
        if not alive_targets:
            _log.info("[SPLIT_HEAL_BY_DAMAGE] %s: no alive targets", caster.name)
            return {"effect_type": "split_heal_by_damage", "target_count": 0, "total_heal": 0,
                    "details": [], "heals": []}

        per_target = total_heal_value // len(alive_targets) if split else total_heal_value
        details = []
        heals = []
        total_actual = 0
        for target in alive_targets:
            hp_before = target.current_hp
            missing_hp = target.max_hp - target.current_hp
            actual_heal = min(per_target, missing_hp)
            target.current_hp = min(target.max_hp, target.current_hp + per_target)
            details.append({"target_id": target.unit_id, "target": target.name, "heal": per_target})
            heals.append({
                "target_id": target.unit_id,
                "target": target.name,
                "hp_before": hp_before,
                "hp_after": target.current_hp,
                "amount": actual_heal,
                "is_crit": False,
                "heal_formula": f"[src_dmg:{total_damage} pct:{percent:.0f}% split:{split} per_target:{per_target}]",
            })
            total_actual += actual_heal
            _log.info("[SPLIT_HEAL_BY_DAMAGE] %s: healed %s +%d HP (actual=%d, total_dmg=%s pct=%s split=%s)",
                      caster.name, target.name, per_target, actual_heal, total_damage, percent, split)

        return {
            "effect_type": "split_heal_by_damage",
            "target_count": len(alive_targets),
            "total_heal": total_actual,
            "source_block_id": source_block_id,
            "source_damage_total": total_damage,
            "percent": percent,
            "details": details,
            "heals": heals,
        }

    def _apply_skill_power_down(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """付与 skill_power_down debuff：当 caster 行动内 SkillPower 乘区按 value 百分比扣减（若雷 230384）。
        duration_type=attacker_action（持续到攻击发起者本次行动结束，由 _cleanup_guard_buffs 清理）。
        """
        if not self.target_service or not self.aura_service:
            _log.info("[SKILL_POWER_DOWN] %s: services unavailable", caster.name)
            return None

        target_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': self._resolve_target_range(effect.target_type),
            'display_target_priority': None,
            'target_type_name': effect.target_type,
        })()
        targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)

        # PS触发时通过_trigger_attacker定位攻击者（如若ノ減衰 230384 对攻击者施加威力降低）
        target_identifier = getattr(effect, 'target_identifier', None)
        trigger_attacker = getattr(self, '_trigger_attacker', None)
        if trigger_attacker and target_identifier == "trigger_attacker":
            if trigger_attacker.side != caster.side and trigger_attacker.is_alive:
                targets = [trigger_attacker]
                _log.info("[SKILL_POWER_DOWN] %s: using trigger_attacker=%s as target",
                          caster.name, trigger_attacker.name)

        value = float(getattr(effect, 'value', 50) or 50)
        duration = getattr(effect, 'duration', 1)
        duration_type = getattr(effect, 'duration_type', 'attacker_action')
        # attacker_action -> DURABLE_WHEN_USED + original_duration_type=attacker_action
        # 由 battle_flow_controller._cleanup_guard_buffs 在攻击者行动结束时清理
        if duration_type == 'attacker_action':
            timing = AuraUpdateTiming.DURABLE_WHEN_USED.value
            duration = -1  # permanent, cleaned up via original_duration_type
        else:
            timing = AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value

        aura_list = []
        for target in targets:
            if not target.is_alive:
                continue
            aura = BuffState(
                buff_id=f"{caster.unit_id}_{self._current_skill_id}_SkillPowerDown_{target.unit_id}",
                name="skill_power_down",
                effect_type=SkillEffectType.SKILL_POWER_DOWN.value,
                value=value,
                duration=duration,
                timing_type=timing,
                source_unit_id=caster.unit_id,
                source_skill_id=self._current_skill_id,
                is_debuff=True,
                original_duration_type=duration_type,
                just_applied=True,
            )
            self.aura_service.add_aura(target, aura)
            aura_list.append({
                "target_id": target.unit_id,
                "target": target.unit_id,
                "effect": SkillEffectType.SKILL_POWER_DOWN.value,
                "source_id": caster.unit_id,
                "source": caster.unit_id,
                "duration": 1,
                "dur_type": "action",
                "detail": f"威力:-{value:.0f}%",
            })
            _log.info("[SKILL_POWER_DOWN] %s: applied to %s value=%s%% dur=%s dur_type=%s",
                      caster.name, target.name, value, duration, duration_type)

        return {
            "effect_type": "aura",
            "is_debuff": True,
            "auras": aura_list,
        }

    def _apply_reset_cooldown(self, caster: UnitState, effect) -> Optional[Dict]:
        # 检查效果级条件
        effect_condition = getattr(effect, 'condition', None)
        if effect_condition and isinstance(effect_condition, dict):
            cond_type = effect_condition.get('type')
            if cond_type == 'damage_target_has_status_ailment':
                # 检查本次技能的伤害目标是否有异常状态（炎上/毒/凍結/眩暈/黑暗/混乱）
                # 異常状態≠debuff，異常状態只是debuff的子集
                STATUS_AILMENT_TYPES = {"knockout", "conflagration", "poison", "freeze",
                                        "darkness", "confusion"}
                bdt = getattr(self, '_block_damage_targets', None)
                if bdt and isinstance(bdt, dict):
                    damaged_units = []
                    seen_ids = set()
                    for units in bdt.values():
                        for u in units:
                            if u.unit_id not in seen_ids and u.is_alive:
                                seen_ids.add(u.unit_id)
                                damaged_units.append(u)
                    has_ailment = any(
                        any(d.effect_type.lower() in STATUS_AILMENT_TYPES for d in u.debuffs)
                        for u in damaged_units
                    )
                else:
                    has_ailment = False
                if not has_ailment:
                    _log.info("[RESET_CD] %s: skipped (damage_target_has_status_ailment: no damage target has status ailment)",
                              caster.name)
                    return {"effect_type": "reset_cooldown", "skill_id": int(effect.value or 0),
                            "caster_name": caster.name, "skipped": True}

        target_skill_id = int(effect.value) if effect.value else 0
        target_skill_name = ""
        was_on_cd = False
        if target_skill_id > 0:
            skill_data = self.data_loader.get_skill_by_id(target_skill_id)
            if skill_data:
                target_skill_name = skill_data.name
        if target_skill_id > 0 and target_skill_id in caster.skill_cooldowns:
            was_on_cd = True
            _log.info("[RESET_CD] %s: reset cooldown for skill_id=%d (was %d)",
                      caster.name, target_skill_id, caster.skill_cooldowns[target_skill_id])
            del caster.skill_cooldowns[target_skill_id]
        else:
            _log.info("[RESET_CD] %s: skill_id=%d not on cooldown or invalid", caster.name, target_skill_id)
        return {
            "effect_type": "reset_cooldown",
            "skill_id": target_skill_id,
            "skill_name": target_skill_name,
            "caster_name": caster.name,
            "was_on_cd": was_on_cd,
        }

    def _apply_resource(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        if not self.resource_service:
            _log.info("[RESOURCE_EFFECT] %s: resource_service unavailable", caster.name)
            return None

        etype = effect.effect_type
        value = int(effect.value or 0)

        if hasattr(effect, 'condition') and isinstance(effect.condition, dict):
            if effect.condition.get('type') == 'target_killed':
                if not getattr(self, '_skill_kills', False):
                    _log.info("[RESOURCE_EFFECT] %s: add_ap skipped (no kills, require_kill condition)",
                              caster.name)
                    return {"effect_type": etype, "value": value, "skipped": True}

        _log.info("[RESOURCE_EFFECT] %s: type=%s value=%d", caster.name, etype, value)

        if etype == "add_ap":
            # add_ap should respect target_type (e.g. ally_highest_atk for パワーアプライ)
            ap_targets_info = []
            ap_target_type = getattr(effect, 'target_type', None)
            if ap_target_type and ap_target_type not in ("self", None):
                target_skill_obj = type('obj', (object,), {
                    'display_target_type': self._resolve_target_type(ap_target_type),
                    'display_target_range': self._resolve_target_range(ap_target_type),
                    'display_target_priority': None,
                    'target_type_name': ap_target_type,
                })()
                ap_targets = self.target_service.select_targets(target_skill_obj, caster, battlefield) if self.target_service else []
                ap_targets = [t for t in ap_targets if t.is_alive]
                # highest_atk filter (same as _apply_aura and _add_status_effect)
                if ap_target_type and "highest_atk" in ap_target_type and ap_targets:
                    ap_targets = [max(ap_targets, key=lambda u: self.damage_service._calculate_final_stat(u, "attack") if self.damage_service else u.attack)]
                    _log.info("[RESOURCE_EFFECT] %s: add_ap highest_atk filter -> %s",
                              caster.name, ap_targets[0].name)
                if ap_targets:
                    for t in ap_targets:
                        old_ap = t.current_ap
                        self.resource_service.restore_ap(t, value)
                        ap_targets_info.append({
                            "target": t.name,
                            "target_id": t.unit_id,
                            "amount": t.current_ap - old_ap,
                            "ap_after": t.current_ap,
                            "ap_max": t.initial_active_point,
                        })
                        _log.info("[RESOURCE_EFFECT] %s: add_ap -> %s: value=%d", caster.name, t.name, value)
                else:
                    _log.info("[RESOURCE_EFFECT] %s: add_ap no valid targets for %s, fallback to caster",
                              caster.name, ap_target_type)
                    old_ap = caster.current_ap
                    self.resource_service.restore_ap(caster, value)
                    ap_targets_info.append({
                        "target": caster.name,
                        "target_id": caster.unit_id,
                        "amount": caster.current_ap - old_ap,
                        "ap_after": caster.current_ap,
                        "ap_max": caster.initial_active_point,
                    })
            else:
                old_ap = caster.current_ap
                self.resource_service.restore_ap(caster, value)
                ap_targets_info.append({
                    "target": caster.name,
                    "target_id": caster.unit_id,
                    "amount": caster.current_ap - old_ap,
                    "ap_after": caster.current_ap,
                    "ap_max": caster.initial_active_point,
                })
            return {
                "effect_type": "add_ap",
                "value": value,
                "targets": ap_targets_info,
            }
        elif etype == "add_ep":
            # value_source=max_ep: 将EP填充至满
            ep_value_source = getattr(effect, 'value_source', None)
            if ep_value_source == "max_ep":
                value = caster.max_extra_point - caster.current_ep
                _log.info("[RESOURCE_EFFECT] %s: add_ep value_source=max_ep, filling %d EP",
                          caster.name, value)
            ep_targets = []
            if effect.target_type in ("ally_all", "self_and_friends", "ally_single", "ally_back", "ally_front", "ally_front_row", "friends", "friend"):
                target_skill_obj = type('obj', (object,), {
                    'display_target_type': self._resolve_target_type(effect.target_type),
                    'display_target_range': self._resolve_target_range(effect.target_type),
                    'display_target_priority': None,
                    'target_type_name': effect.target_type,
                })()
                targets = self.target_service.select_targets(target_skill_obj, caster, battlefield) if self.target_service else []
                element_filter = getattr(self, '_target_element_filter', None)
                if element_filter is not None:
                    targets = [t for t in targets if getattr(t, 'element', 0) == element_filter]
                    _log.info("[RESOURCE_EFFECT] %s: add_ep target_element filter=%d, filtered targets=%d",
                              caster.name, element_filter, len(targets))
                exclude_self = effect.target_type not in ("self_and_friends", "ally_back", "ally_front", "ally_front_row")
                alive_targets = [t for t in targets if t.is_alive and not (exclude_self and t.unit_id == caster.unit_id)]

                # nearest_ally: 先获取所有友方（排除自身），再从中选距离最近的
                target_identifier = getattr(effect, 'target_identifier', None)
                if target_identifier == "nearest_ally":
                    from src.entities_v2.enums import Side as _SideEP
                    team = battlefield.friend_team if caster.side == _SideEP.ALLY else battlefield.enemy_team
                    alive_targets = [u for u in team if u.is_alive and u.unit_id != caster.unit_id]
                    if alive_targets and self.target_service:
                        nearest = self.target_service.get_nearest_ally(caster, alive_targets)
                        if nearest:
                            alive_targets = [nearest]
                            _log.info("[RESOURCE_EFFECT] %s: add_ep nearest_ally -> %s",
                                      caster.name, nearest.name)

                # distribute模式：将EP总值平均分配给目标
                flags = getattr(effect, 'flags', {}) or {}
                if flags.get('distribute') and alive_targets:
                    per_target = value // len(alive_targets)
                    _log.info("[RESOURCE_EFFECT] %s: add_ep distribute %d EP among %d allies -> %d each",
                              caster.name, value, len(alive_targets), per_target)
                else:
                    per_target = value

                for target in alive_targets:
                    old_ep = target.current_ep
                    self.resource_service.generate_ep(target, per_target)
                    actual_gain = target.current_ep - old_ep
                    ep_targets.append({
                        "target": target.name,
                        "target_id": target.unit_id,
                        "amount": actual_gain,
                        "ep_after": target.current_ep,
                        "ep_max": target.max_extra_point,
                    })
                    _log.info("[RESOURCE_EFFECT] %s -> %s: add_ep +%d (EP=%d/%d)",
                              caster.name, target.name, actual_gain, target.current_ep, target.max_extra_point)
            else:
                old_ep = caster.current_ep
                self.resource_service.generate_ep(caster, value)
                actual_gain = caster.current_ep - old_ep
                ep_targets.append({
                    "target": caster.name,
                    "target_id": caster.unit_id,
                    "amount": actual_gain,
                    "ep_after": caster.current_ep,
                    "ep_max": caster.max_extra_point,
                })

            return {
                "effect_type": "add_ep",
                "value": value,
                "targets": ep_targets,
            }
        elif etype == "remove_ap":
            targets = []
            if effect.target_type in ("enemy_single", "enemies", "enemy",
                                      "enemy_single_highest_atk", "enemy_single_highest_spd",
                                      "enemy_single_lowest_spd",
                                      "enemy_lowest_hp", "enemy_single_furthest"):
                if self.target_service:
                    # 优先从_block_damage_targets缓存获取目标（确保与damage效果目标一致）
                    cached_targets = getattr(self, '_block_damage_targets', None)
                    if cached_targets is not None and isinstance(cached_targets, dict) and effect.target_type in cached_targets:
                        targets = list(cached_targets[effect.target_type])
                    else:
                        target_skill_obj = type('obj', (object,), {
                            'display_target_type': self._resolve_target_type(effect.target_type),
                            'display_target_range': self._resolve_target_range(effect.target_type),
                            'display_target_priority': None,
                            'target_type_name': effect.target_type,
                        })()
                        targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)
            elif effect.target_type == "enemy_all":
                if self.target_service:
                    target_skill_obj = type('obj', (object,), {
                        'display_target_type': self._resolve_target_type("enemy_all"),
                        'display_target_range': self._resolve_target_range("enemy_all"),
                        'display_target_priority': None,
                        'target_type_name': "enemy_all",
                    })()
                    targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)
            elif effect.target_type in ("self",):
                targets = [caster]
            # cover替换：如果cover生效，remove_ap目标也应替换为cover者
            targets = self._apply_cover_debuff_replacement(caster, targets, battlefield)
            # enemy_all: 对所有存活敌人削减AP；其他类型: 仅对第一个目标
            if effect.target_type == "enemy_all":
                result_targets = []
                for t in targets:
                    if t.is_alive:
                        actual_ap = min(value, t.current_ap)
                        if actual_ap <= 0:
                            _log.info("[RESOURCE_EFFECT] %s: remove_ap skipped (target %s has 0 AP)",
                                      caster.name, t.name)
                            continue
                        self.resource_service.consume_ap(t, actual_ap)
                        _log.info("[RESOURCE_EFFECT] %s: remove_ap from %s: requested=%d actual=%d ap_after=%d",
                                  caster.name, t.name, value, actual_ap, t.current_ap)
                        entry = {
                            "target_id": t.unit_id, "target": t.unit_id,
                            "amount": actual_ap, "ap_after": t.current_ap, "ap_max": t.initial_active_point
                        }
                        cover_replaced_for = getattr(self, '_cover_debuff_replacements', {}).get(t.unit_id)
                        if cover_replaced_for:
                            entry["cover_replaced_for"] = cover_replaced_for
                        result_targets.append(entry)
                if result_targets:
                    return {"effect_type": "remove_ap", "targets": result_targets}
                else:
                    _log.info("[RESOURCE_EFFECT] %s: remove_ap skipped, no valid targets for enemy_all", caster.name)
            else:
                target = targets[0] if targets else None
                if target is not None and target.is_alive:
                    actual_ap = min(value, target.current_ap)
                    if actual_ap <= 0:
                        _log.info("[RESOURCE_EFFECT] %s: remove_ap skipped (target %s has 0 AP)",
                                  caster.name, target.name)
                    else:
                        self.resource_service.consume_ap(target, actual_ap)
                        _log.info("[RESOURCE_EFFECT] %s: remove_ap from %s: requested=%d actual=%d",
                                  caster.name, target.name, value, actual_ap)
                        entry = {"effect_type": "remove_ap", "targets": [{
                            "target_id": target.unit_id, "target": target.unit_id,
                            "amount": actual_ap, "ap_after": target.current_ap, "ap_max": target.initial_active_point
                        }]}
                        cover_replaced_for = getattr(self, '_cover_debuff_replacements', {}).get(target.unit_id)
                        if cover_replaced_for:
                            entry["targets"][0]["cover_replaced_for"] = cover_replaced_for
                        return entry
                else:
                    _log.info("[RESOURCE_EFFECT] %s: remove_ap skipped, no valid target", caster.name)
        elif etype == "remove_pp":
            all_pp_targets = []
            if effect.target_type in ("enemy_single", "enemies", "enemy", "enemy_all", "enemy_row", "enemy_column"):
                if self.target_service:
                    cached_targets = getattr(self, '_block_damage_targets', None)
                    if cached_targets is not None and isinstance(cached_targets, dict) and effect.target_type in cached_targets:
                        targets = list(cached_targets[effect.target_type])
                    else:
                        target_skill_obj = type('obj', (object,), {
                            'display_target_type': self._resolve_target_type(effect.target_type),
                            'display_target_range': self._resolve_target_range(effect.target_type),
                            'display_target_priority': None,
                            'target_type_name': effect.target_type,
                        })()
                        targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)
                    element_filter_pp = getattr(self, '_target_element_filter', None)
                    if element_filter_pp is not None:
                        targets = [t for t in targets if getattr(t, 'element', 0) == element_filter_pp]
                        _log.info("[RESOURCE_EFFECT] %s: remove_pp element filter=%d, filtered targets=%d",
                                  caster.name, element_filter_pp, len(targets))
                    char_type_filter = getattr(self, '_target_char_type_filter', None)
                    if char_type_filter is not None:
                        if isinstance(char_type_filter, int):
                            char_type_filter = [char_type_filter]
                        targets = [t for t in targets if getattr(t, 'character_type', 0) in char_type_filter]
                        _log.info("[RESOURCE_EFFECT] %s: remove_pp char_type filter=%s, filtered targets=%d",
                                  caster.name, char_type_filter, len(targets))
                    # cover替换：对每个目标单独处理
                    covered_targets = self._apply_cover_debuff_replacement(caster, targets, battlefield) if targets else []
                    for target in covered_targets:
                        if target is not None and target.is_alive:
                            # hp_threshold_cross等条件检查
                            effect_condition = getattr(effect, 'condition', None)
                            if effect_condition and isinstance(effect_condition, dict):
                                if not self._check_target_condition(target, effect_condition):
                                    continue
                            pp_flags = getattr(effect, 'flags', None) or {}
                            pp_threshold = pp_flags.get('pp_threshold', 0)
                            if pp_threshold > 0 and target.current_pp < pp_threshold:
                                _log.info("[RESOURCE_EFFECT] %s: remove_pp skipped (target %s PP %d < threshold %d)",
                                          caster.name, target.name, target.current_pp, pp_threshold)
                                continue
                            if pp_flags.get('remove_all_pp') or value == -1:
                                amount = target.current_pp
                            else:
                                amount = value if value else 1
                            # cap amount at current_pp: consume_pp在current_pp<amount时会失败
                            actual_amount = min(amount, target.current_pp)
                            if actual_amount <= 0:
                                _log.info("[RESOURCE_EFFECT] %s: remove_pp skipped (target %s has 0 PP)",
                                          caster.name, target.name)
                                continue
                            self.resource_service.consume_pp(target, actual_amount)
                            _log.info("[RESOURCE_EFFECT] %s: remove_pp from %s: requested=%d actual=%d",
                                      caster.name, target.name, amount, actual_amount)
                            entry = {
                                "target_id": target.unit_id, "target": target.unit_id,
                                "amount": actual_amount, "pp_after": target.current_pp, "pp_max": target.initial_passive_point
                            }
                            cover_replaced_for = getattr(self, '_cover_debuff_replacements', {}).get(target.unit_id)
                            if cover_replaced_for:
                                entry["cover_replaced_for"] = cover_replaced_for
                            all_pp_targets.append(entry)
            if all_pp_targets:
                return {"effect_type": "remove_pp", "targets": all_pp_targets}
            else:
                _log.info("[RESOURCE_EFFECT] %s: remove_pp skipped, no valid target", caster.name)
        elif etype == "remove_ep":
            # 检查是否多目标（如EX技能对3体敌人削EP）
            ep_flags = getattr(effect, 'flags', None) or {}
            ep_target_count = ep_flags.get('target_count', 1) if isinstance(ep_flags, dict) else 1
            all_ep_targets = []

            if ep_target_count > 1:
                # 多目标：优先从_block_damage_targets缓存获取所有被攻击目标
                cached_targets = getattr(self, '_block_damage_targets', None)
                if cached_targets is not None and isinstance(cached_targets, dict):
                    for _tk, _tv in cached_targets.items():
                        if not _tk or not isinstance(_tv, list):
                            continue
                        for _t in _tv:
                            if _t is None or not _t.is_alive:
                                continue
                            if any(x.get("target_id") == _t.unit_id for x in all_ep_targets):
                                continue
                            # cover替换
                            replaced = self._apply_cover_debuff_replacement(caster, [_t], battlefield)
                            actual_t = replaced[0] if replaced else _t
                            if actual_t is None or not actual_t.is_alive:
                                continue
                            amount = value if value else 1
                            self.resource_service.consume_ep(actual_t, amount)
                            _log.info("[RESOURCE_EFFECT] %s: remove_ep from %s: value=%d ep_after=%d/%d",
                                      caster.name, actual_t.name, amount, actual_t.current_ep, actual_t.max_extra_point)
                            entry = {
                                "target_id": actual_t.unit_id, "target": actual_t.unit_id,
                                "amount": amount, "ep_after": actual_t.current_ep, "ep_max": actual_t.max_extra_point
                            }
                            cover_replaced_for = getattr(self, '_cover_debuff_replacements', {}).get(actual_t.unit_id)
                            if cover_replaced_for:
                                entry["cover_replaced_for"] = cover_replaced_for
                            all_ep_targets.append(entry)
                if all_ep_targets:
                    return {"effect_type": "remove_ep", "targets": all_ep_targets}
                else:
                    _log.info("[RESOURCE_EFFECT] %s: remove_ep multi-target skipped, no valid targets", caster.name)

            # 单目标分支
            target = None
            if effect.target_type in ("enemy_single", "enemies", "enemy", "enemy_all",
                                      "enemy_single_highest_atk", "enemy_single_highest_spd",
                                      "enemy_single_lowest_spd",
                                      "enemy_single_highest_ep",
                                      "enemy_lowest_hp", "enemy_single_furthest"):
                if self.target_service:
                    cached_targets = getattr(self, '_block_damage_targets', None)
                    if cached_targets is not None and isinstance(cached_targets, dict) and effect.target_type in cached_targets:
                        targets = list(cached_targets[effect.target_type])
                    else:
                        target_skill_obj = type('obj', (object,), {
                            'display_target_type': self._resolve_target_type(effect.target_type),
                            'display_target_range': self._resolve_target_range(effect.target_type),
                            'display_target_priority': None,
                            'target_type_name': effect.target_type,
                        })()
                        targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)
                    if targets:
                        target = targets[0]
            elif effect.target_type in ("self",):
                target = caster
            # PS触发时通过_trigger_attacker定位攻击者
            if target is None:
                trigger_attacker = getattr(self, '_trigger_attacker', None)
                if trigger_attacker and trigger_attacker.is_alive:
                    target = trigger_attacker
                    _log.info("[RESOURCE_EFFECT] %s: remove_ep using trigger_attacker=%s", caster.name, target.name)
            # cover替换：如果cover生效，remove_ep目标也应替换为cover者
            if target is not None:
                replaced = self._apply_cover_debuff_replacement(caster, [target], battlefield)
                target = replaced[0] if replaced else None
            if target is not None and target.is_alive:
                amount = value if value else 1
                self.resource_service.consume_ep(target, amount)
                _log.info("[RESOURCE_EFFECT] %s: remove_ep from %s: value=%d ep_after=%d/%d",
                          caster.name, target.name, amount, target.current_ep, target.max_extra_point)
                entry = {
                    "target_id": target.unit_id, "target": target.unit_id,
                    "amount": amount, "ep_after": target.current_ep, "ep_max": target.max_extra_point
                }
                cover_replaced_for = getattr(self, '_cover_debuff_replacements', {}).get(target.unit_id)
                if cover_replaced_for:
                    entry["cover_replaced_for"] = cover_replaced_for
                return {"effect_type": "remove_ep", "targets": [entry]}
            else:
                _log.info("[RESOURCE_EFFECT] %s: remove_ep skipped, no valid target", caster.name)

        return {"effect_type": etype, "value": value}

    def _get_buff_types(self):
        return {
            "status_attack", "status_defense", "status_speed",
            "status_max_hp", "status_critical_chance",
            "shield", "cheat_death", "evade", "sure_hit",
            "heal_over_time", "critical_bonus_modification",
            "dealt_damage", "received_healing",
            "enchant_damage", "enchant_attack",
            "penetrate_defense", "modify_skill_power",
            "atk_up", "def_up", "crit_rate_up", "dmg_dealt_up",
            "spd_up", "crit_dmg_up", "dmg_taken_down",
            "debuff_immune",
            "heal_efficacy_up", "add_max_ap",
            "perfect_evasion", "add_damage_to_attack",
            "ignore_defense", "ignore_shield",
            "add_fury",
            "card_buff", "damage_link",
            "good_luck",
            "max_hp_up",
            "dmg_invulnerable",
            "block_specific_aura",
            # guard作为buff类型保留，但通过不同的机制触发
            # - 旧版guard（如130009）：通过buff系统生效
            # - 新版cover附带的guard：通过unit.guard_active生效
            "guard",
        }

    def _get_debuff_types(self):
        return {
            "poison", "conflagration", "freeze", "knockout", "confusion", "mark", "action_damage", "genwaku",
            SkillEffectType.POISON.value, SkillEffectType.CONFLAGRATION.value,
            SkillEffectType.FREEZE.value, SkillEffectType.KNOCKOUT.value,
            SkillEffectType.CONFUSION.value,
            SkillEffectType.MARK.value, SkillEffectType.ACTION_DAMAGE.value,
            SkillEffectType.GENWAKU.value,
            "received_damage", "attribute_attack", "attribute_defense",
            "block_auras", "block_evade",
            "stun", "spd_down", "dmg_dealt_down",
            "atk_down", "def_down", "crit_rate_down", "crit_dmg_down", "dmg_taken_up",
            "critical_forbidden",
            "ep_gain_down",
        }

    def _has_debuff_immune(self, target: UnitState) -> bool:
        return any(
            b.effect_type in ("debuff_immune", "DebuffImmune")
            for b in (getattr(target, 'buffs', []) or [])
        )

    def _consume_debuff_immune(self, target: UnitState) -> None:
        """消费debuff_immune buff的hit_limited，当hit_limited降为0时移除buff"""
        immune_buffs = [b for b in target.buffs
                        if b.effect_type in ("debuff_immune", "DebuffImmune")]
        for buff in immune_buffs:
            if hasattr(buff, 'hit_limited') and buff.hit_limited and buff.hit_limited > 0:
                buff.hit_limited -= 1
                _log.info("[DEBUFF_IMMUNE] %s: debuff_immune hit_limited %d->%d",
                          target.name, buff.hit_limited + 1, buff.hit_limited)
                if buff.hit_limited <= 0:
                    target.buffs = [b for b in target.buffs if b.buff_id != buff.buff_id]
                    _log.info("[DEBUFF_IMMUNE] %s: debuff_immune buff EXPIRED", target.name)
            break  # 只消费第一个debuff_immune buff

    def _check_target_condition(self, target: UnitState, effect_condition: dict) -> bool:
        if not effect_condition or not isinstance(effect_condition, dict):
            return True
        cond_type = effect_condition.get('type')
        if not cond_type:
            return True
        if cond_type == 'target_has_status_ailment':
            # 異常状態≠debuff，只检查异常状态（炎上/毒/凍結/眩暈/黑暗/混乱）
            STATUS_AILMENT_TYPES = {"knockout", "conflagration", "poison", "freeze",
                                    "darkness", "confusion"}
            return any(d.effect_type.lower() in STATUS_AILMENT_TYPES for d in target.debuffs)
        if cond_type == 'target_has_poison':
            return any(
                b.effect_type in ("poison", "Poison", SkillEffectType.POISON.value)
                for b in target.debuffs
            )
        if cond_type == 'target_has_burn':
            return any(
                b.effect_type in ("conflagration", "Conflagration", SkillEffectType.CONFLAGRATION.value)
                for b in target.debuffs
            )
        if cond_type == 'target_hp_above':
            threshold = effect_condition.get('value', 0)
            hp_pct = target.current_hp / target.max_hp * 100 if target.max_hp > 0 else 0
            return hp_pct >= threshold
        if cond_type == 'target_hp_below':
            threshold = effect_condition.get('pct', effect_condition.get('value', 0))
            hp_pct = target.current_hp / target.max_hp * 100 if target.max_hp > 0 else 0
            return hp_pct <= threshold
        if cond_type == 'hp_threshold_cross':
            # HP穿越阈值判定：伤害前HP > 阈值 且 伤害后HP <= 阈值
            threshold = effect_condition.get('value', 70)
            hp_before = self._last_damage_hp_before.get(target.unit_id, target.current_hp)
            threshold_hp = int(target.max_hp * threshold / 100)
            result = hp_before > threshold_hp and target.current_hp <= threshold_hp
            if not result:
                _log.info("[CHECK_CONDITION] %s: hp_threshold_cross FAILED (hp_before=%d threshold_hp=%d hp_after=%d)",
                          target.name, hp_before, threshold_hp, target.current_hp)
            return result
        if cond_type == 'target_has_mark':
            mark_name = effect_condition.get('mark_name', '')
            has_mark = any(
                d.effect_type == SkillEffectType.MARK.value and d.name == mark_name
                for d in target.debuffs
            ) or any(
                b.effect_type == SkillEffectType.MARK.value and b.name == mark_name
                for b in target.buffs
            )
            return has_mark
        if cond_type == 'target_is_front_row':
            # 检查目标是否为前排
            pos_name = target.position.name if hasattr(target, 'position') else ''
            return 'FRONT' in pos_name
        if cond_type == 'target_is_back_row':
            # 检查目标是否为后排
            pos_name = target.position.name if hasattr(target, 'position') else ''
            return 'BACK' in pos_name
        if cond_type == 'target_character_type':
            _ct_val = effect_condition.get('value')
            if isinstance(_ct_val, list):
                return getattr(target, 'character_type', 0) in _ct_val
            else:
                return getattr(target, 'character_type', 0) == _ct_val
        return True

    def _get_resource_types(self):
        return {
            "add_ap", "add_ep", "remove_ap", "remove_pp", "remove_ep",
        }

    def _resolve_target_type(self, effect_target_type: str) -> int:
        """
        将效果中的target_type字符串转为 DisplayTargetType int

        目标类型语义定义（与 skill_effects_hybrid.json 中的 target_type 对应）：
        ─────────────────────────────────────────────────────────────────
        "self"                          → SELF         仅自身
        "friends" / "friend"            → FRIENDS      自身以外的友方（不含自己）
        "ally_single"                   → FRIENDS      自身以外的单个友方
        "ally_single_include_self"      → SELF_AND_FRIENDS  优先自身以外的单个友方，无其他友方时回退自身
        "ally_all"                      → SELF_AND_FRIENDS  所有友方（含自己）
        "self_and_friends"              → SELF_AND_FRIENDS  自身及所有友方
        "ally_back"                     → SELF_AND_FRIENDS  后排友方（含自己在后排时）
        "ally_front"                    → SELF_AND_FRIENDS  前排友方（含自己在前排时）
        "ally_column" / "ally_row"      → SELF_AND_FRIENDS  同列/同行友方（含自己）
        "ally_highest_atk"              → SELF_AND_FRIENDS  攻击力最高的友方（含自己）
        "enemies" / "enemy_*"           → ENEMIES      敌方单位
        "all"                           → ALL          所有单位（友方+敌方）
        "adjacent_enemies"              → ADJACENT     邻接敌方
        ─────────────────────────────────────────────────────────────────
        关键区分：
        - "friends"/"friend"/"ally_single" → 不含自己（用于如「まじ本気だすぞー！！」block2
          给自身以外友方加buff、「ブラック・スタイル」EP均摊给其他友方）
        - "ally_back"/"ally_front" → 含自己（用于如「グローリーコール」给后排光属性角色+EP，
          施法者若在后排且满足条件也应被包含）
        - "ally_all" → 含自己（所有友方，用于如「グローリーコール」block1给全体加攻防）
        """
        from ...entities_v2.enums import DisplayTargetType
        t = effect_target_type.lower() if effect_target_type else "unknown"
        if t in ("self",): return DisplayTargetType.SELF.value
        if t in ("enemies", "enemy", "enemy_single", "enemy_all",
                 "enemy_column", "enemy_row", "enemy_front", "enemy_random",
                 "enemy_highest_atk", "enemy_single_highest_atk",
                 "enemy_single_highest_spd", "enemy_single_lowest_spd",
                 "enemy_lowest_hp", "enemy_single_furthest", "last_target",
                 "enemy_back_row",
                 "enemy_single_highest_hp_ratio",
                 "enemy_single_highest_current_hp",
                 "enemy_row_of_lowest_def",
                 "enemy_single_lowest_def_x2",
                 "attacked_targets"):
            return DisplayTargetType.ENEMIES.value
        if t in ("friends", "friend", "ally_single"):
            return DisplayTargetType.FRIENDS.value
        if t in ("ally_single_include_self", "ally_single_lowest_hp_x2"):
            return DisplayTargetType.SELF_AND_FRIENDS.value
        # [GAME_BUG_SIMULATION] 技能「装いを新たに」(110050) 两阶段链式最近索敌
        # 候选池必须含自身（自身在前排时 A=自身），故映射到 SELF_AND_FRIENDS
        if t in ("ally_single_chained_nearest",):
            return DisplayTargetType.SELF_AND_FRIENDS.value
        if t in ("ally_front", "ally_front_row", "ally_back", "ally_column", "ally_row",
                 "ally_highest_atk"):
            return DisplayTargetType.SELF_AND_FRIENDS.value
        if t in ("ally_all", "self_and_friends"): return DisplayTargetType.SELF_AND_FRIENDS.value
        if t in ("all",): return DisplayTargetType.SELF_AND_FRIENDS_AND_ENEMIES.value
        if t in ("adjacent_enemies", "adjacent_to_nearest_enemy",): return DisplayTargetType.ADJACENT_ENEMIES.value
        return DisplayTargetType.ENEMIES.value

    def _resolve_target_range(self, effect_target_type: str) -> int:
        from ...entities_v2.enums import DisplayTargetRange
        t = effect_target_type.lower() if effect_target_type else "unknown"
        if t in ("self",): return DisplayTargetRange.ONE_PAWN.value
        if t in ("enemy_single", "ally_single", "ally_single_include_self",
                 "ally_single_chained_nearest",
                 "enemy_single_highest_atk", "enemy_single_highest_spd",
                 "enemy_single_lowest_spd",
                 "enemy_single_furthest",
                 "enemy_single_highest_ep",
                 "enemy_single_highest_hp_ratio",
                 "enemy_single_highest_current_hp",
                 "enemy_single_highest_hp_ratio_back_priority",
                 "enemy_single_lowest_hp_ratio"): return DisplayTargetRange.ONE_PAWN.value
        if t in ("enemy_row", "enemy_front", "ally_front", "ally_front_row", "ally_back", "ally_row",
                 "enemy_back_row",
                 "enemy_row_of_lowest_def"):
            return DisplayTargetRange.LINE.value
        if t in ("enemy_single_lowest_def_x2",
                 "ally_single_lowest_hp_x2"):
            return DisplayTargetRange.TWO_PAWNS.value
        if t in ("enemy_column", "ally_column",
                 "enemy_column_mark_priority",
                 "enemy_column_furthest"): return DisplayTargetRange.COLUMN.value
        if t in ("friends", "friend", "self_and_friends", "all", "adjacent_enemies",
                 "adjacent_to_nearest_enemy",
                 "enemy_all", "ally_all", "enemies", "enemy",
                 "ally_highest_atk", "enemy_highest_atk",
                 "attacked_targets"):
            return DisplayTargetRange.ALL_PAWNS.value
        return DisplayTargetRange.ONE_PAWN.value

    def _postfilter_damage_targets(self, target_type: str, targets: list,
                                    caster: UnitState, effect_flags: dict,
                                    consume_stealth: bool = True) -> list:
        """对特殊索敌类型应用后过滤，与实际damage执行的后过滤逻辑保持一致。

        prescan必须调用此方法，否则trigger检查会使用与实际damage不同的目标，
        导致target_is_self等条件误判（如ブレイジングハート误触发bug：
        prescan用NEAREST选了PS持有者，实际damage用后排+最高HP比例选了其他单位）。

        consume_stealth=False 时仅模拟ステルス重定向，不实际消費（用于prescan）。
        """
        if not targets:
            return targets

        dmg_targets = list(targets)

        if target_type and "highest_atk" in target_type:
            best = self.target_service.select_max_with_stealth(
                dmg_targets,
                key_func=lambda u: self.damage_service._calculate_final_stat(u, "attack") if self.damage_service else u.attack,
                consume=consume_stealth
            )
            dmg_targets = [best] if best else []
        elif target_type and "highest_spd" in target_type:
            best = self.target_service.select_max_with_stealth(
                dmg_targets,
                key_func=lambda u: self.damage_service._calculate_final_stat(u, "speed") if self.damage_service else u.speed,
                consume=consume_stealth
            )
            dmg_targets = [best] if best else []
        elif target_type and "lowest_spd" in target_type:
            best = self.target_service.select_min_with_stealth(
                dmg_targets,
                key_func=lambda u: self.damage_service._calculate_final_stat(u, "speed") if self.damage_service else u.speed,
                consume=consume_stealth
            )
            dmg_targets = [best] if best else []
        elif target_type and "furthest" in target_type and "column_furthest" not in target_type:
            best = self.target_service.select_min_with_stealth(
                dmg_targets,
                key_func=lambda u: self._get_farthest_key(caster.position, u),
                consume=consume_stealth
            )
            dmg_targets = [best] if best else []
        elif target_type and "highest_ep" in target_type:
            best = self.target_service.select_max_with_stealth(
                dmg_targets,
                key_func=lambda u: u.current_ep,
                consume=consume_stealth
            )
            dmg_targets = [best] if best else []
        elif target_type == "enemy_single_highest_hp_ratio_back_priority":
            back_targets = [u for u in dmg_targets if self.target_service._is_back_row(u)]
            search_pool = back_targets if back_targets else dmg_targets
            best = self.target_service.select_max_with_stealth(
                search_pool,
                key_func=lambda u: (u.current_hp / u.max_hp) if u.max_hp > 0 else 0,
                consume=consume_stealth
            )
            dmg_targets = [best] if best else []
        elif target_type == "enemy_single_highest_hp_ratio":
            best = self.target_service.select_max_with_stealth(
                dmg_targets,
                key_func=lambda u: (u.current_hp / u.max_hp) if u.max_hp > 0 else 0,
                consume=consume_stealth
            )
            dmg_targets = [best] if best else []
        elif target_type == "enemy_single_highest_current_hp":
            best = self.target_service.select_max_with_stealth(
                dmg_targets,
                key_func=lambda u: u.current_hp,
                consume=consume_stealth
            )
            dmg_targets = [best] if best else []
        elif target_type == "enemy_single_lowest_hp_ratio":
            best = self.target_service.select_min_with_stealth(
                dmg_targets,
                key_func=lambda u: (u.current_hp / u.max_hp) if u.max_hp > 0 else 0,
                consume=consume_stealth
            )
            dmg_targets = [best] if best else []
        elif target_type == "enemy_column_furthest":
            anchor = self.target_service.select_min_with_stealth(
                dmg_targets,
                key_func=lambda u: self._get_farthest_key(caster.position, u),
                consume=consume_stealth
            )
            if anchor is None:
                dmg_targets = []
            else:
                anchor_col = self.target_service._get_column_index(anchor)
                dmg_targets = [u for u in dmg_targets if self.target_service._get_column_index(u) == anchor_col]
        elif target_type == "enemy_column_mark_priority":
            mark_name = effect_flags.get('mark_priority', 'サンタタグ')
            marked_units = [u for u in dmg_targets if any(
                getattr(b, 'name', '') == mark_name and getattr(b, 'effect_type', '').lower() == 'mark'
                for b in ((u.buffs or []) + (u.debuffs or []))
            )]
            candidates = marked_units if marked_units else dmg_targets
            anchor = self.target_service.select_min_with_stealth(
                candidates,
                key_func=lambda u: self._get_distance_key(caster, u),
                consume=consume_stealth
            )
            if anchor is None:
                dmg_targets = []
            else:
                anchor_col = self.target_service._get_column_index(anchor)
                dmg_targets = [u for u in dmg_targets if self.target_service._get_column_index(u) == anchor_col]

        return dmg_targets

    def _get_distance_key(self, anchor: UnitState, unit: UnitState):
        ar, ac = _POS_RC[anchor.position]
        tr, tc = _POS_RC[unit.position]
        # 欧几里得平方距离（含斜向距离），而非曼哈顿距离
        dist_sq = (tr - ar) ** 2 + (tc - ac) ** 2
        return (dist_sq, tr, tc)

    def _get_farthest_key(self, caster_pos, unit: UnitState):
        """基于列参考点的最远距离排序键（参考position_system.md）"""
        _, cc = _POS_RC[caster_pos]
        tr, tc = _POS_RC[unit.position]
        dist_sq = (tr - 0) ** 2 + (tc - cc) ** 2
        return (-dist_sq, tr, tc)

    def deduct_skill_cost(self, unit: UnitState, skill_id: int) -> bool:
        """公开方法：在技能准备阶段扣除资源"""
        meta = self.data_loader.get_skill_by_id(skill_id)
        if not meta:
            return False
        return self._deduct_cost(unit, meta)

    def _deduct_cost(self, unit: UnitState, skill_data) -> bool:
        cost = skill_data.resource_cost
        _log.info("[DEDUCT] %s: skill_type=%d cost=%d AP=%d PP=%d EP=%d/%d",
                  unit.name, skill_data.skill_type, cost,
                  unit.current_ap, unit.current_pp, unit.current_ep, unit.max_extra_point)
        if skill_data.skill_type == 1:  # AS
            if self.resource_service.consume_ap(unit, cost):
                self.resource_service.generate_ep(unit, cost)
                return True
            return False
        elif skill_data.skill_type == 2:  # PS
            if self.resource_service.consume_pp(unit, cost):
                self.resource_service.generate_ep(unit, cost)
                return True
            return False
        elif skill_data.skill_type == 3:  # EX
            return self.resource_service.consume_ep_for_ex(unit)
        return True

    def update_cooldown_after_skill_use(self, unit: UnitState, skill_id: int):
        resolved = self._resolver.resolve(skill_id, unit.skill_levels.get(skill_id, 1))
        if not resolved:
            return
        if resolved.cooldown_update_timing is None:
            return
        if resolved.cooldown is not None and resolved.cooldown > 0:
            unit.skill_cooldowns[skill_id] = resolved.cooldown

    def update_action_cooldowns(self, unit: UnitState, pre_action_snapshot: dict = None):
        """行动后冷却递减 (cooldown_update_timing: 2)"""
        if pre_action_snapshot is not None:
            for sid, cd in list(pre_action_snapshot.items()):
                if cd > 0 and sid in unit.skill_cooldowns:
                    if not self._is_turn_end_cooldown(unit, sid):
                        unit.skill_cooldowns[sid] -= 1
                        if unit.skill_cooldowns[sid] <= 0:
                            del unit.skill_cooldowns[sid]
            return
        for sid in list(unit.skill_cooldowns.keys()):
            if unit.skill_cooldowns[sid] > 0:
                if self._is_turn_end_cooldown(unit, sid):
                    continue
                unit.skill_cooldowns[sid] -= 1
                if unit.skill_cooldowns[sid] <= 0:
                    del unit.skill_cooldowns[sid]

    def update_turn_end_cooldowns(self, unit: UnitState, turn_start_snapshot: dict = None):
        """回合结束冷却递减 (cooldown_update_timing: 1)"""
        if turn_start_snapshot is not None:
            for sid, cd in list(turn_start_snapshot.items()):
                if cd > 0 and sid in unit.skill_cooldowns:
                    if self._is_turn_end_cooldown(unit, sid):
                        unit.skill_cooldowns[sid] -= 1
                        if unit.skill_cooldowns[sid] <= 0:
                            del unit.skill_cooldowns[sid]
            return
        for sid in list(unit.skill_cooldowns.keys()):
            if unit.skill_cooldowns[sid] > 0:
                if not self._is_turn_end_cooldown(unit, sid):
                    continue
                unit.skill_cooldowns[sid] -= 1
                if unit.skill_cooldowns[sid] <= 0:
                    del unit.skill_cooldowns[sid]

    def _is_turn_end_cooldown(self, unit: UnitState, skill_id: int) -> bool:
        """判断技能是否采用回合结束冷却 (cooldown_update_timing: 1)"""
        resolved = self._resolver.resolve(skill_id, unit.skill_levels.get(skill_id, 1))
        if not resolved:
            return False
        timing = resolved.cooldown_update_timing
        return timing == 1

    def _apply_consume_hp(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        flags = getattr(effect, 'flags', {}) or {}
        hp_base = flags.get('hp_base', 'current_hp')
        pct = effect.value or 0

        if hp_base == 'max_hp':
            effective_max_hp = self.damage_service._calculate_final_stat(caster, "max_hp")
            consume_amount = int(effective_max_hp * pct / 100)
        else:
            consume_amount = int(caster.current_hp * pct / 100)

        actual_consume = min(consume_amount, caster.current_hp - 1)
        caster.current_hp -= actual_consume
        self._hp_consumed = actual_consume

        _log.info("[CONSUME_HP] %s: consumed %d HP (%.0f%% of %s), hp %d→%d",
                  caster.name, actual_consume, pct, hp_base,
                  caster.current_hp + actual_consume, caster.current_hp)

        return {
            "effect_type": "consume_hp",
            "consumed": actual_consume,
        }

    def _apply_hp_ratio_damage(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        if not self.damage_service or not self.target_service:
            return None

        flags = getattr(effect, 'flags', {}) or {}
        value_source = getattr(effect, 'value_source', None)
        dmg_pct = effect.value or 100

        # damage_cap_atk_pct: 伤害上限为ATK的指定百分比
        cap_atk_pct = flags.get('damage_cap_atk_pct', 0)

        target_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': self._resolve_target_range(effect.target_type),
            'display_target_priority': None,
            'target_type_name': effect.target_type,
        })()

        # 优先使用mark条件匹配的所有目标（如target_has_mark条件记录的目标列表）
        if (hasattr(self, '_mark_condition_targets') and self._mark_condition_targets
                and effect.target_type in ("enemy_single",)):
            targets = [t for t in self._mark_condition_targets if t.is_alive]
            _log.info("[HP_RATIO_DMG] %s: using _mark_condition_targets=%s",
                      caster.name, [t.name for t in targets])
        elif (hasattr(self, '_mark_condition_target') and self._mark_condition_target
                and effect.target_type in ("enemy_single",)):
            targets = [self._mark_condition_target]
            _log.info("[HP_RATIO_DMG] %s: using _mark_condition_target=%s",
                      caster.name, self._mark_condition_target.name)
        elif (hasattr(self, '_block_damage_targets') and self._block_damage_targets
                and effect.target_type in self._block_damage_targets):
            # 使用block预填的目标（如target_has_mark条件预填的攻击目标）
            targets = [t for t in self._block_damage_targets[effect.target_type] if t.is_alive]
            _log.info("[HP_RATIO_DMG] %s: using _block_damage_targets[%s]=%s",
                      caster.name, effect.target_type, [t.name for t in targets])
        else:
            targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)

        total_damage = 0
        targets_hit = []
        for target in targets:
            if not target.is_alive:
                continue

            # 根据value_source确定基础值
            if value_source == "target_lost_hp":
                # 基于目标已损HP（max_hp - current_hp）
                base_value = target.max_hp - target.current_hp
                raw_power = base_value * dmg_pct / 100.0
                # 应用ATK上限
                if cap_atk_pct > 0:
                    effective_atk = self.damage_service._calculate_final_stat(caster, "attack")
                    cap = effective_atk * cap_atk_pct / 100.0
                    raw_power = min(raw_power, cap)
                    _log.info("[HP_RATIO_DMG] %s -> %s: target_lost_hp=%d dmg_pct=%.0f raw=%.1f cap=%.1f(ATK*%d%%)",
                              caster.name, target.name, base_value, dmg_pct, raw_power, cap, cap_atk_pct)
                else:
                    _log.info("[HP_RATIO_DMG] %s -> %s: target_lost_hp=%d dmg_pct=%.0f raw_power=%.1f",
                              caster.name, target.name, base_value, dmg_pct, raw_power)
            elif value_source == "target_current_hp":
                # 基于目标当前HP
                base_value = target.current_hp
                raw_power = base_value * dmg_pct / 100.0
                # 应用ATK上限
                if cap_atk_pct > 0:
                    effective_atk = self.damage_service._calculate_final_stat(caster, "attack")
                    cap = effective_atk * cap_atk_pct / 100.0
                    raw_power = min(raw_power, cap)
                    _log.info("[HP_RATIO_DMG] %s -> %s: target_current_hp=%d dmg_pct=%.0f raw=%.1f cap=%.1f(ATK*%d%%)",
                              caster.name, target.name, base_value, dmg_pct, raw_power, cap, cap_atk_pct)
                else:
                    _log.info("[HP_RATIO_DMG] %s -> %s: target_current_hp=%d dmg_pct=%.0f raw_power=%.1f",
                              caster.name, target.name, base_value, dmg_pct, raw_power)
            elif value_source == "caster_current_hp":
                # 基于施法者当前HP（如技能110053 RAY OF HERO）
                base_value = caster.current_hp
                raw_power = base_value * dmg_pct / 100.0
                # 应用ATK上限
                if cap_atk_pct > 0:
                    effective_atk = self.damage_service._calculate_final_stat(caster, "attack")
                    cap = effective_atk * cap_atk_pct / 100.0
                    raw_power = min(raw_power, cap)
                    _log.info("[HP_RATIO_DMG] %s -> %s: caster_current_hp=%d dmg_pct=%.0f raw=%.1f cap=%.1f(ATK*%d%%)",
                              caster.name, target.name, base_value, dmg_pct, raw_power, cap, cap_atk_pct)
                else:
                    _log.info("[HP_RATIO_DMG] %s -> %s: caster_current_hp=%d dmg_pct=%.0f raw_power=%.1f",
                              caster.name, target.name, base_value, dmg_pct, raw_power)
            else:
                # 原有逻辑：基于自身消耗的HP
                consumed = getattr(self, '_hp_consumed', 0)
                raw_power = consumed * dmg_pct / 100.0
                _log.info("[HP_RATIO_DMG] %s: consumed=%d dmg_pct=%.0f raw_power=%.1f",
                          caster.name, consumed, dmg_pct, raw_power)

            hp_before = target.current_hp
            actual_damage = int(raw_power)
            # 混乱减免（仅减免，不应用代理数值——代理数值仅在ATK-DEF模式适用）
            if getattr(caster, 'is_confused', False):
                confusion_buff = self.damage_service._get_confusion_buff(caster) if self.damage_service else None
                if confusion_buff and confusion_buff.confusion_dmg_reduction > 0:
                    orig_actual = actual_damage
                    actual_damage = max(1, int(actual_damage * (1 - confusion_buff.confusion_dmg_reduction / 100.0)))
                    _log.info("[HP_RATIO_DMG] CONFUSION reduction: %d -> %d (-%.1f%%)",
                              orig_actual, actual_damage, confusion_buff.confusion_dmg_reduction)
            target.current_hp = max(0, target.current_hp - actual_damage)
            total_damage += actual_damage
            caster.damage_dealt_total += actual_damage
            target.damage_taken_total += actual_damage

            targets_hit.append({
                "target": target.name,
                "target_id": target.unit_id,
                "hp_before": hp_before,
                "hp_after": target.current_hp,
                "damage": actual_damage,
                "actual_damage": actual_damage,
                "shield_absorbed": 0,
                "crit": False,
                "hits": [actual_damage],
            })

            dead_mark = " 💀DEAD" if target.current_hp <= 0 else ""
            _log.info("[HP_RATIO_DMG] %s -> %s: hp %d→%d (-%d)%s",
                      caster.name, target.name, hp_before, target.current_hp, actual_damage, dead_mark)

            if target.current_hp <= 0:
                self._pending_deaths.add(target.unit_id)
                _log.info("[HP_RATIO_DMG] %s: death deferred for %s", caster.name, target.name)

        self._most_recent_damage += total_damage
        if value_source != "target_lost_hp":
            self._hp_consumed = 0

        return {
            "effect_type": "hp_ratio_damage",
            "targets": targets_hit,
            "total_damage": total_damage,
            "damage": total_damage,
        }

    def _apply_damage_special(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        if not self.target_service:
            return None

        flags = getattr(effect, 'flags', {}) or {}
        apply_guard = flags.get('apply_guard', False)
        can_evade = flags.get('can_evade', False)
        apply_shield = flags.get('apply_shield', False)

        value_source = getattr(effect, 'value_source', None)
        dmg_pct = effect.value or 0

        if value_source == "self_max_hp":
            effective_max_hp = self.damage_service._calculate_final_stat(caster, "max_hp")
            raw_damage = int(float(effective_max_hp) * dmg_pct / 100.0)
        elif value_source == "self_current_hp":
            raw_damage = int(float(caster.current_hp) * dmg_pct / 100.0)
        else:
            effective_atk = self.damage_service._calculate_final_stat(caster, "attack")
            raw_damage = int(float(effective_atk) * dmg_pct / 100.0)

        _log.info("[DAMAGE_SPECIAL] %s: value_source=%s dmg_pct=%.0f raw_damage=%d flags=%s",
                  caster.name, value_source, dmg_pct, raw_damage, flags)

        target_skill_obj = type('obj', (object,), {
            'display_target_type': self._resolve_target_type(effect.target_type),
            'display_target_range': self._resolve_target_range(effect.target_type),
            'display_target_priority': None,
            'target_type_name': effect.target_type,
        })()

        targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)

        total_damage = 0
        targets_hit = []
        for target in targets:
            if not target.is_alive:
                continue

            current_raw = raw_damage

            # 混乱减免（仅减免，代理数值仅适用于ATK-DEF模式，damage_special不应用代理）
            if getattr(caster, 'is_confused', False):
                confusion_buff = self.damage_service._get_confusion_buff(caster) if self.damage_service else None
                if confusion_buff and confusion_buff.confusion_dmg_reduction > 0:
                    orig_raw = current_raw
                    current_raw = max(1, int(current_raw * (1 - confusion_buff.confusion_dmg_reduction / 100.0)))
                    _log.info("[DAMAGE_SPECIAL] CONFUSION reduction: %d -> %d (-%.1f%%)",
                              orig_raw, current_raw, confusion_buff.confusion_dmg_reduction)

            # evade check: 可被闪避
            evaded = False
            if can_evade:
                evade_buffs = [b for b in target.buffs if b.effect_type == SkillEffectType.EVADE.value and b.hit_limited > 0]
                if evade_buffs and not getattr(target, 'is_charging', False):
                    # 必中效果优先
                    sure_hit_buffs = [b for b in caster.buffs if b.effect_type == SkillEffectType.SURE_HIT.value]
                    if sure_hit_buffs:
                        _log.info("[DAMAGE_SPECIAL] %s has sure_hit, %s's evade NOT triggered",
                                  caster.name, target.name)
                    else:
                        ev_buff = evade_buffs[0]
                        ev_buff.hit_limited -= 1
                        _log.info("[DAMAGE_SPECIAL] %s evades damage_special from %s! hit_limited=%d",
                                  target.name, caster.name, ev_buff.hit_limited)
                        if ev_buff.hit_limited <= 0:
                            target.buffs = [b for b in target.buffs if b.buff_id != ev_buff.buff_id]
                            _log.info("[DAMAGE_SPECIAL] %s: Evade buff EXPIRED", target.name)
                        evaded = True

            if evaded:
                targets_hit.append({
                    "target": target.name,
                    "target_id": target.unit_id,
                    "hp_before": target.current_hp,
                    "hp_after": target.current_hp,
                    "damage": 0,
                    "actual_damage": 0,
                    "shield_absorbed": 0,
                    "crit": False,
                    "evaded": True,
                })
                continue

            # guard reduction: 受guard效果影响
            if apply_guard:
                guard_mult = self.damage_service._get_guard_multiplier(target)
                current_raw = max(1, int(current_raw * guard_mult))
                _log.info("[DAMAGE_SPECIAL] %s: guard_mult=%.4f, damage after guard=%d",
                          target.name, guard_mult, current_raw)

            # shield absorption: 可被护盾吸收
            shield_absorbed = 0
            if apply_shield:
                remaining = current_raw
                caster_char_type = getattr(caster, 'character_type', 1)
                is_en_damage = (caster_char_type == 2)

                if is_en_damage and target.en_shield > 0:
                    absorbed = min(remaining, target.en_shield)
                    target.en_shield -= absorbed
                    shield_absorbed += absorbed
                    remaining -= absorbed
                elif not is_en_damage and target.physical_shield > 0:
                    absorbed = min(remaining, target.physical_shield)
                    target.physical_shield -= absorbed
                    shield_absorbed += absorbed
                    remaining -= absorbed

                if remaining > 0 and target.shield > 0:
                    absorbed = min(remaining, target.shield)
                    target.shield -= absorbed
                    shield_absorbed += absorbed
                    remaining -= absorbed

                # Sub-unit absorption
                if remaining > 0:
                    sub_unit_buffs = [b for b in target.buffs if b.effect_type == SkillEffectType.SUB_UNIT.value and b.sub_unit_hp > 0]
                    for sub_buff in sub_unit_buffs:
                        if remaining <= 0:
                            break
                        absorbed = min(remaining, sub_buff.sub_unit_hp)
                        sub_buff.sub_unit_hp -= absorbed
                        shield_absorbed += absorbed
                        remaining -= absorbed
                        if sub_buff.sub_unit_hp <= 0:
                            target.buffs = [b for b in target.buffs if b.buff_id != sub_buff.buff_id]

                # 非闪避命中最低1点伤害，可作用于护盾或HP
                if remaining <= 0 and raw_damage > 0:
                    min_absorbed = False
                    caster_char_type = getattr(caster, 'character_type', 1)
                    is_en_damage = (caster_char_type == 2)
                    if is_en_damage and target.en_shield > 0:
                        target.en_shield -= 1
                        shield_absorbed += 1
                        min_absorbed = True
                    elif not is_en_damage and target.physical_shield > 0:
                        target.physical_shield -= 1
                        shield_absorbed += 1
                        min_absorbed = True
                    elif target.shield > 0:
                        target.shield -= 1
                        shield_absorbed += 1
                        min_absorbed = True
                    if not min_absorbed:
                        remaining = 1

                current_raw = remaining

            hp_before = target.current_hp
            actual_dmg = current_raw
            overflow = max(0, actual_dmg - hp_before)
            target.current_hp = max(0, target.current_hp - actual_dmg)
            total_damage += actual_dmg
            targets_hit.append({
                "target": target.name,
                "target_id": target.unit_id,
                "hp_before": hp_before,
                "hp_after": target.current_hp,
                "damage": actual_dmg,
                "actual_damage": actual_dmg,
                "shield_absorbed": shield_absorbed,
                "crit": False,
                "evaded": False,
            })
            _log.info("[DAMAGE_SPECIAL] %s -> %s: hp %d→%d (-%d, shield_absorbed=%d)",
                      caster.name, target.name, hp_before, target.current_hp, actual_dmg, shield_absorbed)
            if target.current_hp <= 0:
                self._pending_deaths.add(target.unit_id)
                _log.info("[DAMAGE_SPECIAL] %s: death deferred for %s", caster.name, target.name)

        return {
            "effect_type": "damage_special",
            "targets": targets_hit,
            "total_damage": total_damage,
            "damage": total_damage,
        }

    def _apply_sub_unit(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """Apply a sub-unit buff to the target(s).

        Sub-unit is a buff that combines:
        1. Shield HP: absorbs damage on behalf of the holder
        2. Additional damage: adds N hits of damage when holder attacks
        3. Optional add_status_to_attack: applies a debuff to attack target when holder attacks

        The sub_unit_hp is based on caster's maxHP × percentage.
        The value field represents the additional damage percentage (ATK × value%).
        Supports target_count > 1 to apply sub_unit to multiple allies.
        """
        effect_flags = getattr(effect, 'flags', None) or {}
        hp_pct = effect_flags.get('sub_unit_hp_pct', 25.0)  # default 25% of maxHP
        atk_pct = effect.value or 0  # additional damage = ATK × atk_pct%
        target_count_limit = effect_flags.get('target_count', 1) or 1

        # add_status_to_attack: 子機追加伤害时同时施加debuff（如spd_down）
        add_status_info = effect_flags.get('add_status_to_attack', None)

        # Calculate sub-unit HP
        effective_max_hp = self.damage_service._calculate_final_stat(caster, "max_hp")
        sub_unit_max_hp = int(effective_max_hp * hp_pct / 100.0)
        if sub_unit_max_hp <= 0:
            sub_unit_max_hp = 1

        # Determine targets (support multiple targets via target_count)
        if effect.target_type == "self":
            target_list = [caster]
        else:
            # 优先使用缓存的伤害目标（与def_up等效果共享目标）
            cached_targets = getattr(self, '_block_damage_targets', None)
            if cached_targets is not None and isinstance(cached_targets, dict) and effect.target_type in cached_targets:
                target_list = list(cached_targets[effect.target_type])
                _log.info("[SUB_UNIT] %s: using cached targets (%d) for target_type=%s",
                          caster.name, len(target_list), effect.target_type)
            else:
                # target_count > 1时扩展目标范围（与_apply_aura一致）
                _su_resolved_range = self._resolve_target_range(effect.target_type)
                if target_count_limit > 1 and _su_resolved_range == 1:  # ONE_PAWN
                    from ...entities_v2.enums import DisplayTargetRange
                    _su_resolved_range = (DisplayTargetRange.TWO_PAWNS.value if target_count_limit == 2
                                          else DisplayTargetRange.ALL_PAWNS.value)
                selected = self.target_service.select_targets(
                    type('obj', (object,), {
                        'display_target_type': self._resolve_target_type(effect.target_type),
                        'display_target_range': _su_resolved_range,
                        'display_target_priority': self._current_skill_priority,
                        'target_type_name': effect.target_type,
                    })(),
                    caster, battlefield
                )
                target_list = selected or []

        # en_type_priority: 优先EN类型友方(自身以外) > 非EN类型友方(自身以外) > 自身
        # 必须对完整友方列表按距离排序后再筛EN/非EN，否则ONE_PAWN缩窄后会遗漏更远的EN友方
        if effect_flags.get('en_type_priority') and target_list:
            from src.entities_v2.enums import Side as _SideSu
            _ally_team = battlefield.friend_team if caster.side == _SideSu.ALLY else battlefield.enemy_team
            _others = [u for u in _ally_team if u.is_alive and u.unit_id != caster.unit_id]
            if _others:
                _others.sort(key=lambda u: self.target_service._get_sort_key(caster, u))
                _en_ordered = [u for u in _others if getattr(u, 'character_type', 0) == 2]
                _non_en_ordered = [u for u in _others if getattr(u, 'character_type', 0) != 2]
                _priority_list = _en_ordered + _non_en_ordered
                if _priority_list:
                    target_list = [_priority_list[0]]
                    _log.info("[SUB_UNIT] %s: en_type_priority -> %s (character_type=%d)",
                              caster.name, target_list[0].name, getattr(target_list[0], 'character_type', 0))
                else:
                    target_list = [caster]
                    _log.info("[SUB_UNIT] %s: en_type_priority fallback -> self", caster.name)
            else:
                target_list = [caster]
                _log.info("[SUB_UNIT] %s: en_type_priority fallback -> self (no other ally)", caster.name)

        # 应用display_target_range限制（如TWO_PAWNS=2体）
        if target_count_limit > 1 and len(target_list) > target_count_limit:
            target_list = target_list[:target_count_limit]

        # 过滤死亡目标
        target_list = [t for t in target_list if t.is_alive]
        if not target_list:
            _log.info("[SUB_UNIT] %s: no valid target for sub_unit", caster.name)
            return None

        # Determine duration
        dur_type = getattr(effect, 'duration_type', None) or "action"
        duration = getattr(effect, 'duration', None) or 1
        if dur_type == "action":
            timing = AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value
        elif dur_type == "turn":
            timing = AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END.value
        else:
            timing = AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value

        import uuid
        sub_unit_name = effect_flags.get('sub_unit_name', 'SubUnit')
        caster_atk_snapshot = self.damage_service._calculate_final_stat(caster, "attack")
        _log.info("[SUB_UNIT_CREATE] %s: base_atk=%d, final_atk(snapshot)=%d (buffs=%d, atk_up=%d)",
                  caster.name, getattr(caster, 'attack', 0), caster_atk_snapshot,
                  len(caster.buffs),
                  sum(1 for b in caster.buffs
                      if b.effect_type == SkillEffectType.STATUS_ATTACK.value))

        # 解析add_status_to_attack中的value_tag为实际数值
        if add_status_info and add_status_info.get('value_tag'):
            _skill_id = self._current_skill_id
            _skill_level = caster.skill_levels.get(_skill_id, 1)
            _skill_meta = self.data_loader.get_skill_by_id(_skill_id)
            if _skill_meta:
                try:
                    _tag_values = self._resolver._resolve_template_tags(_skill_meta, _skill_level)
                    _resolved_val = _tag_values.get(add_status_info['value_tag'])
                    if _resolved_val is not None:
                        add_status_info = dict(add_status_info)  # copy to avoid mutating original
                        add_status_info['value'] = float(_resolved_val)
                        add_status_info.pop('value_tag', None)
                        _log.info("[SUB_UNIT] %s: resolved add_status_to_attack value_tag '%s' -> %.1f (Lv%d)",
                                  caster.name, add_status_info.get('value'), _skill_level)
                except Exception as _e:
                    _log.warning("[SUB_UNIT] %s: failed to resolve value_tag '%s': %s",
                                caster.name, add_status_info.get('value_tag'), _e)

        # apply_count: 对每个目标应用N个独立实例（如PS1/PS2的カムラッド×3）
        apply_count = int(effect_flags.get('apply_count', 1) or 1)
        if apply_count < 1:
            apply_count = 1

        # [GAME_BUG_SIMULATION] 技能「装いを新たに」(110050) 子機Ⅱ跨目标联动失效
        # 游戏内bug: 多个子機Ⅱ的持续时间仅看最先失效的单位，一方失效时另一方同时失效
        # 通过shared link_group_id将本次技能创建的所有子機Ⅱ关联，任一失效时级联移除其余
        # 原实现路径（无linked_expiry flag）保持不变，link_group_id为空字符串不影响原有逻辑
        linked_expiry = bool(effect_flags.get('linked_expiry', False))
        link_group_id = f"linked_subunit_{uuid.uuid4().hex[:8]}" if linked_expiry else ""

        applied_targets = []
        for target in target_list:
            for _ in range(apply_count):
                buff_id = f"{caster.unit_id}_SubUnit_{target.unit_id}_{uuid.uuid4().hex[:8]}"

                # 构造hit_limited_flags存储add_status_to_attack信息
                hlf = {}
                if add_status_info:
                    hlf['add_status_to_attack'] = add_status_info

                sub_unit_buff = BuffState(
                    buff_id=buff_id,
                    name=sub_unit_name,
                    effect_type=SkillEffectType.SUB_UNIT.value,
                    value=atk_pct,
                    duration=duration,
                    timing_type=timing,
                    source_unit_id=caster.unit_id,
                    source_skill_id=self._current_skill_id,
                    caster_attack=caster_atk_snapshot,
                    is_debuff=False,
                    is_stackable=True,  # SubUnit can coexist as multiple instances
                    sub_unit_hp=sub_unit_max_hp,
                    sub_unit_max_hp=sub_unit_max_hp,
                    hit_limited_flags=hlf,
                    sub_unit_link_group=link_group_id,
                )

                self.aura_service.add_aura(target, sub_unit_buff)
                self._newly_created_sub_unit_ids.add(buff_id)
                _log.info("[SUB_UNIT] %s -> %s: sub_unit '%s' applied, HP=%d/%d, atk_dmg=%.1f%%, dur=%d(%s), buff_id=%s, add_status=%s",
                          caster.name, target.name, sub_unit_name,
                          sub_unit_max_hp, sub_unit_max_hp, atk_pct, duration, dur_type, buff_id,
                          add_status_info.get('status') if add_status_info else 'none')
                # 每个独立 sub_unit 实例作为单独条目，叙事层按实例输出日志
                applied_targets.append({
                    "target": target.name,
                    "target_id": target.unit_id,
                    "sub_unit_name": sub_unit_name,
                    "sub_unit_hp": sub_unit_max_hp,
                    "sub_unit_max_hp": sub_unit_max_hp,
                    "atk_dmg_pct": atk_pct,
                    "duration": duration,
                    "dur_type": dur_type,
                })

        return {
            "effect_type": "sub_unit",
            "targets": applied_targets,
            "total_damage": 0,
        }

    def _apply_remove_shield(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """移除目标所有护盾buff和shield值（天崩等技能）"""
        rs_target_type = getattr(effect, 'target_type', 'enemy_single')
        if self.target_service:
            cached_targets = getattr(self, '_block_damage_targets', None)
            if cached_targets is not None and isinstance(cached_targets, dict) and rs_target_type in cached_targets:
                targets = list(cached_targets[rs_target_type])
            else:
                target_skill_obj = type('obj', (object,), {
                    'display_target_type': self._resolve_target_type(rs_target_type),
                    'display_target_range': self._resolve_target_range(rs_target_type),
                    'display_target_priority': None,
                    'target_type_name': rs_target_type,
                })()
                targets = self.target_service.select_targets(target_skill_obj, caster, battlefield)
        elif rs_target_type in ("self",):
            targets = [caster]
        else:
            targets = []
        removed_info = []
        for target in targets:
            if not target.is_alive:
                continue
            # 移除所有shield类型buff
            shield_buffs = [b for b in target.buffs
                           if b.effect_type in (SkillEffectType.SHIELD.value, "shield", "Shield")]
            removed_count = len(shield_buffs)
            removed_names = [getattr(b, 'name', b.effect_type) for b in shield_buffs]
            for b in shield_buffs:
                target.buffs.remove(b)
            # 清零shield值
            old_shield = target.shield
            old_physical = target.physical_shield
            old_en = target.en_shield
            target.shield = 0
            target.physical_shield = 0
            target.en_shield = 0
            _log.info("[REMOVE_SHIELD] %s: removed %d shield buffs, shield %d->0, physical_shield %d->0, en_shield %d->0",
                      target.name, removed_count, old_shield, old_physical, old_en)
            removed_info.append({
                "target_id": target.unit_id,
                "target_name": target.name,
                "removed_count": removed_count,
                "removed_names": removed_names,
            })
        return {"effect_type": "remove_shield", "targets": removed_info}

    def _apply_remove_sub_unit(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """移除目标所有sub_unit buff（如技能130136 PS1清除自身カムラッドⅠ/Ⅱ）"""
        rs_target_type = getattr(effect, 'target_type', 'self')
        if rs_target_type == "self":
            target_list = [caster]
        elif self.target_service:
            cached_targets = getattr(self, '_block_damage_targets', None)
            if cached_targets is not None and isinstance(cached_targets, dict) and rs_target_type in cached_targets:
                target_list = list(cached_targets[rs_target_type])
            else:
                target_skill_obj = type('obj', (object,), {
                    'display_target_type': self._resolve_target_type(rs_target_type),
                    'display_target_range': self._resolve_target_range(rs_target_type),
                    'display_target_priority': None,
                    'target_type_name': rs_target_type,
                })()
                target_list = self.target_service.select_targets(target_skill_obj, caster, battlefield)
        else:
            target_list = []

        removed_info = []
        for target in target_list:
            if not target.is_alive:
                continue
            sub_buffs = [b for b in target.buffs if b.effect_type == SkillEffectType.SUB_UNIT.value]
            removed_count = len(sub_buffs)
            removed_names = [getattr(b, 'name', 'SubUnit') for b in sub_buffs]
            for b in sub_buffs:
                target.buffs.remove(b)
            _log.info("[REMOVE_SUB_UNIT] %s: removed %d sub_unit buffs (names=%s)",
                      target.name, removed_count, removed_names)
            removed_info.append({
                "target_id": target.unit_id,
                "target_name": target.name,
                "removed_count": removed_count,
                "removed_names": removed_names,
            })
        return {"effect_type": "remove_sub_unit", "targets": removed_info}

    def _apply_remove_mark(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """移除指定名称的mark

        支持的flags:
        - mark_name: 要移除的mark名称
        - remove_all: 移除所有匹配的mark
        - remove_linked: 移除mark时联动移除linked_buff_id匹配的buff/debuff（包括buffs，不仅debuffs）
        - value: 移除指定数量的mark（如value=3移除3个）
        """
        effect_flags = getattr(effect, 'flags', None) or {}
        mark_name = effect_flags.get('mark_name', '')
        remove_all = effect_flags.get('remove_all', False)
        remove_linked = effect_flags.get('remove_linked', True)  # 默认联动移除
        # 支持value字段指定移除数量（如負けん気移除3个）
        remove_count = getattr(effect, 'value', None)
        if remove_count is None:
            remove_count = effect_flags.get('count', 0)
        try:
            remove_count = int(remove_count) if remove_count is not None else 0
        except (TypeError, ValueError):
            remove_count = 0

        cached_targets = getattr(self, '_block_damage_targets', None)
        if cached_targets is not None and isinstance(cached_targets, dict) and effect.target_type in cached_targets:
            targets = list(cached_targets[effect.target_type])
        else:
            targets = self.target_service.select_targets(
                type('obj', (object,), {
                    'display_target_type': self._resolve_target_type(effect.target_type),
                    'display_target_range': self._resolve_target_range(effect.target_type),
                    'display_target_priority': None,
                    'target_type_name': effect.target_type,
                })(),
                caster, battlefield,
            )

        # lowest_hp_priority: 按HP百分比升序排序
        if effect_flags.get('lowest_hp_priority') and targets:
            targets.sort(key=lambda u: u.current_hp / u.max_hp if u.max_hp > 0 else 0)

        # target_count: 限制目标数量
        target_count = effect_flags.get('target_count', 0)
        if target_count > 0 and len(targets) > target_count:
            targets = targets[:target_count]

        all_removed = []
        for target in targets:
            if not target.is_alive:
                continue

            removed = 0
            if remove_all:
                # 移除所有匹配名称的mark
                marks_to_remove = [b for b in target.debuffs + target.buffs
                                 if b.effect_type == SkillEffectType.MARK.value and b.name == mark_name]
                for m in marks_to_remove:
                    if m in target.debuffs:
                        target.debuffs.remove(m)
                    elif m in target.buffs:
                        target.buffs.remove(m)
                    removed += 1
                # 联动移除linked到该mark的buff/debuff
                if remove_linked:
                    self._remove_linked_buffs_by_mark(target, mark_name)
            elif remove_count > 0:
                # 移除指定数量的mark（如負けん気移除3个）
                for _ in range(remove_count):
                    _found = False
                    for lst in [target.debuffs, target.buffs]:
                        for b in lst:
                            if b.effect_type == SkillEffectType.MARK.value and b.name == mark_name:
                                lst.remove(b)
                                removed += 1
                                _found = True
                                break
                        if _found:
                            break
                    if not _found:
                        break  # 没有更多mark了
                # 每移除1个mark联动移除1个linked buff/debuff
                if remove_linked and removed > 0:
                    self._remove_linked_buffs_by_mark(target, mark_name, max_count=removed)
            else:
                # 移除1个mark
                for lst in [target.debuffs, target.buffs]:
                    for b in lst:
                        if b.effect_type == SkillEffectType.MARK.value and b.name == mark_name:
                            lst.remove(b)
                            removed = 1
                            break
                    if removed:
                        break
                # 同时移除linked到该mark的buff/debuff（仅移除1个mark时也联动）
                if remove_linked and removed:
                    self._remove_linked_buffs_by_mark(target, mark_name, max_count=1)

            _log.info("[REMOVE_MARK] %s: removed %d mark(s) '%s'", target.name, removed, mark_name)
            all_removed.append({
                "target_id": target.unit_id,
                "mark_name": mark_name,
                "removed_count": removed,
            })

        return {
            "effect_type": "remove_mark",
            "targets": all_removed,
            "mark_name": mark_name,
        }

    def _remove_linked_buffs_by_mark(self, target: UnitState, mark_name: str, max_count: int = 0) -> None:
        """联动移除linked_buff_id匹配mark_name的buff/debuff

        max_count > 0 时只移除指定数量，max_count=0 时移除全部
        """
        removed = 0
        # 移除linked的buffs
        linked_buffs = [b for b in target.buffs
                       if getattr(b, 'linked_buff_id', '') == mark_name]
        for lb in linked_buffs:
            if max_count > 0 and removed >= max_count:
                break
            target.buffs.remove(lb)
            removed += 1
            _log.info("[LINKED_MARK] %s: buff %s removed (linked to mark %s removal)",
                      target.name, lb.name, mark_name)
        # 移除linked的debuffs
        if max_count == 0 or removed < max_count:
            linked_debuffs = [d for d in target.debuffs
                            if getattr(d, 'linked_buff_id', '') == mark_name]
            for ld in linked_debuffs:
                if max_count > 0 and removed >= max_count:
                    break
                target.debuffs.remove(ld)
                removed += 1
                _log.info("[LINKED_MARK] %s: debuff %s removed (linked to mark %s removal)",
                          target.name, ld.name, mark_name)

    def _apply_cover(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """
        援护效果：从预扫描的攻击目标中选择距离最近的友方进行援护
        - 优先使用预扫描的cover候选（按block顺序排列的被攻击友方）
        - 如果没有预扫描结果，回退到_current_attack_targets
        - cover_target指向被保护的友方（即攻击目标之一）
        - 当该友方被攻击时，援护者替代承受伤害
        - 多目标时选择距离最近的被攻击友方，同距离优先前列/左列
        """
        effect_flags = getattr(effect, 'flags', None) or {}

        # 优先从预扫描的候选中选择cover目标
        candidates = getattr(self, '_pre_scanned_cover_candidates', [])
        if not candidates:
            # 回退：从_current_attack_targets中选择
            candidates = [t for t in getattr(self, '_current_attack_targets', []) if t.is_alive]

        # 过滤掉B自己（caster是PS持有者）
        covered_candidates = [t for t in candidates if t.unit_id != caster.unit_id and t.is_alive]

        if not covered_candidates:
            _log.info("[COVER] %s: no ally in attack targets to cover, skip", caster.name)
            return None

        # 选择距离最近的被攻击友方
        def get_distance(target: UnitState) -> tuple:
            from src.entities_v2.enums import Position
            caster_pos = caster.position
            target_pos = target.position
            pos_scores = {
                Position.ALLY_LEFT_FRONT: (0, 0), Position.ALLY_CENTER_FRONT: (0, 1), Position.ALLY_RIGHT_FRONT: (0, 2),
                Position.ALLY_LEFT_BACK: (1, 0), Position.ALLY_CENTER_BACK: (1, 1), Position.ALLY_RIGHT_BACK: (1, 2),
                Position.ENEMY_LEFT_FRONT: (0, 0), Position.ENEMY_CENTER_FRONT: (0, 1), Position.ENEMY_RIGHT_FRONT: (0, 2),
                Position.ENEMY_LEFT_BACK: (1, 0), Position.ENEMY_CENTER_BACK: (1, 1), Position.ENEMY_RIGHT_BACK: (1, 2),
            }
            caster_info = pos_scores.get(caster_pos, (2, 2))
            target_info = pos_scores.get(target_pos, (2, 2))
            distance = (caster_info[0] - target_info[0]) ** 2 + (caster_info[1] - target_info[1]) ** 2
            # 同距离时优先前排、左列
            is_front = 0 if 'FRONT' in target_pos.name else 1
            pos_order = target_info[1]
            return (distance, is_front, pos_order)

        covered_candidates.sort(key=get_distance)
        selected_target = covered_candidates[0]

        # 设置cover_target为被保护的友方unit_id
        caster.cover_target = selected_target.unit_id
        caster.cover_skill_id = self._current_skill_id

        _log.info("[COVER] %s: covering %s (distance=%d, position=%s)",
                  caster.name, selected_target.name,
                  get_distance(selected_target)[0], selected_target.position)

        return {
            "effect_type": "cover",
            "target_id": selected_target.unit_id,
            "caster_id": caster.unit_id,
        }

    def _apply_guard(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """
        护卫效果：根据duration_type区分新旧guard机制
        - duration_type="attacker_action"（130034新版cover附带）: 使用新版特殊机制，设置unit.guard_active
        - 其他（130009等旧版guard）: 使用旧版buff机制，通过buff系统添加guard buff
        """
        effect_flags = getattr(effect, 'flags', None) or {}
        duration_type = getattr(effect, 'duration_type', None)

        # 获取guard值（从value_tag解析）
        guard_value = 0.0
        value_tag = getattr(effect, 'value_tag', None)
        if value_tag == "guard":
            # 从技能数据中解析guard值
            skill_id = self._current_skill_id
            meta = self.data_loader.get_skill_by_id(skill_id)
            if meta:
                skill_level = caster.skill_levels.get(skill_id, 1)
                tag_values = self._resolver._resolve_template_tags(meta, skill_level)
                guard_value = tag_values.get('guard', 0.0)

        if guard_value <= 0:
            _log.info("[GUARD] %s: guard value is %f, skip", caster.name, guard_value)
            return None

        # 新版guard（cover附带，duration_type="attacker_action"）：使用特殊机制，不添加buff
        if duration_type == "attacker_action":
            caster.guard_rate = guard_value
            caster.guard_active = True
            _log.info("[GUARD] %s: guard_rate=%.1f%% activated (special mechanism, not a buff)", caster.name, guard_value)
            return {
                "effect_type": "guard",
                "guard_rate": guard_value,
                "caster_id": caster.unit_id,
            }

        # 旧版guard（130009等）：通过buff系统添加guard buff
        # guard buff会在受攻击后自动消失（attack_limited=1在buff消耗时处理）
        _log.info("[GUARD] %s: adding guard buff with rate=%.1f%% (legacy buff mechanism)", caster.name, guard_value)
        # _apply_aura は effect.value を参照するため、解決済みの guard_value を設定する
        # （effect.value は null だが value_tag="guard" で template_tags から解決される）
        effect.value = guard_value
        return self._apply_aura(caster, effect, battlefield, is_debuff=False)

    def _apply_modify_pp(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        """PP増減効果 (modify_pp): 暴撃時PP回復などのon_crit blockで使用"""
        value = int(getattr(effect, 'value', 0) or 0)
        if value == 0:
            _log.info("[MODIFY_PP] %s: value=0, skip", caster.name)
            return None

        old_pp = caster.current_pp
        if value > 0:
            if self.resource_service:
                self.resource_service.restore_pp(caster, value)
            else:
                cap = caster.initial_passive_point
                caster.current_pp = min(caster.current_pp + value, cap)
        else:
            actual = min(caster.current_pp, -value)
            caster.current_pp -= actual

        _log.info("[MODIFY_PP] %s: PP %d -> %d (delta=%d)",
                  caster.name, old_pp, caster.current_pp, caster.current_pp - old_pp)
        return {
            "effect_type": "modify_pp",
            "caster_id": caster.unit_id,
            "old_pp": old_pp,
            "new_pp": caster.current_pp,
            "delta": caster.current_pp - old_pp,
        }

    def _has_active_cover(self, battlefield: BattlefieldState) -> bool:
        """检查战场上是否有活跃的cover状态"""
        for unit in battlefield.get_all_units():
            if unit.is_alive and unit.cover_target is not None:
                return True
        return False

    def _apply_cover_debuff_replacement(self, caster: UnitState, targets: List[UnitState],
                                         battlefield: BattlefieldState) -> List[UnitState]:
        """cover替换：如果cover生效，debuff目标也应替换为cover者

        当技能对目标施加debuff（包括aura debuff、add_status、remove_ap/pp/ep等）时，
        如果目标正被cover保护，则debuff应施加到cover者身上。
        """
        if not self._has_active_cover(battlefield):
            return targets
        ally_team = battlefield.friend_team if caster.side != battlefield.friend_team[0].side else battlefield.enemy_team
        result = list(targets)
        # 记录cover替换映射：coverer_unit_id -> original_target_name
        if not hasattr(self, '_cover_debuff_replacements'):
            self._cover_debuff_replacements = {}
        for ally in ally_team:
            if ally.is_alive and ally.cover_target is not None:
                for i, t in enumerate(result):
                    if t.unit_id == ally.cover_target:
                        # 记录替换信息供叙事使用
                        self._cover_debuff_replacements[ally.unit_id] = t.name
                        result[i] = ally
                        _log.info("[COVER_DEBUFF] %s: replacing debuff target %s with coverer %s",
                                  caster.name, t.name, ally.name)
                        break
        return result

    def _apply_cover_to_targets(self, attacker: UnitState, targets: List[UnitState], battlefield: BattlefieldState) -> None:
        """
        应用cover目标替换：
        - 如果被攻击目标中有设置了cover_target的友方单位，将其替换为cover者
        - cover者额外承受一份伤害（如果cover者自身也是攻击目标，则为双份；如果不是，则为一份）
        - 替换C为B时，标记这是"cover伤害"（享受guard）
        - 如果B本身也在目标列表中，B的直接伤害不享受guard
        - 使用_cover_replaced_indices记录哪些target index是cover替换（用于区分guard）
        """
        # 获取被攻击方的队友列表
        ally_team = battlefield.friend_team if attacker.side != battlefield.friend_team[0].side else battlefield.enemy_team

        # 初始化cover替换索引集合
        if not hasattr(self, '_cover_replaced_indices'):
            self._cover_replaced_indices = set()
        self._cover_replaced_indices = set()  # 每次调用重置

        # 找出所有设置了cover_target的己方单位
        cover_info_list = []
        for ally in ally_team:
            if ally.is_alive and ally.cover_target is not None:
                # 检查cover_target是否还在当前攻击目标列表中
                covered_target = None
                covered_idx = -1
                for i, t in enumerate(targets):
                    if t.unit_id == ally.cover_target and t.is_alive:
                        covered_target = t
                        covered_idx = i
                        break
                if covered_target is not None:
                    cover_info_list.append({
                        'coverer': ally,
                        'covered': covered_target,
                        'covered_idx': covered_idx,
                        'is_coverer_also_target': any(t.unit_id == ally.unit_id for t in targets)
                    })
                    _log.info("[COVER] %s covers %s at idx=%d (is_self_target=%s)",
                              ally.name, covered_target.name, covered_idx, cover_info_list[-1]['is_coverer_also_target'])

        if not cover_info_list:
            return

        # 应用cover目标替换
        for info in cover_info_list:
            coverer = info['coverer']
            covered = info['covered']
            covered_idx = info['covered_idx']

            # 替换目标列表中的目标
            targets[covered_idx] = coverer
            # 记录该index是cover替换
            self._cover_replaced_indices.add(covered_idx)
            _log.info("[COVER_APPLY] %s: replacing target %s(idx=%d) with coverer %s",
                      attacker.name, covered.name, covered_idx, coverer.name)

            # 记录cover信息，用于后续伤害计算和debuff替换
            # 注意：每个coverer只能cover一个目标
            if not hasattr(self, '_cover_info'):
                self._cover_info = {}
            self._cover_info[coverer.unit_id] = {
                'original_target': covered,
                'is_self_also_target': info['is_coverer_also_target'],
                'guard_rate': coverer.guard_rate if coverer.guard_active else 0.0,
                'covered_unit_id': covered.unit_id,  # 被替换的原始目标ID，用于debuff替换
            }

    def _apply_lifesteal(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        recent_dmg = getattr(self, '_most_recent_damage', 0)
        if recent_dmg <= 0:
            _log.info("[LIFESTEAL] %s: no recent damage, skip", caster.name)
            return None

        cure_pct = effect.value or 0
        heal_amount = int(recent_dmg * cure_pct / 100)
        hp_before = caster.current_hp
        effective_max_hp = self.damage_service._calculate_final_stat(caster, "max_hp")
        caster.current_hp = min(effective_max_hp, caster.current_hp + heal_amount)
        actual_heal = caster.current_hp - hp_before

        _log.info("[LIFESTEAL] %s: healed %d (%.0f%% of %d dmg), hp %d→%d",
                  caster.name, actual_heal, cure_pct, recent_dmg, hp_before, caster.current_hp)

        # 计分追踪：记录吸血治疗
        tracker = getattr(battlefield, 'scoring_tracker', None)
        if tracker is not None and actual_heal > 0:
            caster_side = "ally" if caster.side.value == "ally" else "enemy"
            tracker.record_heal(
                source_id=caster.unit_id, source_name=caster.name, source_side=caster_side,
                target_id=caster.unit_id, target_name=caster.name, target_side=caster_side,
                heal_amount=actual_heal,
            )

        return {
            "effect_type": "lifesteal",
            "heal_amount": actual_heal,
            "damage_based_on": recent_dmg,
            "cure_pct": cure_pct,
            "hp_before": hp_before,
            "hp_after": caster.current_hp,
        }

    def _apply_shield_from_damage(self, caster: UnitState, effect, battlefield: BattlefieldState) -> Optional[Dict]:
        recent_dmg = getattr(self, '_most_recent_damage', 0)
        if recent_dmg <= 0:
            _log.info("[SHIELD_FROM_DMG] %s: no recent damage, skip", caster.name)
            return None

        shield_pct = effect.value or 0
        shield_value = int(recent_dmg * shield_pct / 100)
        caster.shield += shield_value

        dur = getattr(effect, 'duration', None)
        if dur is None:
            dur = -1

        dur_type = getattr(effect, 'duration_type', None) or "action"
        if dur_type == "action":
            timing = AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END.value
        else:
            timing = AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END.value

        mapped_effect_type = _JSON_EFFECT_TO_ENUM.get(effect.effect_type, effect.effect_type)
        mapped_effect_type = _MASTERDATA_STATUS_MAP.get(effect.effect_type, mapped_effect_type)

        aura = BuffState(
            buff_id=f"{caster.unit_id}_{mapped_effect_type}_{caster.unit_id}",
            name=mapped_effect_type,
            effect_type=mapped_effect_type,
            value=shield_value,
            duration=dur,
            timing_type=timing,
            source_unit_id=caster.unit_id,
            caster_attack=self.damage_service._calculate_final_stat(caster, "attack"),
            is_debuff=False,
            shield_amount=shield_value,
        )
        self.aura_service.add_aura(caster, aura)

        _log.info("[SHIELD_FROM_DMG] %s: +shield %d (%.0f%% of %d dmg), total=%d",
                  caster.name, shield_value, shield_pct, recent_dmg, caster.shield)

        return {
            "effect_type": "shield_from_damage",
            "shield_value": shield_value,
        }