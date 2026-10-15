"""Measure the costs that decide how to parallelize the optimizer.

Answers three questions:
  1. How big is a candidate state when pickled (does IPC cost matter)?
  2. How long does a spawn pool take to start, and does DataLoader-per-worker fit?
  3. What speedup does a pool actually deliver on real battles?
"""

import json
import logging
import multiprocessing as mp
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")
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

state = {"schema": 1, "enemy_id": preset["enemy_id"],
         "friend_positions": list(positions), "memory_ids": mems,
         "panel": panel}

print("=== 1. state pickle size / cost ===")
blob = pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)
print(f"    pickled size: {len(blob):,} bytes ({len(blob)/1024:.1f} KiB)")
t0 = time.perf_counter()
for _ in range(200):
    pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)
t = (time.perf_counter() - t0) / 200
print(f"    dumps: {t*1000:.3f} ms    loads: ", end="")
t0 = time.perf_counter()
for _ in range(200):
    pickle.loads(blob)
t2 = (time.perf_counter() - t0) / 200
print(f"{t2*1000:.3f} ms")
print(f"    => sending state once per JOB (not per battle) costs "
      f"~{(t+t2)*1000:.2f} ms/job; at 277 ms/battle that is "
      f"{(t+t2)/0.277*100:.2f}% overhead")

print()
print("=== 2. spawn pool startup (workers load DataLoader in initializer) ===")


def _init(base_path):
    from src.data.data_loader import DataLoader
    global _DL
    _DL = DataLoader(base_path=base_path)
    _DL.load_all()
    _DL.get_tactical_exercise_enemies()


def _ping(_):
    return 1


for n in (2, 4, 8, 16):
    ctx = mp.get_context("spawn")
    t0 = time.perf_counter()
    with ctx.Pool(processes=n, initializer=_init, initargs=(str(ROOT),)) as pool:
        pool.map(_ping, range(n))
        t1 = time.perf_counter()
        print(f"    {n:2d} workers: {t1-t0:.2f}s to become ready")

print()
print("=== 3. real battle throughput: serial vs pool ===")
N = 32
SEEDS = [700000 + i for i in range(N)]


def _battle_serial(args):
    """One battle in the worker, using the per-process DataLoader."""
    state, seed = args
    from src.optimizer.engine import Evaluator
    global _EV
    try:
        _EV
    except NameError:
        _EV = Evaluator(str(ROOT), None, mode="tactical")
    return _EV.evaluate(state, seed)


def _init_eval(base_path):
    from src.optimizer.engine import Evaluator
    global _EV
    _EV = Evaluator(base_path, None, mode="tactical")


t0 = time.perf_counter()
for s in SEEDS:
    _battle_serial((state, s))
t_serial = time.perf_counter() - t0
print(f"    serial      : {t_serial:.2f}s  {N/t_serial:.1f} battles/s")

for n in (4, 8, 16):
    ctx = mp.get_context("spawn")
    t0 = time.perf_counter()
    with ctx.Pool(processes=n, initializer=_init_eval, initargs=(str(ROOT),)) as pool:
        scores = pool.map(_battle_serial, [(state, s) for s in SEEDS], chunksize=1)
    t_par = time.perf_counter() - t0
    print(f"    pool {n:2d}     : {t_par:.2f}s  {N/t_par:.1f} battles/s"
          f"   speedup {t_serial/t_par:.2f}x (incl. startup)")

print()
print("=== 4. correctness: pool results must equal serial results ===")
ctx = mp.get_context("spawn")
with ctx.Pool(processes=4, initializer=_init_eval, initargs=(str(ROOT),)) as pool:
    pool_scores = pool.map(_battle_serial, [(state, s) for s in SEEDS[:8]], chunksize=1)
serial_scores = [_battle_serial((state, s)) for s in SEEDS[:8]]
same = all(abs(a - b) < 1e-9 for a, b in zip(pool_scores, serial_scores))
print(f"    identical: {same}")
for a, b in zip(pool_scores[:3], serial_scores[:3]):
    print(f"      pool={a:,.0f}  serial={b:,.0f}")
