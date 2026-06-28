from typing import Tuple, List, Dict
from ...entities_v2.unit_state import UnitState
from ...entities_v2.enums import SkillEffectType
from ..battle_logger import battle_logger

_log = battle_logger()

class StatusService:
    """
    状态服务
    负责检查状态（眩晕/冰冻）和处理持续性效果（DOT/HOT）
    """
    
    def is_stunned(self, unit: UnitState) -> bool:
        """检查单位是否眩晕"""
        stunned = self._has_effect(unit, SkillEffectType.KNOCKOUT.value)
        if stunned:
            _log.info("[STATUS] %s is STUNNED", unit.name)
        return stunned

    def is_frozen(self, unit: UnitState) -> bool:
        """检查单位是否冰冻"""
        frozen = self._has_effect(unit, SkillEffectType.FREEZE.value)
        if frozen:
            _log.info("[STATUS] %s is FROZEN", unit.name)
        return frozen

    def is_confused(self, unit: UnitState) -> bool:
        """检查单位是否混乱"""
        confused = self._has_effect(unit, SkillEffectType.CONFUSION.value)
        if confused:
            _log.info("[STATUS] %s is CONFUSED", unit.name)
        return confused

    def get_confusion_buff(self, unit: UnitState):
        """获取单位的混乱debuff（用于读取参数），无则返回None"""
        for buff in unit.debuffs:
            if buff.effect_type == SkillEffectType.CONFUSION.value:
                return buff
        for buff in unit.buffs:
            if buff.effect_type == SkillEffectType.CONFUSION.value:
                return buff
        return None

    def apply_burn_damage(self, unit: UnitState) -> tuple:
        burn_buffs = [b for b in unit.debuffs if b.effect_type == SkillEffectType.CONFLAGRATION.value]
        count = len(burn_buffs)
        multiplier = 2 if count >= 3 else 1

        if count > 0:
            _log.info("[STATUS] %s BURN: stacks=%d mult=%dx", unit.name, count, multiplier)

        total_damage = 0
        calc_detail = None
        for i, debuff in enumerate(burn_buffs):
            base_damage = int(debuff.value)
            final_damage = base_damage * multiplier
            total_damage += self._apply_direct_damage(unit, final_damage)
            _log.info("[STATUS]   burn[%d]: base=%d final=%d hp:%d->%d",
                      i + 1, base_damage, final_damage,
                      unit.current_hp + final_damage, unit.current_hp)

        if total_damage > 0:
            calc_detail = {
                "base_damage": int(burn_buffs[0].value) if burn_buffs else 0,
                "multiplier": multiplier,
                "stacks": count,
            }

        return total_damage, count, calc_detail

    def apply_poison_damage(self, unit: UnitState) -> tuple:
        total_damage = 0
        poison_buffs = [b for b in unit.debuffs if b.effect_type == SkillEffectType.POISON.value]
        calc_detail = None

        if poison_buffs:
            _log.info("[STATUS] %s POISON: effects=%d hp_ratio=%.3f",
                      unit.name, len(poison_buffs),
                      poison_buffs[0].value if poison_buffs else 0)

        for debuff in poison_buffs:
            current_hp_damage = int(unit.current_hp * debuff.value)
            caster_attack_cap = int(debuff.caster_attack * 1.0) if hasattr(debuff, 'caster_attack') and debuff.caster_attack else current_hp_damage
            damage = min(current_hp_damage, caster_attack_cap)
            damage = max(1, damage)
            total_damage += self._apply_direct_damage(unit, damage)
            _log.info("[STATUS]   poison: hp%%_dmg=%d cap=%d final=%d hp:%d->%d",
                      int(unit.current_hp * debuff.value), caster_attack_cap,
                      damage, unit.current_hp + damage, unit.current_hp)
            if calc_detail is None:
                calc_detail = {
                    "hp_pct": debuff.value,
                    "atk_cap": caster_attack_cap,
                }

        return total_damage, calc_detail

    def apply_regen(self, unit: UnitState, damage_service=None, battlefield=None) -> Tuple[int, List[Dict]]:
        """应用HOT回复效果。

        Args:
            unit: 目标单位
            damage_service: 伤害服务（用于治疗量乘区计算）
            battlefield: 战场状态（用于caster_alive检查）

        Returns:
            (total_heal, regen_details): 总回复量和详情列表
            regen_details中每个dict包含: amount, source_unit_id
        """
        total_heal = 0
        regen_details = []
        buffs_to_remove = []
        for buff in unit.buffs:
            if buff.effect_type == SkillEffectType.HEAL_OVER_TIME.value:
                # caster_alive 检查
                if getattr(buff, 'caster_alive', False) and battlefield is not None:
                    source_unit = next((u for u in battlefield.get_all_units() if u.unit_id == buff.source_unit_id), None)
                    if source_unit and not source_unit.is_alive:
                        # 施法者已死亡，标记移除此buff
                        buffs_to_remove.append(buff)
                        _log.info("[CASTER_ALIVE] %s: HOT removed (caster %s is dead)", unit.name, source_unit.name)
                        continue

                # 根据heal_base计算治疗基数
                hot_heal_base = getattr(buff, 'heal_base', '') or 'atk'
                if hot_heal_base == 'max_hp':
                    heal = int(unit.max_hp * buff.value / 100)
                elif hot_heal_base == 'lost_hp':
                    lost_hp = unit.max_hp - unit.current_hp
                    heal = int(lost_hp * buff.value / 100)
                else:
                    heal = int(buff.caster_attack * buff.value / 100)
                # HOT不暴击，只有即时治疗允许暴击
                # 受到治疗量乘区
                if damage_service is not None:
                    heal_received_mult = damage_service._get_heal_received_multiplier(unit)
                    if heal_received_mult != 1.0:
                        heal = int(heal * heal_received_mult)
                if unit.current_hp < unit.max_hp:
                    old_hp = unit.current_hp
                    unit.current_hp = min(unit.current_hp + heal, unit.max_hp)
                    actual = unit.current_hp - old_hp
                    total_heal += actual
                    _log.info("[STATUS] %s REGEN: +%d HP (%d->%d)",
                              unit.name, actual, old_hp, unit.current_hp)
                    regen_details.append({
                        'amount': actual,
                        'source_unit_id': buff.source_unit_id,
                    })

        # 移除caster_alive过期的buff
        for b in buffs_to_remove:
            if b in unit.buffs:
                unit.buffs.remove(b)

        return total_heal, regen_details
        
    def apply_action_damage(self, unit: UnitState) -> Tuple[int, int]:
        """行動時ダメージ：行动时受到施法者攻击力x%的伤害（EN伤害）
        行动时伤害可以被盾吸收

        Returns:
            (total_damage, total_shield_absorbed): 总伤害和总盾吸收量
        """
        total_damage = 0
        total_shield_absorbed = 0
        action_dmg_buffs = [b for b in unit.debuffs if b.effect_type == SkillEffectType.ACTION_DAMAGE.value]

        if action_dmg_buffs:
            _log.info("[STATUS] %s ACTION_DAMAGE: effects=%d", unit.name, len(action_dmg_buffs))

        for debuff in action_dmg_buffs:
            # 伤害 = 施法者快照攻击力 × value%
            caster_atk = debuff.caster_attack if hasattr(debuff, 'caster_attack') and debuff.caster_attack else 0
            damage_pct = debuff.value if debuff.value else 0
            damage = int(caster_atk * damage_pct / 100)
            damage = max(1, damage)  # 最低1点伤害

            # 行动时伤害先经过盾吸收，再扣HP
            remaining = damage
            shield_absorbed = 0
            # EN盾优先吸收EN伤害
            if remaining > 0 and unit.en_shield > 0:
                absorb = min(remaining, unit.en_shield)
                shield_absorbed += absorb
                remaining -= absorb
                unit.en_shield -= absorb
            # 通用盾
            if remaining > 0 and unit.shield > 0:
                absorb = min(remaining, unit.shield)
                shield_absorbed += absorb
                remaining -= absorb
                unit.shield -= absorb

            if remaining > 0:
                total_damage += self._apply_direct_damage(unit, remaining)
            total_shield_absorbed += shield_absorbed

            _log.info("[STATUS]   action_damage: atk=%d pct=%.1f%% final=%d shield_absorbed=%d hp:%d->%d",
                      caster_atk, damage_pct, damage, shield_absorbed,
                      unit.current_hp + (remaining if remaining > 0 else 0), unit.current_hp)

        return total_damage, total_shield_absorbed

    def _has_effect(self, unit: UnitState, effect_type_value: str) -> bool:
        """检查是否有指定类型的Buff/Debuff"""
        # 检查Debuffs
        for buff in unit.debuffs:
            if buff.effect_type == effect_type_value:
                return True
        # 检查Buffs
        for buff in unit.buffs:
            if buff.effect_type == effect_type_value:
                return True
        return False
        
    def _apply_direct_damage(self, unit: UnitState, amount: int) -> int:
        """
        应用直接伤害
        注意：
        1. 状态伤害(DOT)穿透护盾，直接扣除HP (已确认机制)
        2. 状态伤害可以致死
        """
        if amount <= 0:
            return 0
            
        old_hp = unit.current_hp
        unit.current_hp = max(0, unit.current_hp - amount)
        damage_dealt = old_hp - unit.current_hp

        # 累计伤害计数：仅记录HP部分
        if damage_dealt > 0:
            unit.cumulative_hp_damage += damage_dealt

        if unit.current_hp == 0:
            unit.is_alive = False
            
        return damage_dealt
