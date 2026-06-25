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
        # 检查ep_gain_down debuff：减少EP获取量
        actual_amount = float(amount)
        ep_reduction = 0.0
        for d in unit.debuffs:
            if d.effect_type == "EpGainDown" and d.value > 0:
                ep_reduction = max(ep_reduction, d.value)
                _log.info("[EP_GAIN_DOWN] %s: ep_gain_down active, reduction=%.1f%%", unit.name, d.value)
        if ep_reduction > 0:
            actual_amount = amount * (1.0 - ep_reduction / 100.0)
            _log.info("[EP_GAIN_DOWN] %s: EP gain reduced %d -> %.2f (%.1f%% reduction)",
                      unit.name, amount, actual_amount, ep_reduction)
        old = unit.current_ep
        cap = unit.max_extra_point
        unit.current_ep = min(unit.current_ep + actual_amount, cap)
        _log.info("[RESOURCE] %s generate_ep: %s -> %s (+%.2f, cap=%d)",
                  unit.name, old, unit.current_ep, actual_amount, cap)
