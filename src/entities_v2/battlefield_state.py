#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
战场状态 - 纯数据类
src/entities_v2/battlefield_state.py
"""

from dataclasses import dataclass, field
from typing import List, Optional, Any, TYPE_CHECKING
from .enums import Side
from .unit_state import UnitState

if TYPE_CHECKING:
    from ..combat_v2.scoring_tracker import ScoringTracker

@dataclass
class BattlefieldState:
    """
    战场状态
    包含战斗中所有的全局数据
    """
    
    # ========== 队伍信息 ==========
    friend_team: List[UnitState] = field(default_factory=list)
    enemy_team: List[UnitState] = field(default_factory=list)
    
    # ========== 全局资源 ==========
    memory_cards: List[Any] = field(default_factory=list) # 存储回忆卡完整数据
    
    # ========== 战斗进度 ==========
    turn_number: int = 1
    wave_number: int = 1
    round_number: int = 0
    total_actions: int = 0
    
    # ========== 元数据 ==========
    battle_id: str = ""
    max_turns: int = 15

    # ========== 计分系统 (战术演习用) ==========
    scoring_tracker: Optional['ScoringTracker'] = None
    
    def add_unit(self, unit: UnitState):
        """添加单位到战场（自动确保 unit_id 唯一）"""
        existing_ids = {u.unit_id for u in self.get_all_units()}
        if unit.unit_id in existing_ids:
            base = unit.unit_id
            suffix = 1
            while f"{base}_{suffix}" in existing_ids:
                suffix += 1
            unit.unit_id = f"{base}_{suffix}"
        if unit.side == Side.ALLY:
            self.friend_team.append(unit)
        elif unit.side == Side.ENEMY:
            self.enemy_team.append(unit)
        else:
            raise ValueError(f"Unknown side: {unit.side}")
    
    def get_all_units(self) -> List[UnitState]:
        """获取所有单位"""
        return self.friend_team + self.enemy_team
    
    def get_alive_units(self, side: Optional[Side] = None) -> List[UnitState]:
        """
        获取存活单位
        Args:
            side: 可选，指定阵营
        """
        units = []
        source = self.get_all_units()
        
        for unit in source:
            if not unit.is_alive:
                continue
                
            if side and unit.side != side:
                continue
                
            units.append(unit)
            
        return units
    
    def get_unit_by_id(self, unit_id: str) -> Optional[UnitState]:
        """根据ID获取单位"""
        for unit in self.get_all_units():
            if unit.unit_id == unit_id:
                return unit
        return None
