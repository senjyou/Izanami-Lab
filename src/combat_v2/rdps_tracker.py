#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RDPS (Raid DPS) 统计追踪器
src/combat_v2/rdps_tracker.py

职责：
- 追踪每场战斗中每个上场角色的真实输出贡献（RDPS）
- 辅助角色的 buff/debuff 贡献归因到施加者，而非受益的 DPS
- 每张回忆卡的贡献独立统计
- 守恒性保证：sum(unit.total_rdps) + sum(memory_card.total_rdps) == total_damage_to_enemies

核心方法：方案A-精确（解析法 baseline_ally）
- 对每个乘区过滤掉我方来源的 buff/debuff，复用 DamageService._aggregate_buff_value 重新聚合
- baseline_ally 保留敌方施加的 buff/debuff 作为前提条件
- bonus_ally = actual_damage - baseline_ally，仅包含我方 buff 的贡献
- 使用 Aumann-Shapley 对数比例法将 bonus_ally 分配到各乘区
"""

import math
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..entities_v2.unit_state import UnitState, BuffState
    from ..entities_v2.battlefield_state import BattlefieldState
    from .services.damage_service import DamageService, DamageResult

_log = logging.getLogger(__name__)


@dataclass
class UnitRDPSStats:
    """单个角色的 RDPS 统计"""
    unit_id: str = ""
    name: str = ""
    side: str = ""

    # === 伤害分类（float 内部精度，输出时转 int） ===
    direct_damage: float = 0.0          # 自身直接伤害（含克制、技能威力、敌方减伤归因、固有暴击）
    buff_contribution: float = 0.0      # 增益贡献（施加 buff 带来的额外伤害）
    debuff_contribution: float = 0.0    # 减益贡献（施加 debuff 带来的额外伤害）
    enchant_contribution: float = 0.0   # 附魔/追加伤害贡献

    # === 乘区细分（调试/展开用） ===
    atk_buff_contribution: float = 0.0
    def_debuff_contribution: float = 0.0
    dealt_dmg_contribution: float = 0.0
    received_dmg_contribution: float = 0.0
    crit_contribution: float = 0.0
    penetrate_contribution: float = 0.0

    @property
    def total_rdps(self) -> float:
        return self.direct_damage + self.buff_contribution + self.debuff_contribution + self.enchant_contribution


@dataclass
class MemoryCardRDPSStats:
    """单张回忆卡的 RDPS 统计"""
    card_id: int = 0
    card_name: str = ""

    buff_contribution: float = 0.0      # 该卡施加 buff 带来的额外伤害
    debuff_contribution: float = 0.0    # 该卡施加 debuff 带来的额外伤害
    direct_damage: float = 0.0          # 该卡直接造成的伤害（如附魔）

    @property
    def total_rdps(self) -> float:
        return self.buff_contribution + self.debuff_contribution + self.direct_damage


@dataclass
class RDPSResult:
    """单场战斗 RDPS 结果"""
    unit_stats: Dict[str, UnitRDPSStats] = field(default_factory=dict)
    memory_card_stats: Dict[int, MemoryCardRDPSStats] = field(default_factory=dict)
    total_damage_to_enemies: int = 0

    # 验证字段
    sum_unit_rdps: int = 0
    sum_memory_rdps: int = 0
    discrepancy: int = 0  # total_damage - sum_unit_rdps - sum_memory_rdps（应为0）

    def to_dict(self) -> dict:
        return {
            "total_damage_to_enemies": self.total_damage_to_enemies,
            "unit_stats": {
                uid: {
                    "unit_id": s.unit_id,
                    "name": s.name,
                    "side": s.side,
                    "direct_damage": int(s.direct_damage),
                    "buff_contribution": int(s.buff_contribution),
                    "debuff_contribution": int(s.debuff_contribution),
                    "enchant_contribution": int(s.enchant_contribution),
                    "total_rdps": int(s.total_rdps),
                    "detail": {
                        "atk_buff": int(s.atk_buff_contribution),
                        "def_debuff": int(s.def_debuff_contribution),
                        "dealt_dmg": int(s.dealt_dmg_contribution),
                        "received_dmg": int(s.received_dmg_contribution),
                        "crit": int(s.crit_contribution),
                        "penetrate": int(s.penetrate_contribution),
                    },
                }
                for uid, s in self.unit_stats.items()
            },
            "memory_card_stats": {
                str(cid): {
                    "card_id": s.card_id,
                    "card_name": s.card_name,
                    "buff_contribution": int(s.buff_contribution),
                    "debuff_contribution": int(s.debuff_contribution),
                    "direct_damage": int(s.direct_damage),
                    "total_rdps": int(s.total_rdps),
                }
                for cid, s in self.memory_card_stats.items()
            },
            "sum_unit_rdps": self.sum_unit_rdps,
            "sum_memory_rdps": self.sum_memory_rdps,
            "discrepancy": self.discrepancy,
        }


class RDPSTracker:
    """RDPS 追踪器

    使用方案A-精确（解析法 baseline_ally）进行伤害归因：
    1. 过滤掉我方来源的 buff/debuff，重新聚合各乘区值得到 baseline_ally
    2. bonus_ally = actual_damage - baseline_ally
    3. 用 Aumann-Shapley 对数比例法将 bonus_ally 分配到各乘区
    4. 每个乘区内按 buff 值比例归因到具体施加者
    """

    def __init__(self, damage_service: 'DamageService' = None):
        self._unit_stats: Dict[str, UnitRDPSStats] = {}
        self._memory_card_stats: Dict[int, MemoryCardRDPSStats] = {}
        self._skill_to_card: Dict[int, int] = {}  # source_skill_id -> card_id
        self._total_damage_to_enemies: int = 0
        self._damage_service: Optional['DamageService'] = damage_service
        self._battlefield: Optional['BattlefieldState'] = None
        self._tracking_enabled: bool = False
        self._tracking_log: List[str] = []
        self._track_event_count: int = 0

    def set_damage_service(self, damage_service: 'DamageService'):
        self._damage_service = damage_service

    def set_battlefield(self, battlefield: 'BattlefieldState'):
        self._battlefield = battlefield

    # ========== 追踪日志 ==========

    def enable_tracking(self):
        """启用追踪日志（单次模拟用，记录每次伤害归因细节）"""
        self._tracking_enabled = True
        self._tracking_log = []
        self._track_event_count = 0

    def disable_tracking(self):
        self._tracking_enabled = False

    def is_tracking_enabled(self) -> bool:
        return self._tracking_enabled

    def get_tracking_log(self) -> List[str]:
        return list(self._tracking_log)

    def _track(self, msg: str):
        if self._tracking_enabled:
            self._tracking_log.append(msg)

    def _track_event_header(self, damage_type: str, caster, target, actual_damage):
        self._track_event_count += 1
        self._track(f"--- RDPS Track #{self._track_event_count:03d} [{damage_type}] ---")
        self._track(f"  {caster.name} ({caster.unit_id}) -> {target.name} ({target.unit_id})")
        self._track(f"  Damage: {actual_damage}")

    # ========== 注册方法 ==========

    def ensure_unit(self, unit_id: str, name: str, side: str):
        if unit_id not in self._unit_stats:
            self._unit_stats[unit_id] = UnitRDPSStats(unit_id=unit_id, name=name, side=side)

    def ensure_memory_card(self, card_id: int, card_name: str):
        if card_id not in self._memory_card_stats:
            self._memory_card_stats[card_id] = MemoryCardRDPSStats(card_id=card_id, card_name=card_name)

    def register_card_skill(self, card_id: int, skill_id: int):
        self._skill_to_card[skill_id] = card_id

    # ========== 主入口 ==========

    def record_damage_with_attribution(self, caster: 'UnitState', target: 'UnitState',
                                       actual_damage: int,
                                       dmg_result: Optional['DamageResult'] = None,
                                       damage_type: str = "main",
                                       enchant_source_id: Optional[str] = None,
                                       battlefield: Optional['BattlefieldState'] = None,
                                       damage_service: Optional['DamageService'] = None,
                                       calc_detail: Optional[dict] = None,
                                       enchant_buff: Optional['BuffState'] = None):
        """记录伤害事件并进行归因

        Args:
            caster: 攻击者
            target: 防御者
            actual_damage: 实际造成的伤害
            dmg_result: DamageResult（主伤害有，附魔等为 None）
            damage_type: "main"/"enchant"/"add_dmg"/"sub_unit"/"hp_ratio"/"special"
            enchant_source_id: 附魔/追加/子单位伤害的 buff 提供者 unit_id
            battlefield: 战场状态
            damage_service: DamageService 实例
            calc_detail: hp_ratio/special 伤害的独立 calc_detail
            enchant_buff: 附魔/追加/子单位 buff 对象（用于判断是否回忆卡 buff）
        """
        if target is None or target.side.value != "enemy":
            return

        if actual_damage <= 0:
            return

        # 确保使用正确的 battlefield 和 damage_service
        bf = battlefield or self._battlefield
        ds = damage_service or self._damage_service
        if ds is None:
            _log.warning("[RDPS] no damage_service available, skipping attribution")
            return

        self._total_damage_to_enemies += actual_damage
        self.ensure_unit(caster.unit_id, caster.name, caster.side.value)

        self._track_event_header(damage_type, caster, target, actual_damage)

        if damage_type in ("enchant", "add_dmg", "sub_unit"):
            self._record_enchant_damage(caster, target, actual_damage, enchant_source_id, bf,
                                        enchant_buff)
            return

        if damage_type in ("hp_ratio", "special"):
            self._record_special_damage(caster, target, actual_damage, damage_type,
                                        calc_detail, bf, ds)
            return

        # 主伤害归因
        if dmg_result is None or dmg_result.calc_detail is None:
            self._add_contribution(caster.unit_id, "direct_damage", float(actual_damage))
            return

        self._record_main_damage(caster, target, actual_damage, dmg_result, bf, ds)

    # ========== 主伤害归因（方案A-精确） ==========

    def _record_main_damage(self, caster: 'UnitState', target: 'UnitState',
                            actual_damage: int, dmg_result: 'DamageResult',
                            battlefield: 'BattlefieldState',
                            damage_service: 'DamageService'):
        """主伤害归因：解析法计算 baseline_ally，log-ratio 分配 bonus"""
        calc = dmg_result.calc_detail

        # Step 1: 解析法计算 baseline_ally
        baseline = self._compute_baseline_ally(caster, target, calc, dmg_result,
                                               damage_service, battlefield)

        # Step 2: 暴击特殊处理
        effective_crit_factor = self._get_effective_crit_factor(dmg_result, calc)
        is_crit = effective_crit_factor > 1.0
        baseline_crit_factor = baseline["baseline_crit_factor"]

        p_base = caster.crit_rate
        p_final = damage_service._calculate_crit_rate(caster)

        if is_crit:
            non_crit_damage = actual_damage / effective_crit_factor
        else:
            non_crit_damage = float(actual_damage)

        # Step 3: baseline_ally_non_crit (提前计算，暴击收益分解需要)
        if is_crit and baseline_crit_factor > 0:
            baseline_ally_non_crit = baseline["baseline_ally"] / baseline_crit_factor
        else:
            baseline_ally_non_crit = baseline["baseline_ally"]

        bonus_ally_non_crit = non_crit_damage - baseline_ally_non_crit

        # Step 4: 暴击收益分解 — 统一修复方案
        # crit_payoff = (baseline_ally_nc + bonus_nc) × (eff_crit - 1)
        #             = baseline_crit_payoff + bonus_crit_payoff
        # baseline部分分配到 direct(inherent) / crit_dmg_up / crit_rate_up
        # bonus部分加入 bonus_for_attribution 做 log-ratio（归因到 non-crit buff 施加者）
        if is_crit:
            baseline_crit_payoff = baseline_ally_non_crit * (effective_crit_factor - 1.0)
            bonus_crit_payoff = bonus_ally_non_crit * (effective_crit_factor - 1.0)

            # crit_dmg_up_share (仅基于baseline，不含bonus_nc泄漏)
            if effective_crit_factor > baseline_crit_factor and effective_crit_factor > 1.0:
                crit_dmg_up_share = baseline_crit_payoff * (effective_crit_factor - baseline_crit_factor) \
                                    / (effective_crit_factor - 1.0)
            else:
                crit_dmg_up_share = 0.0

            # crit_rate_up_share (仅基于baseline，不含bonus_nc泄漏)
            if p_final > p_base and p_final > 0 and effective_crit_factor > 1.0:
                crit_rate_up_share = baseline_crit_payoff * (baseline_crit_factor - 1.0) \
                                     / (effective_crit_factor - 1.0) \
                                     * (p_final - p_base) / p_final
            else:
                crit_rate_up_share = 0.0

            # true_inherent (仅基于baseline的固有暴击收益)
            if baseline_crit_factor > 1.0 and p_final > 0:
                true_inherent = baseline_ally_non_crit * (baseline_crit_factor - 1.0) * p_base / p_final
            elif baseline_crit_factor > 1.0:
                # p_final=0 但仍暴击（强制暴击/技能bonus），整个 baseline 暴击收益归 direct
                true_inherent = baseline_crit_payoff
            else:
                true_inherent = 0.0

            # bonus部分 = bonus_nc + bonus_crit_payoff (non-crit buff 的直接收益 + 暴击放大收益)
            bonus_for_attribution = bonus_ally_non_crit + bonus_crit_payoff
        else:
            crit_dmg_up_share = 0.0
            crit_rate_up_share = 0.0
            true_inherent = 0.0
            bonus_crit_payoff = 0.0
            bonus_for_attribution = bonus_ally_non_crit

        self._track(f"  [baseline] atk={baseline['baseline_atk']} def={baseline['baseline_def_orig']} "
                    f"base_diff={baseline['baseline_base_diff']} crit_f={baseline_crit_factor:.3f} "
                    f"dealt={baseline['baseline_dealt_mult']:.3f} recv={baseline['baseline_received_mult']:.3f}")
        self._track(f"  [baseline_ally] {baseline['baseline_ally']:.1f} -> non_crit {baseline_ally_non_crit:.1f}")
        self._track(f"  [actual] {actual_damage} | crit={is_crit} eff_crit_f={effective_crit_factor:.3f} "
                    f"p_base={p_base:.4f} p_final={p_final:.4f}")
        self._track(f"  [bonus] non_crit={non_crit_damage:.1f} bonus_nc={bonus_ally_non_crit:.1f} "
                    f"crit_dmg_up={crit_dmg_up_share:.1f} crit_rate_up={crit_rate_up_share:.1f} "
                    f"true_inherent={true_inherent:.1f} bonus_crit_payoff={bonus_crit_payoff:.1f} "
                    f"bonus_for_attr={bonus_for_attribution:.1f}")
        self._track(f"  [direct] {caster.unit_id} += {baseline_ally_non_crit + true_inherent:.1f}")

        # 直接伤害基数 = baseline_ally_non_crit + true_inherent（仅baseline的暴击收益）
        self._add_contribution(caster.unit_id, "direct_damage",
                               baseline_ally_non_crit + true_inherent)

        if abs(bonus_for_attribution) > 0.5 or crit_dmg_up_share > 0.5 or crit_rate_up_share > 0.5:
            m_base_diff, m_dealt, m_received, m_crit_dmg = self._compute_zone_multipliers(
                calc, baseline, effective_crit_factor)

            self._track(f"  [zones] m_base_diff={m_base_diff:.4f} m_dealt={m_dealt:.4f} "
                        f"m_received={m_received:.4f} m_crit_dmg={m_crit_dmg:.4f}")

            # non_crit 部分 log-ratio（含 leaked_crit）
            non_crit_zones = {"base_diff": m_base_diff, "dealt": m_dealt, "received": m_received}
            log_sum_nc = sum(math.log(v) for v in non_crit_zones.values() if v > 0 and v != 1.0)

            if log_sum_nc != 0:
                for zone_name, m_val in non_crit_zones.items():
                    if m_val > 0 and m_val != 1.0:
                        share = bonus_for_attribution * math.log(m_val) / log_sum_nc
                        self._track(f"  [zone:{zone_name}] m={m_val:.4f} share={share:.1f}")
                        self._attribute_zone(zone_name, caster, target, share,
                                             baseline, calc, battlefield, damage_service)
            elif abs(bonus_for_attribution) > 0.5:
                # 无乘区变化但 bonus != 0（leaked_crit 或浮点误差），归攻击者
                self._track(f"  [zone:fallback] bonus_for_attr={bonus_for_attribution:.1f} -> direct")
                self._track(f"  [direct] {caster.unit_id} += {bonus_for_attribution:.1f}")
                self._add_contribution(caster.unit_id, "direct_damage", bonus_for_attribution)

            # crit_damage_up 归因
            if crit_dmg_up_share > 0.5:
                self._track(f"  [crit_dmg_up] share={crit_dmg_up_share:.1f}")
                self._attribute_buffs_by_value(
                    caster, caster.buffs, caster.debuffs,
                    "CriticalBonusModification",
                    crit_dmg_up_share, "buff_contribution", "crit_contribution",
                    battlefield, damage_service)

            # crit_rate_up 归因
            if crit_rate_up_share > 0.5:
                self._track(f"  [crit_rate_up] share={crit_rate_up_share:.1f}")
                self._attribute_buffs_by_value(
                    caster, caster.buffs, caster.debuffs,
                    "StatusCriticalChance",
                    crit_rate_up_share, "buff_contribution", "crit_contribution",
                    battlefield, damage_service)

    def _compute_baseline_ally(self, caster: 'UnitState', target: 'UnitState',
                               calc: dict, dmg_result: 'DamageResult',
                               damage_service: 'DamageService',
                               battlefield: 'BattlefieldState') -> dict:
        """解析法计算 baseline_ally：移除我方 buff/debuff，保留敌方 buff/debuff"""

        def enemy_only(buffs_list, ref_caster):
            return [b for b in buffs_list if not self._is_ally_source(b, ref_caster)]

        from ..entities_v2.enums import SkillEffectType as SET

        # === ATK 乘区 ===
        raw_atk = caster.attack
        enemy_atk_pct = damage_service._aggregate_buff_value_signed(
            enemy_only(caster.buffs, caster), enemy_only(caster.debuffs, caster),
            SET.STATUS_ATTACK.value, value_tag=0, unit=caster)
        enemy_atk_fixed = damage_service._aggregate_buff_value_signed(
            enemy_only(caster.buffs, caster), enemy_only(caster.debuffs, caster),
            SET.STATUS_ATTACK.value, value_tag=1, unit=caster)
        baseline_atk = max(0, int(raw_atk * (1.0 + enemy_atk_pct) + enemy_atk_fixed))

        # === DEF 乘区 ===
        raw_def = target.defense
        enemy_def_pct = damage_service._aggregate_buff_value_signed(
            enemy_only(target.buffs, caster), enemy_only(target.debuffs, caster),
            SET.STATUS_DEFENSE.value, value_tag=0, unit=target)
        enemy_def_fixed = damage_service._aggregate_buff_value_signed(
            enemy_only(target.buffs, caster), enemy_only(target.debuffs, caster),
            SET.STATUS_DEFENSE.value, value_tag=1, unit=target)
        baseline_def_orig = max(0, int(raw_def * (1.0 + enemy_def_pct) + enemy_def_fixed))

        # === 穿透乘区 ===
        baseline_penetrate_pct = calc.get("ignore_def_pct", 0)
        baseline_def_after_penetrate = max(0, int(baseline_def_orig * (1.0 - baseline_penetrate_pct / 100.0)))
        baseline_base_diff = max(1, baseline_atk - baseline_def_after_penetrate)

        # === 暴击乘区 ===
        is_crit = self._is_crit_happened(dmg_result)
        if is_crit:
            inherent_crit_damage = caster.crit_damage
            enemy_crit_dmg = damage_service._aggregate_buff_value_signed(
                enemy_only(caster.buffs, caster), enemy_only(caster.debuffs, caster),
                SET.CRITICAL_BONUS_MODIFICATION.value, unit=caster)
            baseline_crit_factor = 1.5 + inherent_crit_damage + enemy_crit_dmg
        else:
            baseline_crit_factor = 1.0

        # === 给予伤害乘区 ===
        enemy_dealt_pct = damage_service._aggregate_buff_value_signed(
            enemy_only(caster.buffs, caster), enemy_only(caster.debuffs, caster),
            SET.DEALT_DAMAGE.value, unit=caster)
        baseline_dealt_mult = 1.0 + enemy_dealt_pct

        # === 受击伤害乘区（公式: 1 - net） ===
        enemy_received_net = damage_service._aggregate_buff_value_signed(
            enemy_only(target.buffs, caster), enemy_only(target.debuffs, caster),
            SET.RECEIVED_DAMAGE.value, unit=target, attacker=caster)
        baseline_received_mult = max(0.0, 1.0 - enemy_received_net)

        # === 计算 baseline_ally ===
        skill_factor = calc.get("skill_factor", 1.0)
        attr_factor = calc.get("attr_factor", 1.0)
        guard_mult = calc.get("guard_mult", 1.0)
        hp_scaling = calc.get("hp_scaling", 1.0)

        baseline_ally = (baseline_base_diff * skill_factor * attr_factor
                         * baseline_crit_factor * baseline_dealt_mult * baseline_received_mult
                         * guard_mult * hp_scaling)

        return {
            "baseline_ally": baseline_ally,
            "baseline_atk": baseline_atk,
            "baseline_def_orig": baseline_def_orig,
            "baseline_def_after_penetrate": baseline_def_after_penetrate,
            "baseline_base_diff": baseline_base_diff,
            "baseline_crit_factor": baseline_crit_factor,
            "baseline_dealt_mult": baseline_dealt_mult,
            "baseline_received_mult": baseline_received_mult,
            "baseline_penetrate_pct": baseline_penetrate_pct,
        }

    # ========== 乘区归因 ==========

    def _compute_zone_multipliers(self, calc: dict, baseline: dict,
                                  effective_crit_factor: float):
        """计算各乘区乘率 m_i = actual / baseline_ally"""
        bbd = baseline["baseline_base_diff"]
        m_base_diff = calc["base_diff"] / bbd if bbd > 0 else 1.0

        bcf = baseline["baseline_crit_factor"]
        m_crit_dmg = effective_crit_factor / bcf if bcf > 0 else 1.0

        bdm = baseline["baseline_dealt_mult"]
        m_dealt = calc["dealt_mult"] / bdm if bdm != 0 else 1.0

        brm = baseline["baseline_received_mult"]
        m_received = calc["received_mult"] / brm if brm != 0 else 1.0

        return m_base_diff, m_dealt, m_received, m_crit_dmg

    def _attribute_zone(self, zone_name: str, caster: 'UnitState', target: 'UnitState',
                        share: float, baseline: dict, calc: dict,
                        battlefield: 'BattlefieldState',
                        damage_service: 'DamageService'):
        """将某乘区的 share 归因到具体 buff 施加者"""
        if abs(share) < 0.5:
            return

        from ..entities_v2.enums import SkillEffectType as SET

        if zone_name == "base_diff":
            self._attribute_atk_def_penetrate(caster, target, share, baseline, calc,
                                              battlefield, damage_service)
        elif zone_name == "dealt":
            # dealt 乘区仅由 DEALT_DAMAGE buff/debuff 决定（_get_damage_dealt_multiplier
            # 仅聚合 DEALT_DAMAGE）。SKILL_POWER_DOWN 影响 skill_factor（独立乘区），
            # 不属于 dealt 乘区，不应在此归因。
            # 原实现错误地额外调用 SKILL_POWER_DOWN 归因（使用相同 share），
            # 导致 share 双重计入：第一次归因到 DealtDamage buff，第二次因无 buff
            # 触发 fallback 将同一 share 再计入 direct_damage。
            self._attribute_buffs_by_value(
                caster, caster.buffs, caster.debuffs,
                SET.DEALT_DAMAGE.value,
                share, "buff_contribution", "dealt_dmg_contribution",
                battlefield, damage_service)
        elif zone_name == "received":
            self._attribute_buffs_by_value(
                caster, target.buffs, target.debuffs,
                SET.RECEIVED_DAMAGE.value,
                share, "debuff_contribution", "received_dmg_contribution",
                battlefield, damage_service)

    def _attribute_atk_def_penetrate(self, caster: 'UnitState', target: 'UnitState',
                                     share: float, baseline: dict, calc: dict,
                                     battlefield: 'BattlefieldState',
                                     damage_service: 'DamageService'):
        """ATK/DEF/穿透 乘区归因（分解为子乘区）"""
        from ..entities_v2.enums import SkillEffectType as SET

        actual_atk = calc["atk"]
        actual_def_orig = calc["def_orig"]
        actual_base_diff = calc["base_diff"]
        baseline_atk = baseline["baseline_atk"]
        baseline_def_orig = baseline["baseline_def_orig"]
        baseline_base_diff = baseline["baseline_base_diff"]

        # 纯 ATK/DEF 乘区
        actual_bd_no_pen = max(1, actual_atk - actual_def_orig)
        baseline_bd_no_pen = max(1, baseline_atk - baseline_def_orig)
        m_atk_def = actual_bd_no_pen / baseline_bd_no_pen if baseline_bd_no_pen > 0 else 1.0

        # 穿透乘区
        m_actual_pen = actual_base_diff / actual_bd_no_pen if actual_bd_no_pen > 0 else 1.0
        m_baseline_pen = baseline_base_diff / baseline_bd_no_pen if baseline_bd_no_pen > 0 else 1.0
        m_penetrate = m_actual_pen / m_baseline_pen if m_baseline_pen > 0 else 1.0

        sub_zones = {"atk_def": m_atk_def, "penetrate": m_penetrate}
        log_sum = sum(math.log(v) for v in sub_zones.values() if v > 0 and v != 1.0)

        self._track(f"  [base_diff] share={share:.1f} m_atk_def={m_atk_def:.4f} "
                    f"m_penetrate={m_penetrate:.4f} log_sum={log_sum:.4f}")

        if log_sum == 0:
            if abs(share) > 0.5:
                self._track(f"  [base_diff] no sub-zone change -> direct({caster.unit_id}) += {share:.1f}")
                self._add_contribution(caster.unit_id, "direct_damage", share)
            return

        atk_def_share = share * math.log(m_atk_def) / log_sum if m_atk_def > 0 and m_atk_def != 1.0 else 0.0
        penetrate_share = share * math.log(m_penetrate) / log_sum if m_penetrate > 0 and m_penetrate != 1.0 else 0.0

        self._track(f"  [base_diff] atk_def_share={atk_def_share:.1f} penetrate_share={penetrate_share:.1f}")

        # ATK/DEF 子乘区
        if abs(atk_def_share) > 0.5:
            delta_atk = actual_atk - baseline_atk
            delta_def = baseline_def_orig - actual_def_orig
            denom = delta_atk + delta_def
            if denom != 0:
                atk_share = atk_def_share * delta_atk / denom
                def_share = atk_def_share * delta_def / denom
            else:
                atk_share = atk_def_share
                def_share = 0.0

            self._attribute_buffs_by_value(
                caster, caster.buffs, caster.debuffs,
                SET.STATUS_ATTACK.value,
                atk_share, "buff_contribution", "atk_buff_contribution",
                battlefield, damage_service,
                base_stat_unit=caster)
            self._attribute_buffs_by_value(
                caster, target.buffs, target.debuffs,
                SET.STATUS_DEFENSE.value,
                def_share, "debuff_contribution", "def_debuff_contribution",
                battlefield, damage_service,
                base_stat_unit=target)

        # 穿透子乘区
        if abs(penetrate_share) > 0.5:
            self._attribute_buffs_by_value(
                caster, caster.buffs, caster.debuffs,
                SET.PENETRATE_DEFENSE.value,
                penetrate_share, "buff_contribution", "penetrate_contribution",
                battlefield, damage_service)

    def _compute_buff_weight(self, buff: 'BuffState', effect_type: str,
                             base_stat_unit: Optional['UnitState'],
                             damage_service: 'DamageService') -> float:
        """计算buff的有效贡献权重，使百分比buff和固值buff在同一尺度上可比

        固值buff(value_tag=1): 权重=value（绝对值）
        百分比buff(value_tag=0): 权重=value/100 * base_stat（转换为等效固值）

        对于ATK/DEF等存在混合类型的乘区，此方法确保比例分配公平。
        例如：+1000固值ATK 和 +50%ATK(base_atk=2000) 实际各贡献1000 ATK，
        修复前权重为 1000 vs 0.5（极度不均衡），修复后权重为 1000 vs 1000（公平分配）。
        """
        val = abs(damage_service._normalize_buff_value(buff))
        if val == 0:
            return 0
        if getattr(buff, 'value_tag', 0) == 1:
            return val
        from ..entities_v2.enums import SkillEffectType as SET
        if effect_type == SET.STATUS_ATTACK.value and base_stat_unit is not None:
            return val * base_stat_unit.attack
        elif effect_type == SET.STATUS_DEFENSE.value and base_stat_unit is not None:
            return val * base_stat_unit.defense
        return val

    def _attribute_buffs_by_value(self, caster: 'UnitState',
                                  buffs: List['BuffState'], debuffs: List['BuffState'],
                                  effect_type: str, share: float,
                                  contribution_field: str, detail_field: str,
                                  battlefield: 'BattlefieldState',
                                  damage_service: 'DamageService',
                                  base_stat_unit: Optional['UnitState'] = None,
                                  debuff_effect_type: Optional[str] = None,
                                  debuff_contribution_field: Optional[str] = None):
        """按 buff 值比例归因到具体施加者

        Args:
            effect_type: buff 的效果类型
            debuff_effect_type: debuff 的效果类型（默认与 effect_type 相同）。
                当 buff 和 debuff 使用不同 effect_type 时（如 dealt 乘区的
                DealtDamage buff 与 SKILL_POWER_DOWN debuff），必须通过此参数
                在单次调用中合并归因，避免多次调用导致 share 双重计入。
            debuff_contribution_field: debuff 的角色归因字段（默认与 contribution_field 相同）
        """
        if abs(share) < 0.5:
            return

        buff_eff = effect_type
        debuff_eff = debuff_effect_type or effect_type

        ally_buffs = [b for b in buffs if b.effect_type == buff_eff
                      and self._is_ally_source(b, caster)]
        ally_debuffs = [d for d in debuffs if d.effect_type == debuff_eff
                        and self._is_ally_source(d, caster)]

        all_sources = []
        for b in ally_buffs:
            val = self._compute_buff_weight(b, buff_eff, base_stat_unit, damage_service)
            if val > 0:
                all_sources.append((b, val, "buff"))
        for d in ally_debuffs:
            val = self._compute_buff_weight(d, debuff_eff, base_stat_unit, damage_service)
            if val > 0:
                all_sources.append((d, val, "debuff"))

        total_val = sum(v for _, v, _ in all_sources)

        # 追踪日志：buff 权重明细（诊断回忆卡/混合buff归因问题的关键点）
        if self._tracking_enabled and all_sources:
            base_desc = (f"base={base_stat_unit.name}(atk={base_stat_unit.attack})"
                         if base_stat_unit else "base=None")
            eff_desc = (f"buff_eff={buff_eff} debuff_eff={debuff_eff}"
                        if debuff_eff != buff_eff else f"effect_type={buff_eff}")
            self._track(f"  [buff_attr] {eff_desc} share={share:.1f} "
                        f"field={contribution_field} {base_desc}")
            for buff, val, kind in all_sources:
                src = buff.source_unit_id or "(self)"
                card_mark = f" card_skill={buff.source_skill_id}" if buff.is_memory_buff else ""
                self._track(f"    - {kind} '{buff.name}' val_tag={getattr(buff,'value_tag',0)} "
                            f"raw_val={buff.value} weight={val:.2f} src={src}{card_mark}")
            self._track(f"    total_weight={total_val:.2f}")

        if total_val == 0:
            if abs(share) > 0.5:
                self._track(f"    [direct] {caster.unit_id} += {share:.1f} (no ally buffs)")
                self._add_contribution(caster.unit_id, "direct_damage", share)
            return

        for buff, val, kind in all_sources:
            contribution = share * val / total_val
            if abs(contribution) < 0.01:
                continue

            # 记忆卡独立统计：只归因到回忆卡，不归因到角色（避免双重计算）
            if buff.is_memory_buff and buff.source_skill_id:
                card_id = self._skill_to_card.get(buff.source_skill_id)
                if card_id is not None:
                    card_field = "buff_contribution" if kind == "buff" else "debuff_contribution"
                    self._track(f"    -> card {card_id} += {contribution:.1f} ({card_field})")
                    self._add_memory_card_contribution(card_id, card_field, contribution)
                    continue

            source_id = buff.source_unit_id or caster.unit_id
            self.ensure_unit(source_id, self._get_unit_name(source_id, battlefield),
                             caster.side.value)
            unit_field = contribution_field if kind == "buff" \
                else (debuff_contribution_field or contribution_field)
            self._track(f"    -> unit {source_id} += {contribution:.1f} ({unit_field})")
            self._add_contribution(source_id, unit_field, contribution,
                                   detail_field, contribution)

    # ========== 附魔/追加/子单位伤害 ==========

    def _record_enchant_damage(self, caster: 'UnitState', target: 'UnitState',
                               actual_damage: int, enchant_source_id: Optional[str],
                               battlefield: 'BattlefieldState',
                               enchant_buff: Optional['BuffState'] = None):
        """附魔/追加/子单位伤害：100% 归因于 buff 提供者

        若 buff 来自回忆卡，归因到回忆卡的 direct_damage 而非角色 enchant_contribution
        """
        # 回忆卡附魔/追加/子单位伤害 → 归因到回忆卡
        if enchant_buff is not None and enchant_buff.is_memory_buff and enchant_buff.source_skill_id:
            card_id = self._skill_to_card.get(enchant_buff.source_skill_id)
            if card_id is not None:
                self._track(f"  [enchant] memory_card {card_id} += {actual_damage} (direct_damage)")
                self._add_memory_card_contribution(card_id, "direct_damage", float(actual_damage))
                return

        if not enchant_source_id:
            enchant_source_id = caster.unit_id

        source_name = self._get_unit_name(enchant_source_id, battlefield)
        self.ensure_unit(enchant_source_id, source_name, caster.side.value)
        self._track(f"  [enchant] unit {enchant_source_id} += {actual_damage} (enchant_contribution)")
        self._add_contribution(enchant_source_id, "enchant_contribution", float(actual_damage))

    # ========== HP比例/特殊伤害 ==========

    def _record_special_damage(self, caster: 'UnitState', target: 'UnitState',
                               actual_damage: int, damage_type: str,
                               calc_detail: Optional[dict],
                               battlefield: 'BattlefieldState',
                               damage_service: 'DamageService'):
        """HP比例/特殊伤害归因"""
        if not calc_detail:
            self._add_contribution(caster.unit_id, "direct_damage", float(actual_damage))
            return

        from ..entities_v2.enums import SkillEffectType as SET

        if damage_type == "hp_ratio":
            self._record_hp_ratio_damage(caster, target, actual_damage,
                                         calc_detail, battlefield, damage_service)
        elif damage_type == "special":
            self._record_damage_special(caster, target, actual_damage,
                                        calc_detail, battlefield, damage_service)
        else:
            self._add_contribution(caster.unit_id, "direct_damage", float(actual_damage))

    def _record_hp_ratio_damage(self, caster: 'UnitState', target: 'UnitState',
                                actual_damage: int, calc_detail: dict,
                                battlefield: 'BattlefieldState',
                                damage_service: 'DamageService'):
        """HP比例伤害归因
        calc_detail: {value_source, dmg_pct, base_value, raw_power, cap, effective_atk, cap_atk_pct}
        - raw_power = base_value × dmg_pct / 100
        - cap = effective_atk × cap_atk_pct / 100
        - 当 raw_power > cap 时，实际伤害 = cap，ATK buff 影响伤害
        - 当 raw_power <= cap 时，实际伤害 = raw_power，ATK buff 无影响
        """
        from ..entities_v2.enums import SkillEffectType as SET

        raw_power = calc_detail.get("raw_power", 0)
        cap = calc_detail.get("cap", 0)
        effective_atk = calc_detail.get("effective_atk", 0)
        cap_atk_pct = calc_detail.get("cap_atk_pct", 0)

        self._track(f"  [hp_ratio] raw_power={raw_power} cap={cap} eff_atk={effective_atk} "
                    f"cap_atk_pct={cap_atk_pct} raw_atk={caster.attack}")

        if cap <= 0 or raw_power <= cap:
            # 未触及上限：全归 direct_damage
            self._track(f"  [hp_ratio] uncapped -> direct({caster.unit_id}) += {actual_damage}")
            self._add_contribution(caster.unit_id, "direct_damage", float(actual_damage))
            return

        # 触及上限：伤害 = cap
        # baseline_cap = raw_atk × cap_atk_pct / 100
        raw_atk = caster.attack
        baseline_cap = raw_atk * cap_atk_pct / 100.0
        bonus = float(actual_damage) - baseline_cap

        # 直接伤害 = baseline_cap
        self._track(f"  [hp_ratio] capped: baseline_cap={baseline_cap:.1f} bonus={bonus:.1f}")
        self._track(f"  [direct] {caster.unit_id} += {baseline_cap:.1f}")
        self._add_contribution(caster.unit_id, "direct_damage", baseline_cap)

        if bonus > 0.5:
            # bonus 按 ATK buff 比例归因
            self._attribute_buffs_by_value(
                caster, caster.buffs, caster.debuffs,
                SET.STATUS_ATTACK.value,
                bonus, "buff_contribution", "atk_buff_contribution",
                battlefield, damage_service,
                base_stat_unit=caster)
        elif bonus < -0.5:
            # 负向偏差（如guard/shield扣减）归 direct_damage 以保持守恒
            self._track(f"  [direct] {caster.unit_id} += {bonus:.1f} (negative bonus)")
            self._add_contribution(caster.unit_id, "direct_damage", bonus)

    def _record_damage_special(self, caster: 'UnitState', target: 'UnitState',
                               actual_damage: int, calc_detail: dict,
                               battlefield: 'BattlefieldState',
                               damage_service: 'DamageService'):
        """特殊伤害归因
        calc_detail: {value_source, dmg_pct, base_value, effective_value}
        - value_source="self_max_hp": effective_value = max_hp × pct，受 max_hp_up 影响
        - value_source="self_current_hp": effective_value = current_hp × pct，不受 buff 影响
        - else (ATK模式): effective_value = atk × pct，受 ATK buff 影响
        """
        from ..entities_v2.enums import SkillEffectType as SET

        value_source = calc_detail.get("value_source", "")
        dmg_pct = calc_detail.get("dmg_pct", 100)
        effective_value = calc_detail.get("effective_value", 0)
        base_value = calc_detail.get("base_value", 0)

        self._track(f"  [special] value_source={value_source} dmg_pct={dmg_pct} "
                    f"base_value={base_value} eff_value={effective_value}")

        if value_source == "self_current_hp":
            # 不受 buff 影响，全归 direct
            self._track(f"  [special] self_current_hp -> direct({caster.unit_id}) += {actual_damage}")
            self._add_contribution(caster.unit_id, "direct_damage", float(actual_damage))
            return

        if value_source == "self_max_hp":
            raw_max_hp = caster.max_hp
            baseline_value = raw_max_hp * dmg_pct / 100.0
            bonus = float(actual_damage) - baseline_value
            self._track(f"  [special] self_max_hp: baseline={baseline_value:.1f} bonus={bonus:.1f}")
            self._track(f"  [direct] {caster.unit_id} += {baseline_value:.1f}")
            self._add_contribution(caster.unit_id, "direct_damage", baseline_value)
            if bonus > 0.5:
                self._attribute_buffs_by_value(
                    caster, caster.buffs, caster.debuffs,
                    SET.STATUS_MAX_HP.value,
                    bonus, "buff_contribution", "atk_buff_contribution",
                    battlefield, damage_service)
            elif bonus < -0.5:
                self._track(f"  [direct] {caster.unit_id} += {bonus:.1f} (negative bonus)")
                self._add_contribution(caster.unit_id, "direct_damage", bonus)
            return

        # 默认 ATK 模式
        raw_atk = caster.attack
        baseline_value = raw_atk * dmg_pct / 100.0
        bonus = float(actual_damage) - baseline_value
        self._track(f"  [special] atk_mode: baseline={baseline_value:.1f} bonus={bonus:.1f}")
        self._track(f"  [direct] {caster.unit_id} += {baseline_value:.1f}")
        self._add_contribution(caster.unit_id, "direct_damage", baseline_value)
        if bonus > 0.5:
            self._attribute_buffs_by_value(
                caster, caster.buffs, caster.debuffs,
                SET.STATUS_ATTACK.value,
                bonus, "buff_contribution", "atk_buff_contribution",
                battlefield, damage_service,
                base_stat_unit=caster)
        elif bonus < -0.5:
            self._track(f"  [direct] {caster.unit_id} += {bonus:.1f} (negative bonus)")
            self._add_contribution(caster.unit_id, "direct_damage", bonus)

    # ========== 辅助方法 ==========

    def _is_ally_source(self, buff: 'BuffState', caster: 'UnitState') -> bool:
        """判断 buff 施加者是否与 caster 同阵营（我方）

        注意：is_memory_buff 不能用于判断阵营。敌方舞台增量buff也设置
        is_memory_buff=True（用于阶段清理），但其 source_unit_id 指向敌方单位。
        必须优先通过 source_unit_id 查找来源单位的阵营来判断。
        """
        if not buff.source_unit_id:
            return True
        source_unit = self._find_unit_by_id(buff.source_unit_id)
        if source_unit is None:
            # 来源无法定位时，回忆卡保守视为我方，其他视为非我方
            return bool(buff.is_memory_buff)
        return source_unit.side == caster.side

    def _find_unit_by_id(self, unit_id: str) -> Optional['UnitState']:
        if self._battlefield is None:
            return None
        return self._battlefield.get_unit_by_id(unit_id)

    def _get_unit_name(self, unit_id: str, battlefield: 'BattlefieldState') -> str:
        unit = battlefield.get_unit_by_id(unit_id) if battlefield else None
        return unit.name if unit else unit_id

    def _get_effective_crit_factor(self, dmg_result: 'DamageResult', calc: dict) -> float:
        """获取有效暴击乘率"""
        if calc.get("crit_factor", 1.0) > 1.0:
            return calc["crit_factor"]

        if not dmg_result or not dmg_result.hit_crits or not any(dmg_result.hit_crits):
            return 1.0

        if not dmg_result.hit_details:
            return 1.0

        crit_hits = [d for d, c in zip(dmg_result.hit_details, dmg_result.hit_crits) if c and d > 0]
        non_crit_hits = [d for d, c in zip(dmg_result.hit_details, dmg_result.hit_crits) if not c and d > 0]

        if not crit_hits:
            return 1.0
        if not non_crit_hits:
            return 1.5

        avg_non_crit = sum(non_crit_hits) / len(non_crit_hits)
        avg_crit = sum(crit_hits) / len(crit_hits)
        return avg_crit / avg_non_crit if avg_non_crit > 0 else 1.5

    def _is_crit_happened(self, dmg_result: 'DamageResult') -> bool:
        if dmg_result is None:
            return False
        if dmg_result.is_critical:
            return True
        if dmg_result.hit_crits and any(dmg_result.hit_crits):
            return True
        return False

    # ========== 贡献记录 ==========

    def _add_contribution(self, unit_id: str, field_name: str, value: float,
                          detail_field: str = None, detail_value: float = None):
        """添加贡献到角色统计"""
        if unit_id not in self._unit_stats:
            self._unit_stats[unit_id] = UnitRDPSStats(unit_id=unit_id, name=unit_id)

        stats = self._unit_stats[unit_id]
        if hasattr(stats, field_name):
            setattr(stats, field_name, getattr(stats, field_name) + value)
        if detail_field and hasattr(stats, detail_field):
            setattr(stats, detail_field, getattr(stats, detail_field) + (detail_value if detail_value is not None else value))

    def _add_memory_card_contribution(self, card_id: int, field_name: str, value: float):
        """添加贡献到记忆卡统计"""
        if card_id not in self._memory_card_stats:
            self._memory_card_stats[card_id] = MemoryCardRDPSStats(card_id=card_id)
        stats = self._memory_card_stats[card_id]
        if hasattr(stats, field_name):
            setattr(stats, field_name, getattr(stats, field_name) + value)

    # ========== 结果构建 ==========

    def build_result(self, units: Optional[list] = None,
                     memory_cards: Optional[list] = None) -> RDPSResult:
        """构建最终 RDPS 结果

        Args:
            units: 战场单位列表，用于补充未注册的角色
            memory_cards: 回忆卡列表，用于补充名称
        """
        # 确保所有上场单位都在统计中（即使没造成伤害）
        if units:
            for unit in units:
                if unit.side.value == "ally":
                    self.ensure_unit(unit.unit_id, unit.name, unit.side.value)

        # 补充记忆卡名称
        if memory_cards:
            for card in memory_cards:
                card_id = getattr(card, 'card_id', 0)
                card_name = getattr(card, 'name', '')
                if card_id and card_id in self._memory_card_stats:
                    self._memory_card_stats[card_id].card_name = card_name

        # 计算汇总
        sum_unit = sum(s.total_rdps for s in self._unit_stats.values())
        sum_memory = sum(s.total_rdps for s in self._memory_card_stats.values())

        # 浮点取整误差归一化
        total_int = self._total_damage_to_enemies
        sum_unit_int = int(round(sum_unit))
        sum_memory_int = int(round(sum_memory))
        discrepancy = total_int - sum_unit_int - sum_memory_int

        if discrepancy != 0 and self._unit_stats:
            # 误差分配给 direct_damage 最大的角色
            max_unit_id = max(self._unit_stats,
                              key=lambda uid: self._unit_stats[uid].direct_damage)
            self._unit_stats[max_unit_id].direct_damage += discrepancy
            sum_unit_int += discrepancy
            discrepancy = 0

        return RDPSResult(
            unit_stats=dict(self._unit_stats),
            memory_card_stats=dict(self._memory_card_stats),
            total_damage_to_enemies=total_int,
            sum_unit_rdps=sum_unit_int,
            sum_memory_rdps=sum_memory_int,
            discrepancy=discrepancy,
        )

    # ========== 守恒性验证 ==========

    def verify_tracking_log_conservation(self) -> list:
        """验证追踪日志的逐次攻击守恒性

        解析 _tracking_log，对每个 track 检查:
            direct + buff_contribution + debuff_contribution + enchant_contribution == actual_damage

        Returns:
            violations: list of dict，每个包含 track/actual/direct/buff/debuff/enchant/total/diff。
            空列表表示所有 track 守恒（差异在容差内）。
        """
        import re

        if not self._tracking_log:
            return []

        violations = []
        current_track_lines: List[str] = []
        track_num = 0

        def _check_track(num, lines):
            actual = 0
            for line in lines:
                m = re.match(r'\s*Damage: (\d+)', line)
                if m:
                    actual = int(m.group(1))
                    break

            direct = 0.0
            buff = 0.0
            debuff = 0.0
            enchant = 0.0

            for line in lines:
                line = line.strip()
                m = re.search(r'\[direct\] \S+ \+= (-?[\d.]+)', line)
                if m:
                    direct += float(m.group(1))
                    continue
                m = re.search(r'uncapped -> direct\(\S+\) \+= (-?[\d.]+)', line)
                if m:
                    direct += float(m.group(1))
                    continue
                m = re.search(r'(?:-> |\[enchant\] )unit \S+ \+= (-?[\d.]+) \((\w+)\)', line)
                if m:
                    val = float(m.group(1))
                    field = m.group(2)
                    if field == 'buff_contribution':
                        buff += val
                    elif field == 'debuff_contribution':
                        debuff += val
                    elif field == 'enchant_contribution':
                        enchant += val
                    elif field == 'direct_damage':
                        direct += val
                    continue
                m = re.search(r'(?:-> card |\[enchant\] memory_card )\d+ \+= (-?[\d.]+) \((\w+)\)', line)
                if m:
                    val = float(m.group(1))
                    field = m.group(2)
                    if field == 'buff_contribution':
                        buff += val
                    elif field == 'debuff_contribution':
                        debuff += val
                    elif field == 'direct_damage':
                        enchant += val
                    continue

            total = direct + buff + debuff + enchant
            if abs(total - actual) > 1.0:
                violations.append({
                    'track': str(num),
                    'actual': actual,
                    'direct': direct,
                    'buff': buff,
                    'debuff': debuff,
                    'enchant': enchant,
                    'total': total,
                    'diff': total - actual,
                })

        for line in self._tracking_log:
            if line.startswith('--- RDPS Track #'):
                if current_track_lines:
                    _check_track(track_num, current_track_lines)
                track_num += 1
                current_track_lines = []
            else:
                current_track_lines.append(line)
        if current_track_lines:
            _check_track(track_num, current_track_lines)

        return violations

    def verify_total_conservation(self) -> int:
        """验证总量守恒性: sum(unit.total_rdps) + sum(memory_card.total_rdps) == total_damage

        Returns:
            discrepancy: 总伤害 - 总归因（应为0，允许浮点误差±1）
        """
        sum_unit = sum(s.total_rdps for s in self._unit_stats.values())
        sum_memory = sum(s.total_rdps for s in self._memory_card_stats.values())
        return int(round(self._total_damage_to_enemies - sum_unit - sum_memory))

