# -*- coding: utf-8 -*-
"""Multi-select memory chooser for the optimizer's pinned-memory set.

Built on the official single-select :class:`MemoryPickerDialog`, reusing its
film-strip card grid, rarity filter and search. Two things differ:

* clicking toggles a card instead of closing the dialog, and the dialog returns
  a sorted list;
* the check mark is an overlay label rather than a canvas item, because the base
  class loads thumbnails asynchronously and redraws each canvas with
  ``delete("all")`` -- anything drawn on the canvas would be erased a frame later.

The dialog selects the memories to PIN (必选). Everything not pinned stays
available for the search to swap, so an empty selection means "search freely".
"""

import tkinter as tk
from tkinter import ttk

from gui.dialogs.memory_picker import MemoryPickerDialog

# Maximum pinnable memories: a lineup equips exactly six, so pinning more leaves
# nothing to search.
MAX_PINNED = 6


class MemoryMultiPicker(MemoryPickerDialog):
    """Pick memories for the optimizer. ``result`` is a sorted list of ids.

    Used for both roles the optimizer needs, which differ only in their bounds:

    * the **pinned** set (必选) -- memories forced into the lineup, at most six;
    * the **candidate pool** (候选卡池) -- memories the search may choose from,
      which must be large enough to fill the remaining slots.

    ``noun`` names the role in the counter so the two dialogs cannot be confused.
    """

    def __init__(self, parent, app, title="选择回忆卡",
                 preselected=None, maximum=MAX_PINNED, minimum=0,
                 noun="固定", allow_empty=False):
        self._pinned = set(preselected or [])
        self._maximum = maximum
        self._minimum = int(minimum)
        self._noun = noun
        self._allow_empty = bool(allow_empty)
        super().__init__(parent, app, title=title)
        # The base class sets self.result in __init__/select; take over after
        # the widget tree exists.
        self.result = sorted(self._pinned)
        self._install_actions()

    # ------------------------------------------------------------------ layout
    def _install_actions(self):
        """Put the confirm controls into the dialog's existing bottom bar.

        The base class already packed a bottom frame holding only a 取消 button.
        Packing a second bar after it risks getting squeezed to zero height, so
        the existing frame is reused when it can be identified; otherwise a new
        bar is created as a fallback.
        """
        bar = self._find_bottom_bar()
        if bar is None:
            bar = ttk.Frame(self)
            bar.pack(fill="x", side="bottom", padx=10, pady=6)

        for child in bar.winfo_children():
            if isinstance(child, ttk.Button) and child.cget("text") == "取消":
                child.destroy()

        self._count_var = tk.StringVar()
        ttk.Label(bar, textvariable=self._count_var,
                  font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        ttk.Button(bar, text="清空", command=self._clear).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="确认", command=self._on_confirm).pack(side=tk.RIGHT)
        ttk.Button(bar, text="取消", command=self._on_close).pack(side=tk.RIGHT, padx=4)
        self._update_count()

    def _find_bottom_bar(self):
        """Locate the base class's bottom frame (a frame holding only 取消)."""
        for child in self.winfo_children():
            if not isinstance(child, ttk.Frame):
                continue
            buttons = [c for c in child.winfo_children()
                       if isinstance(c, ttk.Button)]
            if buttons and all(b.cget("text") == "取消" for b in buttons):
                return child
        return None

    # --------------------------------------------------------------- selection
    def _clear(self):
        self._pinned.clear()
        self._refresh_grid()

    def _on_select(self, mid):
        """Toggle membership instead of closing (the key override)."""
        if mid in self._pinned:
            self._pinned.discard(mid)
        else:
            if self._maximum is not None and len(self._pinned) >= self._maximum:
                self._update_count(hint=f"最多{self._noun} {self._maximum} 张")
                return
            self._pinned.add(mid)
        self._refresh_grid()

    def _update_count(self, hint=""):
        if not hasattr(self, "_count_var"):
            return                       # called during the base class build
        text = f"已{self._noun} {len(self._pinned)} 张"
        if self._minimum:
            text += f"（至少 {self._minimum} 张）"
        if hint:
            text += f" — {hint}"
        self._count_var.set(text)

    def _on_confirm(self):
        """Accept, but refuse a selection that cannot fill the lineup.

        A pool smaller than six is unusable rather than merely small: the search
        would spend its budget proving it cannot build a legal lineup, so the
        dialog says so here instead.
        """
        if not self._allow_empty and len(self._pinned) < self._minimum:
            need = self._minimum - len(self._pinned)
            self._update_count(hint=f"还需选择 {need} 张")
            return
        self.result = sorted(self._pinned)
        self.destroy()

    def _on_close(self):
        self.result = None
        self.destroy()

    # -------------------------------------------------------------------- grid
    def _refresh_grid(self):
        super()._refresh_grid()
        self._mark_pinned()
        self._update_count()

    def _mark_pinned(self):
        """Overlay a badge on each pinned card.

        A label placed over the card frame survives the asynchronous thumbnail
        redraw; a canvas item would not.
        """
        try:
            scheme = self.app._get_scheme()
        except Exception:
            return
        widgets = getattr(self, "_card_widgets", None) or {}
        for mid, canvas in widgets.items():
            if mid not in self._pinned:
                continue
            try:
                card = canvas.master
                badge = tk.Label(card, text="固定", bg=scheme["accent"],
                                 fg="#1e1e2e", padx=4,
                                 font=("Microsoft YaHei UI", 8, "bold"))
                badge.place(x=0, y=0)
            except tk.TclError:
                pass                 # card vanished between rebuild and marking

    @property
    def pinned(self):
        """The pinned ids as a sorted list."""
        return sorted(self._pinned)
