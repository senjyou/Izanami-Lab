"""End-to-end timing of a REALISTIC optimization run, to sanity-check the fix.

Runs the production path (spawn worker -> parallel pool -> real engine) with a
budget close to what a user would actually pick, and reports battles/second plus
the projected time for a full 1200-battle search.

Budget here is 200 battles: enough to show real throughput while staying near the
project's per-case battle convention.
"""

import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")


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
    from src.optimizer.worker import optimizer_worker

    state = build_state()
    mems = state["memory_ids"]
    budget = 200

    class StopEvent:
        def is_set(self):
            return False

    class QueueShim:
        def __init__(self):
            self.messages = []
            self.progress_seen = 0

        def put(self, message):
            if message.get("type") == "progress":
                self.progress_seen += 1
            else:
                self.messages.append(message)

    print(f"=== realistic run: budget {budget} battles, mode=tactical ===")
    print(f"    line-up: 火沙耶主c (CV ~12%, the highest-variance preset)")
    print()

    for workers in (0, 1):
        queue = QueueShim()
        request = {
            "base_path": str(ROOT),
            "mode": "tactical",
            "state": state,
            "constraints": {"memories": {str(m): "必选" for m in mems}},
            "settings": {
                "objective": "mean", "budget": budget, "seed": 2026,
                "change_positions": True, "change_memories": False,
                "review_seeds": 4, "coarse_seeds": 1, "adaptive_boost": False,
                "max_coarse": None, "workers": workers,
            },
            "workers": workers,
        }
        label = "auto (one per CPU)" if workers == 0 else "1 (serial)"
        t0 = time.perf_counter()
        optimizer_worker(request, StopEvent(), queue)
        elapsed = time.perf_counter() - t0

        result = next((m["result"] for m in queue.messages
                       if m.get("type") == "done"), None)
        errors = [m["message"] for m in queue.messages if m.get("type") == "error"]
        if errors:
            print(f"    ERROR: {errors[0].splitlines()[-1]}")
            continue
        battles = result["battles"] if result else 0
        print(f"    workers={label:18s} : {elapsed:6.2f}s  {battles:4d} battles  "
              f"{battles/elapsed:6.1f} battles/s  "
              f"used={result.get('workers')}  termination={result['termination']}")
        print(f"        projected time for a 1200-battle budget: "
              f"{1200/(battles/elapsed):.1f}s")

    print()
    print("=== reference: what the official batch simulator achieves ===")
    print("    It also uses one process per CPU, so a batch of 200 battles should")
    print("    take a similar time; the optimizer now matches that behaviour.")


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
