"""Verify the parallel optimizer: correctness, determinism, and real speedup.

Three things must hold before the parallel path can replace the serial one:

  1. **Identical results** - the pool must return exactly the scores the serial
     path returns for the same (state, seed). Anything else would silently change
     what the optimizer optimizes.
  2. **Worker-count independence** - the same search with 1 worker and with 8 must
     produce the same champion, because the search is seeded, not order-dependent.
  3. **Real speedup** - measured against the serial path.

Everything runs inside ``main()`` under an ``if __name__ == "__main__"`` guard.
That is mandatory for a spawn-based pool on Windows: a child re-imports this file
as ``__mp_main__``, and without the guard it would re-execute the whole script and
recurse. (The real application guards this the same way in ``gui_app.py``.)
"""

import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.optimizer import objective as obj  # noqa: E402
from src.optimizer.engine import Evaluator  # noqa: E402
from src.optimizer.parallel import BattlePool, resolve_workers  # noqa: E402
from src.optimizer.search import SearchSettings, run_search  # noqa: E402

ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")
failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  OK    {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


def build_state():
    glob = json.loads((ACC / "global_config.json").read_text(encoding="utf-8"))
    chars = json.loads((ACC / "char_config.json").read_text(encoding="utf-8"))
    preset = json.loads((ACC / "tactical_presets" / "火沙耶主c.json").read_text(encoding="utf-8"))
    positions = preset["friend_positions"]
    mems = sorted(int(str(m).split("]")[0].lstrip("[")) for m in preset["mems_friend"])
    panel = {
        "character_level": glob["character_level"],
        "school_levels": dict(glob["school_levels"]),
        "equipment_ids": [], "equipment_enabled": True,
        "equipment_bonuses": {int(k): dict(v) for k, v in glob.get("equipment", {}).items()},
        "character_levels": {}, "rarities": {}, "affection_levels": {},
        "modules": {}, "skill_levels": {},
    }
    for cid in positions:
        if not cid:
            continue
        c = chars[str(cid)]
        panel["character_levels"][str(cid)] = c.get("level", glob["character_level"])
        panel["rarities"][str(cid)] = c.get("rarity", glob["default_rarity"])
        panel["affection_levels"][str(cid)] = c.get("affection", glob["default_affection"])
        panel["skill_levels"][str(cid)] = {str(k): v for k, v in c.get("skill_levels", {}).items()}
        gear = c.get("gear", [])
        panel["modules"][str(cid)] = [
            dict(module_id=31 + g,
                 tier=c.get(f"mod_tier_{k}", c.get("mod_tier", 10)),
                 level=c.get(f"mod_level_{k}", c.get("mod_level", 55)),
                 gear_effects=[dict(effect_type=e["effect_type"], value=float(e["value"]))
                               for e in gear if e.get("group") == g])
            for g, k in enumerate(("hp", "atk", "def"))]
    return {"schema": 1, "enemy_id": preset["enemy_id"],
            "friend_positions": list(positions), "memory_ids": mems, "panel": panel}


def main():
    state = build_state()
    mems = state["memory_ids"]

    print("=== 1. resolve_workers ===")
    check("0 means automatic (one per CPU)", resolve_workers(0, 100) >= 1,
          resolve_workers(0, 100))
    check("capped by available jobs", resolve_workers(0, 3) == 3, resolve_workers(0, 3))
    check("explicit value respected", resolve_workers(4, 100) == 4, resolve_workers(4, 100))
    check("explicit value still capped", resolve_workers(16, 2) == 2, resolve_workers(16, 2))

    print()
    print("=== 2. pool scores identical to serial scores ===")
    SEEDS = [880000 + i for i in range(8)]
    ev = Evaluator(str(ROOT), None, mode="tactical")
    serial = [ev.evaluate(state, s) for s in SEEDS]
    del ev
    with BattlePool(str(ROOT), None, mode="tactical", workers=4) as pool:
        got = pool.evaluate_jobs([(state, SEEDS)], phase="verify")[0]
    check("pool == serial (exact)", serial == got)
    for a, b in list(zip(serial, got))[:3]:
        print(f"        serial={a:,.0f}  pool={b:,.0f}")
    print(f"    pool reported {pool.battles} battles")

    print()
    print("=== 3. real speedup: 24 battles ===")
    N = 24
    SEEDS2 = [890000 + i for i in range(N)]
    TASKS = [(state, s) for s in SEEDS2]
    ev = Evaluator(str(ROOT), None, mode="tactical")
    t0 = time.perf_counter()
    for s in SEEDS2:
        ev.evaluate(state, s)
    t_serial = time.perf_counter() - t0
    del ev
    print(f"    serial   : {t_serial:.2f}s  {N/t_serial:.1f} battles/s")

    for n in (4, 8, 16):
        with BattlePool(str(ROOT), None, mode="tactical", workers=n) as pool:
            t0 = time.perf_counter()
            pool.evaluate_battles(TASKS, phase="verify")
            t_par = time.perf_counter() - t0
        print(f"    {n:2d} workers: {t_par:.2f}s  {N/t_par:.1f} battles/s  "
              f"speedup {t_serial/t_par:.2f}x  (incl. pool startup)")

    print()
    print("=== 4. worker-count independence: same champion ===")
    constraints = {"memories": {str(m): "必选" for m in mems}}

    def run_with(workers):
        settings = SearchSettings(objective=obj.OBJECTIVE_MEAN, budget=120,
                                  change_memories=False, review_seeds=4,
                                  coarse_seeds=1, workers=workers,
                                  adaptive_boost=False)
        if workers == 0:
            ev = Evaluator(str(ROOT), None, mode="tactical")
            return run_search(ev, state, constraints, settings, pool=None)
        with BattlePool(str(ROOT), None, mode="tactical", workers=workers) as pool:
            return run_search(None, state, constraints, settings, pool=pool)

    t0 = time.perf_counter()
    serial_result = run_with(0)
    t_s = time.perf_counter() - t0
    print(f"    serial   : {t_s:.2f}s  champion={serial_result.best['friend_positions']}"
          f"  battles={serial_result.battles}")

    t0 = time.perf_counter()
    par_result = run_with(8)
    t_p = time.perf_counter() - t0
    print(f"    8 workers: {t_p:.2f}s  champion={par_result.best['friend_positions']}"
          f"  battles={par_result.battles}")

    check("same battle count", serial_result.battles == par_result.battles,
          (serial_result.battles, par_result.battles))
    check("same champion",
          serial_result.best["friend_positions"] == par_result.best["friend_positions"],
          (serial_result.best["friend_positions"], par_result.best["friend_positions"]))
    s_keys = [c["key"] for c in serial_result.candidates]
    p_keys = [c["key"] for c in par_result.candidates]
    check("same candidate set", set(s_keys) == set(p_keys), (len(s_keys), len(p_keys)))
    check("same ranking order", s_keys == p_keys)
    print(f"    search speedup: {t_s/t_p:.2f}x")

    print()
    if failures:
        print(f"FAILED ({len(failures)}): " + ", ".join(failures))
        return 1
    print("parallel verification passed")
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())

