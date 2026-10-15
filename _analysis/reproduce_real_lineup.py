"""REPRODUCE the user's real 100-battle run from their actual account config.

Source of truth (read-only, from the live user profile):
  C:\\Users\\ARIS\\AppData\\Roaming\\Izanami Lab\\accounts\\主号\\tactical_presets\\火沙耶主c.json
  C:\\Users\\ARIS\\AppData\\Roaming\\Izanami Lab\\accounts\\主号\\global_config.json
  C:\\Users\\ARIS\\AppData\\Roaming\\Izanami Lab\\accounts\\主号\\char_config.json

User's reported 100-battle result:
  mean 80,597,341.4   sd 9,415,342.4
  max 103,253,240     min 59,662,680
  Q1 73,804,246       Q3 88,705,667.5
  Roll5 91,485,697

Goal: rebuild the exact state, confirm the reported numbers reproduce, and then
measure the distribution shape that drives Roll5.

Budget: 100 battles, matching the user's own run (their config has runs=100;
this is a reproduction of a real acceptance case, not a test-suite case).
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

from src.optimizer.engine import TacticalEvaluator  # noqa: E402

HERE = Path(__file__).parent
ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")

preset = json.loads((ACC / "tactical_presets" / "火沙耶主c.json").read_text(encoding="utf-8"))
glob = json.loads((ACC / "global_config.json").read_text(encoding="utf-8"))
chars = json.loads((ACC / "char_config.json").read_text(encoding="utf-8"))

POSITIONS = preset["friend_positions"]


def mem_id(entry):
    return int(str(entry).split("]")[0].lstrip("["))


MEMORY_IDS = [mem_id(m) for m in preset["mems_friend"]]


def module_from_char(cid, group):
    """Build the 3 modules for a character from char_config gear entries."""
    c = chars[str(cid)]
    gear = c.get("gear", [])
    mods = []
    for g in range(3):
        try:
            typ = {"hp": c.get(f"mod_tier_hp", c.get("mod_tier", 10)),
                   "atk": c.get(f"mod_tier_atk", c.get("mod_tier", 10)),
                   "def": c.get(f"mod_tier_def", c.get("mod_tier", 10))}[("hp", "atk", "def")[g]]
            lvl = {"hp": c.get(f"mod_level_hp", c.get("mod_level", 55)),
                   "atk": c.get(f"mod_level_atk", c.get("mod_level", 55)),
                   "def": c.get(f"mod_level_def", c.get("mod_level", 55))}[("hp", "atk", "def")[g]]
        except Exception:
            typ, lvl = 10, 55
        effs = [dict(effect_type=e["effect_type"], value=float(e["value"]))
                for e in gear if e.get("group") == g]
        mods.append(dict(module_id=31 + g, tier=typ, level=lvl, gear_effects=effs))
    return mods


panel = {
    "character_level": glob["character_level"],
    "school_levels": dict(glob["school_levels"]),
    "equipment_ids": [],
    "equipment_enabled": True,
    "equipment_bonuses": {int(k): dict(v) for k, v in glob.get("equipment", {}).items()},
    "character_levels": {},
    "rarities": {},
    "affection_levels": {},
    "modules": {},
    "skill_levels": {},
}
for pos in POSITIONS:
    if pos is None:
        continue
    c = chars.get(str(pos))
    if not c:
        continue
    panel["character_levels"][str(pos)] = c.get("level", glob["character_level"])
    panel["rarities"][str(pos)] = c.get("rarity", glob["default_rarity"])
    panel["affection_levels"][str(pos)] = c.get("affection", glob["default_affection"])
    panel["skill_levels"][str(pos)] = {str(k): v for k, v in c.get("skill_levels", {}).items()}
    panel["modules"][str(pos)] = module_from_char(pos, None)

state = {
    "schema": 1,
    "enemy_id": preset["enemy_id"],
    "friend_positions": list(POSITIONS),
    "memory_ids": sorted(MEMORY_IDS),
    "panel": panel,
}

print("=" * 78)
print("REBUILT STATE FROM USER'S LIVE CONFIG")
print("=" * 78)
print(f"  lineup    : {[p for p in POSITIONS]}")
print(f"  enemy     : {preset['enemy_id']}")
print(f"  memories  : {state['memory_ids']}")
print(f"  char level: {panel['character_level']}  rarity default {glob['default_rarity']}")
print(f"  runs(glob): {glob.get('runs')}   max_turns: {glob.get('max_turns')}")
print()
for pos in POSITIONS:
    if pos is None:
        continue
    g = chars[str(pos)].get("gear", [])
    print(f"  {pos}: L{panel['character_levels'][str(pos)]} R{panel['rarities'][str(pos)]} "
          f"sk={list(panel['skill_levels'][str(pos)].values())} gear={len(g)}")

ev = TacticalEvaluator(str(ROOT), None)

# user's seed basis: the batch path uses time-based seeds; we use a fixed block
N = 100
BASE_SEED = 300_000
seeds = [BASE_SEED + i for i in range(N)]

scores = []
for s in seeds:
    scores.append(ev.evaluate(state, s))

xs = sorted(scores)


def quantile(sorted_xs, p):
    if not sorted_xs:
        return 0.0
    idx = p * (len(sorted_xs) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_xs) - 1)
    frac = idx - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def roll5(samples):
    sx = sorted(samples)
    n = len(sx)
    return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5) for i, x in enumerate(sx, start=1))


mean = statistics.mean(scores)
sd = statistics.stdev(scores)
r5 = roll5(scores)
print()
print("=" * 78)
print(f"REPRODUCTION: {N} battles on the rebuilt state")
print("=" * 78)
print(f"  {'metric':22} {'mine':>16} {'yours':>16} {'diff':>9}")
USER = dict(mean=80597341.4, sd=9415342.4, mx=103253240.0, mn=59662680.0,
            q1=73804246.0, q3=88705667.5, r5=91485697.0)
rows = [("mean", mean, USER["mean"]), ("sd", sd, USER["sd"]),
        ("max", max(scores), USER["mx"]), ("min", min(scores), USER["mn"]),
        ("Q1", quantile(xs, 0.25), USER["q1"]), ("Q3", quantile(xs, 0.75), USER["q3"]),
        ("Roll5", r5, USER["r5"])]
for label, mine, yours in rows:
    d = (mine - yours) / yours * 100 if yours else 0
    print(f"  {label:22} {mine:>16,.1f} {yours:>16,.1f} {d:>+8.2f}%")

print()
print(f"  CV = {sd/mean*100:.3f}%   (yours {(USER['sd']/USER['mean'])*100:.3f}%)")
print(f"  max/min = {max(scores)/min(scores):.4f}x  "
      f"(yours {USER['mx']/USER['mn']:.4f}x)")

# ---- distribution shape + Roll5 implication ----
print()
print("=" * 78)
print("DISTRIBUTION SHAPE (drives Roll5)")
print("=" * 78)
n = len(scores)
m2 = sum((x - mean) ** 2 for x in scores) / n
m3 = sum((x - mean) ** 3 for x in scores) / n
m4 = sum((x - mean) ** 4 for x in scores) / n
skew = m3 / (m2 ** 1.5) if m2 else 0
kurt = m4 / (m2 ** 2) - 3 if m2 else 0
C5 = 1.162964
print(f"  skewness        {skew:+.3f}   (0 = normal)")
print(f"  excess kurtosis {kurt:+.3f}   (0 = normal)")
print(f"  observed Roll5      {r5:,.0f}")
print(f"  normal approx       {mean + C5*sd:,.0f}   "
      f"(diff {(mean + C5*sd - r5)/r5*100:+.2f}%)")

hist_lo, hist_hi = xs[0], xs[-1]
nb = 12
w = (hist_hi - hist_lo) / nb if hist_hi > hist_lo else 1
print("\n  histogram:")
for i in range(nb):
    a = hist_lo + i * w
    b = a + w
    c = sum(1 for x in xs if (a <= x < b) or (i == nb - 1 and x == hist_hi))
    print(f"    {a:>13,.0f} - {b:>13,.0f} | {'#'*c} {c}")

# how many seeds for a stable Roll5 here?
print()
print("=" * 78)
print("SEED REQUIREMENT FOR ROLL5 ON THIS REAL LINEUP")
print("=" * 78)
ref = r5
rng = random.Random(99)
print(f"  {'seeds':>6} {'Roll5 mean':>15} {'bias':>12} {'sd':>12} {'rel sd':>8}")
for k in (2, 4, 8, 16, 32, 64):
    ests = []
    for _ in range(200):
        samp = rng.sample(scores, k)
        ests.append(roll5(samp))
    m = statistics.mean(ests)
    s_ = statistics.stdev(ests)
    print(f"  {k:>6} {m:>15,.0f} {m-ref:>12,.0f} {s_:>12,.0f} {s_/ref*100:>7.2f}%")

(HERE / "real_lineup_reproduction.json").write_text(json.dumps(
    dict(state=state, scores=scores, mean=mean, sd=sd, roll5=r5,
         user=USER), indent=1), encoding="utf-8")
print(f"\nwrote real_lineup_reproduction.json")
