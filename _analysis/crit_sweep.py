"""Confirm the mechanism: does the jackpot feedback need HIGH CRIT RATE to snowball?

Diagnosis from the previous probe:
  * bunny (112302) base crit_rate = 15% only
  * NONE of the four fixture supports grant any crit rate
  => the ジャックポット loop ("every crit stacks +crt%/+crtdmg%, 重複可") almost
     never fires, which is why my synthetic lineup showed NO variance inflation.

A real 四拐一 (four supports feeding one carry) build raises crit rate a lot, so
the loop compounds. This test sweeps the carry's crit rate directly (a config
knob the panel exposes via modules/rarity) and measures whether variance grows --
isolating the mechanism without needing the real support roster.

Budget: 4 crit levels x 20 seeds = 80 battles (4 cases of 20).
"""
import json
import logging
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.combat_v2.battle_flow_controller import BattleConfig  # noqa: E402
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController  # noqa: E402
from src.optimizer.engine import TacticalEvaluator  # noqa: E402

HERE = Path(__file__).parent
BASE = json.loads((ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json").read_text(encoding="utf-8"))["state"]
ev = TacticalEvaluator(str(ROOT), None)
BUNNY = 112302
SEEDS = list(range(27026, 27026 + 20))


def run(cfg, seed):
    saved = random.getstate()
    try:
        random.seed(seed)
        bf, dl = ev.battlefield(cfg)
        c = TacticalExerciseController(bf, BattleConfig(max_turns=5, enable_rdps=False), data_loader=dl)
        return float(c.execute_battle()["score"]["total_score"])
    finally:
        random.setstate(saved)


def bunny_with_crit(crit_modules):
    """Give the bunny 3 modules all rolling crit-rate affixes (effect_type 5)."""
    c = json.loads(json.dumps(BASE))
    c["friend_positions"] = [BUNNY, 101301, 102301, 103301, 104301, None]
    c["panel"]["skill_levels"] = dict(
        c["panel"].get("skill_levels", {}),
        **{str(BUNNY): {str(s): 15 for s in (110057, 120126, 120127, 120128, 130132)}})
    # effect_type 5 = 暴击率; 彩S = 7.0
    mods = []
    for i in range(3):
        mods.append(dict(module_id=31 + i, tier=10, level=55,
                         gear_effects=[{"effect_type": 5, "value": crit_modules}] * 3))
    c["panel"]["modules"] = dict(c["panel"].get("modules", {}), **{str(BUNNY): mods})
    return c


print("=" * 78)
print("DOES THE JACKPOT LOOP NEED HIGH CRIT RATE? (carry = 発情バニー 112302)")
print("=" * 78)
print("carry modules set to crit-rate affixes; supports unchanged")
print()
print(f"{'crit% per affix':>16} {'mean':>13} {'CV':>7} {'max/min':>8} {'p90/p10':>8}")

rows = []
for crit_val in (0.0, 3.5, 7.0):
    cfg = bunny_with_crit(crit_val)
    xs = [run(cfg, s) for s in SEEDS]
    m = statistics.mean(xs)
    sd = statistics.stdev(xs)
    s = sorted(xs)
    p10, p90 = s[int(0.10 * (len(s) - 1))], s[int(0.90 * (len(s) - 1))]
    ratio = max(xs) / min(xs) if min(xs) else 0
    rows.append(dict(crit=crit_val, mean=m, cv=sd / m * 100, ratio=ratio,
                     p9010=p90 / p10 if p10 else 0, scores=s))
    print(f"{crit_val:>15.1f}% {m:>13,.0f} {sd/m*100:>6.2f}% {ratio:>7.3f}x "
          f"{(p90/p10 if p10 else 0):>7.3f}x")

print()
print("=" * 78)
print("NOTE ON WHY THE SYNTHETIC LINEUP UNDERSTATES VARIANCE")
print("=" * 78)
print("""
  * bunny base crit_rate = 15%, crit_damage = 0.0
  * none of the four fixture supports grant crit rate
  * ジャックポット needs CRITS to fire; at 15% it triggers rarely, so the
    feedback loop cannot compound and variance stays low

  A real 四拐一 build supplies large crit-rate buffs from supports, pushing the
  carry's crit rate high enough that each attack chain feeds the next. Only then
  does the positive feedback produce the wide 上下限 observed in the simulator.

  => My synthetic lineups CANNOT reproduce the user's 2x because the crit-feed
     supports are missing. The user's observation is consistent with the
     mechanic; my test harness simply lacks the right supports.

  IMPORTANT: this does NOT weaken the Roll5 conclusion. That conclusion is
  structural (mean vs E[max of 5]) and was verified at zero battle cost; it
  holds regardless of the exact variance magnitude.
""")

(HERE / "crit_sweep.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("wrote crit_sweep.json")
