"""Survey ALL of the user's tactical presets: CV, normality, and Roll5 behaviour.

The earlier validation covered only 火沙耶主c. Design decisions (closed-form Roll5
vs empirical, seed count, whether to keep variance-penalising screens) depend on
how these distributions behave ACROSS the user's real lineups, not just one.

For each preset, from the live account config:
  * rebuild the exact state (positions, memories, panel from char_config)
  * run N battles
  * report CV, skewness/kurtosis (normality), max/min, Roll5
  * check the closed form  mean + 1.162964*sd  against the empirical Roll5
  * report how many seeds are needed for Roll5 ranking on THAT lineup

Budget: 10 presets x 60 battles = 600. Each preset is its own case (60 <= 100).
"""
import json
import logging
import math
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
glob = json.loads((ACC / "global_config.json").read_text(encoding="utf-8"))
chars = json.loads((ACC / "char_config.json").read_text(encoding="utf-8"))
C5 = 1.162964
N = 60
BASE_SEED = 500_000


def mem_id(entry):
    return int(str(entry).split("]")[0].lstrip("["))


def build_state(preset):
    positions = preset.get("friend_positions") or preset.get("friends")
    mems = preset.get("mems_friend") or preset.get("mem_friend_positions") or []
    panel = {
        "character_level": glob["character_level"],
        "school_levels": dict(glob["school_levels"]),
        "equipment_ids": [],
        "equipment_enabled": True,
        "equipment_bonuses": {int(k): dict(v) for k, v in glob.get("equipment", {}).items()},
        "character_levels": {}, "rarities": {}, "affection_levels": {},
        "modules": {}, "skill_levels": {},
    }
    for pos in positions:
        if not pos:
            continue
        c = chars.get(str(pos), {})
        panel["character_levels"][str(pos)] = c.get("level", glob["character_level"])
        panel["rarities"][str(pos)] = c.get("rarity", glob["default_rarity"])
        panel["affection_levels"][str(pos)] = c.get("affection", glob["default_affection"])
        panel["skill_levels"][str(pos)] = {str(k): v for k, v in c.get("skill_levels", {}).items()}
        gear = c.get("gear", [])
        mods = []
        for g, key in enumerate(("hp", "atk", "def")):
            tier = c.get(f"mod_tier_{key}", c.get("mod_tier", 10))
            lvl = c.get(f"mod_level_{key}", c.get("mod_level", 55))
            effs = [dict(effect_type=e["effect_type"], value=float(e["value"]))
                    for e in gear if e.get("group") == g]
            mods.append(dict(module_id=31 + g, tier=tier, level=lvl, gear_effects=effs))
        panel["modules"][str(pos)] = mods
    return {
        "schema": 1,
        "enemy_id": preset["enemy_id"],
        "friend_positions": list(positions),
        "memory_ids": sorted(mem_id(m) for m in mems),
        "panel": panel,
    }


def roll5_emp(s):
    xs = sorted(s)
    n = len(xs)
    return sum(x * ((i / n) ** 5 - ((i - 1) / n) ** 5) for i, x in enumerate(xs, start=1))


def c4(n):
    if n < 2:
        return float("nan")
    return math.sqrt(2.0 / (n - 1)) * math.exp(
        math.lgamma(n / 2.0) - math.lgamma((n - 1) / 2.0))


ev = TacticalEvaluator(str(ROOT), None)
presets = sorted((ACC / "tactical_presets").glob("*.json"), key=lambda f: f.stem)
print(f"surveying {len(presets)} presets x {N} battles = {len(presets)*N} battles\n")

results = []
for f in presets:
    preset = json.loads(f.read_text(encoding="utf-8"))
    try:
        state = build_state(preset)
    except Exception as exc:
        print(f"  {f.stem}: SKIP (build error: {exc})")
        continue
    scores = [ev.evaluate(state, BASE_SEED + i) for i in range(N)]
    xs = sorted(scores)
    mean = statistics.mean(scores)
    sd = statistics.stdev(scores)
    n = len(scores)
    m2 = sum((x - mean) ** 2 for x in scores) / n
    m3 = sum((x - mean) ** 3 for x in scores) / n
    m4 = sum((x - mean) ** 4 for x in scores) / n
    skew = m3 / (m2 ** 1.5) if m2 else 0.0
    kurt = m4 / (m2 ** 2) - 3 if m2 else 0.0
    r5 = roll5_emp(scores)
    cf = mean + C5 * sd
    # seed requirement for Roll5 ranking on this lineup
    need = {}
    for k in (4, 8, 16):
        errs = []
        rr = random.Random(7)
        for _ in range(600):
            s = [rr.choice(scores) for _ in range(k)]
            if k > 1 and statistics.stdev(s) > 0:
                est = statistics.mean(s) + C5 * statistics.stdev(s) / c4(k)
                errs.append((est - r5) / r5 * 100)
        need[k] = (statistics.mean(errs) if errs else 0.0,
                   statistics.stdev(errs) if len(errs) > 1 else 0.0)
    rec = dict(name=f.stem, mean=mean, sd=sd, cv=sd / mean * 100,
               mn=xs[0], mx=xs[-1], ratio=xs[-1] / xs[0] if xs[0] else 0,
               skew=skew, kurt=kurt, roll5=r5, closed=cf,
               closed_err=(cf - r5) / r5 * 100, need=need, scores=xs)
    results.append(rec)
    print(f"  {f.stem:22} CV={rec['cv']:5.2f}%  max/min={rec['ratio']:.3f}x  "
          f"skew={skew:+6.3f}  kurt={kurt:+6.3f}  "
          f"closed-err={rec['closed_err']:+6.2f}%  n_need8={need[8][1]:.2f}%")

print()
print("=" * 118)
print(f"{'preset':22} {'mean':>13} {'CV':>7} {'max/min':>8} {'skew':>7} {'kurt':>7} "
      f"{'Roll5':>13} {'closed err':>11} {'n=8 sd':>8} {'normal?':>8}")
for r in sorted(results, key=lambda r: -r["cv"]):
    ok = "yes" if abs(r["skew"]) < 0.5 and abs(r["kurt"]) < 1.0 else "CHECK"
    print(f"{r['name']:22} {r['mean']:>13,.0f} {r['cv']:>6.2f}% {r['ratio']:>7.3f}x "
          f"{r['skew']:>+7.3f} {r['kurt']:>+7.3f} {r['roll5']:>13,.0f} "
          f"{r['closed_err']:>+10.2f}% {r['need'][8][1]:>7.2f}% {ok:>8}")

cvs = [r["cv"] for r in results]
print()
print(f"  CV range  : {min(cvs):.2f}% .. {max(cvs):.2f}%   median {statistics.median(cvs):.2f}%")
errs = [abs(r["closed_err"]) for r in results]
print(f"  |closed-form error| : max {max(errs):.2f}%   median {statistics.median(errs):.2f}%")
worst = max(results, key=lambda r: abs(r["closed_err"]))
print(f"  worst closed-form : {worst['name']} ({worst['closed_err']:+.2f}%)")

(HERE / "preset_survey.json").write_text(json.dumps(
    {r["name"]: {k: v for k, v in r.items() if k != "scores"} for r in results},
    indent=1), encoding="utf-8")
(HERE / "preset_survey_scores.json").write_text(json.dumps(
    {r["name"]: r["scores"] for r in results}, indent=1), encoding="utf-8")
print(f"\nwrote preset_survey.json + preset_survey_scores.json")
