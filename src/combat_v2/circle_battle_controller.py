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
"""

from typing import Optional, Dict, Any

from .battle_flow_controller import BattleFlowController, BattleConfig
from .battle_logger import battle_logger

_log = battle_logger()


class CircleBattleController(BattleFlowController):
    """对抗压制战模式控制器"""

    def __init__(self, battlefield, config: Optional[BattleConfig] = None,
                 data_loader: Any = None, narrative: Any = None,
                 season: int = 5, stage: int = 100):
        super().__init__(battlefield, config, data_loader, narrative)
        self._season = season
        self._stage = stage
        self._is_circle_battle = True

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
