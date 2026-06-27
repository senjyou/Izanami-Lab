#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
复合战术演习模式控制器
src/combat_v2/composite_tactic_controller.py

职责：
- 管理3支队伍依次出战的战斗流程
- 每队最多5回合，团灭或打完5回合后切换下一队
- 敌方HP跨队伍继承，但buff/debuff/AP/PP/EP不继承（重置为初始值）
- 仅BOSS(Enemy1)死亡后复活并增强，小怪不复活
- BOSS复活阶段跨队伍继承
- 分数 = 三队对BOSS造成的总伤害（含溢出）
- 角色复用惩罚：重复1次HP/ATK/DEF×50%，重复2次HP/ATK/DEF=1
"""

import math
from typing import Optional, Dict, Any, List

from ..entities_v2.battlefield_state import BattlefieldState
from ..entities_v2.unit_state import UnitState, BuffState
from ..entities_v2.enums import Side, Position, SkillEffectType

from .battle_flow_controller import BattleFlowController, BattleConfig
from .battle_logger import battle_logger
from .scoring_tracker import ScoringTracker

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


class CompositeTacticController(BattleFlowController):
    """复合战术演习模式控制器"""

    def __init__(self, battlefield: BattlefieldState, config: Optional[BattleConfig] = None,
                 data_loader: Any = None, narrative: Any = None,
                 teams: Optional[List[List[UnitState]]] = None,
                 team_memories: Optional[List[List[Any]]] = None,
                 boss_unit_id: str = ""):
        """
        Args:
            battlefield: 战场状态（enemy_team应已设置好，friend_team将被替换为第1队）
            teams: 3支队伍的单位列表
            team_memories: 3支队伍的回忆卡列表
            boss_unit_id: BOSS单位的unit_id（用于追踪伤害）
        """
        super().__init__(battlefield, config or BattleConfig(max_turns=5), data_loader, narrative)

        self._teams = teams or []
        self._team_memories = team_memories or [[], [], []]
        self._boss_unit_id = boss_unit_id
        self._current_team_index = 0

        # BOSS复活阶段（跨队伍继承）
        self._boss_stage = 0
        self._boss_base_stats: Dict[str, float] = {}  # BOSS阶段0基础属性
        self._boss_killed_count = 0

        # 分数追踪
        self._boss_damage_total = 0
        self._team_results: List[Dict] = []
        self._enemy_hp_at_team_start = 0  # 全体敌方HP总和（队伍开始时）
        self._revival_max_hp_list: List[int] = []  # 本次队伍战斗中BOSS每次复活的最大HP
        self._enemy_damage_snapshot: Dict[str, int] = {}  # 敌方单位damage_taken_total快照（队伍开始时）
        self._heal_snapshot: Dict[str, int] = {}  # 友方单位hp_healed快照（队伍开始时，取自ScoringTracker）

        # 标记
        self._is_composite_tactic = True
        self.skill_service._tactical_exercise_mode = True  # 延迟阵亡判定
        self._pending_resurrection_narrative = []  # 延迟输出的BOSS复活叙事数据

        # 记录BOSS阶段0基础属性
        boss = self._find_boss()
        if boss:
            self._boss_base_stats = {
                "hp": float(boss.max_hp),
                "attack": float(boss.attack),
                "defense": float(boss.defense),
                "speed": float(boss.speed),
                "crit_rate": float(boss.crit_rate),
            }
            _log.info("[COMPOSITE_TACTIC] BOSS %s 阶段0属性: HP=%d ATK=%d DEF=%d SPD=%d CRIT=%.4f",
                      boss.name, boss.max_hp, boss.attack, boss.defense, boss.speed, boss.crit_rate)

        # 记录敌方初始AP/PP/EP（用于队伍切换时重置）
        self._enemy_initial_resources: Dict[str, Dict] = {}
        for enemy in self.battlefield.enemy_team:
            self._enemy_initial_resources[enemy.unit_id] = {
                "ap": enemy.current_ap,
                "pp": enemy.current_pp,
                "ep": enemy.current_ep,
            }

        # 角色复用统计
        self._character_usage: Dict[int, int] = {}  # character_id → 出现次数
        for team in self._teams:
            seen_in_team = set()
            for unit in team:
                cid = getattr(unit, "character_id", None)
                if cid is not None and cid not in seen_in_team:
                    seen_in_team.add(cid)
                    self._character_usage[cid] = self._character_usage.get(cid, 0) + 1

    def _find_boss(self) -> Optional[UnitState]:
        """查找BOSS单位"""
        for enemy in self.battlefield.enemy_team:
            if enemy.unit_id == self._boss_unit_id:
                return enemy
        # 如果没找到，返回第一个敌人作为BOSS
        if self.battlefield.enemy_team:
            return self.battlefield.enemy_team[0]
        return None

    # ════════════════════════════════════════════════════════════════════════════
    # 战斗主流程
    # ════════════════════════════════════════════════════════════════════════════

    def execute_battle(self) -> Dict[str, Any]:
        """执行复合战术演习：3队依次出战"""
        _log.info("[COMPOSITE_TACTIC] ============ 复合战术演习开始 ============")
        _log.info("[COMPOSITE_TACTIC] 共 %d 支队伍", len(self._teams))

        # 敌方元素协同（仅一次）
        from .services.element_synergy import apply_element_synergy
        apply_element_synergy(self.battlefield.enemy_team, self.narrative)

        # 组队属性加成已直接修改BOSS基础属性，重新记录阶段0基础属性为加成后的值
        # 这样BOSS复活时使用的基础属性包含组队加成，确保阶段增量乘区基于加成后的基础值
        boss_after_synergy = self._find_boss()
        if boss_after_synergy:
            self._boss_base_stats = {
                "hp": float(boss_after_synergy.max_hp),
                "attack": float(boss_after_synergy.attack),
                "defense": float(boss_after_synergy.defense),
                "speed": float(boss_after_synergy.speed),
                "crit_rate": float(boss_after_synergy.crit_rate),
            }
            _log.info("[COMPOSITE_TACTIC] BOSS %s 组队加成后阶段0属性: HP=%d ATK=%d DEF=%d SPD=%d CRIT=%.4f",
                      boss_after_synergy.name, boss_after_synergy.max_hp, boss_after_synergy.attack,
                      boss_after_synergy.defense, boss_after_synergy.speed, boss_after_synergy.crit_rate)

        # 敌方战斗开始触发（仅一次）
        self.skill_service.set_battlefield(self.battlefield)

        self.battlefield.current_trigger_phase = None

        # 逐队战斗
        for team_index in range(len(self._teams)):
            self._current_team_index = team_index
            _log.info("[COMPOSITE_TACTIC] ==================================================")
            _log.info("[COMPOSITE_TACTIC] 队伍 %d 出战", team_index + 1)

            self._setup_team_for_battle(team_index)

            # 每队都输出出战横幅和阵容header
            if self.narrative:
                self.narrative.composite_team_banner(team_index, len(self._teams))
                self.narrative.header(self.battlefield.friend_team, self.battlefield.enemy_team, 0, 0)
                if team_index == 0:
                    self.narrative.battle_start()

            team_result = self._run_team_battle(team_index)
            self._team_results.append(team_result)

            _log.info("[COMPOSITE_TACTIC] 队伍 %d 结束: 净伤害=%d, 回合=%d, 团灭=%s",
                      team_index + 1, team_result["damage_to_boss"],
                      team_result["rounds_survived"], team_result["team_wiped"])

            # 输出该队战斗结果摘要
            if self.narrative:
                self._output_team_summary(team_index, team_result)

            # 检查BOSS是否还存在
            boss = self._find_boss()
            if boss and boss.is_alive:
                _log.info("[COMPOSITE_TACTIC] BOSS当前HP=%d/%d, 阶段=%d",
                          boss.current_hp, boss.max_hp, self._boss_stage)

        # 汇总结果
        total_score = sum(r["damage_to_boss"] for r in self._team_results)

        _log.info("[COMPOSITE_TACTIC] ============ 复合战术演习结束 ============")
        _log.info("[COMPOSITE_TACTIC] 总分数(净伤害=对敌方HP伤害-敌方回血): %d", total_score)
        _log.info("[COMPOSITE_TACTIC] BOSS被击杀次数: %d", self._boss_killed_count)
        _log.info("[COMPOSITE_TACTIC] BOSS最终阶段: %d", self._boss_stage)

        if self.narrative:
            self.narrative.composite_final_summary(
                total_score, self._team_results, self._boss_killed_count, self._boss_stage)

        return {
            "result": "FINISHED",
            "score": total_score,
            "boss_stage": self._boss_stage,
            "boss_killed_count": self._boss_killed_count,
            "team_results": self._team_results,
            "total_turns": sum(r["rounds_survived"] for r in self._team_results),
            "is_composite_tactic": True,
        }

    def _setup_team_for_battle(self, team_index: int):
        """设置当前队伍并重置敌方状态"""
        team = self._teams[team_index]
        memories = self._team_memories[team_index] if team_index < len(self._team_memories) else []

        # 替换友方队伍
        self.battlefield.friend_team = list(team)

        # 应用角色复用惩罚
        self._apply_duplicate_penalty(team_index)

        # 更新回忆卡
        self.battlefield.memory_cards = list(memories)

        # 重置敌方状态（清除非阶段增量buff/debuff，重置AP/PP/EP）
        self._reset_enemy_state_for_new_team()

        # 重置回合数
        self.battlefield.turn_number = 0
        self._acted_this_round.clear()
        self._round_eligible_ids = set()

        # 友方元素协同
        from .services.element_synergy import apply_element_synergy
        apply_element_synergy(self.battlefield.friend_team, self.narrative)

        # 重建显示名称
        self._build_display_names()

        # 记录全体敌方HP总和（用于计算该队净伤害=对敌方HP伤害-敌方回血量）
        boss = self._find_boss()
        if boss:
            self._enemy_hp_at_team_start = sum(e.current_hp for e in self.battlefield.enemy_team if e.is_alive)
            self._revival_max_hp_list = []
            # 快照敌方damage_taken_total，用于计算该队对每个敌方的伤害
            self._enemy_damage_snapshot = {
                e.unit_id: getattr(e, 'damage_taken_total', 0) for e in self.battlefield.enemy_team
            }
            _log.info("[COMPOSITE_TACTIC] 队伍%d开始, BOSS HP=%d/%d, 阶段=%d, 全敌HP合计=%d",
                      team_index + 1, boss.current_hp, boss.max_hp, self._boss_stage,
                      self._enemy_hp_at_team_start)

        # 快照ScoringTracker中友方单位的hp_healed（用于计算该队期间提供治疗量）
        self._heal_snapshot = {}
        for u in self.battlefield.friend_team:
            stats = self._scoring_tracker._unit_stats.get(u.unit_id)
            self._heal_snapshot[u.unit_id] = stats.hp_healed if stats else 0

        # 输出队伍信息
        _log.info("[COMPOSITE_TACTIC] 我方阵容:")
        for u in self.battlefield.friend_team:
            _log.info("[COMPOSITE_TACTIC]   %s | HP=%d/%d ATK=%d DEF=%d SPD=%d",
                      u.name, u.current_hp, u.max_hp, u.attack, u.defense, u.speed)

    def _run_team_battle(self, team_index: int) -> Dict[str, Any]:
        """运行单支队伍的战斗（最多5回合）"""
        max_turns = self.config.max_turns
        team_wiped = False

        # 应用回忆卡效果（每队重新应用）
        self._apply_memory_card_effects()

        # 波次开始触发
        wave_start_actions = self.trigger_service.trigger_wave_start(self.battlefield)
        if self.narrative and wave_start_actions:
            self.narrative.wave_start(f"队伍{team_index + 1}出战")
        self._execute_global_trigger_actions(wave_start_actions)

        for turn_number in range(1, max_turns + 1):
            self.battlefield.turn_number = turn_number
            if self._execute_turn(turn_number):
                team_wiped = True
                break

        # 波次结束触发
        self.trigger_service.trigger_wave_end(self.battlefield)

        # 计算该队对敌方的净伤害（对敌方HP伤害 - 敌方回血量，打在盾上的不算）
        # 公式：(队伍开始时全敌HP + BOSS复活HP) - 队伍结束时全敌HP = 净HP减少量
        boss = self._find_boss()
        revival_hp_sum = sum(self._revival_max_hp_list)
        enemy_hp_at_end = sum(e.current_hp for e in self.battlefield.enemy_team if e.is_alive)
        net_damage = (self._enemy_hp_at_team_start + revival_hp_sum) - enemy_hp_at_end
        if net_damage < 0:
            net_damage = 0

        # 检查是否团灭
        alive_friends = [u for u in self.battlefield.friend_team if u.is_alive]
        if not alive_friends:
            team_wiped = True

        # 收集单位统计（供叙事日志和GUI结果显示使用）
        ally_stats = []
        for u in self.battlefield.friend_team:
            # hp_healed 取该队期间的增量（ScoringTracker累积值 - 队伍开始时快照）
            stats = self._scoring_tracker._unit_stats.get(u.unit_id)
            current_hp_healed = stats.hp_healed if stats else 0
            snapshot_hp_healed = self._heal_snapshot.get(u.unit_id, 0)
            team_hp_healed = max(0, current_hp_healed - snapshot_hp_healed)
            ally_stats.append({
                "name": self._get_display_name(u),
                "damage_dealt": getattr(u, 'damage_dealt_total', 0),
                "damage_received": getattr(u, 'damage_taken_total', 0),
                "hp_healed": team_hp_healed,
                "alive": u.is_alive,
            })
        enemy_stats = []
        for e in self.battlefield.enemy_team:
            snapshot = self._enemy_damage_snapshot.get(e.unit_id, 0)
            enemy_stats.append({
                "name": self._get_display_name(e),
                "damage_received": getattr(e, 'damage_taken_total', 0) - snapshot,
                "current_hp": e.current_hp if e.is_alive else 0,
                "max_hp": e.max_hp,
            })

        return {
            "team_index": team_index,
            "damage_to_boss": net_damage,
            "rounds_survived": self.battlefield.turn_number,
            "team_wiped": team_wiped,
            "ally_stats": ally_stats,
            "enemy_stats": enemy_stats,
        }

    def _output_team_summary(self, team_index: int, team_result: Dict):
        """输出单队战斗结果摘要到叙事日志"""
        ally_stats = [(s["name"], s["damage_dealt"], s["damage_received"], s["alive"])
                      for s in team_result["ally_stats"]]
        enemy_stats = [(s["name"], s["damage_received"], s["current_hp"], s["max_hp"])
                       for s in team_result["enemy_stats"]]

        self.narrative.composite_team_summary(
            team_index,
            team_result["damage_to_boss"],
            team_result["rounds_survived"],
            team_result["team_wiped"],
            ally_stats,
            enemy_stats,
        )

    # ════════════════════════════════════════════════════════════════════════════
    # 战斗结束条件
    # ════════════════════════════════════════════════════════════════════════════

    def _check_battle_end(self) -> bool:
        """复合战术演习：仅我方全灭时当前队伍战斗结束"""
        alive_friends = [u for u in self.battlefield.friend_team if u.is_alive]
        if not alive_friends:
            _log.info("[COMPOSITE_TACTIC] ============ 队伍%d全灭 ============", self._current_team_index + 1)
            return True
        return False

    # ════════════════════════════════════════════════════════════════════════════
    # BOSS复活机制（仅BOSS复活，小怪不复活）
    # ════════════════════════════════════════════════════════════════════════════

    def _on_deaths_resolved(self, newly_dead: list) -> None:
        """击杀触发器处理完毕后，仅复活BOSS（小怪不复活）。

        在 PAWN_DIED/PAWN_KILLED 等触发器之后、AFTER_ALLY_ATTACKED 之前调用，
        确保复活后的单位（已清除眩晕等debuff）能正常响应后续触发器。
        叙事输出延迟到 _on_death_narrative_complete 中，确保在死亡通知之后。
        """
        self._pending_resurrection_narrative = []
        for enemy in newly_dead:
            if enemy.side == Side.ENEMY and not enemy.is_alive:
                if enemy.unit_id == self._boss_unit_id:
                    # BOSS复活（跳过叙事输出，延迟到_on_death_narrative_complete）
                    narrative_data = self._resurrect_boss(enemy, skip_narrative=True)
                    if narrative_data:
                        self._pending_resurrection_narrative.append(narrative_data)
                    # 重新加入行动轴
                    if enemy.current_ap > 0 or self.action_axis._is_ep_full(enemy):
                        if enemy.unit_id not in self._acted_this_round and enemy.unit_id in self._round_eligible_ids:
                            self.action_axis.action_axis = [
                                u for u in self.action_axis.action_axis if u.unit_id != enemy.unit_id
                            ]
                            self.action_axis.action_axis.append(enemy)
                            self.action_axis.resort_action_axis()
                            _log.info("[COMPOSITE_TACTIC] BOSS %s 已重新加入行动轴", enemy.name)
                else:
                    _log.info("[COMPOSITE_TACTIC] 小怪 %s 被击杀，不复活", enemy.name)

    def _on_death_narrative_complete(self, newly_dead: list) -> None:
        """死亡通知输出完毕后，输出BOSS复活（阶段提升）的叙事日志。"""
        for narrative_data in self._pending_resurrection_narrative:
            if self.narrative:
                self.narrative.tactical_exercise_stage_up(**narrative_data)
        self._pending_resurrection_narrative = []

    def _resurrect_boss(self, boss: UnitState, skip_narrative: bool = False) -> Optional[Dict]:
        """BOSS复活：阶段+1、属性增长、清除非阶段增量buff/debuff

        阶段增量以百分比buff形式存储（is_memory_buff=True），与PS技能buff一起参与
        Base * (1 + Sum%) 计算，确保百分比buff以阶段0基础属性（含组队加成）为基准。

        Args:
            boss: 被击败的BOSS单位
            skip_narrative: 如果为True，跳过叙事输出并返回叙事数据字典供延迟输出

        Returns:
            当skip_narrative=True时，返回叙事数据字典；否则返回None
        """
        self._boss_stage += 1
        self._boss_killed_count += 1
        n = self._boss_stage

        base = self._boss_base_stats
        if not base:
            _log.warning("[COMPOSITE_TACTIC] 未找到BOSS基础属性，使用当前属性")
            base = {
                "hp": float(boss.max_hp),
                "attack": float(boss.attack),
                "defense": float(boss.defense),
                "speed": float(boss.speed),
                "crit_rate": float(boss.crit_rate),
            }
            self._boss_base_stats = base

        # 阶段增量公式（复用战术演习公式）
        n_for_hp_atk_def = min(n, 20)
        atk_def_pct = 0.2 * n_for_hp_atk_def + 0.005 * max(0, n_for_hp_atk_def - 3) * max(0, n_for_hp_atk_def - 2)
        spd_pct = 0.05 * n

        stat_multiplier = 1.0 + atk_def_pct
        new_hp = math.floor(base["hp"] * stat_multiplier)
        new_attack = math.floor(base["attack"] * stat_multiplier)
        new_defense = math.floor(base["defense"] * stat_multiplier)
        new_speed = math.floor(base["speed"] * (1.0 + spd_pct))
        new_crit_rate = base["crit_rate"] + 0.01 * n

        old_hp = boss.max_hp
        old_atk = self.damage_service._calculate_final_stat(boss, "attack")
        old_def = self.damage_service._calculate_final_stat(boss, "defense")
        old_spd = self.damage_service._calculate_final_stat(boss, "speed")
        old_crit = boss.crit_rate

        # 保存AP/PP/EP
        saved_ap = boss.current_ap
        saved_pp = boss.current_pp
        saved_ep = boss.current_ep

        # 清除所有非回忆卡buff（包括旧阶段增量stage_ buff），仅保留回忆卡buff
        # 旧stage_ buff必须清除，否则跨阶段累积叠加（is_memory_buff=True会无条件求和）
        kept_buffs = [b for b in boss.buffs if b.is_memory_buff and not b.buff_id.startswith("stage_")]
        buffs_cleared = len(boss.buffs) - len(kept_buffs)
        # 清除非回忆卡debuff，保留回忆卡debuff(is_memory_buff=True)
        debuffs_cleared = len([d for d in boss.debuffs if not d.is_memory_buff])
        boss.buffs = kept_buffs
        boss.debuffs = [d for d in boss.debuffs if d.is_memory_buff]
        boss.is_stunned = False
        boss.is_frozen = False

        # 恢复基础属性（base已包含组队加成）
        boss.attack = int(base["attack"])
        boss.defense = int(base["defense"])
        boss.speed = int(base["speed"])
        boss.max_hp = new_hp
        boss.current_hp = new_hp
        boss.crit_rate = new_crit_rate

        # 添加新的阶段增量百分比buff
        stage_buffs = [
            (SkillEffectType.STATUS_ATTACK.value, atk_def_pct * 100, "阶段增量ATK"),
            (SkillEffectType.STATUS_DEFENSE.value, atk_def_pct * 100, "阶段增量DEF"),
            (SkillEffectType.STATUS_SPEED.value, spd_pct * 100, "阶段增量SPD"),
        ]
        for effect_type, value, name in stage_buffs:
            buff = BuffState(
                buff_id=f"stage_{n}_{effect_type}_{boss.unit_id}",
                name=name,
                effect_type=effect_type,
                value=value,
                duration=-1,
                timing_type=0,
                source_unit_id=boss.unit_id,
                source_skill_id=0,
                is_debuff=False,
                value_tag=0,
                is_memory_buff=True,
            )
            boss.buffs.append(buff)

        # 恢复AP/PP/EP
        boss.current_ap = saved_ap
        boss.current_pp = saved_pp
        boss.current_ep = saved_ep

        # 标记存活
        boss.is_alive = True
        boss.is_death_notified = False

        # 记录复活的最大HP（用于计算伤害）
        self._revival_max_hp_list.append(new_hp)

        _log.info("[COMPOSITE_TACTIC] ==================================================")
        _log.info("[COMPOSITE_TACTIC] BOSS %s 进入阶段 %d！", boss.name, n)
        _log.info("[COMPOSITE_TACTIC] HP: %d → %d (x%.4f)", old_hp, new_hp, stat_multiplier)
        _log.info("[COMPOSITE_TACTIC] ATK: %d → %d [base=%d + buff=%.1f%%]",
                  old_atk, new_attack, int(base["attack"]), atk_def_pct * 100)
        _log.info("[COMPOSITE_TACTIC] DEF: %d → %d [base=%d + buff=%.1f%%]",
                  old_def, new_defense, int(base["defense"]), atk_def_pct * 100)
        _log.info("[COMPOSITE_TACTIC] SPD: %d → %d [base=%d + buff=%.1f%%]",
                  old_spd, new_speed, int(base["speed"]), spd_pct * 100)
        _log.info("[COMPOSITE_TACTIC] CRIT: %.4f → %.4f (+%.4f)", old_crit, new_crit_rate, 0.01 * n)
        _log.info("[COMPOSITE_TACTIC] 清除 Buff x%d, Debuff x%d", buffs_cleared, debuffs_cleared)
        _log.info("[COMPOSITE_TACTIC] AP=%d PP=%d EP=%d (保持不变)", saved_ap, saved_pp, saved_ep)
        _log.info("[COMPOSITE_TACTIC] ==================================================")

        # 叙事日志
        narrative_data = {
            "unit_name": self._get_display_name(boss),
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

    # ════════════════════════════════════════════════════════════════════════════
    # 队伍切换时的敌方状态重置
    # ════════════════════════════════════════════════════════════════════════════

    def _reset_enemy_state_for_new_team(self):
        """队伍切换时重置敌方状态：
        - 保留: HP（含死亡状态）、BOSS阶段增量buff、非回忆卡buff/debuff
        - 清除: 回忆卡buff/debuff(is_memory_buff=True，但stage_开头的阶段增量buff除外)
        - 重置: AP/PP/EP → 初始值

        注：回忆卡随队伍切换而更换，其施加的buff/debuff不可跨队伍继承；
        但敌方自身技能施加的buff/debuff应保留（队伍切换不清除敌方状态）。
        """
        for enemy in self.battlefield.enemy_team:
            # 保留阶段增量buff(stage_开头)和非回忆卡buff，清除回忆卡buff
            enemy.buffs = [b for b in enemy.buffs if b.buff_id.startswith("stage_") or not b.is_memory_buff]
            # 清除回忆卡debuff(is_memory_buff=True)，保留技能施加的普通debuff
            enemy.debuffs = [d for d in enemy.debuffs if not d.is_memory_buff]
            enemy.is_stunned = False
            enemy.is_frozen = False

            # 重置AP/PP/EP为初始值
            initial = self._enemy_initial_resources.get(enemy.unit_id, {})
            enemy.current_ap = initial.get("ap", enemy.initial_active_point)
            enemy.current_pp = initial.get("pp", enemy.initial_passive_point)
            enemy.current_ep = initial.get("ep", 0)

            # 重置技能冷却
            enemy.skill_cooldowns.clear()

            # 重置蓄力状态
            enemy.is_charging = False
            enemy.charge_skill_id = None

            # 注意：不修改HP和is_alive（HP跨队伍继承，死亡的小怪保持死亡）

    # ════════════════════════════════════════════════════════════════════════════
    # 角色复用惩罚
    # ════════════════════════════════════════════════════════════════════════════

    def _apply_duplicate_penalty(self, team_index: int):
        """对当前队伍中的重复角色应用属性惩罚

        只对非首次出现的队伍应用惩罚：
        - 第2次出现(重复1次): HP/ATK/DEF × 50%
        - 第3次出现(重复2次): HP/ATK/DEF = 1
        """
        # 统计当前队伍之前各角色已出现的队伍数
        prior_usage: Dict[int, int] = {}
        for idx in range(team_index):
            seen_in_team = set()
            for unit in self._teams[idx]:
                cid = getattr(unit, "character_id", None)
                if cid is not None and cid not in seen_in_team:
                    seen_in_team.add(cid)
                    prior_usage[cid] = prior_usage.get(cid, 0) + 1

        for unit in self.battlefield.friend_team:
            cid = getattr(unit, "character_id", None)
            if cid is None:
                continue
            prior_count = prior_usage.get(cid, 0)
            if prior_count == 0:
                continue  # 首次出现，不惩罚

            if prior_count == 1:
                # 重复1次：HP/ATK/DEF × 50%
                penalty_rate = 0.5
                unit.max_hp = max(1, int(unit.max_hp * penalty_rate))
                unit.current_hp = unit.max_hp
                unit.attack = max(1, int(unit.attack * penalty_rate))
                unit.defense = max(1, int(unit.defense * penalty_rate))
                _log.info("[COMPOSITE_TACTIC] %s 重复编组1次, HP/ATK/DEF ×50%% → HP=%d ATK=%d DEF=%d",
                          unit.name, unit.max_hp, unit.attack, unit.defense)
                if self.narrative:
                    self.narrative.system_message(
                        f"[重复编组惩罚] {unit.name} 在前序队伍已编入，HP/ATK/DEF ×50% "
                        f"→ HP={unit.max_hp} ATK={unit.attack} DEF={unit.defense}"
                    )
            elif prior_count >= 2:
                # 重复2次：HP/ATK/DEF = 1
                unit.max_hp = 1
                unit.current_hp = 1
                unit.attack = 1
                unit.defense = 1
                _log.info("[COMPOSITE_TACTIC] %s 重复编组2次, HP/ATK/DEF = 1", unit.name)
                if self.narrative:
                    self.narrative.system_message(
                        f"[重复编组惩罚] {unit.name} 已在2支前序队伍编入，HP/ATK/DEF = 1"
                    )

    # ════════════════════════════════════════════════════════════════════════════
    # 属性访问
    # ════════════════════════════════════════════════════════════════════════════

    @property
    def boss_stage(self) -> int:
        return self._boss_stage

    @property
    def boss_killed_count(self) -> int:
        return self._boss_killed_count

    @property
    def total_score(self) -> int:
        return sum(r.get("damage_to_boss", 0) for r in self._team_results)
