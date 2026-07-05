"""Reproduce bug: アイギスランパード (130009) doesn't trigger when
カウンターショット (230391, after_as_attacked PS counterattack) attacks the holder,
because the cooldown was set by a previous trigger during the same turn.

Scenario:
1. Enemy attacks ally → アイギスランパード triggers → cooldown set to 1
2. Ally's action starts → cooldown still 1 (not decremented yet)
3. Ally attacks enemy with AS → enemy counterattacks
4. アイギスランパード should trigger but cooldown=1 → SKIPPED (BUG)
5. End of ally's action → cooldown decremented to 0
"""
import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
for name in ['src.combat_v2.battle_narrative', 'src.combat_v2.battle_logger']:
    logging.getLogger(name).setLevel(logging.WARNING)

from src.data.data_loader import DataLoader
from src.entities_v2.unit_state import UnitState
from src.entities_v2.battlefield_state import BattlefieldState
from src.entities_v2.enums import Side, Position
from src.combat_v2.battle_flow_controller import BattleFlowController, BattleConfig

AIGIS_RAMPART = 130009
COUNTER_SHOT = 230391
MISEN_KAMAE = 230393
ALLIED_AS = 120013
NOBLE_CHAR_ID = 121301


def _make_unit(unit_id, name, side, position, *, hp=100000, atk=10000,
               defense=4000, speed=500, element=2, character_type=1,
               character_id=0, skills=None, skill_levels=None, pp=10, ap=10):
    return UnitState(
        unit_id=unit_id, name=name, side=side, position=position,
        character_id=character_id, level=10, element=element,
        character_type=character_type,
        max_hp=hp, current_hp=hp,
        attack=atk, defense=defense, speed=speed,
        crit_rate=0.0, crit_damage=0.5, advantage_damage=0.0,
        initial_active_point=4, initial_passive_point=4, max_extra_point=0,
        current_ap=ap, current_pp=pp, current_ep=0,
        skills=skills or [], skill_levels=skill_levels or {},
        skill_cooldowns={},
    )


def main():
    dl = DataLoader()
    dl.load_all()

    # Ally: ノーブル・グレイス with AS + アイギスランパード
    ally = _make_unit("ally", "ノーブル・グレイス", Side.ALLY,
                      Position.ALLY_CENTER_FRONT, hp=200000,
                      character_id=NOBLE_CHAR_ID,
                      skills=[AIGIS_RAMPART, ALLIED_AS],
                      skill_levels={AIGIS_RAMPART: 10, ALLIED_AS: 10},
                      speed=600, element=5, pp=10)
    # Enemy: holder of カウンターショット + 見切り構え・素
    enemy = _make_unit("enemy", "霞光", Side.ENEMY,
                       Position.ENEMY_CENTER_FRONT, hp=1000000,
                       skills=[COUNTER_SHOT, MISEN_KAMAE],
                       skill_levels={COUNTER_SHOT: 10, MISEN_KAMAE: 10},
                       speed=400, element=1, pp=10)

    bf = BattlefieldState()
    bf.friend_team = [ally]
    bf.enemy_team = [enemy]

    config = BattleConfig(max_turns=1)
    controller = BattleFlowController(bf, data_loader=dl, config=config)
    controller._build_display_names()
    controller.skill_service.set_battlefield(bf)
    controller._deferred_crit_triggers = []

    print("\n=== Scenario: Simulate アイギスランパード triggered earlier (cooldown=1) ===")
    print(f"Ally HP before: {ally.current_hp}/{ally.max_hp}")
    print(f"Ally PP before: {ally.current_pp}")
    print(f"Ally skill_cooldowns before: {ally.skill_cooldowns}")

    # Step 0: Simulate that アイギスランパード was triggered earlier (by another enemy attack)
    # Set cooldown to 1 as if it was triggered during a previous enemy's action
    ally.skill_cooldowns[AIGIS_RAMPART] = 1
    print(f"\n[SETUP] Set ally skill_cooldowns[{AIGIS_RAMPART}] = 1 (simulating previous trigger)")

    # Step 1: Execute AS (ally's action)
    print("\n--- Step 1: Execute AS (ソーヴィニヨン) ---")
    result = controller.skill_service.execute_skill(ally, ALLIED_AS, bf, skip_cost=True)
    print(f"AS result: success={result.get('success')}")
    print(f"Ally skill_cooldowns after AS: {ally.skill_cooldowns}")

    # Step 2: Collect damaged targets
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

    # Step 3: Fire AFTER_AS_ATTACKED
    print("\n--- Step 3: Fire AFTER_AS_ATTACKED ---")
    primary_target = damaged_targets[0] if damaged_targets else None
    after_as_attacked = controller.trigger_service.trigger_after_as_attacked(
        damaged_targets, bf, actor=ally, primary_target=primary_target
    )
    print(f"AFTER_AS_ATTACKED actions: {[(a.instance.owner.name, a.skill_id) for a in after_as_attacked]}")

    # Step 4: Execute the counterattack PS
    print("\n--- Step 4: Execute counterattack PS via _execute_trigger_actions ---")
    hp_before_counter = ally.current_hp
    controller._execute_trigger_actions(after_as_attacked, ally)

    print(f"\n--- Results ---")
    print(f"Ally HP: {hp_before_counter} -> {ally.current_hp}")
    print(f"Ally skill_cooldowns: {ally.skill_cooldowns}")

    # Check if ally has guard buff (from アイギスランパード)
    ally_guard_buffs = [b for b in ally.buffs if b.effect_type == 'Guard']
    print(f"Ally Guard buffs: {len(ally_guard_buffs)}")

    # Check if ally took full damage (no guard)
    hp_lost = hp_before_counter - ally.current_hp
    if hp_lost > 0 and not ally_guard_buffs:
        print(f"\n*** BUG REPRODUCED: Ally took {hp_lost} damage from counterattack with NO guard (cooldown blocked アイギスランパード) ***")
    elif hp_lost > 0 and ally_guard_buffs:
        print(f"\n*** OK: アイギスランパード triggered despite cooldown (guard buff present) ***")
    elif hp_lost == 0:
        print(f"\n*** Counterattack may not have happened. ***")


if __name__ == '__main__':
    main()
