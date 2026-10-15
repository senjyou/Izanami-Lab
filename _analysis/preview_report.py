"""Preview the real rendered report, using the user's own account data.

Prints exactly what the result panel will show for a run shaped like the one the
user reported, so the two display rules can be checked by eye:

  * no character or memory id anywhere
  * a leaderboard, not a table
"""
import json
import logging
import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from gui.optimizer_report import NameResolver, format_report  # noqa: E402
from src.data.data_loader import DataLoader  # noqa: E402

ACC = Path(r"C:\Users\ARIS\AppData\Roaming\Izanami Lab\accounts\主号")

loader = DataLoader(base_path=str(ROOT))
loader.load_all()

# The user's reported champion and members, taken verbatim from their output.
best_positions = [100303, None, 132301, 117302, 104302, 113301]
best_mems = [30007, 30029, 30031, 30034, 30038, 30039]
current_positions = [100303, None, 145301, 112302, 111301, 117302]


def summary(rank, mean, sd, cv):
    return {"rank": rank, "mean": mean, "sd": sd, "cv": cv,
            "min": mean - 2 * sd, "max": mean + 2 * sd,
            "roll5": rank, "n": 8, "objective": "roll5"}


candidates = []
for i in range(10):
    pos = list(best_positions) if i % 2 == 0 else list(current_positions)
    mems = list(best_mems) if i % 2 == 0 else sorted(best_mems)[::-1]
    candidates.append({
        "rank": i + 1,
        "key": f"k{i}",
        "arrangement": pos,
        "memory_ids": mems,
        "is_baseline": (i == 7),
        "summary": summary(125_030_076 - i * 1_500_000,
                           113_177_162 - i * 900_000,
                           8_132_029 - i * 200_000,
                           7.2 + i * 0.15),
    })

result = {
    "mode": "tactical",
    "objective": "roll5",
    "settings": {"budget": 6408, "review_seeds": 8, "coarse_seeds": 2},
    "best": {"friend_positions": best_positions, "memory_ids": best_mems},
    "best_summary": summary(125_030_076, 113_177_162, 8_132_029, 7.2),
    "baseline": {"friend_positions": best_positions, "memory_ids": best_mems},
    "baseline_summary": summary(110_383_176, 108_581_142, 1_236_337, 1.1),
    "candidates": candidates,
    "battles": 6406,
    "cache_hits": 0,
    "elapsed": 143.3,
    "termination": "完成",
    "detail": "粗筛 2135 个候选，精评 1068 个（其余 1067 个受预算限制未精评）",
    "space": {"positions": 720, "memories": 924, "combined": 665_280},
    "workers": 16,
}

report = format_report(result, NameResolver(loader))
print(report)

print("=" * 66)
print("RULE CHECKS")
print("=" * 66)
leaked_chars = [cid for cid in best_positions if cid and str(cid) in report]
leaked_mems = [m for m in best_mems if str(m) in report]
print(f"  character ids leaked : {leaked_chars or 'none'}")
print(f"  memory ids leaked    : {leaked_mems or 'none'}")
print(f"  contains a bar chart : {any(c in report for c in '█░')}")
print(f"  contains tab columns : {chr(9)}{chr(9)} in report -> {chr(9)*2 in report}")
print(f"  names present        : "
      f"{sum(1 for m in best_mems if NameResolver(loader).memory(m) in report)}/6 memories")
print()
print("RESULT:", "PASS" if not leaked_chars and not leaked_mems else "FAIL")
sys.exit(0 if not leaked_chars and not leaked_mems else 1)
