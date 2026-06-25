#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
战术演习模式控制器
src/combat_v2/tactical_exercise_controller.py

职责：
- 管理战术演习模式的特殊战斗逻辑
- 敌方单位被击败后自动复活至满血，阶段+1，属性增长
- 复活时清除所有buff/debuff，保持AP/PP/EP不变
"""

import math
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

from ..entities_v2.battlefield_state import BattlefieldState
from ..entities_v2.unit_state import UnitState, BuffState
from ..entities_v2.enums import Side, Position, SkillEffectType

from .battle_flow_controller import BattleFlowController, BattleConfig
from .battle_logger import battle_logger
from .scoring_tracker import ScoringTracker, BattleScoreResult

_log = battle_logger()

# 敌方站位映射：1-6 → Position
ENEMY_POSITION_MAP = {
    1: Position.ENEMY_LEFT_FRONT,
    2: Position.ENEMY_CENTER_FRONT,
    3: Position.ENEMY_RIGHT_FRONT,
    4: Position.ENEMY_LEFT_BACK,
    5: Position.ENEMY_CENTER_BACK,
    6: Position.ENEMY_RIGHT_BACK,
}


class TacticalExerciseController(BattleFlowController):
    """战术演习模式控制器"""

    def __init__(self, battlefield: BattlefieldState, config: Optional[BattleConfig] = None,
                 data_loader: Any = None, narrative: Any = None):
        super().__init__(battlefield, config, data_loader, narrative)
        self._stage = 0  # 当前阶段数（从0开始）
        self._base_stats: Dict[str, Dict[str, float]] = {}  # 阶段0基础属性 {unit_id: {hp, atk, def, spd, crit}}
        self._total_stages_cleared = 0  # 总共清除的阶段数
        self._is_tactical_exercise = True
        self._pending_resurrection_narrative = []  # 延迟输出的复活叙事数据
        self.skill_service._tactical_exercise_mode = True  # 战术演习模式：延迟阵亡判定

        # 初始化计分追踪器
        self._scoring_tracker = ScoringTracker()
        self.battlefield.scoring_tracker = self._scoring_tracker

        # 记录每个敌方单位的阶段0属性
        for unit in self.battlefield.enemy_team:
            self._base_stats[unit.unit_id] = {
                "hp": float(unit.max_hp),
                "attack": float(unit.attack),
                "defense": float(unit.defense),
                "speed": float(unit.speed),
                "crit_rate": float(unit.crit_rate),
            }
            _log.info("[TACTICAL_EX] 敌方 %s 阶段0属性: HP=%d ATK=%d DEF=%d SPD=%d CRIT=%.4f",
                      unit.name, unit.max_hp, unit.attack, unit.defense, unit.speed, unit.crit_rate)

    def _check_battle_end(self) -> bool:
        """战术演习：仅当我方全灭时战斗结束"""
        alive_friends = [u for u in self.battlefield.friend_team if u.is_alive]
        if not alive_friends:
            _log.info("[BATTLE] ============ 战术演习结束：我方全灭 ============")
            return True
        return False

    def _execute_unit_action(self, unit: UnitState, turn: int) -> None:
        """执行单位行动，并处理敌方复活逻辑"""
        # 调用父类执行行动（复活已通过_on_deaths_resolved钩子在触发器流程中处理）
        super()._execute_unit_action(unit, turn)

        # 安全网：检查是否有敌方单位在PS技能执行期间被击败但未被复活
        # （例如PS连锁击杀的情况）
        for enemy in self.battlefield.enemy_team:
            if not enemy.is_alive:
                self._resurrect_enemy(enemy)
                # 只有在本轮初始行动轴中的单位才可重新加入行动轴
                # 复活后EP满/AP>0但本轮初始不在行动轴中的单位，等下一轮再行动
                if (enemy.current_ap > 0 or self.action_axis._is_ep_full(enemy)):
                    if enemy.unit_id not in self._acted_this_round and enemy.unit_id in self._round_eligible_ids:
                        self.action_axis.action_axis = [u for u in self.action_axis.action_axis if u.unit_id != enemy.unit_id]
                        self.action_axis.action_axis.append(enemy)
                        self.action_axis.resort_action_axis()
                        _log.info("[TACTICAL_EX] %s 已重新加入行动轴", enemy.name)
                    else:
                        _log.info("[TACTICAL_EX] %s 不重新加入行动轴 (acted=%s, eligible=%s)",
                                  enemy.name, enemy.unit_id in self._acted_this_round,
                                  enemy.unit_id in self._round_eligible_ids)

    def _on_deaths_resolved(self, newly_dead: list) -> None:
        """击杀触发器处理完毕后，复活阵亡的敌方单位。

        在 PAWN_DIED/PAWN_KILLED 等触发器之后、AFTER_ALLY_ATTACKED 之前调用，
        确保复活后的单位（已清除眩晕等debuff）能正常响应后续触发器。
        叙事输出延迟到 _on_death_narrative_complete 中，确保在死亡通知之后。
        """
        self._pending_resurrection_narrative = []
        for enemy in newly_dead:
            if enemy.side == Side.ENEMY and not enemy.is_alive:
                narrative_data = self._resurrect_enemy(enemy, skip_narrative=True)
                if narrative_data:
                    self._pending_resurrection_narrative.append(narrative_data)
                # 将复活的敌方重新加入行动轴（如果它可以行动且在本轮初始行动轴中且未行动过）
                if enemy.current_ap > 0 or self.action_axis._is_ep_full(enemy):
                    if enemy.unit_id not in self._acted_this_round and enemy.unit_id in self._round_eligible_ids:
                        # 先移除行动轴中已有的同unit_id条目，避免重复
                        self.action_axis.action_axis = [u for u in self.action_axis.action_axis if u.unit_id != enemy.unit_id]
                        self.action_axis.action_axis.append(enemy)
                        self.action_axis.resort_action_axis()
                        _log.info("[TACTICAL_EX] %s 已重新加入行动轴", enemy.name)
                    else:
                        _log.info("[TACTICAL_EX] %s 不重新加入行动轴 (acted=%s, eligible=%s)",
                                  enemy.name, enemy.unit_id in self._acted_this_round,
                                  enemy.unit_id in self._round_eligible_ids)

    def _on_death_narrative_complete(self, newly_dead: list) -> None:
        """死亡通知输出完毕后，输出复活（阶段提升）的叙事日志。"""
        for narrative_data in self._pending_resurrection_narrative:
            if self.narrative:
                self.narrative.tactical_exercise_stage_up(**narrative_data)
        self._pending_resurrection_narrative = []

    def _resurrect_enemy(self, enemy: UnitState, skip_narrative: bool = False) -> Optional[Dict]:
        """
        复活敌方单位：满血、阶段+1、属性增长、清除所有buff/debuff

        阶段增量以百分比buff形式存储（is_memory_buff=True），与PS技能buff一起参与
        Base * (1 + Sum%) 计算，确保百分比buff以阶段0基础属性为基准。

        Args:
            enemy: 被击败的敌方单位
            skip_narrative: 如果为True，跳过叙事输出并返回叙事数据字典供延迟输出

        Returns:
            当skip_narrative=True时，返回叙事数据字典；否则返回None
        """
        self._stage += 1
        self._total_stages_cleared += 1
        n = self._stage

        base = self._base_stats.get(enemy.unit_id)
        if not base:
            _log.warning("[TACTICAL_EX] 未找到敌方 %s 的基础属性，使用当前属性作为阶段0", enemy.name)
            base = {
                "hp": float(enemy.max_hp),
                "attack": float(enemy.attack),
                "defense": float(enemy.defense),
                "speed": float(enemy.speed),
                "crit_rate": float(enemy.crit_rate),
            }
            self._base_stats[enemy.unit_id] = base

        # 计算阶段n的属性增量百分比
        # ATK/DEF/HP增量: 0.2*n + 0.005*max(0,n-3)*max(0,n-2)
        # 从阶段21开始，HP/ATK/DEF不再提升，维持在阶段20的数值
        n_for_hp_atk_def = min(n, 20)
        atk_def_pct = 0.2 * n_for_hp_atk_def + 0.005 * max(0, n_for_hp_atk_def - 3) * max(0, n_for_hp_atk_def - 2)
        # SPD增量: 0.05*n （正常提升，不受阶段20上限影响）
        spd_pct = 0.05 * n

        # 计算阶段n的有效属性值（用于叙事日志显示）
        stat_multiplier = 1.0 + atk_def_pct
        new_hp = math.floor(base["hp"] * stat_multiplier)
        new_attack = math.floor(base["attack"] * stat_multiplier)
        new_defense = math.floor(base["defense"] * stat_multiplier)
        new_speed = math.floor(base["speed"] * (1.0 + spd_pct))
        new_crit_rate = base["crit_rate"] + 0.01 * n

        old_hp = enemy.max_hp
        old_atk = self.damage_service._calculate_final_stat(enemy, "attack")
        old_def = self.damage_service._calculate_final_stat(enemy, "defense")
        old_spd = self.damage_service._calculate_final_stat(enemy, "speed")
        old_crit = enemy.crit_rate

        # 保存当前的AP/PP/EP
        saved_ap = enemy.current_ap
        saved_pp = enemy.current_pp
        saved_ep = enemy.current_ep

        # 清除所有buff，保留回忆卡debuff(is_memory_buff=True)
        # 注：回忆卡debuff由回忆卡施加，跨阶段应保留；阶段增量buff后面会重新添加
        buffs_cleared = len(enemy.buffs)
        debuffs_to_remove = [d for d in enemy.debuffs if not d.is_memory_buff]
        debuffs_cleared = len(debuffs_to_remove)
        enemy.buffs.clear()
        enemy.debuffs = [d for d in enemy.debuffs if d.is_memory_buff]

        # 重置异常状态标志位（眩晕/冻结等由debuff驱动，debuff已清除，标志位也需同步）
        enemy.is_stunned = False
        enemy.is_frozen = False

        # 恢复ATK/DEF/SPD为阶段0基础值（max_hp/crit_rate直接修改）
        enemy.attack = int(base["attack"])
        enemy.defense = int(base["defense"])
        enemy.speed = int(base["speed"])

        # max_hp直接修改（太多地方直接读取unit.max_hp）
        enemy.max_hp = new_hp
        enemy.current_hp = new_hp
        enemy.crit_rate = new_crit_rate

        # 添加阶段增量百分比buff（is_memory_buff=True，无条件叠加）
        # 这些buff与PS技能buff一起参与 Base * (1 + Sum%) 计算
        stage_buffs = [
            (SkillEffectType.STATUS_ATTACK.value, atk_def_pct * 100, "阶段增量ATK"),
            (SkillEffectType.STATUS_DEFENSE.value, atk_def_pct * 100, "阶段增量DEF"),
            (SkillEffectType.STATUS_SPEED.value, spd_pct * 100, "阶段增量SPD"),
        ]
        for effect_type, value, name in stage_buffs:
            buff = BuffState(
                buff_id=f"stage_{n}_{effect_type}_{enemy.unit_id}",
                name=name,
                effect_type=effect_type,
                value=value,
                duration=-1,  # 永久
                timing_type=0,
                source_unit_id=enemy.unit_id,
                source_skill_id=0,
                is_debuff=False,
                value_tag=0,  # 百分比
                is_memory_buff=True,  # 无条件叠加，不被non-stackable规则覆盖
            )
            enemy.buffs.append(buff)

        # 恢复AP/PP/EP（不变）
        enemy.current_ap = saved_ap
        enemy.current_pp = saved_pp
        enemy.current_ep = saved_ep

        # 标记为存活
        enemy.is_alive = True
        enemy.is_death_notified = False

        _log.info("[TACTICAL_EX] ==================================================")
        _log.info("[TACTICAL_EX] %s 进入阶段 %d！", enemy.name, n)
        _log.info("[TACTICAL_EX] HP:  %d -> %d (x%.4f)", old_hp, new_hp, stat_multiplier)
        _log.info("[TACTICAL_EX] ATK: %d -> %d (x%.4f) [base=%d + buff=%.1f%%]",
                  old_atk, new_attack, stat_multiplier, int(base["attack"]), atk_def_pct * 100)
        _log.info("[TACTICAL_EX] DEF: %d -> %d (x%.4f) [base=%d + buff=%.1f%%]",
                  old_def, new_defense, stat_multiplier, int(base["defense"]), atk_def_pct * 100)
        _log.info("[TACTICAL_EX] SPD: %d -> %d (x%.4f) [base=%d + buff=%.1f%%]",
                  old_spd, new_speed, 1.0 + spd_pct, int(base["speed"]), spd_pct * 100)
        _log.info("[TACTICAL_EX] CRIT: %.4f -> %.4f (+%.4f)", old_crit, new_crit_rate, 0.01 * n)
        _log.info("[TACTICAL_EX] 清除 Buff x%d, Debuff x%d", buffs_cleared, debuffs_cleared)
        _log.info("[TACTICAL_EX] AP=%d PP=%d EP=%d (保持不变)", saved_ap, saved_pp, saved_ep)
        _log.info("[TACTICAL_EX] ==================================================")

        # 叙事日志
        narrative_data = {
            "unit_name": self._get_display_name(enemy),
            "stage": n,
            "new_hp": new_hp, "new_atk": new_attack, "new_def": new_defense,
            "new_spd": new_speed, "new_crit": new_crit_rate,
            "old_hp": old_hp, "old_atk": old_atk, "old_def": old_def,
            "old_spd": old_spd, "old_crit": old_crit,
            "buffs_cleared": buffs_cleared, "debuffs_cleared": debuffs_cleared,
        }
        if skip_narrative:
            return narrative_data
        if self.narrative:
            self.narrative.tactical_exercise_stage_up(**narrative_data)
        return None

    def execute_battle(self) -> Dict[str, Any]:
        """执行战术演习战斗，返回包含阶段信息的结果"""
        result = super().execute_battle()

        # 添加阶段信息
        result["stages_cleared"] = self._total_stages_cleared
        result["final_stage"] = self._stage
        result["is_tactical_exercise"] = True

        # 构建得分结果
        battle_result_str = result.get("result", "UNKNOWN")
        if result.get("winner") == "FRIEND":
            battle_result_str = "WIN"
        elif result.get("winner") == "ENEMY":
            battle_result_str = "LOSS"

        score_result = self._scoring_tracker.build_result(
            stages_cleared=self._total_stages_cleared,
            total_turns=result["total_turns"],
            battle_result=battle_result_str,
        )
        result["score"] = score_result.to_dict()
        result["score_result"] = score_result

        # 在叙事日志中输出计分统计
        if self.narrative:
            self.narrative.tactical_exercise_score(score_result)

        _log.info("[TACTICAL_EX] 战术演习完成：共清除 %d 个阶段", self._total_stages_cleared)
        _log.info("[TACTICAL_EX] 得分: %d (伤害=%d 回血=%d)",
                  score_result.total_score,
                  score_result.total_damage_to_enemies,
                  score_result.enemy_healing_received)

        return result

    @property
    def stage(self) -> int:
        return self._stage

    @property
    def total_stages_cleared(self) -> int:
        return self._total_stages_cleared