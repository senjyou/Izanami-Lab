#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
行动轴管理服务
src/combat_v2/services/action_axis_service.py
"""

from typing import List, Optional
from ...entities_v2.enums import Position, Side
from ...entities_v2.unit_state import UnitState
from ...entities_v2.battlefield_state import BattlefieldState
from ..battle_logger import battle_logger

_log = battle_logger()

class ActionAxisService:
    """
    行动轴管理服务
    
    职责：
    - 生成行动轴
    - 排序（速度+位置）
    - 获取下一个行动单位
    - 重新排序
    """
    
    def __init__(self):
        self.action_axis: List[UnitState] = []
        self._damage_service = None

    def set_damage_service(self, damage_service):
        """设置伤害服务引用，用于计算有效速度（含buff/debuff）"""
        self._damage_service = damage_service
    
    def generate_action_axis(self, battlefield: BattlefieldState) -> None:
        """
        生成行动轴
        
        规则：
        - AP > 0 或 EP已满的单位
        - 按速度+位置排序
        """
        self.action_axis = []
        
        for unit in battlefield.get_all_units():
            if not unit.is_alive:
                continue
            
            # 可行动条件：AP > 0 或 EP已满 或 正在蓄力中
            # 蓄力中的单位即使AP=0、EP不满也必须加入行动轴以执行蓄力技能
            if unit.current_ap > 0 or self._is_ep_full(unit) or getattr(unit, 'is_charging', False):
                self.action_axis.append(unit)
        
        # 排序
        self._sort_action_axis()

        _log.info("[ACTION_AXIS] generated: %d units", len(self.action_axis))
        for unit in self.action_axis:
            ep_full = "EP_FULL" if self._is_ep_full(unit) else ""
            _log.info("[ACTION_AXIS]   %s | spd=%d pos=%s AP=%d EP=%d/%d prio=%d %s",
                      unit.name, unit.speed, unit.position.name if unit.position else "?",
                      unit.current_ap, unit.current_ep, unit.max_extra_point,
                      unit.current_action_priority, ep_full)
    
    def get_next_unit(self) -> Optional[UnitState]:
        """获取并移除下一个行动单位"""
        if self.action_axis:
            return self.action_axis.pop(0)
        return None
    
    def resort_action_axis(self) -> None:
        """重新排序行动轴（每次行动后调用）"""
        self._sort_action_axis()
    
    def is_empty(self) -> bool:
        """行动轴是否为空"""
        return len(self.action_axis) == 0
        
    def _is_ep_full(self, unit: UnitState) -> bool:
        """检查EP是否已满（无EX技能的单位EP永远不为满）"""
        if unit.max_extra_point <= 0:
            return False
        return unit.current_ep >= unit.max_extra_point
    
    def _sort_action_axis(self) -> None:
        """
        排序行动轴
        
        规则：
        1. 有效速度降序（含buff/debuff）
        2. 速度相同时：己方优先于敌方
        3. 速度相同时同阵营：按站位优先级（左前 > 中前 > 右前 > 左后 > 中后 > 右后）
        4. 以上均相同时：按角色ID
        """
        def sort_key(unit: UnitState):
            # 使用有效速度（含buff/debuff），而非基础速度
            if self._damage_service:
                effective_speed = self._damage_service._calculate_final_stat(unit, "speed")
            else:
                effective_speed = unit.speed
            side_priority = 0 if unit.side == Side.ALLY else 1
            position_priority = self._get_position_priority(unit.position)
            
            try:
                char_id = int(unit.character_id)
            except:
                char_id = 0
                
            return (-effective_speed, side_priority, position_priority, char_id)
        
        self.action_axis.sort(key=sort_key)
        
        # 更新每个单位的当前行动优先级字段（仅用于调试）
        for idx, unit in enumerate(self.action_axis):
            unit.current_action_priority = idx + 1

    def _get_position_priority(self, position: Position) -> int:
        """
        获取位置优先级
        数值越小优先级越高
        
        规则：
        前排优先于后排
        从左到右 (左 > 中 > 右)
        """
        priority_map = {
            # 我方前排
            Position.ALLY_LEFT_FRONT: 1,
            Position.ALLY_CENTER_FRONT: 2,
            Position.ALLY_RIGHT_FRONT: 3,
            # 我方后排
            Position.ALLY_LEFT_BACK: 4,
            Position.ALLY_CENTER_BACK: 5,
            Position.ALLY_RIGHT_BACK: 6,
            
            # 敌方前排
            Position.ENEMY_LEFT_FRONT: 1,
            Position.ENEMY_CENTER_FRONT: 2,
            Position.ENEMY_RIGHT_FRONT: 3,
            # 敌方后排
            Position.ENEMY_LEFT_BACK: 4,
            Position.ENEMY_CENTER_BACK: 5,
            Position.ENEMY_RIGHT_BACK: 6,
        }
        return priority_map.get(position, 99)
