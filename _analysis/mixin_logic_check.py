"""Unit-level checks of the optimizer tab mixin's pure logic.

Avoids the whole application (and the Windows-only pywinstyles dependency) by
driving the parts of the mixin that only transform data: pool construction,
constraint translation, and the position/memory apply path against fake slots.
"""

import sys
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))

from gui.optimizer_tab_mixin import OptimizeTabMixin  # noqa: E402
from src.optimizer import space as space_mod  # noqa: E402

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  OK    {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


class FakeLoader:
    """Minimal loader: only the memory catalogue is needed by these paths."""

    def __init__(self, ids):
        self._ids = ids

    def load_memories(self):
        return {mid: None for mid in self._ids}


class FakeSlots:
    def __init__(self, n, key):
        self.slots = [{"cid": None} for _ in range(n)] if key == "char" \
            else [{"mid": None} for _ in range(n)]


class FakeTab(OptimizeTabMixin):
    _OPTIMIZE_MODE = "tactical"

    def __init__(self, memories, selection):
        self._memories = memories
        self._selection = selection
        self.app = type("App", (), {"data_loader": FakeLoader(memories)})()
        self.char = [{"cid": None} for _ in range(6)]
        self.mem = [{"mid": None} for _ in range(6)]
        self.changed = 0

    # --- tab contract the mixin relies on ---
    def _get_selection(self):
        return self._selection

    def _get_char_slots(self, is_enemy=False):
        return self.char

    def _get_mem_slots(self, is_enemy=False):
        return self.mem

    def _set_slot_char(self, slot, cid):
        slot["cid"] = cid

    def _clear_slot(self, slot):
        slot["cid"] = None

    def _set_mem_slot(self, index, mid, is_enemy=False):
        self.mem[index]["mid"] = mid

    def _clear_mem_slot(self, index, is_enemy=False):
        self.mem[index]["mid"] = None

    def _after_slot_changed(self):
        self.changed += 1


print("=== memory catalogue access ===")
tab = FakeTab([10001, 10002, 10003], {})
pool = tab._optimize_all_memories()
check("catalogue read", pool == [10001, 10002, 10003], pool)

print()
print("=== pinned-memory reading from the selection ===")
sel = {"friends": [1], "mems_friend": ["[30031] お嬢様", "[30025] 絶対命令"]}
tab = FakeTab([30031, 30025, 30042], sel)
check("pinned parsed from names", tab._optimize_pinned_memories() == [30031, 30025],
      tab._optimize_pinned_memories())

print()
print("=== space + budget planning (now owned by the dialog/budget module) ===")
template = {"schema": 1, "enemy_id": 1, "friend_positions": [1, 2, 3, 4, 5, None],
            "memory_ids": [30031, 30025, 30042, 10001, 10002, 10003],
            "panel": {"character_level": 200, "school_levels": {},
                      "equipment_ids": [], "equipment_enabled": True,
                      "equipment_bonuses": {}, "character_levels": {},
                      "rarities": {}, "affection_levels": {}, "modules": {},
                      "skill_levels": {}}}
from src.optimizer import budget as budget_mod  # noqa: E402
from src.optimizer import space as space_mod  # noqa: E402
import math  # noqa: E402

# A realistic pool: nothing pinned, 12 cards to choose 6 from.
pool12 = {"memories": {str(m): "候选" for m in range(1, 13)}}


class _S:
    change_positions = True
    change_memories = True
    seed = 0


positions, memories, combined = space_mod.space_size(template, pool12, _S())
check("pool drives the combination count",
      memories == math.comb(12, 6), memories)
check("positions multiply in", combined == positions * memories, combined)
plan = budget_mod.plan_search(combined, "roll5")
check("plan produced", plan["budget"] > 0, plan)
print(f"        {budget_mod.describe_plan(plan)}")
check("plan mentions screening and refining",
      "候选" in budget_mod.describe_plan(plan))
check("plan is honest about sampling",
      ("抽样" in budget_mod.describe_plan(plan))
      or plan["exhaustive"])

print()
print("=== pinning shrinks the space ===")
pinned = {"memories": {**{str(m): "必选" for m in (1, 2)},
                       **{str(m): "候选" for m in range(3, 13)}}}
_, mem_pinned, _ = space_mod.space_size(template, pinned, _S())
check("2 pinned leaves C(10,4)", mem_pinned == math.comb(10, 4), mem_pinned)
check("pinning reduces the space", mem_pinned < memories,
      f"{memories} -> {mem_pinned}")

print()
print("=== an unusable pool is reported, not searched ===")
narrow = {"memories": {"1": "必选"}}     # 5 required, no candidates to fill slot 6
try:
    space_mod.space_size(template, narrow, _S())
    check("too-small pool raises", False, "no exception")
except Exception as exc:
    check("too-small pool raises", True)
    print(f"        {exc}")

print()
print("=== apply a snapshot back into the slots ===")
tab = FakeTab([30031, 30025, 30042, 10001, 10002, 10003], sel)
state = {"friend_positions": [7, None, 8, 9, 10, 11],
         "memory_ids": [30031, 30025, 30042, 10001, 10002, 10003]}
tab._optimize_apply(state)
check("positions written", [s["cid"] for s in tab.char] == [7, None, 8, 9, 10, 11],
      [s["cid"] for s in tab.char])
check("memories written", [s["mid"] for s in tab.mem] == state["memory_ids"],
      [s["mid"] for s in tab.mem])
check("tab notified of the change", tab.changed == 1, tab.changed)

print()
print("=== apply with a short memory list clears the rest ===")
tab = FakeTab([30031], sel)
tab._optimize_apply({"friend_positions": [1, 2, 3, 4, 5, None],
                     "memory_ids": [30031, 30025]})
check("missing memory slots cleared", [s["mid"] for s in tab.mem][2:] == [None] * 4,
      [s["mid"] for s in tab.mem])

print()
print("=== mode label and base-path helpers ===")
check("tactical label", tab._optimize_mode_label() == "战术演习")
class CircleTab(FakeTab):
    _OPTIMIZE_MODE = "circle"
check("circle label", CircleTab([1], {})._optimize_mode_label() == "对抗压制战")
check("base path resolves", bool(tab._optimize_base_path()))
check("user dir resolves", bool(tab._optimize_user_dir()))

print()
if failures:
    print(f"FAILED ({len(failures)}): " + ", ".join(failures))
    sys.exit(1)
print("all mixin logic checks passed")
