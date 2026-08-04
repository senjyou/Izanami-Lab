from dataclasses import dataclass
from typing import List, Optional, Any, Callable, Dict
from unittest.mock import MagicMock
import math
import random

from ...entities_v2.unit_state import UnitState, BuffState
from ...entities_v2.enums import SkillEffectType, Attribute
from ..battle_logger import battle_logger

_log = battle_logger()

@dataclass
class DamageResult:
    total_damage: int
    is_critical: bool
    attribute_factor: float
    hit_details: List[int]
    hit_crits: List[bool]
    hit_evades: List[bool] = None  # 每hit是否被闪避
    calc_detail: Dict[str, Any] = None  # 伤害计算分解

class DamageService:
    def __init__(self):
        self._crit_override_func: Optional[Callable[[Dict], bool]] = None
        self._crit_context: Dict[str, Any] = {}

    def set_crit_override(self, func: Optional[Callable[[Dict], bool]]):
        """设置暴击覆盖函数。func接收context dict，返回bool（True=暴击）"""
        self._crit_override_func = func

    def clear_crit_override(self):
        """清除暴击覆盖函数，恢复随机判定"""
        self._crit_override_func = None
        self._crit_context = {}

    @staticmethod
    def _normalize_buff_value(buff: BuffState) -> float:
        tag = getattr(buff, "value_tag", 0)
        if tag == 1:
            return float(buff.value)
        return buff.value / 100.0

    @staticmethod
    def _aggregate_buff_value(buffs: List[BuffState], effect_type: str, is_debuff_list: bool = False,
                              value_tag: int = None, unit: UnitState = None,
                              attacker: UnitState = None) -> float:
        """
        按三类buff规则汇总某effect_type的总值：
        - 记忆卡buff (is_memory_buff): 无条件可叠加，全部求和
        - 技能可叠加buff (is_stackable): 可叠加，全部求和
        - 技能不可叠加buff (默认): 取最大值（同effect_type只保留最大）
          注意：debuff也是同理，三类debuff规则相同

        Args:
            value_tag: 可选过滤器，None=不区分，0=仅聚合百分比buff，1=仅聚合固定值buff
            unit: 可选，用于hp_threshold条件检查
            attacker: 可选，用于mark_condition条件检查
        """
        memory_sum = 0.0
        stackable_sum = 0.0
        non_stackable_max = 0.0
        has_non_stackable = False

        for buff in buffs:
            if buff.effect_type != effect_type:
                continue
            # Skip carried_debuff payloads - they don't affect the unit's own stats
            if getattr(buff, 'hit_limited_flags', {}).get('carried_debuff'):
                continue
            # 条件性buff：hp_threshold检查，仅当HP≥阈值时生效
            hp_threshold = getattr(buff, 'hp_threshold', 0)
            if hp_threshold > 0 and unit is not None:
                hp_pct = unit.current_hp / unit.max_hp * 100 if unit.max_hp > 0 else 0
                if hp_pct < hp_threshold:
                    _log.info("[CONDITIONAL_BUFF] %s: %s skipped (HP %.1f%% < threshold %.1f%%)",
                              unit.name, buff.name, hp_pct, hp_threshold)
                    continue
            # 条件性buff：mark_condition检查，仅当攻击者持有指定mark时生效
            mark_cond = getattr(buff, 'mark_condition', '')
            if mark_cond:
                if attacker is None:
                    _log.info("[CONDITIONAL_BUFF] %s: %s skipped (no attacker for mark_condition='%s')",
                              getattr(unit, 'name', '?'), buff.name, mark_cond)
                    continue
                attacker_has_mark = any(
                    (b.effect_type == SkillEffectType.MARK.value and b.name == mark_cond)
                    for b in attacker.buffs
                ) or any(
                    (d.effect_type == SkillEffectType.MARK.value and d.name == mark_cond)
                    for d in attacker.debuffs
                )
                if not attacker_has_mark:
                    _log.info("[CONDITIONAL_BUFF] %s: %s skipped (attacker %s lacks mark '%s')",
                              getattr(unit, 'name', '?'), buff.name, attacker.name, mark_cond)
                    continue
            # 可选：按value_tag过滤（0=百分比，1=固定值）
            if value_tag is not None:
                tag = getattr(buff, "value_tag", 0)
                if tag != value_tag:
                    continue
            val = DamageService._normalize_buff_value(buff)
            # hp_ratio_dynamic: 动态减伤（如130155 たまには羽を伸ばして）
            # 减伤值随持有者实时HP比例变化：HP100%→0%, HP40%及以下→最大值, 线性插值
            # 公式: hp_pct>=0.4时 effective = val * (1-hp_pct)/0.6; hp_pct<0.4时 effective = val
            if getattr(buff, 'hp_ratio_dynamic', False) and unit is not None:
                hp_ratio = unit.current_hp / unit.max_hp if unit.max_hp > 0 else 0
                if hp_ratio >= 0.4:
                    val = val * (1 - hp_ratio) / 0.6
                else:
                    val = val  # 最大值
                _log.info("[HP_RATIO_DYNAMIC] %s: %s hp_ratio=%.4f => dynamic_val=%.4f (max=%.4f)",
                          getattr(unit, 'name', '?'), buff.name, hp_ratio, val,
                          DamageService._normalize_buff_value(buff))
            # hp_ratio_dynamic_direct: 动态减伤（如130156 油断は禁物ですよ）
            # 减伤值随持有者实时HP比例线性变化：HP100%→最大值, HP0%→0%
            # 公式: effective = val * (current_hp / max_hp)
            if getattr(buff, 'hp_ratio_dynamic_direct', False) and unit is not None:
                hp_ratio = unit.current_hp / unit.max_hp if unit.max_hp > 0 else 0
                val = val * hp_ratio
                _log.info("[HP_RATIO_DYNAMIC_DIRECT] %s: %s hp_ratio=%.4f => dynamic_val=%.4f (max=%.4f)",
                          getattr(unit, 'name', '?'), buff.name, hp_ratio, val,
                          DamageService._normalize_buff_value(buff))
            # hp_ratio_dynamic_inverse: 动态增益（如130059 まだ終わんないけど？）
            # 增益值随持有者实时HP比例反比变化：HP100%→0%, HP0%→max, 线性插值
            # 公式: effective = val * (1 - hp_ratio)
            if getattr(buff, 'hp_ratio_dynamic_inverse', False) and unit is not None:
                hp_ratio = unit.current_hp / unit.max_hp if unit.max_hp > 0 else 0
                val = val * (1 - hp_ratio)
                _log.info("[HP_RATIO_DYNAMIC_INVERSE] %s: %s hp_ratio=%.4f => dynamic_val=%.4f (max=%.4f)",
                          getattr(unit, 'name', '?'), buff.name, hp_ratio, val,
                          DamageService._normalize_buff_value(buff))
            if buff.is_memory_buff:
                memory_sum += val
            elif buff.is_stackable:
                stackable_sum += val
            else:
                if abs(val) > abs(non_stackable_max) or not has_non_stackable:
                    non_stackable_max = val
                    has_non_stackable = True

        result = memory_sum + stackable_sum + non_stackable_max
        return result

    def _aggregate_buff_value_signed(self, buffs: List[BuffState], debuffs: List[BuffState],
                                      effect_type: str, value_tag: int = None, unit: UnitState = None,
                                      attacker: UnitState = None) -> float:
        """汇总buff和debuff的净值：buff加，debuff减"""
        buff_val = self._aggregate_buff_value(buffs, effect_type, value_tag=value_tag, unit=unit, attacker=attacker)
        debuff_val = self._aggregate_buff_value(debuffs, effect_type, is_debuff_list=True, value_tag=value_tag, unit=unit, attacker=attacker)
        return buff_val - debuff_val

    def _get_confusion_buff(self, unit: UnitState):
        """获取单位的混乱debuff，无则返回None"""
        for buff in unit.debuffs:
            if buff.effect_type == SkillEffectType.CONFUSION.value:
                return buff
        for buff in unit.buffs:
            if buff.effect_type == SkillEffectType.CONFUSION.value:
                return buff
        return None

    def _aggregate_buff_value_signed_filtered(self, buffs: List[BuffState], debuffs: List[BuffState],
                                               effect_type: str, damage_element: int = 0,
                                               value_tag: int = None, unit: UnitState = None,
                                               attacker: UnitState = None) -> float:
        """汇总buff和debuff的净值，根据damage_element过滤DealtDamage类型buff

        Args:
            damage_element: 0=全属性(不过滤), 1=仅物理, 2=仅能量
        """
        if damage_element == 0:
            return self._aggregate_buff_value_signed(buffs, debuffs, effect_type, value_tag, unit=unit, attacker=attacker)

        # 过滤buffs：仅保留damage_element=0(全属性)或damage_element匹配的buff
        filtered_buffs = []
        for b in buffs:
            if b.effect_type == effect_type:
                b_elem = getattr(b, 'damage_element', 0)
                if b_elem == 0 or b_elem == damage_element:
                    filtered_buffs.append(b)
            else:
                filtered_buffs.append(b)

        filtered_debuffs = []
        for d in debuffs:
            if d.effect_type == effect_type:
                d_elem = getattr(d, 'damage_element', 0)
                if d_elem == 0 or d_elem == damage_element:
                    filtered_debuffs.append(d)
            else:
                filtered_debuffs.append(d)

        buff_val = self._aggregate_buff_value(filtered_buffs, effect_type, value_tag=value_tag, unit=unit, attacker=attacker)
        debuff_val = self._aggregate_buff_value(filtered_debuffs, effect_type, is_debuff_list=True, value_tag=value_tag, unit=unit, attacker=attacker)
        return buff_val - debuff_val

    def calculate_damage(self, attacker: UnitState, defender: UnitState, skill_data: Any,
                         is_cover_damage: bool = False, on_crit_callback=None) -> DamageResult:
        """
        核心伤害计算
        Formula:
        Damage = (Base Diff) * (Skill Power) * (Attribute Factor) * (Crit Factor) * (Damage Dealt Multiplier) * (Damage Received Multiplier)

        Args:
            is_cover_damage: 是否是cover替换伤害（享受新版guard），默认False
            on_crit_callback: 暴击时的回调函数 callback(attacker, defender, hit_number)，
                              用于在多hit中暴击后立即施加易伤等debuff，使后续hit享受该效果
        """
        
        _log.info("[DMG_CALC] %s -> %s | base_ATK=%d base_DEF=%d power=%.1f hits=%d elem=%d ignore_def=%s ignore_shield=%s",
                  attacker.name, defender.name,
                  attacker.attack, defender.defense,
                  getattr(skill_data, "power", 100) or 100,
                  getattr(skill_data, "hit_count", 1) or 1,
                  getattr(skill_data, "element", None) or attacker.element,
                  getattr(skill_data, 'ignore_defense', 0),
                  getattr(skill_data, 'ignore_shield', 0))

        # 1. 基础攻防差
        # base_value_source="received_damage": 反撃系PS（如ストイックリコイル）
        # base值 = 受到伤害 × 威力%，替换一般公式的 (atk-def) × 威力%
        # 享受所有乘区（暴击、克制、增减伤），可作用于盾上
        penetrate = 0.0
        skill_ignore_def = 0
        base_value_source = getattr(skill_data, 'base_value_source', None)
        if base_value_source == "received_damage":
            received_dmg = getattr(attacker, 'last_received_damage', 0)
            base_diff = max(1, received_dmg)
            # 反撃模式仍需atk/defense用于calc_detail记录（不参与base_diff计算）
            atk = self._calculate_final_stat(attacker, "attack")
            defense = self._calculate_final_stat(defender, "defense")
            _log.info("[DMG_CALC] step1_base_diff: RECEIVED_DAMAGE mode, last_received_damage=%d => base_diff=%d",
                      received_dmg, base_diff)
        elif base_value_source == "consume_hp":
            # 自傷HP消費をベース値とするダメージ（如 120156 追加ダメージ）
            # base_diff = 消費HP × 威力% / 100，享受全乘区
            consumed_hp = getattr(attacker, 'last_consumed_hp', 0) or 0
            base_diff = max(1, consumed_hp)
            atk = self._calculate_final_stat(attacker, "attack")
            defense = self._calculate_final_stat(defender, "defense")
            _log.info("[DMG_CALC] step1_base_diff: CONSUME_HP mode, last_consumed_hp=%d => base_diff=%d",
                      consumed_hp, base_diff)
        else:
            atk = self._calculate_final_stat(attacker, "attack")
            defense = self._calculate_final_stat(defender, "defense")

            penetrate = self._aggregate_buff_value_signed(attacker.buffs, attacker.debuffs,
                                                         SkillEffectType.PENETRATE_DEFENSE.value)

            skill_ignore_def = getattr(skill_data, 'ignore_defense', 0) or 0
            if skill_ignore_def > 0:
                penetrate += skill_ignore_def / 100.0

            if penetrate > 0:
                orig = defense
                defense = max(0, int(defense * (1 - min(penetrate, 1.0))))
                if defense != orig:
                    _log.info("[DMG_CALC] penetrate_defense: def %d → %d (%.0f%%)",
                              orig, defense, penetrate * 100)

            base_diff = max(1, atk - defense)
            _log.info("[DMG_CALC] step1_base_diff: final_atk=%d final_def=%d => base_diff=%d", atk, defense, base_diff)

        # 混乱处理：代理数值（ATK ≤ DEF时用ATK×代理%替代base_diff）
        confusion_dmg_reduction = 0.0
        if getattr(attacker, 'is_confused', False):
            confusion_buff = self._get_confusion_buff(attacker)
            if confusion_buff:
                confusion_dmg_reduction = confusion_buff.confusion_dmg_reduction
                proxy_pct = confusion_buff.confusion_proxy_atk_pct
                # 仅在正常 ATK-DEF 模式下应用代理数值（received_damage/consume_hp模式不适用）
                if base_value_source not in ("received_damage", "consume_hp") and atk <= defense and proxy_pct > 0:
                    orig_base_diff = base_diff
                    base_diff = max(1, int(atk * proxy_pct / 100.0))
                    _log.info("[DMG_CALC] CONFUSION proxy: atk=%d <= def=%d, base_diff %d -> %d (atk×%.0f%%)",
                              atk, defense, orig_base_diff, base_diff, proxy_pct)
                _log.info("[DMG_CALC] CONFUSION: dmg_reduction=%.1f%%", confusion_dmg_reduction)
        
        # 2. 技能威力因子
        skill_power_val = getattr(skill_data, "power", 100) or 100
        skill_factor = skill_power_val / 100.0
        # skill_power_down debuff: 攻击者持有的SkillPower威力扣减debuff (S6 若雷 230384)
        # 多个skill_power_down debuff叠加（取和），按百分比扣减skill_factor
        _sp_down_pct = 0.0
        for _db in attacker.debuffs:
            if _db.effect_type == SkillEffectType.SKILL_POWER_DOWN.value:
                _sp_down_pct += float(getattr(_db, 'value', 0) or 0)
        if _sp_down_pct > 0:
            _orig_factor = skill_factor
            skill_factor = skill_factor * max(0.0, 1.0 - _sp_down_pct / 100.0)
            _log.info("[DMG_CALC] SKILL_POWER_DOWN: %.1f%% reduction -> factor %.4f -> %.4f",
                      _sp_down_pct, _orig_factor, skill_factor)
        _log.info("[DMG_CALC] step2_skill_factor: power=%.1f => factor=%.4f (after sp_down=%.1f%%)",
                  skill_power_val, skill_factor, _sp_down_pct)
        
        # 3. 属性克制因子
        skill_element = getattr(skill_data, "element", None) or attacker.element
        attr_factor = self._get_attribute_factor(skill_element, defender.element, attacker)
        _log.info("[DMG_CALC] step3_attr_factor: atk_elem=%d def_elem=%d => factor=%.4f",
                  skill_element, defender.element, attr_factor)
        
        # 5. 给予伤害倍率（根据技能伤害类型过滤）
        # character_type: 1=物理, 2=EN(能量), 3=敏捷(物理)
        char_type = getattr(attacker, 'character_type', 0)
        skill_damage_element = 2 if char_type == 2 else 1
        damage_dealt_mult = self._get_damage_dealt_multiplier(attacker, defender, damage_element=skill_damage_element)
        _log.info("[DMG_CALC] step4_dealt_mult: %.4f", damage_dealt_mult)
        
        # 6. 受击方增减伤倍率（根据技能伤害类型过滤）
        damage_received_mult = self._get_damage_received_multiplier(defender, damage_element=skill_damage_element, attacker=attacker)
        _log.info("[DMG_CALC] step5_received_mult: %.4f", damage_received_mult)

        # 7. 格挡(Guard)倍率
        guard_mult = self._get_guard_multiplier(defender, is_cover_damage=is_cover_damage)
        _log.info("[DMG_CALC] step6_guard_mult: %.4f", guard_mult)
        
        # 8. 多Hit + 暴击计算
        hit_count = getattr(skill_data, "hit_count", 1) or 1
        
        total_damage = 0
        hits = []
        hit_crits = []
        hit_evades = []
        is_any_crit = False
        crit_factor = 1.0
        hp_scaling_factor = 1.0
        
        crit_rate = self._calculate_crit_rate(attacker)
        bonus_crit = getattr(skill_data, "bonus_crit_rate", 0.0) or 0.0
        if bonus_crit > 0:
            crit_rate += bonus_crit / 100.0
        cannot_crit = getattr(skill_data, "cannot_crit", False) or False
        if not cannot_crit:
            for debuff in attacker.debuffs:
                if debuff.effect_type == SkillEffectType.CRITICAL_FORBIDDEN.value:
                    cannot_crit = True
                    _log.info("[DMG_CALC] %s: critical_forbidden debuff active -> cannot_crit=True", attacker.name)
                    break
        # force_crit: 强制必定暴击（无视暴击率和暴击禁止debuff）
        # 参考 リディアたいちょうのめいれい(110039) L11+ 後列横一列会心攻撃
        _fc = getattr(skill_data, "force_crit", False)
        force_crit = _fc if isinstance(_fc, bool) else False
        if force_crit:
            cannot_crit = False  # force_crit 覆盖 cannot_crit
            _log.info("[DMG_CALC] %s: force_crit=True, critical forced", attacker.name)
        _log.info("[DMG_CALC] step6_crit_loop: hit_count=%d crit_rate=%.4f cannot_crit=%s bonus_crit=%.1f force_crit=%s",
                  hit_count, crit_rate, cannot_crit, bonus_crit, force_crit)

        # 暗闇チェック（per-skill 一次判定）：攻撃者が暗闇debuffを持有する場合、指定確率でMISS
        # 暗闇はバフ「必中」の効果を無視し、指定確率でスキルの命中を操作
        # 複数の暗闇debuffは独立共存、各々独立して掷骰、いずれか命中即MISS（実MISS率 = 1 - ∏(1-pᵢ)）
        darkness_debuffs = [d for d in attacker.debuffs if d.effect_type == SkillEffectType.DARKNESS.value]
        if darkness_debuffs:
            import random as _rng
            darkness_miss = False
            for d_buff in darkness_debuffs:
                d_pct = getattr(d_buff, 'value', 0) or 0
                if _rng.random() * 100 < d_pct:
                    darkness_miss = True
                    _log.info("[DARKNESS_MISS] %s: darkness debuff (pct=%.1f%%) triggered MISS on skill %s -> %s",
                              attacker.name, d_pct, getattr(skill_data, 'skill_id', '?'), defender.name)
                    break
            if darkness_miss:
                # 全hit设置为闪避（MISS），伤害为0
                for i_hit in range(hit_count):
                    hits.append(0)
                    hit_crits.append(False)
                    hit_evades.append(True)
                _log.info("[DARKNESS_MISS] %s -> %s: all %d hits MISS due to darkness (no evade buff consumed)",
                          attacker.name, defender.name, hit_count)
                return DamageResult(
                    total_damage=0,
                    is_critical=False,
                    attribute_factor=1.0,
                    hit_details=[0] * hit_count,
                    hit_crits=[False] * hit_count,
                    hit_evades=[True] * hit_count,
                    calc_detail={"darkness_miss": True},
                )

        for i_hit in range(hit_count):
            # Per-hit evade check
            # 蓄力中不能回避
            evade_buffs = [b for b in defender.buffs if b.effect_type == SkillEffectType.EVADE.value and b.hit_limited > 0]
            if evade_buffs and not getattr(defender, 'is_charging', False):
                # 必中效果优先：攻击者持有sure_hit时，防御者的闪避不触发且不消耗
                sure_hit_buffs = [b for b in attacker.buffs if b.effect_type == SkillEffectType.SURE_HIT.value]
                if sure_hit_buffs:
                    _log.info("[EVADE_HIT] %s has sure_hit, %s's evade NOT triggered (hit[%d])",
                              attacker.name, defender.name, i_hit + 1)
                else:
                    ev_buff = evade_buffs[0]
                    # 概率回避判定: ev_buff.value > 0 时表示回避概率%（如60.0=60%）
                    # value为0或null时默认100%回避（向后兼容）
                    evade_chance = getattr(ev_buff, 'value', 0) or 0
                    if evade_chance <= 0:
                        # 默认100%回避（向后兼容）
                        evade_triggered = True
                    else:
                        evade_triggered = random.random() * 100 < evade_chance
                        _log.info("[EVADE_HIT] %s evade chance=%.1f%%, hit[%d] roll=%s",
                                  defender.name, evade_chance, i_hit + 1,
                                  "SUCCESS" if evade_triggered else "FAIL")

                    if evade_triggered:
                        ev_buff.hit_limited -= 1
                        _log.info("[EVADE_HIT] %s evades hit[%d] from %s! hit_limited=%d",
                                  defender.name, i_hit + 1, attacker.name, ev_buff.hit_limited)
                        if ev_buff.hit_limited <= 0:
                            defender.buffs = [b for b in defender.buffs if b.buff_id != ev_buff.buff_id]
                            _log.info("[EVADE_HIT] %s: Evade buff EXPIRED", defender.name)
                        # This hit is evaded
                        hits.append(0)
                        hit_crits.append(False)
                        hit_evades.append(True)
                        continue
                    # 回避失败：hit_limited不消耗，继续伤害计算

            # 4. 暴击因子 (每Hit独立)
            if cannot_crit:
                is_crit = False
                crit_factor = 1.0
            elif force_crit:
                # force_crit: 必定暴击（无视暴击率）
                is_crit = True
                crit_factor = 1.5 + self._get_crit_damage_bonus(attacker)
                is_any_crit = True
                _log.info("[DMG_CALC] %s: force_crit hit[%d] -> is_crit=True, crit_factor=%.3f",
                          attacker.name, i_hit + 1, crit_factor)
            else:
                # 设置暴击上下文（供crit_override使用）
                self._crit_context = {
                    'source': 'main_attack',
                    'attacker_name': attacker.name,
                    'attacker_id': attacker.unit_id,
                    'target_name': defender.name,
                    'target_id': defender.unit_id,
                    'skill_name': getattr(skill_data, 'name', ''),
                    'skill_id': getattr(skill_data, 'skill_id', 0),
                    'hit_number': i_hit + 1,
                    'total_hits': hit_count,
                    'cannot_crit': cannot_crit,
                }
                is_crit = self._check_crit(crit_rate)
                if is_crit:
                    crit_factor = 1.5 + self._get_crit_damage_bonus(attacker)
                    is_any_crit = True
                else:
                    crit_factor = 1.0
            
            # 计算单Hit伤害
            hp_scaling_bonus = getattr(skill_data, "hp_scaling_bonus", 0.0) or 0.0
            hp_scaling_factor = 1.0 + hp_scaling_bonus / 100.0 if hp_scaling_bonus > 0 else 1.0
            raw_damage = (
                base_diff *
                skill_factor *
                attr_factor *
                crit_factor *
                damage_dealt_mult *
                damage_received_mult *
                guard_mult *
                hp_scaling_factor
            )

            final_hit_damage = math.floor(raw_damage)
            final_hit_damage = max(1, final_hit_damage)

            # 130160 サマータイム・ロマンス: HP阈值减伤 (dmg_taken_down_threshold)
            # 仅超过 threshold (current_hp × threshold_pct%) 的伤害部分按 value% 减免
            # 公式: actual = min(dmg, threshold) + max(0, dmg - threshold) × (1 - value/100)
            # hit_limited 控制可生效的hit次数 (1/2/3)，每次被击中消耗1次
            for _dtd_buff in defender.buffs:
                if _dtd_buff.effect_type != "dmg_taken_down_threshold":
                    continue
                if getattr(_dtd_buff, 'hit_limited', 0) <= 0:
                    continue
                _thr_pct = getattr(_dtd_buff, 'threshold_pct', 0) or 0
                _thr_base = getattr(_dtd_buff, 'threshold_base', 'current_hp') or 'current_hp'
                if _thr_base == 'max_hp':
                    _threshold = defender.max_hp * _thr_pct / 100.0
                else:
                    _threshold = defender.current_hp * _thr_pct / 100.0
                _reduction_val = DamageService._normalize_buff_value(_dtd_buff)
                if final_hit_damage > _threshold and _threshold > 0:
                    _orig_dtd = final_hit_damage
                    _excess = final_hit_damage - _threshold
                    _reduced_excess = int(_excess * (1.0 - _reduction_val))
                    final_hit_damage = max(1, int(_threshold) + _reduced_excess)
                    _log.info("[DMG_TAKEN_DOWN_THRESHOLD] %s: dmg %d -> %d (threshold=%.0f, excess=%d, reduction=%.1f%%)",
                              defender.name, _orig_dtd, final_hit_damage, _threshold, _excess, _reduction_val * 100)
                else:
                    _log.info("[DMG_TAKEN_DOWN_THRESHOLD] %s: dmg %d <= threshold %.0f, no reduction",
                              defender.name, final_hit_damage, _threshold)

            # 混乱伤害减免：所有伤害按dmg_reduction%减少
            if confusion_dmg_reduction > 0:
                orig_final = final_hit_damage
                final_hit_damage = max(1, int(final_hit_damage * (1 - confusion_dmg_reduction / 100.0)))
                _log.info("[DMG_CALC] CONFUSION reduction: %d -> %d (-%.1f%%)",
                          orig_final, final_hit_damage, confusion_dmg_reduction)

            _log.info("[DMG_CALC]   hit[%d]: base_diff=%d skill_factor=%.4f attr_factor=%.4f crit_factor=%.2f dealt_mult=%.4f received_mult=%.4f guard_mult=%.4f hp_scaling=%.4f raw=%.2f final=%d",
                      i_hit + 1, base_diff, skill_factor, attr_factor, crit_factor,
                      damage_dealt_mult, damage_received_mult, guard_mult, hp_scaling_factor,
                      raw_damage, final_hit_damage)
            
            total_damage += final_hit_damage
            hits.append(final_hit_damage)
            hit_crits.append(is_crit)
            hit_evades.append(False)

            # Hit-limited dmg_dealt_down debuff on attacker: 消耗1次后重算dealt_mult
            # 用于实现"1ヒット分の与ダメージを減少させる"（仅1 hit减伤）的精准减伤机制
            # 与attack_limited(per-skill)不同，hit_limited是per-hit消耗，多hit技能仅第1hit减伤
            attacker_hit_limited_dealt_debuffs = [
                d for d in attacker.debuffs
                if d.hit_limited > 0 and d.attack_limited <= 0
                and d.effect_type == SkillEffectType.DEALT_DAMAGE.value
            ]
            for d in attacker_hit_limited_dealt_debuffs:
                d.hit_limited -= 1
                _log.info("[HIT_LIMITED] %s: attacker debuff %s hit_limited %d->%d (after hit[%d])",
                          attacker.name, d.effect_type, d.hit_limited + 1, d.hit_limited, i_hit + 1)
                if d.hit_limited <= 0:
                    attacker.debuffs = [x for x in attacker.debuffs if x.buff_id != d.buff_id]
                    _log.info("[HIT_LIMITED] %s: attacker debuff %s EXPIRED (hit_limited reached 0)",
                              attacker.name, d.effect_type)
            # 若有消耗，重算dealt_mult供后续hit使用
            if attacker_hit_limited_dealt_debuffs:
                damage_dealt_mult = self._get_damage_dealt_multiplier(
                    attacker, defender, damage_element=skill_damage_element)
                _log.info("[HIT_LIMITED] %s: recalculated dealt_mult=%.4f for subsequent hits",
                          attacker.name, damage_dealt_mult)

            # 130160 サマータイム・ロマンス: dmg_taken_down_threshold buff hit_limited消耗
            # 每次被击中消耗1次，hit_limited归零时移除buff
            _dtd_expired = []
            for _dtd_b in defender.buffs:
                if _dtd_b.effect_type != "dmg_taken_down_threshold":
                    continue
                if getattr(_dtd_b, 'hit_limited', 0) <= 0:
                    continue
                _dtd_b.hit_limited -= 1
                _log.info("[DMG_TAKEN_DOWN_THRESHOLD] %s: hit_limited %d->%d (after hit[%d])",
                          defender.name, _dtd_b.hit_limited + 1, _dtd_b.hit_limited, i_hit + 1)
                if _dtd_b.hit_limited <= 0:
                    _dtd_expired.append(_dtd_b.buff_id)
            if _dtd_expired:
                defender.buffs = [b for b in defender.buffs if b.buff_id not in _dtd_expired]
                _log.info("[DMG_TAKEN_DOWN_THRESHOLD] %s: %d buff(s) expired (hit_limited reached 0)",
                          defender.name, len(_dtd_expired))

            # 暴击回调：在当前hit伤害计算完毕后调用，使后续hit能享受易伤效果
            # 回调可能修改defender的debuffs（如施加dmg_taken_up），需重算damage_received_mult
            if is_crit and on_crit_callback:
                on_crit_callback(attacker, defender, i_hit + 1)
                damage_received_mult = self._get_damage_received_multiplier(
                    defender, damage_element=skill_damage_element, attacker=attacker)
                _log.info("[DMG_CALC] on_crit_callback: recalculated received_mult=%.4f for subsequent hits",
                          damage_received_mult)

        _log.info("[DMG_CALC] RESULT: total=%d crit=%s hit_details=%s",
                  total_damage, is_any_crit, hits)

        calc_detail = {
            "atk": atk,
            "def_orig": self._calculate_final_stat(defender, "defense"),
            "def_after_penetrate": defense,
            "penetrate_pct": penetrate * 100,
            "ignore_def_pct": skill_ignore_def,
            "ignore_shield_pct": getattr(skill_data, 'ignore_shield', 0) or 0,
            "base_diff": base_diff,
            "skill_power": skill_power_val,
            "skill_power_after": skill_factor * 100,
            "skill_power_down_pct": _sp_down_pct,
            "skill_factor": skill_factor,
            "attr_factor": attr_factor,
            "crit_factor": crit_factor if hit_count == 1 else 1.0,
            "dealt_mult": damage_dealt_mult,
            "received_mult": damage_received_mult,
            "guard_mult": guard_mult,
            "hp_scaling": hp_scaling_factor,
        }

        return DamageResult(
            total_damage=total_damage,
            is_critical=is_any_crit,
            attribute_factor=attr_factor,
            hit_details=hits,
            hit_crits=hit_crits,
            hit_evades=hit_evades,
            calc_detail=calc_detail,
        )

    def _calculate_final_stat(self, unit: UnitState, stat_name: str) -> int:
        """计算战斗内最终属性: Base * (1 + Sum(百分比/100)) + Sum(固定值) —— 三类buff规则"""
        base_val = getattr(unit, stat_name, 0)

        if stat_name == "attack":
            target_effect = SkillEffectType.STATUS_ATTACK.value
        elif stat_name == "defense":
            target_effect = SkillEffectType.STATUS_DEFENSE.value
        elif stat_name == "speed":
            target_effect = SkillEffectType.STATUS_SPEED.value
        elif stat_name == "max_hp":
            target_effect = SkillEffectType.STATUS_MAX_HP.value
        else:
            target_effect = SkillEffectType.STATUS_DEFENSE.value

        # 百分比buff/debuff：使用三类buff规则汇总 (value_tag=0)
        # 传递 unit 参数以启用 hp_ratio_dynamic_direct 缩放逻辑（如 130156 油断は禁物ですよ）
        multiplier = self._aggregate_buff_value_signed(unit.buffs, unit.debuffs, target_effect, value_tag=0, unit=unit)

        # 固定值buff/debuff：同样使用三类buff规则汇总 (value_tag=1)
        fixed_add = self._aggregate_buff_value_signed(unit.buffs, unit.debuffs, target_effect, value_tag=1, unit=unit)

        # 公式: Base * (1 + Sum(Percent)) + Sum(Fixed)
        final_val = base_val * (1.0 + multiplier) + fixed_add
        # ATK/DEF/SPD等属性最低为0，不允许负数
        return max(0, int(final_val))

    def _get_attribute_factor(self, atk_attr: int, def_attr: int, attacker: UnitState) -> float:
        """
        计算属性克制系数
        公式: 1.25 + 有利属性伤害倍率 (advantage_damage)
        """
        is_advantage = self._check_element_advantage(atk_attr, def_attr)
        
        if is_advantage:
            # 基础 1.25 + 角色特有的 advantage_damage (float)
            base = 1.25
            bonus = getattr(attacker, "advantage_damage", 0.0)
            return base + bonus
        else:
            return 1.0

    def _check_element_advantage(self, atk_element: int, def_element: int) -> bool:
        """
        判断是否属性克制
        1=火, 2=水, 3=风, 4=土, 5=光, 6=暗
        火(1) > 风(3) > 土(4) > 水(2) > 火(1)
        光(5) <-> 暗(6)
        """
        # 转为 Attribute Enum 比较安全
        try:
            a = Attribute(atk_element)
            d = Attribute(def_element)
        except ValueError:
            return False
            
        if a == Attribute.FIRE: return d == Attribute.WIND
        if a == Attribute.WIND: return d == Attribute.EARTH
        if a == Attribute.EARTH: return d == Attribute.WATER
        if a == Attribute.WATER: return d == Attribute.FIRE
        if a == Attribute.LIGHT: return d == Attribute.DARK
        if a == Attribute.DARK: return d == Attribute.LIGHT
        return False

    def _get_damage_dealt_multiplier(self, unit: UnitState, defender: Optional[UnitState] = None,
                                      damage_element: int = 0,
                                      defender_hp_for_condition: Optional[int] = None) -> float:
        """给予伤害倍率: 1.0 + Sum(三类buff) - Sum(三类debuff)

        Args:
            unit: 攻击者
            defender: 防御者（用于条件判断）
            damage_element: 伤害属性过滤 0=全属性(默认), 1=仅物理, 2=仅能量
            defender_hp_for_condition: 条件判断时使用的防御者HP（用于附魔伤害等场景，
                                       避免因直伤已扣减HP导致条件判断错误）
        """
        target_type = SkillEffectType.DEALT_DAMAGE.value

        attacker_hp_pct = unit.current_hp / unit.max_hp if unit.max_hp > 0 else 0

        # 使用三类buff规则汇总，但根据damage_element过滤
        mult = self._aggregate_buff_value_signed_filtered(
            unit.buffs, unit.debuffs, target_type, damage_element, unit=unit)

        # 条件性dmg_dealt_up buff：根据攻击者与防御者HP比例关系决定是否生效
        # - target_hp_ratio_lower_than_self: 仅当攻击者HP比例高于防御者时生效 (130122)
        # - target_hp_ratio_higher_than_self: 仅当防御者HP比例高于攻击者时生效 (130155 Lv11+)
        # 不满足条件时需从mult中扣除（_aggregate已加入）
        for buff in unit.buffs:
            if buff.effect_type == target_type:
                # 属性过滤
                buff_elem = getattr(buff, 'damage_element', 0)
                if damage_element != 0 and buff_elem != 0 and buff_elem != damage_element:
                    continue
                # 130122: 仅对HP比例低于自身的敌人生效（向后兼容hardcoded检查）
                if buff.source_skill_id == 130122 and defender is not None:
                    cond_hp = defender_hp_for_condition if defender_hp_for_condition is not None else defender.current_hp
                    defender_hp_pct = cond_hp / defender.max_hp if defender.max_hp > 0 else 0
                    if defender_hp_pct >= attacker_hp_pct:
                        val = self._normalize_buff_value(buff)
                        mult -= val
                # 130155 Lv11+: 仅对HP比例高于自身的敌人生效（flag-based）
                elif getattr(buff, 'target_hp_ratio_higher_than_self', False) and defender is not None:
                    cond_hp = defender_hp_for_condition if defender_hp_for_condition is not None else defender.current_hp
                    defender_hp_pct = cond_hp / defender.max_hp if defender.max_hp > 0 else 0
                    if defender_hp_pct <= attacker_hp_pct:
                        val = self._normalize_buff_value(buff)
                        mult -= val
                        _log.info("[DMG_DEALT_COND] %s: %s skipped (defender hp_pct=%.4f <= attacker=%.4f)",
                                  unit.name, buff.name, defender_hp_pct, attacker_hp_pct)

        return 1.0 + mult

    def _get_damage_received_multiplier(self, unit: UnitState, damage_element: int = 0,
                                         attacker: UnitState = None) -> float:
        """受击方增减伤乘区: 1.0 - 减伤Buff总和 + 易伤Debuff总和（三类buff规则）

        Args:
            unit: 受击方
            damage_element: 伤害属性过滤 0=全属性(默认), 1=仅物理, 2=仅能量
            attacker: 攻击方，用于mark_condition条件检查
        """
        target_type = SkillEffectType.RECEIVED_DAMAGE.value

        _log.info("[DEBUG_RCVD] %s: checking buffs=%d debuffs=%d damage_element=%d",
                  unit.name, len(unit.buffs), len(unit.debuffs), damage_element)

        # 使用三类buff规则：buff = 减伤（负值），debuff = 易伤（正值）
        # 根据damage_element过滤dmg_taken_up/dmg_taken_down
        if damage_element != 0:
            net = self._aggregate_buff_value_signed_filtered(
                unit.buffs, unit.debuffs, target_type, damage_element, unit=unit, attacker=attacker)
        else:
            net = self._aggregate_buff_value_signed(unit.buffs, unit.debuffs, target_type, unit=unit, attacker=attacker)

        # 条件性dmg_taken_down buff：根据攻击者与受击者HP比例关系决定是否生效
        # - attacker_hp_ratio_gt_self: 仅当攻击者HP比例高于受击者时生效 (130103)
        # 不满足条件时需从net中扣除（_aggregate已加入）
        if attacker is not None:
            self_hp_pct = unit.current_hp / unit.max_hp if unit.max_hp > 0 else 0
            attacker_hp_pct = attacker.current_hp / attacker.max_hp if attacker.max_hp > 0 else 0
            for buff in unit.buffs:
                if buff.effect_type == target_type:
                    # 属性过滤
                    buff_elem = getattr(buff, 'damage_element', 0)
                    if damage_element != 0 and buff_elem != 0 and buff_elem != damage_element:
                        continue
                    # attacker_hp_ratio_gt_self: 攻击者HP比例 > 自身HP比例 时生效
                    if getattr(buff, 'attacker_hp_ratio_gt_self', False):
                        if attacker_hp_pct <= self_hp_pct:
                            val = self._normalize_buff_value(buff)
                            net -= val  # buff値は减伤(負値)，netから引くことで无効化
                            _log.info("[DMG_RCVD_COND] %s: %s skipped (attacker hp_pct=%.4f <= self=%.4f)",
                                      unit.name, buff.name, attacker_hp_pct, self_hp_pct)

        result = max(0.0, 1.0 - net)
        _log.info("[DEBUG_RCVD] %s: net=%.4f result=%.4f",
                  unit.name, net, result)
        return result

    def _get_heal_received_multiplier(self, unit: UnitState) -> float:
        """受到治疗量乘区: 1.0 + ReceivedHealing buff总和 - ReceivedHealing debuff总和

        Args:
            unit: 被治疗方
        """
        target_type = SkillEffectType.RECEIVED_HEALING.value
        net = self._aggregate_buff_value_signed(unit.buffs, unit.debuffs, target_type)
        result = max(0.0, 1.0 + net)
        _log.info("[HEAL_RCVD] %s: heal_efficacy net=%.4f result=%.4f",
                  unit.name, net, result)
        return result

    def _get_guard_multiplier(self, unit: UnitState, is_cover_damage: bool = False) -> float:
        """格挡(Guard)乘区: 1.0 - (旧版buff guard减伤 + 新版特殊机制guard减伤)
        - 旧版guard（130009等）：通过buff系统生效，不受is_cover_damage影响
        - 新版guard（130034 cover附带）：通过unit.guard_active生效，只有cover伤害才享受
        """
        # 旧版guard：通过buff系统
        guard_reduction = self._aggregate_buff_value_signed(unit.buffs, unit.debuffs, SkillEffectType.GUARD.value)

        # 新版guard：只有cover伤害才享受
        if is_cover_damage:
            guard_active = getattr(unit, 'guard_active', False)
            if guard_active and not isinstance(guard_active, MagicMock):
                guard_rate = getattr(unit, 'guard_rate', 0.0)
                if not isinstance(guard_rate, MagicMock):
                    guard_reduction += guard_rate / 100.0

        return max(0.0, 1.0 - guard_reduction)

    def _calculate_crit_rate(self, unit: UnitState) -> float:
        """计算最终暴击率（三类buff规则）"""
        base_crit = unit.crit_rate
        t_type = SkillEffectType.STATUS_CRITICAL_CHANCE.value
        bonus = self._aggregate_buff_value_signed(unit.buffs, unit.debuffs, t_type)
        result = max(0.0, base_crit + bonus)
        _log.debug("[CRIT_RATE] %s: base=%.4f buff_bonus=%.4f final=%.4f",
                   unit.name, base_crit, bonus, result)
        return result

    def _check_crit(self, rate: float) -> bool:
        """判定暴击"""
        if self._crit_override_func is not None:
            ctx = self._crit_context.copy()
            ctx['crit_rate'] = rate
            return self._crit_override_func(ctx)
        return random.random() < rate

    def check_heal_crit(self, caster: UnitState, context: Dict = None) -> bool:
        """判定治疗暴击。暴击率引用治疗发起者，暴击时治疗量固定1.5倍。

        Args:
            caster: 治疗发起者
            context: 额外上下文（用于crit_override），如healer_name, target_name等
        """
        crit_rate = self._calculate_crit_rate(caster)
        return self._check_heal_crit_impl(crit_rate, caster, context)

    def check_heal_crit_with_rate(self, snapshot_crit_rate: float, context: Dict = None) -> bool:
        """判定HOT治疗暴击。使用快照暴击率。

        Args:
            snapshot_crit_rate: HOT创建时快照的暴击率
            context: 额外上下文（用于crit_override）
        """
        return self._check_heal_crit_impl(snapshot_crit_rate, None, context)

    def _check_heal_crit_impl(self, crit_rate: float, caster: Optional[UnitState] = None,
                               context: Dict = None) -> bool:
        """治疗暴击判定内部实现"""
        if self._crit_override_func is not None:
            ctx = {
                'source': 'heal',
                'attacker_name': context.get('healer_name', caster.name if caster else '') if context else (caster.name if caster else ''),
                'attacker_id': caster.unit_id if caster else '',
                'target_name': context.get('target_name', '') if context else '',
                'target_id': context.get('target_id', '') if context else '',
                'skill_name': context.get('skill_name', '') if context else '',
                'skill_id': context.get('skill_id', 0) if context else 0,
                'hit_number': 1,
                'total_hits': 1,
                'crit_rate': crit_rate,
                'cannot_crit': False,
            }
            return self._crit_override_func(ctx)
        return random.random() < crit_rate

    def _get_crit_damage_bonus(self, unit: UnitState) -> float:
        """暴击伤害倍率修正（三类buff规则）"""
        bonus = 0.0
        bonus += getattr(unit, "crit_damage", 0.0)
        
        t_type = SkillEffectType.CRITICAL_BONUS_MODIFICATION.value
        bonus += self._aggregate_buff_value_signed(unit.buffs, unit.debuffs, t_type)
        
        return bonus
