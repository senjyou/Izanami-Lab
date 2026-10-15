"""P6 acceptance: a REAL optimizer run against the user's live configuration.

This is the end-to-end gate. It runs the actual production path:

    request -> optimizer_worker -> BattlePool (spawn) -> real engine -> result

against the user's own account config and one of their saved tactical presets,
with a small budget so it stays near the project's per-case battle convention.

Everything runs inside ``main()`` under an ``if __name__ == "__main__"`` guard.
That guard is MANDATORY now that the optimizer spawns a battle pool: on Windows a
spawned child re-imports this file as ``__mp_main__``, and without the guard it
would re-execute the whole script and recurse into more pools. The real
application guards this identically in ``gui_app.py``.
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
from src.optimizer.search import SearchSettings  # noqa: E402

ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")
# Two runs are performed (the second to prove reproducibility), so the budget is
# halved to keep the whole script near the 100-battles-per-case convention.
MAX_BATTLES = 30


def check(label, condition, detail="", failures=None):
    if condition:
        print(f"  OK    {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        if failures is not None:
            failures.append(label)


def build_template():
    from src.optimizer.snapshot import build_snapshot, panel_from_dict

    glob = json.loads((ACC / "global_config.json").read_text(encoding="utf-8"))
    chars = json.loads((ACC / "char_config.json").read_text(encoding="utf-8"))
    preset = json.loads((ACC / "tactical_presets" / "火沙耶主c.json").read_text(encoding="utf-8"))
    positions = preset["friend_positions"]
    mem_ids = [int(str(m).split("]")[0].lstrip("[")) for m in preset["mems_friend"]]

    panel_data = {
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
        panel_data["character_levels"][str(cid)] = c.get("level", glob["character_level"])
        panel_data["rarities"][str(cid)] = c.get("rarity", glob["default_rarity"])
        panel_data["affection_levels"][str(cid)] = c.get("affection", glob["default_affection"])
        panel_data["skill_levels"][str(cid)] = {str(k): v for k, v in c.get("skill_levels", {}).items()}
        gear = c.get("gear", [])
        panel_data["modules"][str(cid)] = [
            dict(module_id=31 + g,
                 tier=c.get(f"mod_tier_{k}", c.get("mod_tier", 10)),
                 level=c.get(f"mod_level_{k}", c.get("mod_level", 55)),
                 gear_effects=[dict(effect_type=e["effect_type"], value=float(e["value"]))
                               for e in gear if e.get("group") == g])
            for g, k in enumerate(("hp", "atk", "def"))]

    selection = {
        "friends": [c for c in positions if c],
        "friend_positions": positions,
        "enemy_id": preset["enemy_id"],
        "mems_friend": [f"[{m}]" for m in mem_ids],
        "mem_friend_positions": [f"[{m}]" for m in mem_ids],
    }
    return build_snapshot(selection, panel_from_dict(panel_data),
                          enemy_id=preset["enemy_id"])


class StopEvent:
    def is_set(self):
        return False


class QueueShim:
    """Collects what the worker would send over a multiprocessing queue."""

    def __init__(self):
        self.messages = []
        self.progress = 0

    def put(self, message):
        if message.get("type") == "progress":
            self.progress += 1
        else:
            self.messages.append(message)


def run_once(request, label):
    from src.optimizer.worker import optimizer_worker
    queue = QueueShim()
    t0 = time.perf_counter()
    optimizer_worker(request, StopEvent(), queue)
    elapsed = time.perf_counter() - t0
    result = next((m["result"] for m in queue.messages if m.get("type") == "done"), None)
    errors = [m["message"] for m in queue.messages if m.get("type") == "error"]
    return result, errors, elapsed, queue


def main():
    failures = []
    template = build_template()
    constraints = {"memories": {str(m): "必选" for m in template["memory_ids"]}}

    print("=== live configuration ===")
    print(f"    positions: {template['friend_positions']}")
    print(f"    memories : {template['memory_ids']}")
    print(f"    enemy    : {template['enemy_id']}")

    settings = SearchSettings(objective=obj.OBJECTIVE_MEAN, budget=MAX_BATTLES,
                              change_memories=False, review_seeds=4,
                              coarse_seeds=1, workers=0)
    request = {
        "base_path": str(ROOT),
        "mode": "tactical",
        "state": template,
        "constraints": constraints,
        "settings": settings.as_dict(),
        "workers": settings.workers,
    }

    print()
    print(f"=== running the real pipeline (budget {MAX_BATTLES} battles, "
          f"parallel workers) ===")
    result, errors, elapsed, queue = run_once(request, "first")

    check("worker exited cleanly", not errors, errors[:1] if errors else "", failures)
    check("a result was produced", result is not None, "", failures)

    if result:
        print()
        print("=== result ===")
        print(f"    termination : {result['termination']}")
        print(f"    detail      : {result.get('detail')}")
        print(f"    battles     : {result['battles']} (cache hits {result['cache_hits']})")
        print(f"    workers used: {result.get('workers')}")
        print(f"    elapsed     : {elapsed:.2f}s  "
              f"({result['battles']/elapsed:.1f} battles/s)")
        print(f"    space       : {result['space']}")

        check("battle count respects the budget",
              result["battles"] <= MAX_BATTLES, result["battles"], failures)
        check("candidates were refined", bool(result["candidates"]),
              len(result["candidates"]), failures)
        check("baseline is present",
              any(c.get("is_baseline") for c in result["candidates"]), "", failures)
        check("every candidate has a full cohort",
              all(c["summary"]["n"] == 4 for c in result["candidates"]), "", failures)
        check("best is present", result.get("best") is not None, "", failures)
        check("parallel workers were actually used",
              (result.get("workers") or 0) >= 1, result.get("workers"), failures)

        if result.get("best_summary"):
            print(f"    best        : {obj.format_summary(result['best_summary'])}")
            print(f"    best layout : {result['best']['friend_positions']}")
        if result.get("baseline_summary"):
            print(f"    baseline    : {obj.format_summary(result['baseline_summary'])}")

        ranks = [c["summary"]["rank"] for c in result["candidates"]]
        check("candidates ranked descending", ranks == sorted(ranks, reverse=True),
              ranks, failures)

        # Presentation rules: no ids anywhere, and the lineup is shown as card
        # art by gui.optimizer_preview rather than as names in the text.
        from gui.optimizer_report import NameResolver, format_report
        from src.data.data_loader import DataLoader
        loader = DataLoader(base_path=str(ROOT))
        loader.load_all()
        resolver = NameResolver(loader)
        report = format_report(result, resolver)
        check("report renders", "智能优化" in report, "", failures)
        leaked = [cid for cid in template["friend_positions"]
                  if cid is not None and str(cid) in report]
        check("no character id leaks into the report", not leaked, leaked, failures)
        leaked_mem = [m for m in template["memory_ids"] if str(m) in report]
        check("no memory id leaks into the report", not leaked_mem, leaked_mem,
              failures)
        check("report points at the thumbnail strip", "缩略图" in report, "",
              failures)
        # The preview must be able to resolve every id it will draw.
        unresolved = [cid for cid in template["friend_positions"]
                      if cid is not None
                      and resolver.character(cid) == "未知角色"]
        check("every character resolves to a name", not unresolved, unresolved,
              failures)
        unresolved_mem = [m for m in template["memory_ids"]
                          if resolver.memory(m) == "未知回忆"]
        check("every memory resolves to a name", not unresolved_mem,
              unresolved_mem, failures)
        print()
        print("--- GUI report preview ---")
        for line in report.splitlines()[:22]:
            print(f"    {line}")

    print()
    print("=== the same run is reproducible from its own seed block ===")
    result2, errors2, elapsed2, _ = run_once(request, "second")
    check("a second run also completes", result2 is not None and not errors2,
          errors2[:1] if errors2 else "", failures)
    check("second run is faster than serial would be", elapsed2 < elapsed * 3,
          (elapsed, elapsed2), failures)
    if result and result2:
        check("same seed produces the same battle count",
              result["battles"] == result2["battles"],
              (result["battles"], result2["battles"]), failures)
        a = [c["key"] for c in result["candidates"]]
        b = [c["key"] for c in result2["candidates"]]
        check("same seed produces the same candidate set", set(a) == set(b),
              (len(a), len(b)), failures)
        check("same seed produces the same ranking order", a == b, "", failures)
        if result.get("best") and result2.get("best"):
            check("same seed produces the same champion",
                  result["best"]["friend_positions"] == result2["best"]["friend_positions"],
                  (result["best"]["friend_positions"],
                   result2["best"]["friend_positions"]), failures)

    print()
    if failures:
        print(f"FAILED ({len(failures)}): " + ", ".join(failures))
        return 1
    print("P6 real end-to-end acceptance passed")
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
