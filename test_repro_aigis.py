"""Reproduce bug: アイギスランパード (130009) doesn't trigger when
カウンターショット (230391, after_as_attacked PS counterattack) attacks the holder.
"""
import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

from src.data.data_loader import DataLoader
from src.entities_v2.unit_state import UnitState
from src.entities_v2.battlefield_state import BattlefieldState
from src.entities_v2.enums import Side, Position
from src.combat_v2.battle_flow_controller import BattleFlowController

AIGIS_RAMPART = 130009       # アイギスランパード (before_any_attacked, self-guard)
COUNTER_SHOT = 230391        # カウンターショット (after_as_attacked, counterattack)
MISEN_KAMAE = 230393         # 見切り構え・素 (before_any_attacked, self-guard)
ALLIED_AS = 220369           # 紫影の斬撃 (AS, enemy_all)


def _make_unit(unit_id, name, side, position, *, hp=100000, atk=10000,
               defense=4000, speed=500, element=2, character_type=1,
               skills=None, skill_levels=None, pp=10, ap=10):
    return UnitState(
        unit_id=unit_id, name=name, side=side, position=position,
        character_id=0, level=10, element=element,
        character_type=character_type,
        max_hp=hp, current_hp=hp,
        attack=atk, defense=defense, speed=speed,
        crit_rate=0.0, crit_damage=0.5, advantage_damage=0.0,
        initial_active_point=4, initial_passive_point=4, max_extra_point=10,
        current_ap=ap, current_pp=pp, current_ep=0,
        skills=skills or [], skill_levels=skill_levels or {},
        skill_cooldowns={},
    )


def main():
    dl = DataLoader()
    dl.load_all()

    # Ally: holder of アイギスランパード (slow, so enemy acts first in counter)
    ally = _make_unit("ally", "ノーブル・グレイス", Side.ALLY,
                      Position.ALLY_CENTER_FRONT, hp=200000,
                      skills=[AIGIS_RAMPART, ALLIED_AS],
                      skill_levels={AIGIS_RAMPART: 10, ALLIED_AS: 10},
                      speed=600)
    # Enemy: holder of カウンターショット + 見切り構え・素
    enemy = _make_unit("enemy", "霞光", Side.ENEMY,
                       Position.ENEMY_CENTER_FRONT, hp=1000000,
                       skills=[COUNTER_SHOT, MISEN_KAMAE],
                       skill_levels={COUNTER_SHOT: 10, MISEN_KAMAE: 10},
                       speed=400)

    bf = BattlefieldState()
    bf.friend_team = [ally]
    bf.enemy_team = [enemy]

    controller = BattleFlowController(bf, data_loader=dl)
    controller._build_display_names()
    controller.skill_service.set_battlefield(bf)
    controller._deferred_crit_triggers = []

    print("\n=== Repro: Ally AS attacks enemy, enemy counterattacks, ally's アイギスランパード should trigger ===")
    print(f"Ally HP before: {ally.current_hp}/{ally.max_hp}")
    print(f"Enemy HP before: {enemy.current_hp}/{enemy.max_hp}")

    # Manually execute the AS skill for the ally
    # This will trigger the full flow: AS damage → AFTER_AS_ATTACKED → counterattack
    # The counterattack should then trigger ally's BEFORE_ANY_ATTACKED (アイギスランパード)
    result = controller.skill_service.execute_skill(ally, ALLIED_AS, bf, skip_cost=True)
    print(f"\nAS result: success={result.get('success')}")

    # Now fire the AFTER_AS_ATTACKED triggers (normally done in _execute_unit_action)
    damaged_targets = []
    for applied in result.get("effects_applied", []):
        if applied.get("effect_type") == "damage":
            for t in applied.get("targets", []):
                target_unit = None
                for u in bf.get_all_units():
                    if u.unit_id == t.get('target_id', t.get('target')):
                        target_unit = u
                        break
                if target_unit:
                    damaged_targets.append(target_unit)

    print(f"Damaged targets: {[t.name for t in damaged_targets]}")

    # Fire AFTER_AS_ATTACKED
    after_as_attacked = controller.trigger_service.trigger_after_as_attacked(
        damaged_targets, bf, actor=ally, primary_target=damaged_targets[0] if damaged_targets else None
    )
    print(f"\nAFTER_AS_ATTACKED actions: {[(a.instance.owner.name, a.skill_id) for a in after_as_attacked]}")

    # Execute the counterattack PS
    controller._execute_trigger_actions(after_as_attacked, ally)

    print(f"\nAlly HP after: {ally.current_hp}/{ally.max_hp}")
    print(f"Enemy HP after: {enemy.current_hp}/{enemy.max_hp}")

    # Check if ally has guard buff (from アイギスランパード)
    ally_guard_buffs = [b for b in ally.buffs if b.effect_type == 'Guard']
    print(f"\nAlly Guard buffs: {len(ally_guard_buffs)}")
    for b in ally_guard_buffs:
        print(f"  - {b.effect_type} value={b.value} source={b.source_unit_id}")

    if ally.current_hp < ally.max_hp and not ally_guard_buffs:
        print("\n*** BUG REPRODUCED: Ally took damage from counterattack but NO guard buff from アイギスランパード ***")
    elif ally.current_hp < ally.max_hp and ally_guard_buffs:
        print("\n*** OK: アイギスランパード triggered (guard buff present) ***")
    elif ally.current_hp >= ally.max_hp:
        print("\n*** Counterattack may not have happened. ***")


if __name__ == '__main__':
    main()
