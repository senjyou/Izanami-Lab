#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
对抗压制战（公会战）模式控制器
src/combat_v2/circle_battle_controller.py

职责：
- 管理对抗压制战模式的战斗流程
- 回合耗尽未全灭敌方视为失败
- 无复活机制（与战术演习不同）
- 支持指定赛季和阶段
- 支持敌方初始状态覆盖（自定义当前HP、初始死亡）
"""

from typing import Optional, Dict, Any

from .battle_flow_controller import BattleFlowController, BattleConfig
from .battle_logger import battle_logger

_log = battle_logger()


class CircleBattleController(BattleFlowController):
    """对抗压制战模式控制器"""

    def __init__(self, battlefield, config: Optional[BattleConfig] = None,
                 data_loader: Any = None, narrative: Any = None,
                 season: int = 5, stage: int = 100,
                 enemy_state_overrides: Optional[Dict[int, Dict[str, Any]]] = None):
        super().__init__(battlefield, config, data_loader, narrative)
        self._season = season
        self._stage = stage
        self._is_circle_battle = True
        # enemy_state_overrides: {slot: {"current_hp": int, "dead": bool}}
        # slot 为 1-6，未列出的 slot 使用默认值（满血存活）
        # 兼容JSON反序列化后的字符串键，统一转为int
        self._enemy_state_overrides = {}
        if enemy_state_overrides:
            for k, v in enemy_state_overrides.items():
                try:
                    self._enemy_state_overrides[int(k)] = v
                except (ValueError, TypeError):
                    pass
        # 缓存初始死亡单位，供 _log_initial_state 输出叙事
        self._initial_dead_units: list = []
        # 快照协同前基础max_hp，用于缩放用户自定义HP
        self._enemy_base_max_hp: Dict[int, int] = {}

    def _pre_synergy_setup(self) -> None:
        """元素协同之前，快照敌方基础max_hp（用户输入的HP基于此值）"""
        self._enemy_base_max_hp = {}
        for unit in self.battlefield.enemy_team:
            try:
                slot = int(unit.unit_id.rsplit("_", 1)[-1])
            except (ValueError, IndexError):
                continue
            self._enemy_base_max_hp[slot] = unit.max_hp

    def _post_synergy_setup(self) -> None:
        """元素协同计算完成后，应用敌方初始状态覆盖。

        元素协同已经基于所有加载单位（含预死单位）计算了属性加成并缩放了
        max_hp/attack/defense。在此之后覆盖 current_hp 和 is_alive，
        既能保证组队加成正确计入，又能实现开局即死/自定义HP。

        用户在GUI输入的current_hp是局外基础血量（协同前），
        需按协同倍率缩放为局内实际血量：scaled_hp = base_hp × (max_hp_after / max_hp_before)
        """
        if not self._enemy_state_overrides:
            return

        self._initial_dead_units = []

        for unit in self.battlefield.enemy_team:
            # 从 unit_id 解析 slot：格式为 "E_{enemy_id}_{slot}"
            try:
                slot = int(unit.unit_id.rsplit("_", 1)[-1])
            except (ValueError, IndexError):
                continue

            override = self._enemy_state_overrides.get(slot)
            if not override:
                continue

            if override.get("dead"):
                unit.current_hp = 0
                unit.is_alive = False
                # 标记已通知，防止战斗流程在首次行动时重复输出阵亡日志
                unit.is_death_notified = True
                self._initial_dead_units.append(unit)
                _log.info("[CIRCLE_BATTLE] 敌方 slot=%d %s 初始状态: 死亡", slot, unit.name)
            elif "current_hp" in override:
                base_hp = override["current_hp"]
                base_max_hp = self._enemy_base_max_hp.get(slot, unit.max_hp)
                # 按协同倍率缩放：用户输入的是局外血量，需套用组队加成
                if base_max_hp > 0:
                    synergy_mult = unit.max_hp / base_max_hp
                    scaled_hp = int(base_hp * synergy_mult)
                else:
                    scaled_hp = base_hp
                # 限制不超过协同后max_hp
                unit.current_hp = min(scaled_hp, unit.max_hp)
                unit.is_alive = unit.current_hp > 0
                if not unit.is_alive:
                    unit.is_death_notified = True
                    self._initial_dead_units.append(unit)
                _log.info("[CIRCLE_BATTLE] 敌方 slot=%d %s 初始HP覆盖: 局外=%d × 协同倍率=%.4f → 局内=%d/%d",
                          slot, unit.name, base_hp,
                          unit.max_hp / base_max_hp if base_max_hp > 0 else 1.0,
                          unit.current_hp, unit.max_hp)

    def _log_initial_state(self) -> None:
        """在叙事头部输出之后、触发器之前，输出开局即死单位的阵亡叙事"""
        if not self._initial_dead_units or not self.narrative:
            return
        self.narrative._add("【初始状态】以下敌方单位在战斗开始前已倒下：")
        for unit in self._initial_dead_units:
            display_name = self._get_display_name(unit)
            self.narrative.death(display_name)

    def execute_battle(self) -> Dict[str, Any]:
        """执行对抗压制战，返回包含阶段信息的结果"""
        result = super().execute_battle()

        # 回合耗尽未全灭敌方 → 失败
        if result.get("result") == "TIMEOUT":
            alive_enemies = [u for u in self.battlefield.enemy_team if u.is_alive]
            if alive_enemies:
                result["winner"] = "ENEMY"
                result["result"] = "TIMEOUT_LOSS"
                _log.info("[CIRCLE_BATTLE] 回合耗尽，敌方仍有 %d 个单位存活，判定失败",
                          len(alive_enemies))

        # 添加对抗压制战元数据
        result["is_circle_battle"] = True
        result["season"] = self._season
        result["stage"] = self._stage

        _log.info("[CIRCLE_BATTLE] 第%d赛季 阶段%d 战斗结束: %s",
                  self._season, self._stage,
                  "胜利" if result.get("winner") == "FRIEND" else "失败")

        return result
