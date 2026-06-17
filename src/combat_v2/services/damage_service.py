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

    def _aggregate_buff_value_signed_filtered(self, buffs: List[BuffState], debuffs: List[BuffState],
                                               effect_type: str, damage_element: int = 0,
                                               value_tag: int = None, unit: UnitState = None,
                                               attacker: UnitState = None) -> float:
        """汇总buff和debuff的净值，根据damage_element过滤DealtDamage类型buff

        Args:
            damage_element: 0=全属性(不过滤), 1=仅物理, 2=仅能量
        """
        if damage_element == 0:
            return self._aggregate_buff_value_signed(buffs, debuffs, effect_type, value_tag, attacker=attacker)

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

        buff_val = self._aggregate_buff_value(filtered_buffs, effect_type, value_tag=value_tag, attacker=attacker)
        debuff_val = self._aggregate_buff_value(filtered_debuffs, effect_type, is_debuff_list=True, value_tag=value_tag, attacker=attacker)
        return buff_val - debuff_val

    def calculate_damage(self, attacker: UnitState, defender: UnitState, skill_data: Any, is_cover_damage: bool = False) -> DamageResult:
        """
        核心伤害计算
        Formula:
        Damage = (Base Diff) * (Skill Power) * (Attribute Factor) * (Crit Factor) * (Damage Dealt Multiplier) * (Damage Received Multiplier)

        Args:
            is_cover_damage: 是否是cover替换伤害（享受新版guard），默认False
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
        
        # 2. 技能威力因子
        skill_power_val = getattr(skill_data, "power", 100) or 100
        skill_factor = skill_power_val / 100.0
        _log.info("[DMG_CALC] step2_skill_factor: power=%.1f => factor=%.4f", skill_power_val, skill_factor)
        
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
        _log.info("[DMG_CALC] step6_crit_loop: hit_count=%d crit_rate=%.4f cannot_crit=%s bonus_crit=%.1f",
                  hit_count, crit_rate, cannot_crit, bonus_crit)
        
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

            # 4. 暴击因子 (每Hit独立)
            if cannot_crit:
                is_crit = False
                crit_factor = 1.0
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

            _log.info("[DMG_CALC]   hit[%d]: base_diff=%d skill_factor=%.4f attr_factor=%.4f crit_factor=%.2f dealt_mult=%.4f received_mult=%.4f guard_mult=%.4f hp_scaling=%.4f raw=%.2f final=%d",
                      i_hit + 1, base_diff, skill_factor, attr_factor, crit_factor,
                      damage_dealt_mult, damage_received_mult, guard_mult, hp_scaling_factor,
                      raw_damage, final_hit_damage)
            
            total_damage += final_hit_damage
            hits.append(final_hit_damage)
            hit_crits.append(is_crit)
            hit_evades.append(False)
        
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
        multiplier = self._aggregate_buff_value_signed(unit.buffs, unit.debuffs, target_effect, value_tag=0)

        # 固定值buff/debuff：同样使用三类buff规则汇总 (value_tag=1)
        fixed_add = self._aggregate_buff_value_signed(unit.buffs, unit.debuffs, target_effect, value_tag=1)

        # 公式: Base * (1 + Sum(Percent)) + Sum(Fixed)
        final_val = base_val * (1.0 + multiplier) + fixed_add
        return int(final_val)

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
            unit.buffs, unit.debuffs, target_type, damage_element)

        # 特殊技能130122的条件：仅当攻击者HP比例高于防御者时生效
        # 需要从buff中单独扣除不满足条件的部分
        for buff in unit.buffs:
            if buff.effect_type == target_type:
                # 属性过滤
                buff_elem = getattr(buff, 'damage_element', 0)
                if damage_element != 0 and buff_elem != 0 and buff_elem != damage_element:
                    continue
                if buff.source_skill_id == 130122 and defender is not None:
                    # 使用传入的HP或当前HP进行条件判断
                    cond_hp = defender_hp_for_condition if defender_hp_for_condition is not None else defender.current_hp
                    defender_hp_pct = cond_hp / defender.max_hp if defender.max_hp > 0 else 0
                    if defender_hp_pct >= attacker_hp_pct:
                        val = self._normalize_buff_value(buff)
                        mult -= val

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
