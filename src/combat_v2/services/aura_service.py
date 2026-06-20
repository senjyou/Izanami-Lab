from typing import List, Optional, Protocol

from ...entities_v2.unit_state import UnitState, BuffState
from ...entities_v2.enums import SkillEffectType, AuraUpdateTiming, AuraType
from ..battle_logger import battle_logger

_log = battle_logger()

class AuraService:
    """
    Buff/Debuff 管理服务
    职责：
    1. 添加 Aura (自动处理叠加/覆盖规则)
    2. 移除 Aura
    3. 更新 Aura 持续时间 (根据 AuraUpdateTiming)
    4. 清理过期 Aura
    """

    def add_aura(self, unit: UnitState, aura: BuffState) -> bool:
        # 1. 检查免疫
        if self._is_immune(unit, aura):
            _log.info("[AURA] %s IMMUNE to %s (value=%.1f dur=%d)",
                      unit.name, aura.effect_type, aura.value, aura.duration)
            return False

        # 1.5 眩晕/冻结: 立即同步标志位，防止同回合内PS触发检查漏过
        if aura.effect_type == SkillEffectType.KNOCKOUT.value:
            unit.is_stunned = True
            # 眩晕立即打断蓄力（AP已扣除，不退还）
            if unit.is_charging and unit.charge_skill_id:
                _log.info("[CHARGE_CANCEL] %s: 眩晕立即打断蓄力 [skill_id=%d]",
                          unit.name, unit.charge_skill_id)
                unit.is_charging = False
                unit.charge_skill_id = 0
        elif aura.effect_type == SkillEffectType.FREEZE.value:
            unit.is_frozen = True

        # 2. 区分 Buff 和 Debuff 列表
        target_list = self._get_target_list(unit, aura)
        list_name = "debuffs" if target_list is unit.debuffs else "buffs"

        # 3. 记忆卡buff：无条件可叠加，直接追加
        if aura.is_memory_buff:
            target_list.append(aura)
            _log.info("[AURA] %s add memory_buff %s [%s] val=%.1f dur=%d -> APPEND",
                      unit.name, aura.effect_type, list_name, aura.value, aura.duration)
            return True

        # 4. 技能可叠加buff：带stackable标记，buff_id已唯一化，直接追加
        if aura.is_stackable:
            target_list.append(aura)
            _log.info("[AURA] %s add stackable %s [%s] val=%.1f dur=%d -> APPEND",
                      unit.name, aura.effect_type, list_name, aura.value, aura.duration)
            return True

        # 5. 特殊类型buff处理
        # 毒 (Poison): 保留伤害上限更高的
        if aura.effect_type == SkillEffectType.POISON.value:
            self._handle_poison_stacking(target_list, aura)
            return True

        # 炎上 (Conflagration): 可共存 (直接添加为新实例)
        if aura.effect_type == SkillEffectType.CONFLAGRATION.value:
            target_list.append(aura)
            return True

        # 6. 技能不可叠加buff：同一目标上同effect_type只保留最大值
        #    先按buff_id精确匹配（同源同技能），再按effect_type匹配（不同源）
        existing_index = -1
        for i, existing in enumerate(target_list):
            if existing.buff_id == aura.buff_id:
                existing_index = i
                break

        if existing_index != -1:
            # 存在同源同ID: 覆盖 (刷新持续时间/数值)
            if aura.effect_type in [SkillEffectType.KNOCKOUT.value, SkillEffectType.FREEZE.value]:
                old_dur = target_list[existing_index].duration
                if aura.duration > old_dur:
                    target_list[existing_index] = aura
                else:
                    pass
            else:
                old_aura = target_list[existing_index]
                if abs(aura.value) > abs(old_aura.value):
                    target_list[existing_index] = aura
                    _log.info("[AURA] %s: non-stackable %s value updated %.1f -> %.1f (max, same buff_id)",
                              unit.name, aura.effect_type, old_aura.value, aura.value)
                elif aura.duration > old_aura.duration:
                    old_aura.duration = aura.duration
                    _log.info("[AURA] %s: non-stackable %s duration refreshed %.1f (value kept, same buff_id)",
                              unit.name, aura.effect_type, aura.value)
        else:
            # 不同源但同effect_type的不可叠加buff：取最大值
            existing_by_type = -1
            for i, existing in enumerate(target_list):
                if (existing.effect_type == aura.effect_type
                        and not existing.is_memory_buff
                        and not existing.is_stackable):
                    existing_by_type = i
                    break

            if existing_by_type != -1:
                old_aura = target_list[existing_by_type]
                if abs(aura.value) > abs(old_aura.value):
                    target_list[existing_by_type] = aura
                    _log.info("[AURA] %s: non-stackable %s value updated %.1f -> %.1f (max, diff source)",
                              unit.name, aura.effect_type, old_aura.value, aura.value)
                elif aura.duration > old_aura.duration and abs(aura.value) == abs(old_aura.value):
                    old_aura.duration = aura.duration
                    _log.info("[AURA] %s: non-stackable %s duration refreshed %.1f (value kept, diff source)",
                              unit.name, aura.effect_type, aura.value)
                else:
                    _log.info("[AURA] %s: non-stackable %s IGNORED (existing %.1f >= new %.1f)",
                              unit.name, aura.effect_type, old_aura.value, aura.value)
            else:
                target_list.append(aura)
                _log.info("[AURA] %s add non-stackable %s [%s] val=%s dur=%d -> APPEND",
                          unit.name, aura.effect_type, list_name, aura.value, aura.duration)

        return True

    def remove_aura(self, unit: UnitState, buff_id: str):
        """移除指定 ID 的 Aura"""
        # ID 可能在 buff 或 debuff 中 (虽然通常 ID 应该唯一，但分开查更安全)
        unit.buffs = [b for b in unit.buffs if b.buff_id != buff_id or getattr(b, 'unremovable', False)]
        unit.debuffs = [b for b in unit.debuffs if b.buff_id != buff_id or getattr(b, 'unremovable', False)]
        self._sync_stun_freeze_flags(unit)

    def remove_aura_by_type(self, unit: UnitState, effect_type: str):
        """移除指定类型的 Aura (驱散)"""
        unit.buffs = [b for b in unit.buffs if b.effect_type != effect_type or getattr(b, 'unremovable', False)]
        unit.debuffs = [b for b in unit.debuffs if b.effect_type != effect_type or getattr(b, 'unremovable', False)]
        self._sync_stun_freeze_flags(unit)

    def process_maneuver_end(self, unit: UnitState):
        """
        行动结束时的结算
        """
        expired_before = [b.effect_type for b in unit.buffs + unit.debuffs if b.duration <= 0]
        self._update_duration(unit, [
            AuraUpdateTiming.EPHEMERAL_MANEUVER_END,
            AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END,
            AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END
        ])
        expired_after = [b.effect_type for b in unit.buffs + unit.debuffs if b.duration <= 0]
        newly_expired = set(expired_after) - set(expired_before)
        if newly_expired:
            _log.info("[AURA] %s expired: %s", unit.name, list(newly_expired))

    def process_round_end(self, unit: UnitState):
        """
        回合结束时的结算 (罕见，部分 TurnEnd Timing)
        注意: 文档 SkillTriggerTimings 有 TurnEnd, 但 AuraUpdateTimings 主要是 ManeuverEnd.
        如果有 AuraUpdateTiming.TURN_END (这里假设对应 Custom 或 未列出的逻辑，暂不处理除非有 ID)
        """
        pass

    def process_turn_end(self, unit: UnitState):
        """
        回合结束时递减 duration_type="turn" 的buff/debuff持续时间
        （如damage_link等回合制效果，不在单位行动结束时递减）
        """
        expired_before = [b.effect_type for b in unit.buffs + unit.debuffs if b.duration <= 0]
        for b in unit.buffs + unit.debuffs:
            if getattr(b, 'original_duration_type', '') == 'turn' and b.duration > 0:
                b.duration -= 1
                _log.info("[AURA_TURN_END] %s: %s duration %d->%d (turn制)",
                          unit.name, b.effect_type, b.duration + 1, b.duration)
        expired_after = [b.effect_type for b in unit.buffs + unit.debuffs if b.duration <= 0]
        newly_expired = set(expired_after) - set(expired_before)
        if newly_expired:
            _log.info("[AURA_TURN_END] %s expired: %s", unit.name, list(newly_expired))

    def check_expiration(self, unit: UnitState):
        """清理过期 Aura (Duration == 0 表示已过期, Duration < 0 表示永久)"""
        # 先收集过期的buff，用于联动检查（排除unremovable）
        expired_buffs = [b for b in unit.buffs if b.duration == 0 and not getattr(b, 'unremovable', False)]
        expired_debuffs = [b for b in unit.debuffs if b.duration == 0 and not getattr(b, 'unremovable', False)]

        # 护盾buff过期时，需清除对应的shield值
        for b in expired_buffs:
            if b.effect_type in (SkillEffectType.SHIELD.value, "shield", "Shield"):
                shield_amount = getattr(b, 'shield_amount', 0)
                dmg_elem = getattr(b, 'damage_element', 0)
                if dmg_elem == 1 and unit.physical_shield > 0:
                    actual_remove = min(shield_amount, unit.physical_shield) if shield_amount > 0 else unit.physical_shield
                    unit.physical_shield -= actual_remove
                    _log.info("[SHIELD_EXPIRED] %s: physical_shield buff expired, removing %d (remaining=%d)",
                              unit.name, actual_remove, unit.physical_shield)
                elif dmg_elem == 2 and unit.en_shield > 0:
                    actual_remove = min(shield_amount, unit.en_shield) if shield_amount > 0 else unit.en_shield
                    unit.en_shield -= actual_remove
                    _log.info("[SHIELD_EXPIRED] %s: en_shield buff expired, removing %d (remaining=%d)",
                              unit.name, actual_remove, unit.en_shield)
                elif unit.shield > 0:
                    if shield_amount > 0:
                        actual_remove = min(shield_amount, unit.shield)
                        unit.shield -= actual_remove
                        _log.info("[SHIELD_EXPIRED] %s: shield buff expired, removing %d (remaining=%d)",
                                  unit.name, actual_remove, unit.shield)
                    else:
                        # 没有shield_amount记录时，清除全部shield（如果没有其他shield buff存在）
                        remaining_shield_buffs = [ob for ob in unit.buffs
                                                  if ob.effect_type in (SkillEffectType.SHIELD.value, "shield", "Shield")
                                                  and ob.buff_id != b.buff_id and ob.duration != 0]
                        if not remaining_shield_buffs:
                            unit.shield = 0
                            _log.info("[SHIELD_EXPIRED] %s: last shield buff expired, clearing all shield", unit.name)

        unit.buffs = [b for b in unit.buffs if b.duration != 0 or getattr(b, 'unremovable', False)]
        unit.debuffs = [b for b in unit.debuffs if b.duration != 0 or getattr(b, 'unremovable', False)]
        self._sync_stun_freeze_flags(unit)

        # 检查联动buff消失
        for removed_buff in expired_buffs + expired_debuffs:
            if removed_buff.linked_buff_id:
                # 移除目标上所有匹配linked_buff_id的buff
                linked_type = removed_buff.linked_buff_id
                linked_to_remove = [b for b in unit.buffs if b.effect_type == linked_type or
                                   (hasattr(b, 'name') and b.name == linked_type)]
                linked_to_remove_debuffs = [b for b in unit.debuffs if b.effect_type == linked_type or
                                   (hasattr(b, 'name') and b.name == linked_type)]
                for lb in linked_to_remove:
                    unit.buffs.remove(lb)
                    _log.info("[LINKED_BUFF] %s: linked buff %s removed (triggered by %s expiration)",
                              unit.name, lb.name, removed_buff.name)
                for lb in linked_to_remove_debuffs:
                    unit.debuffs.remove(lb)
                    _log.info("[LINKED_BUFF] %s: linked debuff %s removed (triggered by %s expiration)",
                              unit.name, lb.name, removed_buff.name)

        # 检查linked_mark联动：当mark消失时，linked到该mark的debuff也消失
        for removed_buff in expired_buffs + expired_debuffs:
            if removed_buff.effect_type == SkillEffectType.MARK.value:
                mark_name = getattr(removed_buff, 'name', '')
                if mark_name:
                    linked_debuffs = [d for d in unit.debuffs
                                    if getattr(d, 'linked_buff_id', '') == mark_name]
                    for ld in linked_debuffs:
                        unit.debuffs.remove(ld)
                        _log.info("[LINKED_MARK] %s: debuff %s removed (linked to mark %s expiration)",
                                  unit.name, ld.name, mark_name)
        
    def get_aura_value(self, unit: UnitState, effect_type: str) -> float:
        """获取某类 Aura 的总值 (Sum)"""
        total = 0.0
        for b in unit.buffs:
            if b.effect_type == effect_type:
                total += b.value
        for b in unit.debuffs:
            if b.effect_type == effect_type:
                total += b.value
        return total

    # ========== 内部逻辑 ==========

    def _sync_stun_freeze_flags(self, unit: UnitState):
        """根据当前debuffs同步眩晕/冻结标志位"""
        unit.is_stunned = any(b.effect_type == SkillEffectType.KNOCKOUT.value for b in unit.debuffs)
        unit.is_frozen = any(b.effect_type == SkillEffectType.FREEZE.value for b in unit.debuffs)

    def _get_target_list(self, unit: UnitState, aura: BuffState) -> List[BuffState]:
        if aura.is_debuff:
            return unit.debuffs
        return unit.buffs

    def _update_duration(self, unit: UnitState, timings: List[AuraUpdateTiming]):
        """减少指定 Timing 的 Aura 持续时间"""
        target_timings = {t.value for t in timings}

        for b in unit.buffs:
            if b.timing_type in target_timings:
                # EPHEMERAL类型：无论duration值如何，直接设为0移除
                if b.timing_type in [
                    AuraUpdateTiming.EPHEMERAL_SKILL_END.value,
                    AuraUpdateTiming.EPHEMERAL_MANEUVER_END.value
                ]:
                    b.duration = 0
                elif b.duration < 0:
                    continue
                else:
                    b.duration -= 1

        for b in unit.debuffs:
            if b.timing_type in target_timings:
                if b.timing_type in [
                    AuraUpdateTiming.EPHEMERAL_SKILL_END.value,
                    AuraUpdateTiming.EPHEMERAL_MANEUVER_END.value
                ]:
                    b.duration = 0
                elif b.duration < 0:
                    continue
                else:
                    b.duration -= 1

        # 注意: 不在此处调用check_expiration，由调用方在恢复逻辑后统一清理

    def _is_immune(self, unit: UnitState, aura: BuffState) -> bool:
        """检查是否免疫"""
        # 1. BlockAuras (免疫所有)
        # 检查 unit 是否有 BlockAuras 效果
        for b in unit.buffs: # BlockAuras 是 Buff (Protect)
            if b.effect_type == SkillEffectType.BLOCK_AURAS.value:
                return True
                
        # 2. BlockSpecificAura (免疫特定)
        # 暂不实现具体逻辑，留接口
        return False

    def _handle_poison_stacking(self, target_list: List[BuffState], new_poison: BuffState):
        """
        毒叠加逻辑:
        "不可叠加: 重复赋予毒时，保留伤害上限更大的效果"
        比较的是：施法者攻击力×100% (即 new_poison.caster_attack or implicit capped value? )
        文档公式: 毒伤害 = min(HP*%, Atk*100%). 上限是 Atk*100%.
        所以比较 caster_attack (snapshot).
        """
        # 假设 BuffState 有 store caster_attack 的地方? 
        # 目前 BuffState 定义: value, duration... no caster_attack explicitly except in mechanics doc suggestion.
        # 之前 Mechanics Doc 建议:
        # caster_attack: int # 快照攻击力
        # 但 UnitState.py 还没加这个字段!
        # 为了不改动 UnitState (尽量)，我们可以用 extra fields or metadata?
        # 或者现在加。
        # 鉴于 Poison 逻辑依赖它，且 Mechanics Doc 明确说了需要，我们假设 BuffState 后续会加，或者现在加。
        # 这里先假设 new_poison.value 已经是 "Damage Cap" ? 不，value是百分比.
        # 我们只能比较 new_poison vs existing_poison's priority?
        # 简单处理: 如果已存在 Poison，比较 Duration * Value? 
        # Doc: "比较的是：施法者攻击力×100%"
        # 那么我们必须在 BuffState 存 caster_attack.
        
        # 临时: 总是覆盖? 或者是 "Keep Newest" ?
        # Doc: "持续时间和伤害上限都更优时才覆盖" -> "保留伤害上限更大的".
        # 如果无法获取 Attack，暂定**覆盖** (Newest wins)，这是最常见的 RPG 逻辑之一。
        
        # 移除旧 Poison
        existing = next((b for b in target_list if b.effect_type == SkillEffectType.POISON.value), None)
        if existing:
            # 比较逻辑缺失，做个 TODO
            # Assuming new is better for now, or just replace.
            target_list.remove(existing)
            
        target_list.append(new_poison)

