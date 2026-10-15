"""Is the ジャックポット crit-stacking mechanic actually ENGAGING in my test lineup?

My previous run showed no variance inflation, which is suspicious. Before
concluding anything I must verify the mechanic fires. Unbounded stacking
("重複可") should show up as a growing count of crit_rate_up / crit_dmg_up buffs
on 112302 during the battle.

If the stack count stays ~0, my lineup is misconfigured (wrong skill levels,
wrong position, or the passive never triggers) and the variance number is
meaningless.
"""
import json
import logging
import random
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.combat_v2.battle_flow_controller import BattleConfig  # noqa: E402
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController  # noqa: E402
from src.optimizer.engine import TacticalEvaluator  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json").read_text(encoding="utf-8"))["state"]
ev = TacticalEvaluator(str(ROOT), None)
BUNNY = 112302

print("=== fixture skill_levels (what is configured today?) ===")
print(json.dumps(BASE["panel"].get("skill_levels", {}), ensure_ascii=False)[:400])
print()
print("=== fixture modules for the 5 chars ===")
mods = BASE["panel"].get("modules", {})
for cid, m in list(mods.items())[:6]:
    print(f"  {cid}: {len(m)} modules, tier={[x.get('tier') for x in m]}, "
          f"levels={[x.get('level') for x in m]}")


def probe(cfg, label):
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    saved = random.getstate()
    seen = {}
    try:
        random.seed(18026)
        bf, dl = ev.battlefield(cfg)
        c = TacticalExerciseController(bf, BattleConfig(max_turns=5, enable_rdps=False),
                                       data_loader=dl)
        # capture the bunny's crit-related buffs at battle start, then after each turn
        orig_turn = getattr(c, "_execute_turn", None)

        def snapshot(tag):
            for u in bf.friend_team:
                if u.character_id != BUNNY:
                    continue
                cr = [b for b in getattr(u, "buffs", [])
                      if b.effect_type in ("crit_rate_up", "crit_dmg_up", "StatusCriticalChance")]
                keys = {}
                for b in cr:
                    keys[b.effect_type] = keys.get(b.effect_type, 0) + 1
                seen[tag] = dict(counts=keys, total=len(cr),
                                 crit_rate=getattr(u, "critical_rate", None),
                                 crit_dmg=getattr(u, "critical_damage", None))

        orig_mem = c._apply_memory_card_effects

        def hooked_mem():
            orig_mem()
            snapshot("after_memory")
        c._apply_memory_card_effects = hooked_mem

        res = c.execute_battle()
        snapshot("after_battle")
        print(f"  score = {float(res['score']['total_score']):,.0f}")
        for tag, d in seen.items():
            print(f"  [{tag}] crit-buff stacks={d['counts']} total={d['total']} "
                  f"crit_rate={d['crit_rate']} crit_dmg={d['crit_dmg']}")
    finally:
        random.setstate(saved)


# correctness of skill levels matters: give bunny maxed skills explicitly
def with_max_skills(cfg):
    c = json.loads(json.dumps(cfg))
    sl = dict(c["panel"].get("skill_levels", {}))
    sl[str(BUNNY)] = {str(s): 15 for s in (110057, 120126, 120127, 120128, 130132)}
    c["panel"]["skill_levels"] = sl
    return c


bunny_cfg = json.loads(json.dumps(BASE))
bunny_cfg["friend_positions"] = [BUNNY, 101301, 102301, 103301, 104301, None]
bunny_cfg["memory_ids"] = sorted(BASE["memory_ids"])

probe(dict(BASE, memory_ids=sorted(BASE["memory_ids"])), "A) baseline (no bunny)")
probe(bunny_cfg, "B) bunny, fixture skill levels")
probe(with_max_skills(bunny_cfg), "C) bunny, skills forced to level 15")
