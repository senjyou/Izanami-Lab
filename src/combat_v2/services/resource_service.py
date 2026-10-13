from ...entities_v2.unit_state import UnitState
from ...entities_v2.enums import SkillEffectType
from ..battle_logger import battle_logger

_log = battle_logger()

class ResourceService:
    """
    资源管理服务
    负责AP/PP/EP的消耗、恢复和验证
    """

    def __init__(self):
        # AP上限的额外修正来源（StatusMaxAp buff 聚合）。
        # 由 BattleFlowController 注入 DamageService._calculate_final_stat；
        # 未注入时回退到 initial_active_point（原有行为）。
        self._max_ap_resolver = None

    def set_max_ap_resolver(self, func):
        """注入 AP上限解析函数: func(unit) -> int"""
        self._max_ap_resolver = func

    def get_max_ap(self, unit: UnitState) -> int:
        """单位当前的有效AP上限。

        基准是 initial_active_point（add_max_ap 等技能效果直接改它），
        叠加 StatusMaxAp 类 buff 的修正（回忆卡 400262「最大APを1増加させる」）。
        """
        if self._max_ap_resolver is not None:
            try:
                return int(self._max_ap_resolver(unit))
            except Exception:
                pass
        return unit.initial_active_point

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
        cap = self.get_max_ap(unit)
        unit.current_ap = min(unit.current_ap + amount, cap)
        _log.info("[RESOURCE] %s restore_ap: %d -> %d (+%d, cap=%d)",
                  unit.name, old, unit.current_ap, unit.current_ap - old, cap)

    def restore_pp(self, unit: UnitState, amount: int) -> None:
        if amount <= 0:
            return
        old = unit.current_pp
        cap = unit.initial_passive_point
        unit.current_pp = min(unit.current_pp + amount, cap)
        _log.info("[RESOURCE] %s restore_pp: %d -> %d (+%d, cap=%d)",
                  unit.name, old, unit.current_pp, unit.current_pp - old, cap)

    def restore_ap_pp(self, unit: UnitState) -> None:
        old_ap, old_pp = unit.current_ap, unit.current_pp
        unit.current_ap = self.get_max_ap(unit)
        unit.current_pp = unit.initial_passive_point
        _log.info("[RESOURCE] %s restore_ap_pp: AP %d->%d PP %d->%d",
                  unit.name, old_ap, unit.current_ap, old_pp, unit.current_pp)
        
    def generate_ep(self, unit: UnitState, amount: int, apply_ep_gain_down: bool = False) -> None:
        if amount <= 0:
            return
        old = unit.current_ep
        cap = unit.max_extra_point
        # EpGainDown debuff仅影响自然回EP（AS/PS技能释放自动回EP、每行动+1），
        # 不影响技能效果中的直接EP增减（如add_ep效果的EP+1）
        reduction_pct = 0.0
        if apply_ep_gain_down:
            for d in unit.debuffs:
                if d.effect_type == SkillEffectType.EP_GAIN_DOWN.value:
                    reduction_pct = max(reduction_pct, d.value)
        # EpGainUp buff: EP获取量增加（百分比），与EpGainDown对称，MAX集计
        increase_pct = 0.0
        if apply_ep_gain_down:
            for b in unit.buffs:
                if b.effect_type == SkillEffectType.EP_GAIN_UP.value:
                    increase_pct = max(increase_pct, b.value)
        effective_amount = amount * (1.0 - reduction_pct / 100.0) * (1.0 + increase_pct / 100.0)
        unit.current_ep = min(unit.current_ep + effective_amount, cap)
        if reduction_pct > 0 or increase_pct > 0:
            _log.info("[RESOURCE] %s generate_ep: %g -> %g (+%g base=%d ep_gain_down=-%.0f%% ep_gain_up=+%.0f%%, cap=%d)",
                      unit.name, old, unit.current_ep, unit.current_ep - old, amount, reduction_pct, increase_pct, cap)
        else:
            _log.info("[RESOURCE] %s generate_ep: %d -> %d (+%d, cap=%d)",
                      unit.name, old, unit.current_ep, unit.current_ep - old, cap)
