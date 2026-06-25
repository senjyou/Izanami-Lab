#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
战斗叙事日志生成器
src/combat_v2/battle_narrative.py

以自然语言描述整场战斗过程，输出格式参考游戏回放 log。
"""

from datetime import datetime
from typing import List, Dict, Optional, Any
from ..entities_v2.unit_state import UnitState
from ..entities_v2.enums import Position

POSITION_DISPLAY: Dict[Position, str] = {
    Position.ALLY_LEFT_FRONT: "已方左前位",
    Position.ALLY_CENTER_FRONT: "已方中前位",
    Position.ALLY_RIGHT_FRONT: "已方右前位",
    Position.ALLY_LEFT_BACK: "已方左后位",
    Position.ALLY_CENTER_BACK: "已方中后位",
    Position.ALLY_RIGHT_BACK: "已方右后位",
    Position.ENEMY_LEFT_FRONT: "敌方左前位",
    Position.ENEMY_CENTER_FRONT: "敌方中前位",
    Position.ENEMY_RIGHT_FRONT: "敌方右前位",
    Position.ENEMY_LEFT_BACK: "敌方左后位",
    Position.ENEMY_CENTER_BACK: "敌方中后位",
    Position.ENEMY_RIGHT_BACK: "敌方右后位",
}

ELEMENT_DISPLAY = {
    1: "火", 2: "水", 3: "风", 4: "土", 5: "光", 6: "暗",
}

SKILL_TYPE_LABEL = {1: "AS", 2: "PS", 3: "EX"}


class BattleNarrativeWriter:
    """战斗叙事日志写入器"""

    def __init__(self, data_loader=None):
        self._lines: List[str] = []
        self._turn: int = 0
        self._data_loader = data_loader

    def _add(self, text: str):
        self._lines.append(text)

    def _header_display_name(self, unit: UnitState, all_units: List[UnitState]) -> str:
        same_name = [u for u in all_units if u.name == unit.name]
        if len(same_name) > 1:
            pos = POSITION_DISPLAY.get(unit.position, "?")
            return f"{unit.name}({pos})"
        return unit.name

    def header(self, friends: List[UnitState], enemies: List[UnitState],
               char_count: int = 0, skill_count: int = 0):
        all_units = friends + enemies
        self._add(u"╔══════════════════════════════════════════════════╗")
        self._add(u"║              战斗回放 · 自然语言版                ║")
        self._add(u"╠══════════════════════════════════════════════════╣")
        self._add(u"║                                                  ║")
        self._add(u"║  ◆ 己方阵容                                       ║")
        for u in friends:
            dname = self._header_display_name(u, all_units)
            pos = POSITION_DISPLAY.get(u.position, "?")
            element = ELEMENT_DISPLAY.get(getattr(u, 'element', 0), "?")
            self._add(f"║  {dname} {element} {pos} HP:{u.max_hp}/{u.max_hp} ATK:{u.attack} DEF:{u.defense} SPD:{u.speed} AP:{u.initial_active_point} PP:{u.initial_passive_point}")
        self._add(u"║                                                  ║")
        self._add(u"║  ◆ 敌方阵容                                       ║")
        for u in enemies:
            dname = self._header_display_name(u, all_units)
            pos = POSITION_DISPLAY.get(u.position, "?")
            element = ELEMENT_DISPLAY.get(getattr(u, 'element', 0), "?")
            self._add(f"║  {dname} {element} {pos} HP:{u.max_hp}/{u.max_hp} ATK:{u.attack} DEF:{u.defense} SPD:{u.speed} AP:{u.initial_active_point} PP:{u.initial_passive_point}")
        self._add(u"╚══════════════════════════════════════════════════╝")
        self._add("")

        if char_count or skill_count:
            self._add(f"  [数据加载] 读取了 {char_count} 个角色数据, {skill_count} 个技能数据")

        for u in friends:
            dname = self._header_display_name(u, all_units)
            pos = POSITION_DISPLAY.get(u.position, "?")
            element = ELEMENT_DISPLAY.get(getattr(u, 'element', 0), "?")
            self._add(f"  [登场] {dname} {element} {pos} HP:{u.current_hp}/{u.max_hp} AP:{u.initial_active_point} PP:{u.initial_passive_point}")
        for u in enemies:
            dname = self._header_display_name(u, all_units)
            pos = POSITION_DISPLAY.get(u.position, "?")
            element = ELEMENT_DISPLAY.get(getattr(u, 'element', 0), "?")
            self._add(f"  [登场] {dname} {element} {pos} HP:{u.current_hp}/{u.max_hp} AP:{u.initial_active_point} PP:{u.initial_passive_point}")
        self._add("")

    def battle_start(self):
        self._add(u"╔══════════════════════════════════════════════════╗")
        self._add(u"║                ⚔ 战 斗 开 始 ⚔                    ║")
        self._add(u"╚══════════════════════════════════════════════════╝")
        self._add("")

    def wave_start(self, side_name: str):
        self._add(f"───────────────────── 第1/1波 ({side_name}) ─────────────────────")
        self._add("")

    def turn_start(self, turn: int, max_turns: int):
        self._turn = turn
        self._add("")
        self._add(f"                ══ 第 {turn} 回合 / 共 {max_turns} 回合 ══                ")
        self._add("")

    def action_axis(self, units: List[UnitState]):
        names = [u.name for u in units]
        self._add(f"  [行动轴] {', '.join(names)}")

    def action_axis_display(self, names: List[str]):
        self._add(f"  [行动轴] {', '.join(names)}")

    def unit_action_start(self, unit: UnitState, display_name: str = None):
        name = display_name or unit.name
        self._add(f"  [行动开始] {name}  AP:{unit.current_ap}/{unit.initial_active_point}  PP:{unit.current_pp}/{unit.initial_passive_point}  EP:{unit.current_ep}/{unit.max_extra_point}")

    def unit_action_start_display(self, name: str, ap: int, ap_max: int, pp: int, pp_max: int, ep: int, ep_max: int):
        self._add(f"  [行动开始] {name}  AP:{ap}/{ap_max}  PP:{pp}/{pp_max}  EP:{ep}/{ep_max}")

    def unit_hp_status(self, unit: UnitState, display_name: str = None):
        name = display_name or unit.name
        hp_pct = int(unit.current_hp / unit.max_hp * 100) if unit.max_hp > 0 else 0
        self._add(f"  [状态] {name} HP:{unit.current_hp}/{unit.max_hp}({hp_pct}%)")

    def unit_full_status(self, unit: UnitState, display_name: str = None):
        name = display_name or unit.name
        hp_pct = int(unit.current_hp / unit.max_hp * 100) if unit.max_hp > 0 else 0
        self._add(f"  [状态] {name} HP:{unit.current_hp}/{unit.max_hp}({hp_pct}%)  AP:{unit.current_ap}/{unit.initial_active_point}  EP:{unit.current_ep}/{unit.max_extra_point}")

    def skill_prepare(self, unit: UnitState, skill_name: str, skill_type: int = 1, display_name: str = None):
        name = display_name or unit.name
        st = SKILL_TYPE_LABEL.get(skill_type, "AS")
        self._add(f"  [准备·{st}] {name} 正在准备「{skill_name}」...")

    def skill_use(self, caster_name: str, target_name: str, skill_name: str, skill_type: int = 1):
        st = SKILL_TYPE_LABEL.get(skill_type, "AS")
        self._add(f"  [使用技能·{st}] {caster_name} 对 {target_name} 使用「{skill_name}」")

    def skill_targets(self, caster_name: str, skill_name: str, targets: List[str]):
        target_str = ", ".join(targets)
        self._add(f"  [锁定目标] {caster_name} 的「{skill_name}」瞄准了: {target_str}")

    def skill_cast(self, caster_name: str, target_name: str, skill_name: str, skill_type: int = 1):
        st = SKILL_TYPE_LABEL.get(skill_type, "AS")
        self._add(f"  [技能结束·{st}] 「{skill_name}」施放结束")

    def ps_trigger(self, owner_name: str, skill_name: str, trigger_source: str = ""):
        source_info = f" (触发源: {trigger_source})" if trigger_source else ""
        self._add(f"  ⚡[PS触发] {owner_name} 发动了被动技能「{skill_name}」{source_info}")

    def global_trigger(self, owner_name: str, skill_name: str, timing: str = ""):
        timing_info = f" ({timing})" if timing else ""
        self._add(f"  ⚡[全局触发] {owner_name} 发动了「{skill_name}」{timing_info}")

    def ep_full(self, unit_name: str):
        self._add(f"  [EP满] {unit_name} 的EP已集满，可以使用EX技能!")

    def damage(self, attacker_name: str, attacker_hp: str, target_name: str,
               hp_before: int, hp_after: int, damage: int, damage_type: str,
               modifiers: List[str] = None, shield_absorbed: int = 0, max_hp: int = 0,
               calc_detail: dict = None):
        mods = "".join(f"【{m}】" for m in (modifiers or []))
        shield_info = ""
        if shield_absorbed > 0:
            shield_info = f" (护盾吸收:{shield_absorbed})"
        calc_info = ""
        if calc_detail and damage > 0 and "Miss" not in (modifiers or []):
            cd = calc_detail
            calc_info = (f" [ATK:{cd['atk']} DEF:{cd['def_orig']}→{cd['def_after_penetrate']}"
                        f" base:{cd['base_diff']} power:{cd['skill_power']}"
                        f" attr:{cd['attr_factor']:.4f} dealt:{cd['dealt_mult']:.4f}"
                        f" rcvd:{cd['received_mult']:.4f} crit:{cd['crit_factor']:.2f}"
                        f" guard:{cd['guard_mult']:.4f}")
            hp_scaling = cd.get('hp_scaling')
            if hp_scaling is not None and hp_scaling != 1.0:
                calc_info += f" hp_scale:{hp_scaling:.4f}"
            calc_info += "]"
        if "Miss" in (modifiers or []):
            self._add(f"  [伤害] {attacker_name} ({attacker_hp}) → {target_name} (HP:{hp_after}/{max_hp}): Miss")
        elif damage == 0:
            self._add(f"  [伤害] {attacker_name} ({attacker_hp}) → {target_name} (HP:{hp_after}/{max_hp}): 0 点{damage_type}伤害{shield_info}")
        else:
            self._add(f"  [伤害] {attacker_name} ({attacker_hp}) → {target_name} (HP:{hp_after}/{max_hp}): {damage} 点{damage_type}伤害{mods}{shield_info}{calc_info}")

    def burn_damage(self, target_name: str, damage: int, hp_after: int, max_hp: int, stacks: int,
                    calc_detail: dict = None):
        stack_info = f" (炎上{stacks}层)" if stacks >= 2 else ""
        calc_info = ""
        if calc_detail and damage > 0:
            cd = calc_detail
            calc_info = f" [base:{cd.get('base_damage',0)} mult:{cd.get('multiplier',1)}x]"
        self._add(f"  [炎上伤害] {target_name} 受到炎上伤害: -{damage} HP → (HP:{hp_after}/{max_hp}){stack_info}{calc_info}")

    def poison_damage(self, target_name: str, damage: int, hp_after: int, max_hp: int,
                      calc_detail: dict = None):
        calc_info = ""
        if calc_detail and damage > 0:
            cd = calc_detail
            calc_info = f" [hp_pct:{cd.get('hp_pct',0):.2f} cap:{cd.get('atk_cap',0)}]"
        self._add(f"  [毒伤害] {target_name} 受到毒伤害: -{damage} HP → (HP:{hp_after}/{max_hp}){calc_info}")

    def action_damage(self, target_name: str, damage: int, hp_after: int, max_hp: int, shield_absorbed: int = 0):
        shield_info = f" (护盾吸收:{shield_absorbed})" if shield_absorbed > 0 else ""
        self._add(f"  [行動時ダメージ] {target_name} 行动时受到伤害: -{damage} HP{shield_info} → (HP:{hp_after}/{max_hp})")

    def damage_link_transfer(self, source_target_name: str, linker_name: str,
                              transfer_dmg: int, hp_before: int, hp_after: int, max_hp: int,
                              damage_type: str, link_value: float, source_actual_damage: int,
                              shield_absorbed: int = 0):
        """ダメージリンク転送の叙事ログ出力"""
        shield_info = f" (护盾吸收:{shield_absorbed})" if shield_absorbed > 0 else ""
        self._add(f"  [链接伤害] {source_target_name} → {linker_name} (HP:{hp_after}/{max_hp}): "
                  f"{transfer_dmg} 点{damage_type}链接伤害 (源伤害:{source_actual_damage} × {link_value:.0f}%){shield_info}")

    def enchant_damage(self, attacker_name: str, attacker_hp: str, target_name: str,
                       hp_before: int, hp_after: int, damage: int, damage_type: str,
                       modifiers: List[str] = None, calc_detail: dict = None, max_hp: int = 0):
        mods = "".join(f"【{m}】" for m in (modifiers or []))
        calc_info = ""
        if calc_detail and damage > 0:
            cd = calc_detail
            calc_info = (f" [src_atk:{cd.get('source_atk',0)} b_atk:{cd.get('b_atk',0)}"
                        f" c_def:{cd.get('c_def',0)} base:{cd.get('base_diff',0)}"
                        f" power:{cd.get('power_pct',0):.1f}%"
                        f" crit:{cd.get('crit_factor',1.0):.1f}"
                        f" dealt:{cd.get('b_dealt_mult',1.0):.4f}"
                        f" rcvd:{cd.get('c_received_mult',1.0):.4f}"
                        f" attr:{cd.get('attr_factor',1.0):.4f}]")
        self._add(f"  [附魔伤害] {attacker_name} ({attacker_hp}) → {target_name} (HP:{hp_after}/{max_hp if max_hp else hp_after}): {damage} 点{damage_type}伤害{mods}{calc_info}")

    def freeze_break(self, target_name: str, damage_bonus: float):
        self._add(f"  [冻结解除] {target_name} 冻结被伤害解除，被伤害+{damage_bonus:.0f}%")

    def death(self, unit_name: str):
        self._add(f"  💀【阵亡】{unit_name} 倒下了！")

    def debuff_removed(self, target_name: str, removed_count: int, removed_names: List[str], source_name: str):
        names_str = ", ".join(f"«{n}»" for n in removed_names)
        self._add(f"  [解除减益] {target_name} 解除了 {removed_count} 个减益效果: {names_str} (来源:{source_name})")

    def buff_removed(self, target_name: str, removed_count: int, removed_names: List[str], source_name: str):
        names_str = ", ".join(f"«{n}»" for n in removed_names)
        self._add(f"  [解除增益] {target_name} 解除了 {removed_count} 个增益效果: {names_str} (来源:{source_name})")

    def mark_removed(self, target_name: str, mark_name: str, removed_count: int, source_name: str):
        self._add(f"  [标记清除] {target_name} 的 «{mark_name}» x{removed_count} 被清除 (来源:{source_name})")

    def pp_removed(self, target_name: str, amount: int, pp_after: int, pp_max: int, source_name: str, cover_for: str = ""):
        cover_str = f" (替{cover_for}援护吸收)" if cover_for else ""
        self._add(f"  [资源削除] {target_name} 被清除 {amount} PP{cover_str} (PP:{pp_after}/{pp_max} 来源:{source_name})")

    def ap_removed(self, target_name: str, amount: int, ap_after: int, ap_max: int, source_name: str, cover_for: str = ""):
        cover_str = f" (替{cover_for}援护吸收)" if cover_for else ""
        self._add(f"  [资源削除] {target_name} 被削减 {amount} AP{cover_str} (AP:{ap_after}/{ap_max} 来源:{source_name})")

    def ep_removed(self, target_name: str, amount: int, ep_after: int, ep_max: int, source_name: str, cover_for: str = ""):
        cover_str = f" (替{cover_for}援护吸收)" if cover_for else ""
        self._add(f"  [资源削除] {target_name} 被削减 {amount} EP{cover_str} (EP:{ep_after}/{ep_max} 来源:{source_name})")

    def tactical_exercise_stage_up(self, unit_name: str, stage: int,
                                    new_hp: int, new_atk: int, new_def: int, new_spd: int, new_crit: float,
                                    old_hp: int, old_atk: int, old_def: int, old_spd: int, old_crit: float,
                                    buffs_cleared: int, debuffs_cleared: int):
        """战术演习：敌方进入新阶段"""
        self._add(f"")
        self._add(f"  ╔══════════════════════════════════════════╗")
        self._add(f"  ║  🔥【战术演习】{unit_name} 进入阶段 {stage}！       ║")
        self._add(f"  ╠══════════════════════════════════════════╣")
        self._add(f"  ║  HP:  {old_hp} → {new_hp}                  ║")
        self._add(f"  ║  ATK: {old_atk} → {new_atk}                  ║")
        self._add(f"  ║  DEF: {old_def} → {new_def}                  ║")
        self._add(f"  ║  SPD: {old_spd} → {new_spd}                  ║")
        self._add(f"  ║  CRIT: {old_crit:.4f} → {new_crit:.4f}            ║")
        self._add(f"  ║  清除 Buff x{buffs_cleared}, Debuff x{debuffs_cleared}        ║")
        self._add(f"  ╚══════════════════════════════════════════╝")

    def buff_applied(self, target_name: str, effect: str, source_name: str, duration: int = 0, dur_type: str = "turn", detail: str = ""):
        detail_str = f" {detail}" if detail else ""
        if duration > 0:
            if dur_type == "action":
                unit_label = "行动"
            elif dur_type == "hit":
                unit_label = "次(Hit)"
            else:
                unit_label = "回合"
            dur_str = f" 持续:{duration}{unit_label}"
            self._add(f"  [获得增益] {target_name} «{effect}»{detail_str} (来源:{source_name}{dur_str})")
        else:
            self._add(f"  [获得增益] {target_name} «{effect}»{detail_str} (来源:{source_name})")

    def debuff_applied(self, target_name: str, effect: str, source_name: str, duration: int = 0, dur_type: str = "turn", detail: str = ""):
        detail_str = f" {detail}" if detail else ""
        if duration > 0:
            if dur_type == "action":
                unit_label = "行动"
            elif dur_type == "hit":
                unit_label = "次(Hit)"
            else:
                unit_label = "回合"
            dur_str = f" 持续:{duration}{unit_label}"
            self._add(f"  [获得减益] {target_name} «{effect}»{detail_str} (来源:{source_name}{dur_str})")
        else:
            self._add(f"  [获得减益] {target_name} «{effect}»{detail_str} (来源:{source_name})")

    def debuff_blocked(self, target_name: str, effect: str, source_name: str, reason: str = "debuff_immune"):
        if reason == "debuff_immune":
            self._add(f"  [免疫减益] {target_name} 免疫了 «{effect}» (来源:{source_name})")
        elif reason == "evade":
            self._add(f"  [闪避减益] {target_name} 闪避了 «{effect}» (来源:{source_name})")
        elif reason == "linked_mark_blocked":
            self._add(f"  [免疫减益] {target_name} 免疫了 «{effect}» (来源:{source_name}, 依附效果被免疫)")
        else:
            self._add(f"  [免疫减益] {target_name} 阻止了 «{effect}» (来源:{source_name})")

    def fury_add(self, target_name: str, fury_count: int):
        self._add(f"  [愤怒] {target_name} 获得愤怒 (当前: {fury_count})")

    def lifesteal(self, source_name: str, heal_amount: int, damage_based_on: int,
                  hp_before: int, hp_after: int, max_hp: int, cure_pct: float):
        self._add(f"  [吸血] {source_name} 回复 {heal_amount} HP (造成伤害{damage_based_on}的{cure_pct:.0f}%) HP:{hp_before}/{max_hp}→{hp_after}/{max_hp}")

    def heal(self, source_name: str, target_name: str, amount: int,
             source_hp: str = "", hp_before: int = 0, target_max_hp: int = 0,
             is_crit: bool = False, formula: str = ""):
        hp_after = hp_before + amount
        crit_tag = "【Critical】" if is_crit else ""
        formula_str = f" {formula}" if formula else ""
        if target_max_hp:
            self._add(f"  [治疗] {source_name} (HP:{hp_before}/{target_max_hp}) → {target_name} (HP:{hp_after}/{target_max_hp}): +{amount} HP {crit_tag}{formula_str}")
        else:
            self._add(f"  [治疗] {source_name} ({source_hp}) → {target_name} (HP:{hp_before}/{hp_after}): +{amount} HP {crit_tag}{formula_str}")

    def effect_update(self, unit_name: str, effect: str, duration: int, dur_type: str = "action"):
        unit_label = "行动" if dur_type == "action" else "回合"
        self._add(f"  [效果更新] {unit_name} 的 «{effect}» 持续时间→{duration}{unit_label}")

    def sub_unit_applied(self, target_name: str, sub_unit_name: str, sub_unit_hp: int,
                         sub_unit_max_hp: int, atk_dmg_pct: float, duration: int, dur_type: str = "action",
                         source_name: str = ""):
        unit_label = "行动" if dur_type == "action" else "回合"
        source_info = f" (来源:{source_name})" if source_name else ""
        self._add(f"  [子单位] {target_name} 召唤了「{sub_unit_name}」 HP:{sub_unit_hp}/{sub_unit_max_hp} 攻击力:{atk_dmg_pct:.1f}% 持续:{duration}{unit_label}{source_info}")

    def sub_unit_damage(self, sub_unit_name: str, target_name: str, damage: int,
                        hp_after: int, max_hp: int, crit: bool = False,
                        shield_absorbed: int = 0, calc_detail: dict = None):
        crit_str = "【Critical】" if crit else ""
        shield_str = f" (护盾吸收:{shield_absorbed})" if shield_absorbed > 0 else ""
        calc_info = ""
        if calc_detail and damage > 0:
            cd = calc_detail
            calc_info = (f" [snap_atk:{cd.get('snapshot_atk',0)} a_atk:{cd.get('a_atk',0)}"
                        f" b_def:{cd.get('b_def',0)} base:{cd.get('base_diff',0)}"
                        f" power:{cd.get('power_pct',0):.1f}%"
                        f" crit:{cd.get('crit_factor',1.0):.1f}"
                        f" dealt:{cd.get('a_dealt_mult',1.0):.4f}"
                        f" rcvd:{cd.get('b_received_mult',1.0):.4f}"
                        f" attr:{cd.get('advantage',1.0):.4f}]")
        self._add(f"  [子单位伤害] 「{sub_unit_name}」→ {target_name} (HP:{hp_after}/{max_hp}): {damage} 点物理伤害{crit_str}{shield_str}{calc_info}")

    def sub_unit_absorb(self, holder_name: str, sub_unit_name: str, absorbed: int,
                        sub_unit_hp_after: int, sub_unit_max_hp: int):
        self._add(f"  [子单位吸收] {holder_name} 的「{sub_unit_name}」吸收了 {absorbed} 点伤害 (HP:{sub_unit_hp_after}/{sub_unit_max_hp})")

    def sub_unit_expired(self, holder_name: str, sub_unit_name: str):
        self._add(f"  [子单位消失] {holder_name} 的「{sub_unit_name}」消失了")

    def effect_expired(self, unit_name: str, effect: str, is_debuff: bool = False):
        tag = "失去减益" if is_debuff else "失去增益"
        self._add(f"  [{tag}] {unit_name} «{effect}» 效果消失")

    def bonus_crit(self, unit_name: str, bonus: float):
        self._add(f"  [暴击率上升] {unit_name} 暴击率+{bonus:.0f}% (目标HP≤60%)")

    def resource_deduct(self, unit_name: str, skill_type: int, cost: int, ap: int, ap_max: int, pp: int, pp_max: int, ep: int, ep_max: int):
        if skill_type == 1:
            self._add(f"  [资源消耗] {unit_name} 消耗 {cost} AP (AP:{ap}/{ap_max})")
        elif skill_type == 3:
            self._add(f"  [资源消耗] {unit_name} 消耗全部 EP (EP:{ep}/{ep_max})")
        else:
            self._add(f"  [资源消耗] {unit_name} 消耗 {cost} PP (PP:{pp}/{pp_max})")

    def resource_restore(self, unit_name: str, ap: int, ap_max: int, pp: int = None, pp_max: int = None):
        if pp is not None and pp_max is not None:
            self._add(f"  [资源恢复] {unit_name} AP/PP恢复至满 (AP:{ap}/{ap_max} PP:{pp}/{pp_max})")
        else:
            self._add(f"  [资源恢复] {unit_name} AP恢复+1 (AP:{ap}/{ap_max})")

    def resource_restore_ep(self, unit_name: str, amount: int, ep: int, ep_max: int):
        self._add(f"  [资源恢复] {unit_name} EP恢复+{amount} (EP:{ep}/{ep_max})")

    def reset_cooldown(self, unit_name: str, skill_name: str):
        self._add(f"  [冷却重置] {unit_name} 的「{skill_name}」冷却时间已重置")

    def action_order(self, current_name: str, pending_names: List[str]):
        if pending_names:
            self._add(f"  [行动顺序] 当前:{current_name}  待行动: {', '.join(pending_names)}")
        else:
            self._add(f"  [行动顺序] 当前:{current_name}  全部行动完毕")

    def standby(self, unit_name: str, reason: str = ""):
        reason_str = f" ({reason})" if reason else ""
        self._add(f"  [待机] {unit_name} 无法行动，进入待机状态{reason_str}")

    def charge_start(self, unit_name: str, skill_name: str, skill_type: int = 1):
        st = SKILL_TYPE_LABEL.get(skill_type, "AS")
        self._add(f"  [蓄力·{st}] {unit_name} 开始蓄力「{skill_name}」，下次行动时发动")

    def charge_complete(self, unit_name: str, skill_name: str, skill_type: int = 1):
        st = SKILL_TYPE_LABEL.get(skill_type, "AS")
        self._add(f"  [蓄力完成·{st}] {unit_name} 蓄力完成，发动「{skill_name}」！")

    def charge_cancelled(self, unit_name: str, skill_name: str, reason: str = ""):
        reason_str = f" ({reason})" if reason else ""
        self._add(f"  [蓄力取消] {unit_name} 的「{skill_name}」蓄力被取消{reason_str}")

    def stunned(self, unit_name: str):
        self._add(f"  [眩晕] {unit_name} 处于眩晕状态，跳过行动!")

    def frozen(self, unit_name: str):
        self._add(f"  [冰冻] {unit_name} 处于冰冻状态，跳过行动!")

    def shield_added(self, unit_name: str, amount: int, total: int):
        self._add(f"  [护盾] {unit_name} 获得护盾 +{amount} (总护盾:{total})")

    def memory_effect(self, card_name: str, target_name: str, effect_desc: str):
        self._add(f"  [回忆卡] {card_name} → {target_name} : {effect_desc}")

    def system_message(self, text: str):
        self._add(f"  {text}")

    def turn_end_summary(self, alive_units: List[UnitState], display_names: Dict[str, str] = None):
        self._add("")
        self._add(f"  ──── 第{self._turn}回合结束 ────")
        for u in alive_units:
            name = (display_names or {}).get(u.unit_id, u.name) if display_names else u.name
            hp_pct = int(u.current_hp / u.max_hp * 100) if u.max_hp > 0 else 0
            self._add(f"    {name} HP:{u.current_hp}/{u.max_hp}({hp_pct}%)  AP:{u.current_ap}/{u.initial_active_point}  EP:{u.current_ep}/{u.max_extra_point}")

    def battle_end(self, winner: str, total_turns: int = 0):
        self._add("")
        result_text = u"胜利" if winner == "FRIEND" else (u"败北" if winner == "ENEMY" else u"超时")
        self._add(u"╔══════════════════════════════════════════════════╗")
        self._add(f"║              战斗结束 — {result_text}                      ║")
        if total_turns:
            self._add(f"║              总回合数: {total_turns}                          ║")
        self._add(u"╚══════════════════════════════════════════════════╝")

    def tactical_exercise_score(self, score_result):
        """战术演习计分统计输出"""
        self._add("")
        self._add(u"╔══════════════════════════════════════════════════╗")
        self._add(u"║              战术演习 · 计分统计                    ║")
        self._add(u"╠══════════════════════════════════════════════════╣")
        self._add(f"║  总得分: {score_result.total_score}")
        self._add(f"║  对敌方总伤害: {score_result.total_damage_to_enemies}")
        self._add(f"║  敌方总回复量: {score_result.enemy_healing_received}")
        self._add(f"║  清除阶段数: {score_result.stages_cleared}")
        self._add(f"║  总回合数: {score_result.total_turns}")
        self._add(f"║  战斗结果: {score_result.battle_result}")
        self._add(u"╠══════════════════════════════════════════════════╣")
        self._add(u"║  ◆ 己方单位统计")
        ally_stats = [s for s in score_result.unit_stats.values() if s.side == "ally"]
        for s in ally_stats:
            self._add(f"║    {s.name}: 伤害{s.damage_dealt} 受击{s.damage_received} 治疗{s.hp_healed}")
        self._add(u"╠══════════════════════════════════════════════════╣")
        self._add(u"║  ◆ 敌方单位统计")
        enemy_stats = [s for s in score_result.unit_stats.values() if s.side == "enemy"]
        for s in enemy_stats:
            self._add(f"║    {s.name}: 受击{s.damage_received} 回复{s.hp_received}")
        self._add(u"╚══════════════════════════════════════════════════╝")

    def composite_team_banner(self, team_index: int, total_teams: int):
        """联合战术演习队伍出战横幅"""
        self._add("")
        self._add(u"╔══════════════════════════════════════════════════╗")
        self._add(f"║       联合战术演习 · 队伍{team_index + 1}/{total_teams}出战             ║")
        self._add(u"╚══════════════════════════════════════════════════╝")
        self._add("")

    def composite_team_summary(self, team_index: int, net_damage: int, rounds: int,
                               team_wiped: bool, ally_stats: list, enemy_stats: list):
        """联合战术演习单队战斗结果摘要

        Args:
            team_index: 队伍索引(0-based)
            net_damage: 净伤害
            rounds: 回合数
            team_wiped: 是否团灭
            ally_stats: [(name, damage_dealt, damage_received, alive), ...]
            enemy_stats: [(name, damage_received, current_hp, max_hp), ...]
        """
        result_text = "团灭" if team_wiped else "存活"
        self._add("")
        self._add(u"╔══════════════════════════════════════════════════╗")
        self._add(f"║       队伍{team_index + 1} · 战斗结果")
        self._add(u"╠══════════════════════════════════════════════════╣")
        self._add(f"║  净伤害: {net_damage:,}  回合: {rounds}  结果: {result_text}")
        self._add(u"║──────────────────────────────────────────────────║")
        self._add(u"║  ◆ 己方单位统计")
        for name, dmg_dealt, dmg_recv, alive in ally_stats:
            status = "存活" if alive else "阵亡"
            self._add(f"║    {name}: 伤害{dmg_dealt:,} 受击{dmg_recv:,} {status}")
        self._add(u"║──────────────────────────────────────────────────║")
        self._add(u"║  ◆ 敌方单位统计")
        for name, dmg_recv, cur_hp, max_hp in enemy_stats:
            self._add(f"║    {name}: 受击{dmg_recv:,} HP:{cur_hp}/{max_hp}")
        self._add(u"╚══════════════════════════════════════════════════╝")
        self._add("")

    def composite_final_summary(self, total_score: int, team_results: list,
                                boss_killed_count: int, boss_stage: int):
        """联合战术演习最终结果

        Args:
            total_score: 总分数
            team_results: [{"damage_to_boss": x, "rounds_survived": y, "team_wiped": z}, ...]
            boss_killed_count: BOSS被击杀次数
            boss_stage: BOSS最终阶段
        """
        self._add("")
        self._add(u"╔══════════════════════════════════════════════════╗")
        self._add(u"║       联合战术演习 · 最终结果")
        self._add(u"╠══════════════════════════════════════════════════╣")
        self._add(f"║  总分数(净伤害): {total_score:,}")
        for i, tr in enumerate(team_results):
            result = "团灭" if tr.get("team_wiped") else "存活"
            self._add(f"║  队伍{i + 1}: 净伤害{tr.get('damage_to_boss', 0):,} "
                      f"回合{tr.get('rounds_survived', 0)} {result}")
        self._add(u"║──────────────────────────────────────────────────║")
        self._add(f"║  BOSS被击杀次数: {boss_killed_count}")
        self._add(f"║  BOSS最终阶段: {boss_stage}")
        self._add(u"╚══════════════════════════════════════════════════╝")

    def write(self, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self._lines))

    @staticmethod
    def generate_filename(base_dir: str = ".") -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{base_dir}/battle_{timestamp}.txt"