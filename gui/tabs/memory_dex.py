# -*- coding: utf-8 -*-
"""回忆图鉴视图（嵌在「角色与回忆」Tab 内，与角色参数页分段切换）。

为什么合并在角色参数 Tab 内
--------------------------
用户要为主界面 Notebook 预留标签位，因此图鉴不作为独立 Tab，而是与角色参数
共用一个 Tab（Tab 名「角色与回忆」），内部用分段切换切视图。

本页是**只读**浏览页（回忆卡没有可编辑参数：稀有度/效果都由数据决定），
职责是：卡面网格 + 稀有度筛选 + 搜索 + 详情（大图 / 剧情文本 / 结构化效果），
外加收藏星标（与角色参数页同一个 favorites.json）。

性能
----
164 张卡的合成（开图 + 缩放 + 叠卡框 + 叠徽章 + 轮廓裁切）单张约 5~20ms，
一次性画完会卡住界面，因此：
  * 首次切到本视图才填卡图（`on_shown()`，避免拖慢启动）；
  * 卡图按帧分批异步加载（每帧 4 张，与 MemoryPickerDialog 同一套做法）。
"""

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

from gui.constants import (
    CHAR_TYPE_NAMES,
    ELEMENT_NAMES,
    MEM_RARITY_MAP,
    RARITY_DIR,
    ROLE_TYPE_NAMES,
)
from gui.widgets.favorite_star import star_photo as load_favorite_star
from gui.widgets.formation_card import (
    MEM_H,
    MEM_W,
    load_memory_card_image,
    purge_memory_card_cache,
)
from gui.widgets.grid_layout import cols_for_width, configure_uniform_columns, fit_card_size

_DEFAULT_COLS = 5        # 默认宽度下可容纳的列数（面板缩窄时自动减少）
_CARD_PAD = 3
_CARD_BORDER = 2
# 卡图尺寸随面板宽度自适应：一行正好铺满，且不小于/大于以下范围
_CARD_ASPECT = 300 / 168          # 胶片卡框宽/高（与 MEM_W:MEM_H 同比例）
_MIN_CARD_W, _MAX_CARD_W = 120, 220
_DETAIL_W, _DETAIL_H = 240, 134   # 详情大图（固定尺寸）

# highlight.party_position 是位置位掩码（与引擎 _POSITION_BITMASK_MAP 一致）：
# 1=左前 2=中前 4=右前 8=左后 16=中后 32=右后
_POS_BITS = [(1, "左前"), (2, "中前"), (4, "右前"), (8, "左后"), (16, "中后"), (32, "右后")]
_FRONT_MASK = 1 | 2 | 4
_BACK_MASK = 8 | 16 | 32


def format_position_mask(mask: int) -> str:
    """把位置位掩码渲染成可读文字（整排/整列时用简称，否则逐格列出）。"""
    if not mask:
        return "?"
    if mask & (_FRONT_MASK | _BACK_MASK) == (_FRONT_MASK | _BACK_MASK):
        return "任意位置"
    if mask == _FRONT_MASK:
        return "前排"
    if mask == _BACK_MASK:
        return "后排"
    if mask == (2 | 16):
        return "中列"
    names = [name for bit, name in _POS_BITS if mask & bit]
    return "/".join(names) if names else str(mask)


def format_highlight_condition(hl, app) -> str:
    """把一条 highlight 的匹配条件渲染成一行中文；无任何条件时表示不限。"""
    parts: List[str] = []
    loader = app.data_loader

    team_id = getattr(hl, "character_team_master_id", None)
    if team_id:
        team_name = (loader.load_character_teams() or {}).get(team_id)
        parts.append(f"队伍「{team_name}」" if team_name else f"队伍#{team_id}")

    base_id = getattr(hl, "character_base_master_id", None)
    if base_id:
        base_name = loader.get_character_base_name(base_id)
        parts.append(f"角色「{base_name}」" if base_name else f"角色基底#{base_id}")

    char_id = getattr(hl, "character_master_id", None)
    if char_id:
        ch = loader.get_character_by_id(char_id)
        parts.append(f"形态「{app.format_char_name(ch)}」" if ch else f"角色#{char_id}")

    attr = getattr(hl, "character_attribute", None)
    if attr:
        parts.append(f"{ELEMENT_NAMES.get(attr, attr)}属性")

    role = getattr(hl, "character_role", None)
    if role:
        parts.append(f"定位:{ROLE_TYPE_NAMES.get(role, role)}")

    ctype = getattr(hl, "character_type", None)
    if ctype:
        parts.append(f"类型:{CHAR_TYPE_NAMES.get(ctype, ctype)}")

    pos = getattr(hl, "party_position", None)
    if pos:
        parts.append(f"位置:{format_position_mask(pos)}")

    side = "敌方" if getattr(hl, "is_targeting_friendly_party", True) is False else "己方"
    if parts:
        return f"{side} · " + " · ".join(parts)
    return f"{side}全体（不限条件）"


class MemoryDexView(ttk.Frame):
    """回忆图鉴：左侧卡面网格（稀有度筛选 + 搜索），右侧详情（含收藏星标）。

    搜索范围包含效果名/效果说明（图鉴最常见的用法是「哪张卡给攻击力」）。
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._current_rarity = 0        # 0=全部, 1=SR, 2=SSR, 3=UR, 4=LR
        self._filtered_ids: List[int] = []
        self._card_widgets: Dict[int, tk.Canvas] = {}
        self._selected_mid: Optional[int] = None
        self._wrap_labels: List[tk.Widget] = []
        self._grid_filled = False       # 首次显示前不填卡图（不拖慢启动）
        # 布局：由画布宽度算出 (列数, 卡图宽, 卡图高)，画布一有真实宽度就确定
        self._layout = None
        self._card_w, self._card_h = MEM_W, MEM_H
        self._cols = _DEFAULT_COLS
        self._rendered_size: Optional[Tuple[int, int]] = None
        self._resize_job = None
        self._build()

    # ─────────────────── 布局 ───────────────────

    def _build(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # ── 左：筛选 + 网格 ──
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        ttk.Label(left, text="回忆图鉴", font=("Microsoft YaHei UI", 10, "bold")).pack(pady=(5, 0))

        filter_frame = ttk.Frame(left)
        filter_frame.pack(fill="x", padx=5, pady=5)
        self._rarity_buttons: List[ttk.Label] = []
        ICON_SIZE = 20
        # 0=全部, 1=SR, 2=SSR, 3=UR, 4=LR（与选择弹窗的筛选一致）
        rarity_items = [(0, "全部", None)]
        for rid, (rname, ricon) in MEM_RARITY_MAP.items():
            rarity_items.append((rid, rname, ricon))
        for rid, rname, ricon in rarity_items:
            photo = self._load_rarity_icon(ricon, ICON_SIZE) if ricon else None
            if photo is not None:
                btn = ttk.Label(filter_frame, image=photo, cursor="hand2", style="Seg.TLabel")
                btn.image = photo
            else:
                btn = ttk.Label(filter_frame, text=rname, cursor="hand2", style="Seg.TLabel")
            btn.pack(side=tk.LEFT, padx=1)
            btn.bind("<Button-1>", lambda e, r=rid: self._apply_rarity(r))
            self._rarity_buttons.append(btn)
        self._update_rarity_highlight()

        search_row = ttk.Frame(left)
        search_row.pack(fill="x", padx=5)
        ttk.Label(search_row, text="搜索:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        # 还没填过卡图时不重绘（视图可能一直没被切到过）
        self._search_var.trace_add("write", lambda *a: self.refresh_grid())
        search_entry = ttk.Entry(search_row, textvariable=self._search_var)
        search_entry.pack(side=tk.LEFT, fill="x", expand=True, padx=4)

        grid_frame = ttk.Frame(left)
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._canvas = tk.Canvas(grid_frame, bg=self.app._get_scheme()["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(grid_frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._grid_inner = tk.Frame(self._canvas, bg=self.app._get_scheme()["surface"])
        self._canvas_window = self._canvas.create_window((0, 0), window=self._grid_inner, anchor="nw")
        self._grid_inner.bind("<Configure>",
                              lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        def _bind_mw(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", _bind_mw))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        # ── 右：详情 ──
        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        s = self.app._get_scheme()
        right_canvas = tk.Canvas(right, bg=s["bg"], highlightthickness=0)
        right_scrollbar = ttk.Scrollbar(right, orient="vertical", command=right_canvas.yview)
        self.detail_frame = ttk.Frame(right_canvas)
        self.detail_frame.bind("<Configure>",
                               lambda e: right_canvas.configure(scrollregion=right_canvas.bbox("all")))
        self._detail_window = right_canvas.create_window((0, 0), window=self.detail_frame, anchor="nw")
        right_canvas.configure(yscrollcommand=right_scrollbar.set)
        right_canvas.pack(side="left", fill="both", expand=True)
        right_scrollbar.pack(side="right", fill="y")

        def _on_right_resize(event):
            right_canvas.itemconfig(self._detail_window, width=event.width)
            self._update_wraplength(event.width)

        right_canvas.bind("<Configure>", _on_right_resize)

        def _on_right_mousewheel(e):
            right_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        right_canvas.bind("<Enter>", lambda e: right_canvas.bind_all("<MouseWheel>", _on_right_mousewheel))
        right_canvas.bind("<Leave>", lambda e: right_canvas.unbind_all("<MouseWheel>"))

        self._show_placeholder()

    @staticmethod
    def _load_rarity_icon(filename: Optional[str], size: int):
        if not filename:
            return None
        try:
            photo = tk.PhotoImage(file=str(RARITY_DIR / filename))
            if photo.width() > size:
                factor = max(1, photo.width() // size)
                photo = photo.subsample(factor, factor)
            return photo
        except Exception:
            return None

    # ─────────────────── 外部接口 ───────────────────

    def on_shown(self):
        """切到本视图时调用：首次才真正填卡图（164 张合成不便宜）。

        刚 pack 时画布还没有真实宽度（winfo_width 仍是 1），这种情况交给
        第一次 <Configure> 去填（见 _on_canvas_resize）。
        """
        self._grid_filled = True
        if self._layout is not None:
            self._refresh_grid()

    def refresh_grid(self):
        """主题切换等外部原因触发的重绘（仅在已填过卡图时）。"""
        if self._grid_filled:
            self._refresh_grid()

    # ─────────────────── 网格 ───────────────────

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)
        layout = self._layout_for_width(event.width)
        if layout == self._layout:
            return
        self._layout = layout
        self._cols, self._card_w, self._card_h = layout
        if not self._grid_filled:
            return
        if not self._card_widgets:
            self._refresh_grid()            # 首次铺开
        else:
            self._schedule_grid_refresh()   # 拖动面板时等停下来再重建

    @staticmethod
    def _layout_for_width(avail: int):
        """由可用宽度算出 (列数, 卡图宽, 卡图高)：一行正好铺满。

        列数按「不小于 _MIN_CARD_W」估一个，再把列宽均分给卡图
        （uniform 列会吃掉全部可用宽度），这样右边不会留空、卡片也不会被压窄。
        """
        cols = cols_for_width(avail, _MIN_CARD_W, _CARD_PAD, _CARD_BORDER)
        card_w, card_h = fit_card_size(avail, cols, _CARD_PAD, _CARD_BORDER,
                                       _CARD_ASPECT, _MIN_CARD_W, _MAX_CARD_W)
        return cols, card_w, card_h

    def _schedule_grid_refresh(self):
        """拖动面板时不要每像素重建一次网格（卡图缓存会按尺寸膨胀）。"""
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(120, self._rebuild_after_resize)

    def _rebuild_after_resize(self):
        self._resize_job = None
        self._refresh_grid()

    def _apply_rarity(self, rarity_id: int):
        self._current_rarity = rarity_id
        self._update_rarity_highlight()
        if self._grid_filled:
            self._refresh_grid()
        self._canvas.yview_moveto(0)

    def _update_rarity_highlight(self):
        for i, btn in enumerate(self._rarity_buttons):
            btn.configure(style="SegActive.TLabel" if i == self._current_rarity else "Seg.TLabel")

    def _get_filtered_ids(self) -> List[int]:
        search_text = self._search_var.get().strip().lower()
        try:
            memories = self.app.data_loader.load_memories()
        except Exception:
            return []
        result = []
        for mid, mem in memories.items():
            if self._current_rarity and mem.rarity != self._current_rarity:
                continue
            if search_text and not self._matches_search(mid, mem, search_text):
                continue
            result.append(mid)
        result.sort()
        return result

    def _matches_search(self, mid: int, mem, search_text: str) -> bool:
        """搜索范围：卡ID / 卡名 / 卡面文本 / 效果名 / 效果说明。

        图鉴最常见的用法就是「哪张卡给攻击力」，所以效果文本也参与搜索。
        """
        if search_text in str(mid) or search_text in mem.name.lower():
            return True
        if search_text in (getattr(mem, "description", "") or "").lower():
            return True
        for hl in getattr(mem, "highlights", []) or []:
            sid = getattr(hl, "skill_master_id", None)
            if not sid:
                continue
            effect = self.app.data_loader.get_memory_effect(sid)
            if not effect:
                continue
            if search_text in str(effect.get("name", "")).lower():
                return True
            if search_text in str(effect.get("description", "")).lower():
                return True
        return False

    def _ensure_layout(self):
        """兜底：画布已有真实宽度但首个 <Configure> 还没到（或已被 withdraw）时补算布局。"""
        if self._layout is not None:
            return
        try:
            avail = self._canvas.winfo_width()
        except Exception:
            avail = 1
        if avail > 1:
            self._layout = self._layout_for_width(avail)
            self._cols, self._card_w, self._card_h = self._layout

    def _refresh_grid(self):
        self._ensure_layout()
        self._filtered_ids = self._get_filtered_ids()
        for child in self._grid_inner.winfo_children():
            child.destroy()
        self._card_widgets.clear()

        COLS = self._cols
        card_w, card_h = self._card_w, self._card_h
        s = self.app._get_scheme()
        self._canvas.configure(bg=s["bg"])
        self._grid_inner.configure(bg=s["surface"])

        # 卡图尺寸变了：丢掉上一尺寸的缓存（否则拖动面板会攒出几十种尺寸）
        if self._rendered_size is not None and self._rendered_size != (card_w, card_h):
            purge_memory_card_cache(self._rendered_size)
        self._rendered_size = (card_w, card_h)

        configure_uniform_columns(self._grid_inner, COLS)

        if not self._filtered_ids:
            tk.Label(self._grid_inner, text="没有符合条件的回忆卡", bg=s["surface"],
                     fg=s["border"], font=("Microsoft YaHei UI", 10)).grid(
                row=0, column=0, columnspan=max(1, COLS), pady=40)
            self._thumb_queue = []
            return

        for i, mid in enumerate(self._filtered_ids):
            row, col = divmod(i, COLS)
            card = tk.Frame(self._grid_inner, bg=s["surface"], bd=0,
                            highlightbackground=s["border"], highlightthickness=_CARD_BORDER,
                            cursor="hand2")
            card.grid(row=row, column=col, padx=_CARD_PAD, pady=_CARD_PAD, sticky="n")

            card_canvas = tk.Canvas(card, width=card_w, height=card_h, bg=s["surface"],
                                    highlightthickness=0)
            card_canvas.pack()
            card_canvas.create_text(card_w // 2, card_h // 2, text="...",
                                    fill=s["border"], font=("Microsoft YaHei UI", 9))
            card_canvas.bind("<Button-1>", lambda e, m=mid: self._on_card_click(m))
            card.bind("<Button-1>", lambda e, m=mid: self._on_card_click(m))

            # 卡名（与角色参数页网格同一排版：卡图下方两行；不显示解包 ID）。
            # wraplength 比卡图再窄一点：卡名的请求宽度绝不能超过卡图宽度，
            # 否则卡片框会被撑宽、超出列宽，卡图右侧又被裁掉。
            name = getattr(self.app.data_loader.get_memory(mid), "name", str(mid))
            if len(name) > 14:
                name = name[:13] + "…"
            name_label = tk.Label(card, text=name, bg=s["surface"], fg=s["fg"],
                                  font=("Microsoft YaHei UI", 8),
                                  wraplength=max(40, card_w - 14),
                                  height=2, justify="center")
            name_label.pack(fill="x")
            name_label.bind("<Button-1>", lambda e, m=mid: self._on_card_click(m))

            if mid == self._selected_mid:
                card.configure(highlightbackground=s["accent"])
            self._card_widgets[mid] = card_canvas

        self._thumb_queue = list(self._filtered_ids)
        self._load_thumbs_async()

    def _refresh_card_thumb(self, mid: int):
        """重画单张卡缩略图（收藏角标变化时用，避免整片网格重绘闪烁）。"""
        canvas = self._card_widgets.get(mid)
        if canvas is None:
            return
        try:
            if not canvas.winfo_exists():
                return
        except Exception:
            return
        mem = self.app.data_loader.get_memory(mid)
        rarity = getattr(mem, "rarity", 1) if mem else 1
        photo = load_memory_card_image(mid, rarity, (self._card_w, self._card_h),
                                       favorite=self.app.is_favorite_memory(mid))
        if photo is not None:
            canvas.delete("all")
            canvas.create_image(0, 0, image=photo, anchor="nw")
            canvas._card_photo = photo

    def _load_thumbs_async(self):
        """每帧加载 4 张卡图，避免 164 张一次性合成卡住界面。"""
        queue = getattr(self, "_thumb_queue", None)
        if not queue:
            return
        for _ in range(4):
            if not queue:
                break
            self._refresh_card_thumb(queue.pop(0))
        if queue:
            self.after(10, self._load_thumbs_async)

    def _on_card_click(self, mid: int):
        s = self.app._get_scheme()
        prev = self._selected_mid
        if prev is not None and prev in self._card_widgets:
            try:
                self._card_widgets[prev].master.configure(highlightbackground=s["border"])
            except Exception:
                pass
        self._selected_mid = mid
        canvas = self._card_widgets.get(mid)
        if canvas is not None:
            try:
                canvas.master.configure(highlightbackground=s["accent"])
            except Exception:
                pass
        self._show_detail(mid)

    # ─────────────────── 详情 ───────────────────

    def _show_placeholder(self):
        for w in self.detail_frame.winfo_children():
            w.destroy()
        self._wrap_labels.clear()
        ttk.Label(self.detail_frame, text="选择左侧回忆卡查看卡面与效果",
                  font=("Microsoft YaHei UI", 10)).pack(pady=20)

    def _update_wraplength(self, canvas_width: int):
        """详情区宽度变化时同步换行宽度（Label 不会自动重排文字）。"""
        wrap = max(200, canvas_width - 40)
        for lbl in self._wrap_labels:
            try:
                lbl.configure(wraplength=wrap)
            except Exception:
                pass

    def _show_detail(self, mid: int):
        mem = self.app.data_loader.get_memory(mid)
        if not mem:
            self._show_placeholder()
            return
        for w in self.detail_frame.winfo_children():
            w.destroy()
        self._wrap_labels.clear()

        f = self.detail_frame
        ttk.Label(f, text="").pack()

        # 卡面大图
        photo = load_memory_card_image(mid, getattr(mem, "rarity", 1), (_DETAIL_W, _DETAIL_H),
                                       favorite=self.app.is_favorite_memory(mid))
        if photo is not None:
            img_label = ttk.Label(f, image=photo)
            img_label.image = photo
            img_label.pack(pady=(0, 6))

        # 名称 + 收藏星标（与角色参数页同一个星标交互）
        name_row = ttk.Frame(f)
        name_row.pack(fill="x", padx=10)
        rarity_name = MEM_RARITY_MAP.get(getattr(mem, "rarity", 1), ("?",))[0]
        ttk.Label(name_row, text=mem.name, font=("Microsoft YaHei UI", 14, "bold"),
                  anchor="center").pack(side="left", fill="x", expand=True)
        self._build_favorite_toggle(name_row, mid, self.app.is_favorite_memory(mid))

        # 注意：不显示回忆卡 ID / 技能 ID（解包内容不进 GUI）
        ttk.Label(f, text=f"稀有度: {rarity_name}",
                  font=("Microsoft YaHei UI", 10)).pack(pady=(2, 6))

        # 剧情文本
        desc = getattr(mem, "description", "") or ""
        if desc:
            desc_frame = ttk.LabelFrame(f, text="卡面文本")
            desc_frame.pack(fill="x", padx=8, pady=4)
            lbl = ttk.Label(desc_frame, text=desc.replace("\\n", "\n"),
                            font=("Microsoft YaHei UI", 10), justify="left", wraplength=400)
            lbl.pack(anchor="w", padx=8, pady=6)
            self._wrap_labels.append(lbl)

        # 结构化效果（每条 highlight：适用条件 + 技能名 + 技能描述）
        eff_frame = ttk.LabelFrame(f, text="效果")
        eff_frame.pack(fill="x", padx=8, pady=4)
        highlights = list(getattr(mem, "highlights", []) or [])
        if not highlights:
            ttk.Label(eff_frame, text="（无效果数据）", font=("Microsoft YaHei UI", 10)).pack(
                anchor="w", padx=8, pady=6)
        for i, hl in enumerate(highlights, start=1):
            block = ttk.Frame(eff_frame)
            block.pack(fill="x", padx=6, pady=(6, 2))
            sid = getattr(hl, "skill_master_id", None)
            effect = self.app.data_loader.get_memory_effect(sid) if sid else None
            cond_lbl = ttk.Label(block, text=f"{i}. 适用: {format_highlight_condition(hl, self.app)}",
                                 font=("Microsoft YaHei UI", 10, "bold"), justify="left",
                                 wraplength=400)
            cond_lbl.pack(anchor="w")
            self._wrap_labels.append(cond_lbl)
            if effect:
                skill_lbl = ttk.Label(block, text=effect.get("name", ""),
                                      font=("Microsoft YaHei UI", 9), justify="left")
                skill_lbl.pack(anchor="w")
                desc_lbl = ttk.Label(block, text=effect.get("description", ""),
                                     font=("Microsoft YaHei UI", 9), justify="left", wraplength=400)
                desc_lbl.pack(anchor="w", padx=(12, 0))
                self._wrap_labels.extend([skill_lbl, desc_lbl])
            else:
                ttk.Label(block, text="（缺少效果数据）",
                          font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        ttk.Label(f, text="").pack(pady=(0, 8))

    def _build_favorite_toggle(self, parent, mid: int, is_favorite: bool):
        """收藏星标（与角色参数页同一套 ttk 样式，主题切换自动跟随）。"""
        photo = load_favorite_star(18, is_favorite)
        if photo is None:
            btn = ttk.Label(parent, text="★" if is_favorite else "☆", cursor="hand2",
                            style="Favorite.TLabel",
                            foreground="#ffb300" if is_favorite else self.app._get_scheme()["border"],
                            font=("Microsoft YaHei UI", 14))
        else:
            btn = ttk.Label(parent, image=photo, cursor="hand2", style="Favorite.TLabel")
            btn.image = photo
        btn.pack(side="right", padx=(5, 0))
        btn.bind("<Button-1>", lambda e, m=mid: self._toggle_favorite(m))
        text = "已收藏 - 点击取消收藏" if is_favorite else "点击收藏该回忆卡"
        self._create_tooltip(btn, text)

    def _toggle_favorite(self, mid: int):
        self.app.toggle_favorite_memory(mid)
        # 只重画这一张卡的角标 + 刷新详情（避免 164 张整片重绘的闪烁）
        self._refresh_card_thumb(mid)
        self._show_detail(mid)

    def _create_tooltip(self, widget, text):
        def _show(event):
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
            s = self.app._get_scheme()
            tk.Label(tooltip, text=text, bg=s["surface"], fg=s["fg"], relief="solid",
                     borderwidth=1, font=("Microsoft YaHei UI", 9), padx=4, pady=2).pack()
            widget._tooltip = tooltip

        def _hide(event):
            tooltip = getattr(widget, "_tooltip", None)
            if tooltip:
                tooltip.destroy()
                widget._tooltip = None

        widget.bind("<Enter>", _show)
        widget.bind("<Leave>", _hide)
