# -*- coding: utf-8 -*-
"""Visual lineup preview: candidates shown as their real game cards.

Why pictures and not names
--------------------------
The result cannot print character or memory ids -- those are unpacked game data.
Display names are the alternative, but a name carries little identity for a
player who recognises a character by their art, so a text-only result is hard to
read back onto the formation. This module shows the cards themselves, drawn from
the same assets the编队 page uses, so a result can be checked at a glance.

Sizing
------
Measured in the running application, the result panel is ~544 px wide inside a
horizontal PanedWindow. The编队 page's cards are 154x74 (formation) and 120x67
(memory); six of those are 924 px and 720 px, so both have to shrink. Halving
them gives 462 px and 360 px, which fit with room for padding.

Tk canvases have no transform, so each card is drawn by the existing renderer at
full size and then every image item on it is replaced by a subsampled copy. That
reuses the whole composition path (frame, badge, attribute, level) instead of
duplicating it at a smaller scale, which is what keeps the thumbnails looking
exactly like the编队 cards rather than like a second, divergent renderer.
"""

import tkinter as tk
from tkinter import ttk

from gui.widgets.formation_card import (
    CARD_H, CARD_W, MEM_H, MEM_W,
    render_character_card, render_empty_card,
    render_memory_card, render_memory_empty,
)

# Halved, because that is what fits the measured panel width.
CHAR_SUBSAMPLE = 2
MEM_SUBSAMPLE = 2
THUMB_W = CARD_W // CHAR_SUBSAMPLE
THUMB_H = CARD_H // CHAR_SUBSAMPLE
MEM_THUMB_W = MEM_W // MEM_SUBSAMPLE
MEM_THUMB_H = MEM_H // MEM_SUBSAMPLE

# Candidates shown per page. Three keeps the strip short enough that the result
# panel does not have to scroll for it, and matches what fits comfortably under
# the report.
PAGE_SIZE = 3

# Pages available. Ten pages of three covers the top 30, which is as far as a
# sampled ranking is meaningful: past that the scores are inside the noise band
# and the list stops distinguishing anything.
MAX_PAGES = 10

# A lineup occupies six slots.
ROW_SLOTS = 6


def _normalized_candidates(result):
    """The finalist lineup list the preview draws, from the real V3.2 result.

    The ported engine's final shortlist lives in ``independent_validation.candidates``
    (each with a ``state`` and the final ``mean``); the ``joint_candidate_records``/
    ``joint`` keys are NOT present in the published result. Each finalist's lineup
    comes from its ``state`` (``friend_positions``/``memory_ids``). Returns [] when
    there is no shortlist.
    """
    iv = (result or {}).get("independent_validation") or {}
    cands = list(iv.get("candidates") or [])
    if not cands:
        return []
    objective = ((result or {}).get("settings") or {}).get("objective", "mean")

    def _key(c):
        m = c.get("mean")
        return float(m) if isinstance(m, (int, float)) else float("-inf")
    ordered = sorted(cands, key=_key, reverse=True)

    orig = (result or {}).get("original") or {}
    out = []
    for rank, cand in enumerate(ordered, start=1):
        state = cand.get("state") or {}
        is_base = (tuple(state.get("friend_positions") or ())
                   == tuple(orig.get("friend_positions") or ())
                   and tuple(state.get("memory_ids") or ())
                   == tuple(orig.get("memory_ids") or ()))
        out.append(dict(
            rank=rank,
            is_baseline=is_base,
            arrangement=list(state.get("friend_positions") or []),
            memory_ids=list(state.get("memory_ids") or []),
            summary={"rank": cand.get("mean"),
                     "n": cand.get("seed_count") or 0},
            objective=objective,
        ))
    return out


class ResultPreview(ttk.Frame):
    """A paged strip of candidate thumbnails, for under the result panel.

    ``render(result, data_loader)`` draws page one; the pager moves through the
    ranking a page at a time. Missing art never raises: a card whose image is
    unavailable is drawn as an empty frame or a labelled placeholder, because one
    absent asset must not take down the result panel.

    The pager bar is ALWAYS built, even when there is only one page, so the strip
    keeps a constant height and the panel below it does not jump when a new result
    arrives with more or fewer pages.
    """

    def __init__(self, parent, app, page_size=PAGE_SIZE, max_pages=MAX_PAGES):
        super().__init__(parent)
        self.app = app
        self.page_size = page_size
        self.max_pages = max_pages
        # Tk images are freed when the last Python reference goes; every image
        # handed to a canvas is retained here for the lifetime of the page.
        self._refs = []
        self._result = None
        self._loader = None
        self._page = 0
        self._body = None
        self._page_var = None
        self._prev_btn = None
        self._next_btn = None

    # ------------------------------------------------------------------ public
    def clear(self):
        for child in self.winfo_children():
            child.destroy()
        self._refs.clear()
        self._result = None
        self._loader = None
        self._page = 0
        self._body = None
        self._page_var = None
        self._prev_btn = None
        self._next_btn = None

    def render(self, result, data_loader):
        """Draw the first page of ``result``."""
        self.clear()
        candidates = _normalized_candidates(result)
        if not candidates:
            return
        self._result = result
        self._loader = data_loader
        self._page = 0
        self._build_shell()
        self._draw_page()

    @property
    def page_count(self):
        """How many pages the current result fills, capped at ``max_pages``."""
        total = len(((self._result or {}).get("candidates") or []))
        if total <= 0:
            return 1
        pages = (total + self.page_size - 1) // self.page_size
        return max(1, min(pages, self.max_pages))

    @property
    def page(self):
        """The 1-based page currently shown."""
        return self._page + 1

    def show_page(self, page):
        """Jump to a 1-based page, clamped to the available range."""
        target = max(1, min(int(page), self.page_count)) - 1
        if target == self._page:
            return
        self._page = target
        self._draw_page()

    def next_page(self):
        self.show_page(self._page + 2)

    def prev_page(self):
        self.show_page(self._page)

    # ------------------------------------------------------------------ shell
    def _build_shell(self):
        """Build the header, the pager and an empty body container.

        The shell is built once per result and only the body is redrawn when
        paging, so the pager keeps its position and does not flicker.
        """
        header = ttk.Frame(self)
        header.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(header, text="最优阵容预览",
                  font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        self._build_pager(header)

        self._body = tk.Frame(self, bg=self._scheme()["bg"])
        self._body.pack(fill="x")

    def _build_pager(self, parent):
        """The page control: previous, a page counter, next.

        Built whenever the result fills more than one page. A single-page result
        still reserves the same height, so the strip does not change size when a
        multi-page result replaces it.
        """
        if self.page_count <= 1:
            spacer = ttk.Frame(parent, height=self._pager_row_height())
            spacer.pack(side=tk.RIGHT)
            spacer.pack_propagate(False)
            return
        box = ttk.Frame(parent)
        box.pack(side=tk.RIGHT)
        self._prev_btn = ttk.Button(box, text="◀ 上一页", width=9,
                                    command=self.prev_page)
        self._prev_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._page_var = tk.StringVar()
        ttk.Label(box, textvariable=self._page_var, width=10,
                  anchor="center").pack(side=tk.LEFT)
        self._next_btn = ttk.Button(box, text="下一页 ▶", width=9,
                                    command=self.next_page)
        self._next_btn.pack(side=tk.LEFT, padx=(4, 0))
        self._refresh_pager_state()

    def _pager_row_height(self):
        """Height of the pager row, measured from a real instance.

        Used to reserve the same space on a single-page result, so the strip does
        not change size when a result with several pages replaces one with a
        single page. Measured rather than hard-coded: a guessed constant was 22 px
        against the row's actual 31 px, which made the panel visibly jump.
        """
        if getattr(self, "_pager_height", None) is not None:
            return self._pager_height
        probe = ttk.Frame(self)
        button = ttk.Button(probe, text="下一页 ▶", width=9)
        button.pack(side=tk.LEFT)
        label = ttk.Label(probe, text="10 / 10", width=10, anchor="center")
        label.pack(side=tk.LEFT)
        self.update_idletasks()
        height = probe.winfo_reqheight()
        probe.destroy()
        self._pager_height = max(1, height)
        return self._pager_height

    def _refresh_pager_state(self):
        """Update the counter and disable the buttons at the ends."""
        if self._page_var is None:
            return
        self._page_var.set(f"{self.page} / {self.page_count}")
        if self._prev_btn is not None:
            self._prev_btn.configure(
                state="normal" if self._page > 0 else "disabled")
        if self._next_btn is not None:
            self._next_btn.configure(
                state="normal" if self._page < self.page_count - 1 else "disabled")

    # ----------------------------------------------------------------- drawing
    def _draw_page(self):
        """Redraw the body with the current page's candidates."""
        if self._body is None:
            return
        for child in self._body.winfo_children():
            child.destroy()
        self._refs.clear()
        scheme = self._scheme()

        candidates = _normalized_candidates(self._result)
        start = self._page * self.page_size
        for offset, cand in enumerate(candidates[start:start + self.page_size]):
            # The index drives the "compared with current" line, which belongs on
            # the champion only -- page 1's first entry.
            self._draw_candidate(cand, start + offset, self._result,
                                 self._loader, scheme)
        self._refresh_pager_state()

    def _draw_candidate(self, cand, index, result, data_loader, scheme):
        block = tk.Frame(self._body, bg=scheme["bg"])
        block.pack(fill="x", padx=4, pady=(4, 0))

        tk.Label(block, text=self._caption(cand, index, result),
                 bg=scheme["bg"], fg=scheme["fg"], anchor="w", justify="left",
                 font=("Microsoft YaHei UI", 8)).pack(fill="x")

        self._draw_row(block, cand.get("arrangement") or [], data_loader,
                       scheme, kind="character")
        self._draw_row(block, cand.get("memory_ids") or [], data_loader,
                       scheme, kind="memory")

    def _draw_row(self, parent, ids, data_loader, scheme, kind):
        row = tk.Frame(parent, bg=scheme["bg"])
        row.pack(fill="x", pady=(1, 0))
        for index in range(ROW_SLOTS):
            value = ids[index] if index < len(ids) else None
            if kind == "character":
                canvas = tk.Canvas(row, width=THUMB_W, height=THUMB_H,
                                   bg=scheme["bg"], highlightthickness=0)
            else:
                canvas = tk.Canvas(row, width=MEM_THUMB_W, height=MEM_THUMB_H,
                                   bg=scheme["bg"], highlightthickness=0)
            canvas.pack(side=tk.LEFT, padx=1)
            if kind == "character":
                self._draw_character(canvas, value, data_loader, scheme)
            else:
                self._draw_memory(canvas, value, data_loader, scheme)

    def _draw_character(self, canvas, cid, data_loader, scheme):
        if cid is None:
            self._shrink(canvas, CHAR_SUBSAMPLE)
            return
        rarity = attribute = None
        try:
            character = data_loader.get_character_by_id(cid)
            rarity = getattr(character, "rarity", None)
            attribute = getattr(character, "attribute", None)
        except Exception:
            pass
        portrait = None
        try:
            from gui.widgets.formation_card import load_portrait
            portrait = load_portrait(cid)
        except Exception:
            portrait = None
        if portrait is not None:
            self._refs.append(portrait)
        try:
            render_character_card(canvas, portrait, rarity=rarity,
                                  attribute=attribute,
                                  level=self._level(cid))
        except Exception:
            # Fall back to the empty frame so the slot still reads as occupied
            # by *something*, rather than as a hole in the lineup.
            try:
                render_empty_card(canvas)
            except Exception:
                pass
        self._shrink(canvas, CHAR_SUBSAMPLE)

    def _draw_memory(self, canvas, mid, data_loader, scheme):
        if mid is None:
            try:
                render_memory_empty(canvas, scheme)
            except Exception:
                pass
            self._shrink(canvas, MEM_SUBSAMPLE)
            return
        rarity = 1
        try:
            memory = data_loader.get_memory(mid)
            rarity = getattr(memory, "rarity", 1) or 1
        except Exception:
            pass
        drawn = False
        try:
            drawn = render_memory_card(canvas, mid, rarity)
        except Exception:
            drawn = False
        if not drawn:
            self._placeholder(canvas, mid, data_loader, scheme)
        self._shrink(canvas, MEM_SUBSAMPLE)

    def _placeholder(self, canvas, mid, data_loader, scheme):
        """A labelled frame for a card whose art is missing."""
        name = ""
        try:
            name = (getattr(data_loader.get_memory(mid), "name", "") or "")[:5]
        except Exception:
            name = ""
        canvas.create_rectangle(0, 0, MEM_W, MEM_H,
                                outline=scheme.get("border", "#45475a"),
                                fill=scheme.get("surface", "#313244"))
        canvas.create_text(MEM_W // 2, MEM_H // 2, text=name or "?",
                           fill=scheme.get("fg", "#cdd6f4"), width=MEM_W - 8,
                           font=("Microsoft YaHei UI", 8))

    # ----------------------------------------------------------------- scaling
    def _shrink(self, canvas, factor):
        """Replace every image on the canvas with a subsampled copy.

        Positions and anchors are scaled by the same factor, so the composed card
        keeps its exact layout. A canvas item whose image cannot be read is left
        alone rather than removed, so a partial failure still shows the card.
        """
        if factor <= 1:
            return
        try:
            items = list(canvas.find_all())
        except tk.TclError:
            return
        for item in items:
            try:
                if canvas.type(item) != "image":
                    continue
                name = canvas.itemcget(item, "image")
                if not name:
                    continue
                small = tk.PhotoImage(master=canvas)
                small.tk.call(small, "copy", name, "-subsample", factor, factor)
                x, y = canvas.coords(item)
                canvas.itemconfigure(item, image=small)
                canvas.coords(item, round(x / factor), round(y / factor))
                self._refs.append(small)
            except tk.TclError:
                continue

    # ----------------------------------------------------------------- caption
    def _caption(self, cand, index, result):
        """One line naming the candidate and its score, containing no ids."""
        summary = cand.get("summary") or {}
        objective = cand.get("objective") or "mean"
        from src.optimizer import objective as _obj
        label = _obj.OBJECTIVE_LABELS.get(objective, "均值").split("（")[0]
        parts = [f"#{cand.get('rank', index + 1)}"]
        if cand.get("is_baseline"):
            parts.append("当前阵容")
        score = summary.get("rank")
        if isinstance(score, (int, float)):
            parts.append(f"{label} {score:,.0f}")
        cv = summary.get("cv")
        if isinstance(cv, (int, float)):
            parts.append(f"波动 {cv:.1f}%")
        return "　".join(parts)

    def _level(self, cid):
        """The level this lineup would field, from the app's own configuration."""
        try:
            values = self.app.global_tab.get_values()
            char_config = getattr(self.app, "char_config", {}) or {}
            entry = char_config.get(cid) or char_config.get(str(cid)) or {}
            return entry.get("level", values.get("character_level"))
        except Exception:
            return None

    def _scheme(self):
        try:
            return self.app._get_scheme()
        except Exception:
            return {"bg": "#1e1e2e", "fg": "#cdd6f4", "surface": "#313244",
                    "border": "#45475a"}
