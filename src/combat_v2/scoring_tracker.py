#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
战术演习计分追踪器
src/combat_v2/scoring_tracker.py

职责：
- 追踪单场战斗中每个单位造成的伤害、受到的伤害、提供的回复HP
- 计算最终得分

得分公式：Score = 对敌方造成的总伤害（含溢出） - 敌方受到的总回复量
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class UnitScoreStats:
    """单个单位的得分统计"""
    unit_id: str = ""
    name: str = ""
    side: str = ""  # "ally" or "enemy"
    damage_dealt: int = 0       # 造成的伤害
    damage_received: int = 0    # 受到的伤害
    hp_healed: int = 0          # 提供的回复HP（治疗他人）
    hp_received: int = 0        # 收到的回复HP（被他人治疗）


@dataclass
class BattleScoreResult:
    """单场战斗得分结果"""
    # 得分组成
    total_damage_to_enemies: int = 0   # 对敌方造成的总伤害（含溢出）
    enemy_healing_received: int = 0    # 敌方受到的总回复量
    total_score: int = 0               # 最终得分

    # 各回合分数（用于观察趋势）
    turn_scores: Dict[int, int] = field(default_factory=dict)

    # 单位统计
    unit_stats: Dict[str, UnitScoreStats] = field(default_factory=dict)

    # 汇总
    ally_total_damage_dealt: int = 0
    ally_total_damage_received: int = 0
    ally_total_hp_healed: int = 0
    enemy_total_damage_dealt: int = 0
    enemy_total_damage_received: int = 0
    enemy_total_hp_healed: int = 0

    # 元数据
    stages_cleared: int = 0
    total_turns: int = 0
    battle_result: str = "UNKNOWN"

    def to_dict(self) -> dict:
        return {
            "total_damage_to_enemies": self.total_damage_to_enemies,
            "enemy_healing_received": self.enemy_healing_received,
            "total_score": self.total_score,
            "unit_stats": {
                uid: {
                    "unit_id": s.unit_id,
                    "name": s.name,
                    "side": s.side,
                    "damage_dealt": s.damage_dealt,
                    "damage_received": s.damage_received,
                    "hp_healed": s.hp_healed,
                    "hp_received": s.hp_received,
                }
                for uid, s in self.unit_stats.items()
            },
            "ally_total_damage_dealt": self.ally_total_damage_dealt,
            "ally_total_damage_received": self.ally_total_damage_received,
            "ally_total_hp_healed": self.ally_total_hp_healed,
            "enemy_total_damage_dealt": self.enemy_total_damage_dealt,
            "enemy_total_damage_received": self.enemy_total_damage_received,
            "enemy_total_hp_healed": self.enemy_total_hp_healed,
            "stages_cleared": self.stages_cleared,
            "total_turns": self.total_turns,
            "battle_result": self.battle_result,
        }


class ScoringTracker:
    """战术演习得分追踪器

    得分公式：Score = 对敌方造成的总伤害（含溢出） - 敌方受到的总回复量
    """

    def __init__(self):
        self._unit_stats: Dict[str, UnitScoreStats] = {}

        # 得分组成
        self._total_damage_to_enemies: int = 0
        self._enemy_healing_received: int = 0

        # 当前回合
        self._current_turn: int = 0
        self._turn_scores: Dict[int, int] = {}

    def ensure_unit(self, unit_id: str, name: str, side: str):
        """确保单位已在追踪器中注册"""
        if unit_id not in self._unit_stats:
            self._unit_stats[unit_id] = UnitScoreStats(
                unit_id=unit_id, name=name, side=side
            )

    def set_turn(self, turn: int):
        """设置当前回合"""
        self._current_turn = turn

    def record_damage(self, source_id: str, source_name: str, source_side: str,
                      target_id: str, target_name: str, target_side: str,
                      actual_damage: int, shield_absorbed: int = 0,
                      overflow: int = 0):
        """记录伤害事件

        actual_damage: 实际扣HP的伤害（含溢出部分）
        shield_absorbed: 护盾吸收的伤害（不计入得分）
        overflow: 溢出伤害（超出目标剩余HP的部分，已包含在actual_damage中）
        """
        # 确保单位注册
        self.ensure_unit(source_id, source_name, source_side)
        self.ensure_unit(target_id, target_name, target_side)

        # 记录造成伤害（含溢出，因为溢出也是我方造成的）
        self._unit_stats[source_id].damage_dealt += actual_damage
        # 记录受到伤害（只计实际扣HP的部分，含溢出）
        self._unit_stats[target_id].damage_received += actual_damage

        # 对敌方造成的伤害（含溢出，全部计入得分）
        if target_side == "enemy":
            self._total_damage_to_enemies += actual_damage

    def record_heal(self, source_id: str, source_name: str, source_side: str,
                    target_id: str, target_name: str, target_side: str,
                    heal_amount: int):
        """记录治疗事件"""
        if heal_amount <= 0:
            return

        # 确保单位注册
        self.ensure_unit(source_id, source_name, source_side)
        self.ensure_unit(target_id, target_name, target_side)

        # 提供回复
        self._unit_stats[source_id].hp_healed += heal_amount
        # 收到回复
        self._unit_stats[target_id].hp_received += heal_amount

        # 敌方受到的回复（无论来源，都从得分中扣除）
        if target_side == "enemy":
            self._enemy_healing_received += heal_amount

    def finalize_turn(self):
        """回合结束时保存当前回合分数"""
        if self._current_turn > 0:
            self._turn_scores[self._current_turn] = self.get_current_score()

    def get_current_score(self) -> int:
        """获取当前累计得分

        Score = 对敌方造成的总伤害（含溢出） - 敌方受到的总回复量
        """
        return self._total_damage_to_enemies - self._enemy_healing_received

    def build_result(self, stages_cleared: int = 0, total_turns: int = 0,
                     battle_result: str = "UNKNOWN") -> BattleScoreResult:
        """构建最终得分结果"""
        ally_stats = [s for s in self._unit_stats.values() if s.side == "ally"]
        enemy_stats = [s for s in self._unit_stats.values() if s.side == "enemy"]

        return BattleScoreResult(
            total_damage_to_enemies=self._total_damage_to_enemies,
            enemy_healing_received=self._enemy_healing_received,
            total_score=self.get_current_score(),
            turn_scores=dict(self._turn_scores),
            unit_stats={uid: s for uid, s in self._unit_stats.items()},
            ally_total_damage_dealt=sum(s.damage_dealt for s in ally_stats),
            ally_total_damage_received=sum(s.damage_received for s in ally_stats),
            ally_total_hp_healed=sum(s.hp_healed for s in ally_stats),
            enemy_total_damage_dealt=sum(s.damage_dealt for s in enemy_stats),
            enemy_total_damage_received=sum(s.damage_received for s in enemy_stats),
            enemy_total_hp_healed=sum(s.hp_healed for s in enemy_stats),
            stages_cleared=stages_cleared,
            total_turns=total_turns,
            battle_result=battle_result,
        )
