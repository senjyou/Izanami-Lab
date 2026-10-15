"""Measure DataLoader memory footprint, to pick a safe worker count.

Each spawned worker on Windows re-loads the data (no fork copy-on-write), so the
process count multiplies this footprint. This measures it.
"""

import logging
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)


def rss_mb():
    try:
        import ctypes
        import ctypes.wintypes as wt

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters),
            counters.cb)
        return counters.WorkingSetSize / 1024 / 1024
    except Exception as exc:
        return float("nan")


print(f"baseline RSS (bare interpreter, + src import) : {rss_mb():.0f} MB")

from src.optimizer.engine import Evaluator  # noqa: E402

print(f"after importing engine                        : {rss_mb():.0f} MB")

ev = Evaluator(str(ROOT), None, mode="tactical")
print(f"after Evaluator() = DataLoader.load_all()      : {rss_mb():.0f} MB")

print()
print("=== projected total with N spawned workers ===")
base = rss_mb()
for n in (4, 6, 8, 12, 16):
    print(f"    {n:2d} workers + parent : ~{base * (n + 1):.0f} MB")

print()
print("=== compare: one real battle, to confirm build vs fight cost ===")
import json  # noqa: E402
import time  # noqa: E402

ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")
glob = json.loads((ACC / "global_config.json").read_text(encoding="utf-8"))
chars = json.loads((ACC / "char_config.json").read_text(encoding="utf-8"))
preset = json.loads((ACC / "tactical_presets" / "火沙耶主c.json").read_text(encoding="utf-8"))
positions = preset["friend_positions"]
mems = sorted(int(str(m).split("]")[0].lstrip("[")) for m in preset["mems_friend"])
panel = {"character_level": glob["character_level"],
         "school_levels": dict(glob["school_levels"]),
         "equipment_ids": [], "equipment_enabled": True,
         "equipment_bonuses": {int(k): dict(v) for k, v in glob.get("equipment", {}).items()},
         "character_levels": {}, "rarities": {}, "affection_levels": {},
         "modules": {}, "skill_levels": {}}
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
         "friend_positions": list(positions), "memory_ids": mems, "panel": panel}

# split build vs fight cost precisely
t0 = time.perf_counter()
for i in range(20):
    bf, loader = ev.battlefield(state)
t_build = (time.perf_counter() - t0) / 20

t0 = time.perf_counter()
for i in range(20):
    ev.evaluate(state, 800000 + i)
t_all = (time.perf_counter() - t0) / 20

print(f"    build battlefield only : {t_build*1000:.1f} ms")
print(f"    full evaluate          : {t_all*1000:.1f} ms")
print(f"    => fight (build subtracted): {(t_all - t_build)*1000:.1f} ms")
print(f"    => build is {t_build/t_all*100:.1f}% of the per-battle cost")
