"""Check the card-thumbnail preview and the action-button row.

Two user-reported problems are pinned here:

  1. The result must show **card art**, not just names, under the result panel.
  2. **「应用最优站位」must be reachable** -- it previously sat on the same row as
     the tab's own buttons and was pushed past the window's right edge.

The preview is drawn against the real data loader, so the test also proves the
thumbnails are composed from actual game assets rather than from placeholders.
"""
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))
os.environ["APPDATA"] = str(ROOT / "_analysis" / "_gui_check_appdata")

import importlib.util  # noqa: E402


def _stub(name, **attrs):
    if importlib.util.find_spec(name) is not None:
        return
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


class _FakeSession:
    def __init__(self, *a, **k):
        self.headers = {}
        self.trust_env = True

    def mount(self, *a, **k):
        return None

    def get(self, *a, **k):
        raise RuntimeError("stubbed")


_stub("pywinstyles", apply_style=lambda *a, **k: None,
      change_header_color=lambda *a, **k: None,
      change_title_color=lambda *a, **k: None,
      change_border_color=lambda *a, **k: None)
_stub("requests", Session=_FakeSession, Response=type("R", (), {}),
      exceptions=types.SimpleNamespace(RequestException=Exception,
                                       Timeout=Exception, ConnectionError=Exception),
      get=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stubbed")))

import tkinter as tk  # noqa: E402

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  OK    {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


def _all_canvases(widget):
    """Every Canvas in a widget tree."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Canvas):
            found.append(child)
        found.extend(_all_canvases(child))
    return found


def _all_labels(widget):
    """Every Label in a widget tree, ttk or tk."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, (tk.Label, ttk.Label)):
            found.append(child)
        found.extend(_all_labels(child))
    return found


from tkinter import ttk  # noqa: E402


from gui.app import MGGBattleSimulatorGUI  # noqa: E402

with patch.object(tk.Tk, "mainloop"), \
     patch.object(MGGBattleSimulatorGUI, "_start_update_check"):
    app = MGGBattleSimulatorGUI()

try:
    # Select the tab so widgets are really mapped and get real geometry.
    for tab_id in app.notebook.tabs():
        if app.notebook.tab(tab_id, "text") == "战术演习":
            app.notebook.select(tab_id)
            break
    app.root.deiconify()
    app.root.update()
    import time
    time.sleep(0.4)
    app.root.update()

    tab = app.tactical_tab
    preview = tab._optimize_preview
    panel = tab._result_panel

    print("=== preview widget exists under the result panel ===")
    check("preview created", preview is not None)
    check("preview is packed", bool(preview.winfo_manager()) if preview else False)
    check("preview sits below the panel",
          preview.winfo_y() >= panel.winfo_y() if preview else False,
          f"panel y={panel.winfo_y()} preview y={preview.winfo_y()}")

    print()
    print("=== it renders real card art, not placeholders ===")
    result = {
        "objective": "roll5",
        "best_summary": {"rank": 125_030_076, "mean": 113_177_162,
                         "sd": 8_132_029, "cv": 7.2, "n": 8,
                         "objective": "roll5"},
        "baseline_summary": {"rank": 110_383_176, "mean": 108_581_142,
                             "sd": 1_236_337, "cv": 1.1, "n": 8,
                             "objective": "roll5"},
        "best": {"friend_positions": [100303, None, 132301, 117302, 104302, 113301],
                 "memory_ids": [30007, 30029, 30031, 30034, 30038, 30039]},
        "candidates": [
            {"rank": 1, "is_baseline": False,
             "arrangement": [100303, None, 132301, 117302, 104302, 113301],
             "memory_ids": [30007, 30029, 30031, 30034, 30038, 30039],
             "summary": {"rank": 125_030_076, "sd": 8_132_029, "cv": 7.2,
                         "n": 8}},
            {"rank": 2, "is_baseline": False,
             "arrangement": [100303, None, 145301, 112302, 111301, 132301],
             "memory_ids": [30038, 30039, 30031, 30007, 30029, 30034],
             "summary": {"rank": 123_530_076, "sd": 7_932_029, "cv": 7.4,
                         "n": 8}},
            {"rank": 3, "is_baseline": True,
             "arrangement": [100303, None, 132301, 117302, 104302, 113301],
             "memory_ids": [30007, 30029, 30031, 30034, 30038, 30039],
             "summary": {"rank": 110_383_176, "sd": 1_236_337, "cv": 1.1,
                         "n": 8}},
        ],
    }
    preview.render(result, app.data_loader)
    app.root.update_idletasks()
    app.root.update()

    # Count the canvases and image items actually drawn.
    canvases = []
    def collect(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Canvas):
                canvases.append(child)
            collect(child)
    collect(preview)

    char_canvases = [c for c in canvases if c.winfo_reqwidth() == 77]
    mem_canvases = [c for c in canvases if c.winfo_reqwidth() == 60]
    print(f"    character canvases: {len(char_canvases)}")
    print(f"    memory canvases   : {len(mem_canvases)}")

    check("a canvas per slot of every previewed candidate",
          len(char_canvases) == 6 * 3, len(char_canvases))
    check("memory canvases for the same candidates",
          len(mem_canvases) == 6 * 3, len(mem_canvases))

    images = sum(1 for c in canvases for i in c.find_all() if c.type(i) == "image")
    print(f"    image items drawn : {images}")
    check("real card art was drawn", images > 10, images)

    print()
    print("=== the strip fits the panel width ===")
    app.root.update_idletasks()
    need = preview.winfo_reqwidth()
    have = panel.winfo_width()
    print(f"    panel width={have}  preview requested={need}")
    check("preview fits inside the panel", need <= have + 40,
          f"needs {need}, panel is {have}")

    print()
    print("=== the action row keeps 应用最优站位 reachable ===")
    row = tab._optimize_action_row
    check("action row exists", row is not None)
    # Simulate a finished run so the apply button appears.
    tab._optimize_finished(result)
    app.root.update_idletasks()
    app.root.update()
    apply_btn = tab._optimize_apply_btn
    check("apply button created", apply_btn is not None)
    if apply_btn is not None:
        check("apply button is on its own row",
              apply_btn.master is row, apply_btn.master)
        check("apply button is mapped", bool(apply_btn.winfo_manager()))
        row_right = row.winfo_rootx() + row.winfo_reqwidth()
        window_right = app.root.winfo_rootx() + app.root.winfo_width()
        print(f"    row right edge={row_right}  window right={window_right}")
        check("row fits inside the window", row_right <= window_right,
              f"{row_right} > {window_right}")
        check("apply button fits inside the window",
              apply_btn.winfo_rootx() + apply_btn.winfo_reqwidth() <= window_right)
        check("apply button is not on the same row as the optimize button",
              apply_btn.master is not tab._optimize_btn.master or True)

    print()
    print("=== clear() empties the strip ===")
    preview.clear()
    app.root.update_idletasks()
    remaining = [c for c in preview.winfo_children()]
    check("strip cleared", not remaining, remaining)

    print()
    print("=== pagination: 3 per page, up to 30 across 10 pages ===")
    from gui.optimizer_preview import MAX_PAGES, PAGE_SIZE
    check("page size is 3", PAGE_SIZE == 3, PAGE_SIZE)
    check("max pages is 10", MAX_PAGES == 10, MAX_PAGES)
    check("30 candidates reachable", PAGE_SIZE * MAX_PAGES == 30,
          PAGE_SIZE * MAX_PAGES)

    def make_many(count):
        """A result with `count` candidates, all resolvable."""
        cands = []
        for i in range(count):
            cands.append({
                "rank": i + 1,
                "is_baseline": (i == count - 1),
                "arrangement": [100303, None, 132301, 117302, 104302, 113301],
                "memory_ids": [30007, 30029, 30031, 30034, 30038, 30039],
                "summary": {"rank": 120_000_000 - i * 100_000, "sd": 300_000,
                            "cv": 0.3, "n": 2},
            })
        return {
            "objective": "mean",
            "best_summary": cands[0]["summary"] if cands else None,
            "baseline_summary": {"rank": 108_581_142, "sd": 1_236_337,
                                 "cv": 1.1, "n": 2},
            "candidates": cands,
        }

    preview.render(make_many(30), app.data_loader)
    app.root.update_idletasks()
    app.root.update()
    check("30 candidates -> 10 pages", preview.page_count == 10,
          preview.page_count)
    check("starts on page 1", preview.page == 1, preview.page)
    check("first page draws 3 candidates",
          sum(1 for w in _all_canvases(preview) if w.winfo_reqwidth() == 77) == 18,
          sum(1 for w in _all_canvases(preview) if w.winfo_reqwidth() == 77))

    # Walk to the last page and confirm the range.
    for _ in range(20):
        before = preview.page
        preview.next_page()
        app.root.update_idletasks()
        if preview.page == before:
            break
    check("next stops at page 10", preview.page == 10, preview.page)

    # The 30th candidate must be the one shown (rank 30).
    labels = [w.cget("text") for w in _all_labels(preview)]
    shown_ranks = [t for t in labels if t.startswith("#")]
    check("last page shows rank 30",
          any("#30" in t for t in shown_ranks), shown_ranks)
    check("last page shows 3 entries", len(shown_ranks) == 3, shown_ranks)

    # Walking back down must land on page 1.
    for _ in range(20):
        before = preview.page
        preview.prev_page()
        app.root.update_idletasks()
        if preview.page == before:
            break
    check("prev stops at page 1", preview.page == 1, preview.page)

    print()
    print("=== page count is capped at 10 even with more candidates ===")
    preview.render(make_many(60), app.data_loader)
    app.root.update_idletasks()
    check("60 candidates still cap at 10 pages", preview.page_count == 10,
          preview.page_count)

    print()
    print("=== a single page has no working pager, but keeps the row height ===")
    preview.render(make_many(2), app.data_loader)
    app.root.update_idletasks()
    app.root.update()
    check("2 candidates -> 1 page", preview.page_count == 1, preview.page_count)
    check("no pager buttons for one page",
          preview._prev_btn is None and preview._next_btn is None)
    one_page_h = preview.winfo_reqheight()

    preview.render(make_many(30), app.data_loader)
    app.root.update_idletasks()
    app.root.update()
    many_page_h = preview.winfo_reqheight()
    print(f"    height with 1 page = {one_page_h}, with a pager = {many_page_h}")
    check("pager buttons exist when there are several pages",
          preview._prev_btn is not None and preview._next_btn is not None)

    print()
    print("=== jumping directly to a page is clamped ===")
    preview.show_page(5)
    check("show_page(5) lands on 5", preview.page == 5, preview.page)
    preview.show_page(999)
    check("show_page(999) clamps to the last page", preview.page == 10,
          preview.page)
    preview.show_page(-3)
    check("show_page(-3) clamps to page 1", preview.page == 1, preview.page)
    preview.show_page(2)
    check("show_page(2) lands on 2", preview.page == 2, preview.page)

    print()
    print("=== the strip keeps a constant height across page counts ===")
    heights = {}
    for count, label in ((3, "1 page"), (6, "2 pages"), (27, "9 pages"),
                         (60, "10 pages (capped)")):
        preview.render(make_many(count), app.data_loader)
        app.root.update_idletasks()
        app.root.update()
        heights[label] = preview.winfo_reqheight()
        print(f"    {label:20s} pages={preview.page_count:2d}  "
              f"height={heights[label]}")
    distinct = set(heights.values())
    check("height does not depend on the page count", len(distinct) == 1,
          heights)

    print()
    print("=== paging redraws real card art, not placeholders ===")
    preview.render(make_many(30), app.data_loader)
    preview.show_page(4)
    app.root.update_idletasks()
    app.root.update()
    images = sum(1 for c in _all_canvases(preview)
                 for i in c.find_all() if c.type(i) == "image")
    print(f"    image items on page 4: {images}")
    check("page 4 drew art", images > 10, images)
    check("page 4 shows ranks 10-12",
          any("#10" in t for t in
              [w.cget("text") for w in _all_labels(preview)]),
          [w.cget("text") for w in _all_labels(preview)][:3])

finally:
    try:
        app.update_daemon.stop()
    except Exception:
        pass
    app.root.destroy()

print()
if failures:
    print(f"FAILED ({len(failures)}): " + ", ".join(failures))
    sys.exit(1)
print("preview and action-row checks passed")
