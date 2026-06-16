from ...entities_v2.unit_state import UnitState
from ..battle_logger import battle_logger

_log = battle_logger()

class ResourceService:
    """
    资源管理服务
    负责AP/PP/EP的消耗、恢复和验证
    """
    
    def consume_ap(self, unit: UnitState, amount: int) -> bool:
        if amount < 0:
            return False
        if unit.current_ap < amount:
            _log.info("[RESOURCE] %s consume_ap FAIL: need=%d have=%d", unit.name, amount, unit.current_ap)
            return False
        old = unit.current_ap
        unit.current_ap -= amount
        _log.info("[RESOURCE] %s consume_ap: %d -> %d (used=%d)", unit.name, old, unit.current_ap, amount)
        return True

    def consume_pp(self, unit: UnitState, amount: int) -> bool:
        if amount < 0:
            return False
        if unit.current_pp < amount:
            _log.info("[RESOURCE] %s consume_pp FAIL: need=%d have=%d", unit.name, amount, unit.current_pp)
            return False
        old = unit.current_pp
        unit.current_pp -= amount
        _log.info("[RESOURCE] %s consume_pp: %d -> %d (used=%d)", unit.name, old, unit.current_pp, amount)
        return True

    def consume_ep(self, unit: UnitState, amount: int) -> bool:
        if amount < 0:
            return False
        if unit.current_ep < amount:
            return False
        old = unit.current_ep
        unit.current_ep -= amount
        _log.info("[RESOURCE] %s consume_ep: %d -> %d (used=%d)", unit.name, old, unit.current_ep, amount)
        return True

    def consume_ep_for_ex(self, unit: UnitState) -> bool:
        if unit.current_ep < unit.max_extra_point:
            _log.info("[RESOURCE] %s consume_ep_for_ex FAIL: EP=%d/%d (not full)",
                      unit.name, unit.current_ep, unit.max_extra_point)
            return False
        old = unit.current_ep
        unit.current_ep = 0
        _log.info("[RESOURCE] %s consume_ep_for_ex: %d -> 0 (EX skill)", unit.name, old)
        return True
        
    def restore_ap(self, unit: UnitState, amount: int) -> None:
        if amount <= 0:
            return
        old = unit.current_ap
        cap = unit.initial_active_point
        unit.current_ap = min(unit.current_ap + amount, cap)
        _log.info("[RESOURCE] %s restore_ap: %d -> %d (+%d, cap=%d)",
                  unit.name, old, unit.current_ap, unit.current_ap - old, cap)

    def restore_ap_pp(self, unit: UnitState) -> None:
        old_ap, old_pp = unit.current_ap, unit.current_pp
        unit.current_ap = unit.initial_active_point
        unit.current_pp = unit.initial_passive_point
        _log.info("[RESOURCE] %s restore_ap_pp: AP %d->%d PP %d->%d",
                  unit.name, old_ap, unit.current_ap, old_pp, unit.current_pp)
        
    def generate_ep(self, unit: UnitState, amount: int) -> None:
        if amount <= 0:
            return
        old = unit.current_ep
        cap = unit.max_extra_point
        unit.current_ep = min(unit.current_ep + amount, cap)
        _log.info("[RESOURCE] %s generate_ep: %d -> %d (+%d, cap=%d)",
                  unit.name, old, unit.current_ep, unit.current_ep - old, cap)
