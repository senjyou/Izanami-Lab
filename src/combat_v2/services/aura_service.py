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

        # 1.2 block_buff_by_type 检查: 目标持有 BLOCK_BUFF_BY_TYPE debuff 时，
        # 阻止 blocked_buff_types 列表中的 buff 新付与 (S6 土雷 220362)
        # 注意: BLOCK_BUFF_BY_TYPE 自身不应被自己阻止
        # 关键: buff_block 只阻止 buff (增益, is_debuff=False)，不阻止 debuff (减益, is_debuff=True)
        # 因为 atk_up/atk_down 共享同一 effect_type (StatusAttack)，若不区分 is_debuff
        # 会导致 buff_block 错误阻止 atk_down 等减益效果
        if aura.effect_type != SkillEffectType.BLOCK_BUFF_BY_TYPE.value and not aura.is_debuff:
            for db in unit.debuffs:
                if (db.effect_type == SkillEffectType.BLOCK_BUFF_BY_TYPE.value
                        and db.duration != 0
                        and aura.effect_type in (db.block_status_list or [])):
                    _log.info("[BLOCK_BUFF_BY_TYPE] %s: %s blocked by BlockBuffByType debuff (blocked_list=%s)",
                              unit.name, aura.effect_type, db.block_status_list)
                    return False

        # 标记：当次行动中由add_aura处理的buff，process_maneuver_end跳过递减
        aura.just_applied = True

        # 1.5 眩晕/冻结/混乱: 立即同步标志位，防止同回合内PS触发检查漏过
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
        elif aura.effect_type == SkillEffectType.CONFUSION.value:
            unit.is_confused = True

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
            target_list[existing_index].just_applied = True
            if aura.effect_type in [SkillEffectType.KNOCKOUT.value, SkillEffectType.FREEZE.value,
                                     SkillEffectType.CONFUSION.value]:
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
            # 不同源（不同技能）但同effect_type的不可叠加buff
            control_types = [SkillEffectType.KNOCKOUT.value, SkillEffectType.FREEZE.value,
                             SkillEffectType.CONFUSION.value]
            if aura.effect_type in control_types:
                # 控制类效果（眩晕/冻结/混乱）：保留持续时间更长的
                existing_by_type = -1
                for i, existing in enumerate(target_list):
                    if (existing.effect_type == aura.effect_type
                            and not existing.is_memory_buff
                            and not existing.is_stackable):
                        existing_by_type = i
                        break

                if existing_by_type != -1:
                    old_aura = target_list[existing_by_type]
                    old_aura.just_applied = True
                    if aura.duration > old_aura.duration:
                        target_list[existing_by_type] = aura
                        _log.info("[AURA] %s: %s replaced (new dur %d > old dur %d, diff source)",
                                  unit.name, aura.effect_type, aura.duration, old_aura.duration)
                    else:
                        _log.info("[AURA] %s: %s IGNORED (old dur %d >= new dur %d, diff source)",
                                  unit.name, aura.effect_type, old_aura.duration, aura.duration)
                else:
                    target_list.append(aura)
                    _log.info("[AURA] %s add control %s [%s] val=%s dur=%d -> APPEND",
                              unit.name, aura.effect_type, list_name, aura.value, aura.duration)
            else:
                # 非控制类不可叠加buff：不同源时共存（coexist）
                # 属性计算时_aggregate_buff_value取最大值，所以共存不影响当前效果
                # 但当高数值buff过期时，低数值buff仍然存活，正确过渡
                # （如 リフシルト15% 与 外殻強化25% 共存，25%过期后15%仍然生效）
                target_list.append(aura)
                _log.info("[AURA] %s add non-stackable %s [%s] val=%s dur=%d -> COEXIST (diff source)",
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
            AuraUpdateTiming.DURABLE_TARGET_MANEUVER_END
        ])
        # DURABLE_SOURCE_MANEUVER_END: 只递减 source 是本单位的 buff（即本单位自己给自己上的）
        # 其他单位上的 DURABLE_SOURCE_MANEUVER_END 由 process_source_maneuver_end 在施法者行动结束时递减
        source_timing = AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END.value
        for b in unit.buffs + unit.debuffs:
            if b.timing_type == source_timing and getattr(b, 'source_unit_id', None) == unit.unit_id:
                if b.duration > 0:
                    # 当次行动中由add_aura施加的buff跳过递减（skip_restore除外）
                    if getattr(b, 'just_applied', False) and not getattr(b, 'skip_restore', False):
                        continue
                    b.duration -= 1
        expired_after = [b.effect_type for b in unit.buffs + unit.debuffs if b.duration <= 0]
        newly_expired = set(expired_after) - set(expired_before)
        if newly_expired:
            _log.info("[AURA] %s expired: %s", unit.name, list(newly_expired))

    def process_source_maneuver_end(self, source_unit: UnitState, all_units: List[UnitState]):
        """
        施法者行动结束时，递减其他单位上由该施法者施加的DURABLE_SOURCE_MANEUVER_END buff/debuff。
        修复duration_owner="caster"机制：原本只在buff持有者行动结束时递减，
        现在正确地在施法者行动结束时递减。

        注意：这里不检查just_applied。just_applied只保护"自身施法自身"的buff
        （在process_maneuver_end的DURABLE_SOURCE_MANEUVER_END循环中处理）。
        施加给其他单位的buff应在施法者当次行动结束时正常递减。
        """
        source_timing = AuraUpdateTiming.DURABLE_SOURCE_MANEUVER_END.value
        affected_units = []
        for unit in all_units:
            if unit.unit_id == source_unit.unit_id:
                continue  # 跳过施法者自身（已在process_maneuver_end中处理）
            if not unit.is_alive:
                continue
            modified = False
            for b in unit.buffs + unit.debuffs:
                if (b.timing_type == source_timing
                        and getattr(b, 'source_unit_id', None) == source_unit.unit_id
                        and b.duration > 0):
                    b.duration -= 1
                    modified = True
                    _log.info("[AURA_SOURCE_END] %s: %s duration %d->%d (source %s action ended)",
                              unit.name, b.effect_type, b.duration + 1, b.duration, source_unit.name)
            if modified:
                affected_units.append(unit)
        # 清理过期buff/debuff
        for unit in affected_units:
            self.check_expiration(unit, all_units)

    def process_shield_decay(self, unit: UnitState):
        """
        单位行动结束时，对所有 shield_decay_pct > 0 的盾 buff 进行衰减。
        每行动减少 initial_shield_value × decay_pct / 100 的盾值。
        当 shield_amount <= 0 时，将 duration 设为 0 触发清理。
        实现 110012「シールドは1行動に付き最大値の25%減少する」等机制。

        注意：施法当次行动不衰减（shield_decay_skipped_first标记），从下次行动结束开始衰减。

        Returns:
            list: 衰减详情列表 [(buff_name, reduction, old_amount, new_amount, initial, expired), ...]
                  供调用方输出叙事日志使用。
        """
        decay_details = []
        if not unit.is_alive:
            return decay_details
        modified = False
        for b in unit.buffs:
            if (b.effect_type in (SkillEffectType.SHIELD.value, "shield", "Shield")
                    and getattr(b, 'shield_decay_pct', 0) > 0
                    and getattr(b, 'initial_shield_value', 0) > 0
                    and b.duration != 0):
                # 跳过施法当次行动（首次衰减前 shield_decay_skipped_first=False）
                if not getattr(b, 'shield_decay_skipped_first', False):
                    b.shield_decay_skipped_first = True
                    _log.info("[SHIELD_DECAY] %s: shield buff %s 跳过当次行动衰减 (首次衰减豁免)",
                              unit.name, b.buff_id)
                    continue
                initial = b.initial_shield_value
                reduction = int(initial * b.shield_decay_pct / 100)
                if reduction <= 0:
                    reduction = 1  # 至少减1，避免永不过期
                old_amount = b.shield_amount
                b.shield_amount = max(0, b.shield_amount - reduction)
                # 同步扣除 unit 的 shield 值
                dmg_elem = getattr(b, 'damage_element', 0)
                if dmg_elem == 1 and unit.physical_shield > 0:
                    actual_remove = min(reduction, unit.physical_shield)
                    unit.physical_shield -= actual_remove
                elif dmg_elem == 2 and unit.en_shield > 0:
                    actual_remove = min(reduction, unit.en_shield)
                    unit.en_shield -= actual_remove
                elif unit.shield > 0:
                    actual_remove = min(reduction, unit.shield)
                    unit.shield -= actual_remove
                else:
                    actual_remove = 0
                _log.info("[SHIELD_DECAY] %s: shield buff %s decayed by %d (initial=%d pct=%d%%) amount %d->%d, unit_shield_removed=%d",
                          unit.name, b.buff_id, reduction, initial, b.shield_decay_pct,
                          old_amount, b.shield_amount, actual_remove)
                expired = b.shield_amount <= 0
                decay_details.append((
                    getattr(b, 'name', 'Shield'), reduction, old_amount, b.shield_amount, initial, expired
                ))
                # 当盾值耗尽时，标记为过期
                if expired:
                    b.duration = 0
                    _log.info("[SHIELD_DECAY] %s: shield buff %s EXPIRED (shield_amount reached 0)",
                              unit.name, b.buff_id)
                modified = True
        if modified:
            self.check_expiration(unit)
        return decay_details

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

    def check_expiration(self, unit: UnitState, all_units: Optional[List[UnitState]] = None):
        """清理过期 Aura (Duration == 0 表示已过期, Duration < 0 表示永久)"""
        # 先收集过期的buff，用于联动检查（排除unremovable）
        expired_buffs = [b for b in unit.buffs if b.duration == 0 and not getattr(b, 'unremovable', False)]
        expired_debuffs = [b for b in unit.debuffs if b.duration == 0 and not getattr(b, 'unremovable', False)]

        # [GAME_BUG_SIMULATION] 技能「装いを新たに」(110050) 子機Ⅱ跨目标联动失效
        # 当本目标的linked sub_unit过期时，级联移除其他目标上同link_group的子機Ⅱ
        # 原实现路径（无all_units或sub_unit_link_group为空）保持不变
        if all_units is not None:
            for expired in expired_buffs:
                if (expired.effect_type == SkillEffectType.SUB_UNIT.value
                        and getattr(expired, 'sub_unit_link_group', '')):
                    self._cascade_linked_sub_unit_expiry(expired, unit, all_units)

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

        # 检查linked_mark联动：当mark消失时，linked到该mark的buff/debuff也消失
        for removed_buff in expired_buffs + expired_debuffs:
            if removed_buff.effect_type == SkillEffectType.MARK.value:
                mark_name = getattr(removed_buff, 'name', '')
                if mark_name:
                    # 联动移除linked的buffs（如負けん気对应的atk_up）
                    linked_buffs = [b for b in unit.buffs
                                   if getattr(b, 'linked_buff_id', '') == mark_name]
                    for lb in linked_buffs:
                        unit.buffs.remove(lb)
                        _log.info("[LINKED_MARK] %s: buff %s removed (linked to mark %s expiration)",
                                  unit.name, lb.name, mark_name)
                    # 联动移除linked的debuffs
                    linked_debuffs = [d for d in unit.debuffs
                                    if getattr(d, 'linked_buff_id', '') == mark_name]
                    for ld in linked_debuffs:
                        unit.debuffs.remove(ld)
                        _log.info("[LINKED_MARK] %s: debuff %s removed (linked to mark %s expiration)",
                                  unit.name, ld.name, mark_name)

    def _cascade_linked_sub_unit_expiry(self, expired_buff: BuffState, source_unit: UnitState,
                                         all_units: List[UnitState]) -> List[tuple]:
        """[GAME_BUG_SIMULATION] 跨目标联动移除子機Ⅱ

        仿真游戏内bug: 技能「装いを新たに」(110050)创建的多个子機Ⅱ中，
        任一子機Ⅱ失效（持续时间到/HP耗尽）时，其余子機Ⅱ同时失效。

        原实现路径：sub_unit_link_group为空时直接返回，不影响原有逻辑。
        仅当linked_expiry flag启用时，_apply_sub_unit会生成共享的link_group_id。
        """
        link_group = getattr(expired_buff, 'sub_unit_link_group', '')
        if not link_group:
            return []
        removed = []
        for unit in all_units:
            if unit.unit_id == source_unit.unit_id:
                continue
            if not unit.is_alive:
                continue
            # 只级联未过期的linked sub_unit（duration>0），避免重复移除
            linked_buffs = [b for b in unit.buffs
                           if b.effect_type == SkillEffectType.SUB_UNIT.value
                           and getattr(b, 'sub_unit_link_group', '') == link_group
                           and b.duration > 0]
            for lb in linked_buffs:
                lb.duration = 0
                lb.sub_unit_hp = 0
                _log.info("[LINKED_SUB_UNIT] %s: sub_unit '%s' cascade-expired (linked to %s on %s, group=%s)",
                          unit.name, lb.name, expired_buff.name, source_unit.name, link_group)
                removed.append((unit.name, lb.name))
            if linked_buffs:
                unit.buffs = [b for b in unit.buffs if b.duration != 0 or getattr(b, 'unremovable', False)]
        return removed

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
        """根据当前debuffs同步眩晕/冻结/混乱标志位"""
        unit.is_stunned = any(b.effect_type == SkillEffectType.KNOCKOUT.value for b in unit.debuffs)
        unit.is_frozen = any(b.effect_type == SkillEffectType.FREEZE.value for b in unit.debuffs)
        unit.is_confused = any(b.effect_type == SkillEffectType.CONFUSION.value for b in unit.debuffs)

    def _get_target_list(self, unit: UnitState, aura: BuffState) -> List[BuffState]:
        if aura.is_debuff:
            return unit.debuffs
        return unit.buffs

    def _update_duration(self, unit: UnitState, timings: List[AuraUpdateTiming]):
        """减少指定 Timing 的 Aura 持续时间"""
        target_timings = {t.value for t in timings}

        for b in unit.buffs:
            if b.timing_type in target_timings:
                # EPHEMERAL类型：无论duration值如何、是否just_applied，直接设为0移除
                # 这是"技能/行动结束时立即消失"的语义，不能被just_applied保护
                if b.timing_type in [
                    AuraUpdateTiming.EPHEMERAL_SKILL_END.value,
                    AuraUpdateTiming.EPHEMERAL_MANEUVER_END.value
                ]:
                    b.duration = 0
                    continue
                # DURABLE类型：当次行动中由add_aura施加的buff跳过递减（skip_restore除外）
                if getattr(b, 'just_applied', False) and not getattr(b, 'skip_restore', False):
                    continue
                if b.duration < 0:
                    continue
                else:
                    b.duration -= 1

        for b in unit.debuffs:
            if b.timing_type in target_timings:
                # EPHEMERAL类型：无论duration值如何、是否just_applied，直接设为0移除
                if b.timing_type in [
                    AuraUpdateTiming.EPHEMERAL_SKILL_END.value,
                    AuraUpdateTiming.EPHEMERAL_MANEUVER_END.value
                ]:
                    b.duration = 0
                    continue
                # DURABLE类型：当次行动中由add_aura施加的buff跳过递减（skip_restore除外）
                if getattr(b, 'just_applied', False) and not getattr(b, 'skip_restore', False):
                    continue
                if b.duration < 0:
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

        # 2. BlockSpecificAura (免疫特定状态)
        # 检查 unit 是否有 BlockSpecificAura 效果，且其 block_status_list 包含 incoming aura 的类型
        incoming_type = aura.effect_type.lower()
        for b in unit.buffs:
            if b.effect_type == SkillEffectType.BLOCK_SPECIFIC_AURA.value:
                blocked = [s.lower() for s in b.block_status_list]
                if incoming_type in blocked:
                    _log.info("[BLOCK_SPECIFIC_AURA] %s: %s blocked by BlockSpecificAura (block_status=%s)",
                              unit.name, aura.effect_type, b.block_status_list)
                    return True
        return False

    def _handle_poison_stacking(self, target_list: List[BuffState], new_poison: BuffState):
        """毒叠加逻辑: 不可叠加。

        重复赋予毒时，保留伤害上限更大的效果（即 caster_attack 更高的），
        持续时间继承更长的。毒伤害 = min(HP*value%, caster_attack)，
        所以 caster_attack 更高的毒伤害上限更高。
        """
        existing = next((b for b in target_list if b.effect_type == SkillEffectType.POISON.value), None)
        if not existing:
            target_list.append(new_poison)
            return

        # 保留 caster_attack 更高的作为伤害来源，持续时间继承更长的
        if new_poison.caster_attack > existing.caster_attack:
            # 新毒伤害上限更高 → 以新毒为基础，继承更长的持续时间
            if existing.duration > new_poison.duration:
                new_poison.duration = existing.duration
            target_list.remove(existing)
            target_list.append(new_poison)
            _log.info("[AURA] poison replaced: caster_attack %d -> %d (higher cap), duration=%d",
                      existing.caster_attack, new_poison.caster_attack, new_poison.duration)
        else:
            # 旧毒伤害上限更高或相等 → 保留旧毒，继承更长的持续时间
            old_dur = existing.duration
            if new_poison.duration > existing.duration:
                existing.duration = new_poison.duration
            existing.just_applied = True  # 防止当次行动结束时递减duration
            _log.info("[AURA] poison kept existing: caster_attack %d >= %d, duration %d -> %d (inherited longer)",
                      existing.caster_attack, new_poison.caster_attack, old_dur, existing.duration)


