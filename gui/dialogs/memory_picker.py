# -*- coding: utf-8 -*-
"""回忆卡可视化选择弹窗：新版胶片卡框网格 + 稀有度筛选 + 搜索 + 收藏分页。

从 gui_app.py 抽取。

「分页」只做在弹窗内部（全部回忆卡 / ★收藏），不占主界面 Notebook 的标签位；
收藏页沿用与全部页完全一致的过滤链（稀有度筛选 + 搜索）。已收藏的卡在卡面
右上角显示金色星标（位置见 formation_card 里 _MEM_FAV_* 的说明）。
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict, List

from gui.constants import (
    MEM_RARITY_MAP,
    RARITY_DIR,
)
from gui.widgets.formation_card import load_memory_card_image
from gui.widgets.grid_layout import configure_uniform_columns
from gui.widgets.modal import _bind_modal_minimize_restore

# 弹窗内卡图尺寸（与胶片卡框 300:168 等比：150/84 ≈ 1.786）
_CARD_W, _CARD_H = 150, 84
# 卡片外框（highlightthickness）与卡片间距，用于自适应列数
_CARD_BORDER = 2
_CARD_PAD = 3
_DEFAULT_COLS = 4   # 弹窗默认宽度下可容纳的列数（缩窄窗口时自动减少）

_SCOPE_ALL = "all"
_SCOPE_FAVORITE = "favorite"


class MemoryPickerDialog(tk.Toplevel):
    """回忆卡可视化选择弹窗：新版胶片卡框网格 + 稀有度筛选 + 搜索 + 收藏分页"""

    def __init__(self, parent, app, title="选择回忆卡", exclude_ids=None):
        super().__init__(parent)
        self.app = app
        self.result: Optional[int] = None  # 选中的回忆卡ID
        self._exclude_ids: set = set(exclude_ids or [])
        self._current_rarity = 0  # 0=全部
        self._filtered_ids: List[int] = []
        self._thumb_cache: Dict[int, tk.PhotoImage] = {}
        self._scope = _SCOPE_ALL   # 分页：全部回忆卡 / 收藏
        self._scope_buttons: List = []

        self.title(title)
        self.transient(parent)
        self.grab_set()
        _bind_modal_minimize_restore(self, parent)
        self.resizable(True, True)
        self.geometry("680x620")
        self.minsize(500, 400)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 居中于父窗口
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    def _build(self):
        s = self.app._get_scheme()
        self.configure(bg=s["bg"])

        # ── 顶部：分页（全部/收藏） + 搜索框 + 稀有度筛选 ──
        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", padx=10, pady=5)

        # 分页切换（弹窗内分页，非主界面标签页）
        scope_frame = ttk.Frame(top_frame)
        scope_frame.pack(fill="x", pady=(0, 5))
        fav_count = len(self.app.favorite_memory_ids())
        for key, text in ((_SCOPE_ALL, "全部回忆卡"),
                          (_SCOPE_FAVORITE, f"★ 收藏 ({fav_count})")):
            btn = tk.Label(scope_frame, text=text, cursor="hand2", bd=2, relief="raised",
                           bg=s["surface"], fg=s["fg"], font=("Microsoft YaHei UI", 9),
                           padx=10, pady=2)
            btn.pack(side=tk.LEFT, padx=(0, 4))
            btn.bind("<Button-1>", lambda e, k=key: self._apply_scope(k))
            self._scope_buttons.append((key, btn))
        self._update_scope_highlight()

        # 搜索框
        search_frame = ttk.Frame(top_frame)
        search_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(search_frame, text="搜索:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._refresh_grid())
        search_entry = ttk.Entry(search_frame, textvariable=self._search_var, width=25)
        search_entry.pack(side=tk.LEFT, padx=5, fill="x", expand=True)
        search_entry.bind("<Return>", lambda e: self._refresh_grid())

        # 稀有度筛选按钮（使用图标）
        filter_frame = ttk.Frame(top_frame)
        filter_frame.pack(fill="x")
        self._rarity_buttons: List[tk.Label] = []
        # 0=全部, 1=SR, 2=SSR, 3=UR, 4=LR
        rarity_btn_data = [(0, "全部", None)]
        for rid, (rname, ricon) in MEM_RARITY_MAP.items():
            rarity_btn_data.append((rid, rname, ricon))
        ICON_SIZE = 20
        for rid, rname, ricon in rarity_btn_data:
            if ricon:
                icon_path = RARITY_DIR / ricon
                try:
                    photo = tk.PhotoImage(file=str(icon_path))
                    if photo.width() > ICON_SIZE:
                        photo = photo.subsample(photo.width() // ICON_SIZE, photo.width() // ICON_SIZE)
                except Exception:
                    photo = None
            else:
                photo = None
            if photo:
                btn = tk.Label(filter_frame, image=photo, cursor="hand2", bd=1, relief="raised",
                               bg=s["surface"], padx=2, pady=1)
                btn.image = photo
            else:
                btn = tk.Label(filter_frame, text=rname, cursor="hand2", bd=1, relief="raised",
                               bg=s["surface"], fg=s["fg"], font=("Microsoft YaHei UI", 9),
                               padx=6, pady=2)
            btn.pack(side=tk.LEFT, padx=2)
            btn.bind("<Button-1>", lambda e, r=rid: self._apply_rarity_filter(r))
            self._rarity_buttons.append(btn)
        self._update_rarity_highlight()

        # ── 中部：网格视图 ──
        grid_frame = ttk.Frame(self)
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self._canvas = tk.Canvas(grid_frame, bg=s["bg"], highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(grid_frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._grid_inner = tk.Frame(self._canvas, bg=s["surface"])
        self._canvas_window = self._canvas.create_window((0, 0), window=self._grid_inner, anchor="nw")
        self._grid_inner.bind("<Configure>",
                              lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        def _bind_mw(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _enter(e):
            self._canvas.bind_all("<MouseWheel>", _bind_mw)

        def _leave(e):
            self._canvas.unbind_all("<MouseWheel>")

        self._canvas.bind("<Enter>", _enter)
        self._canvas.bind("<Leave>", _leave)

        # ── 底部：取消按钮 ──
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="取消", command=self._on_close, width=10).pack()

        self._refresh_grid()

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)
        # 窗口被缩窄时按宽度重排列数，避免卡片超出画布
        cols = self._cols_for_width(event.width)
        if cols != getattr(self, "_cols", _DEFAULT_COLS):
            self._cols = cols
            self._refresh_grid()

    @staticmethod
    def _cols_for_width(avail: int) -> int:
        per = _CARD_W + _CARD_BORDER * 2 + _CARD_PAD * 2
        return max(1, avail // per)

    def _apply_scope(self, scope: str):
        """切换分页（全部回忆卡 / ★收藏）。"""
        self._scope = scope
        self._update_scope_highlight()
        self._refresh_grid()
        self._canvas.yview_moveto(0)

    def _update_scope_highlight(self):
        s = self.app._get_scheme()
        for key, btn in self._scope_buttons:
            if key == self._scope:
                btn.config(relief="sunken", bg=s["accent"], fg=s["accent_fg"])
            else:
                btn.config(relief="raised", bg=s["surface"], fg=s["fg"])

    def _apply_rarity_filter(self, rarity_id):
        self._current_rarity = rarity_id
        self._update_rarity_highlight()
        self._refresh_grid()
        # 切换筛选后滚动到顶部
        self._canvas.yview_moveto(0)

    def _update_rarity_highlight(self):
        s = self.app._get_scheme()
        for i, btn in enumerate(self._rarity_buttons):
            if i == self._current_rarity:
                btn.config(relief="sunken", bg=s["accent"], fg="#1e1e2e")
            else:
                btn.config(relief="raised", bg=s["surface"], fg=s["fg"])

    def _get_filtered_ids(self):
        """获取过滤后的回忆卡ID列表"""
        search_text = self._search_var.get().strip().lower()
        # 收藏分页：只保留已收藏的回忆卡（其余过滤条件完全相同）
        favorite_ids = self.app.favorite_memory_ids() if self._scope == _SCOPE_FAVORITE else None
        result = []
        try:
            memories = self.app.data_loader.load_memories()
        except Exception as e:
            print(f"[MemoryPicker] 加载回忆卡数据失败: {e}")
            return result
        for mid, mem in memories.items():
            if favorite_ids is not None and mid not in favorite_ids:
                continue
            if mid in self._exclude_ids:
                continue
            if self._current_rarity != 0 and mem.rarity != self._current_rarity:
                continue
            if search_text:
                if search_text not in str(mid) and search_text not in mem.name.lower():
                    continue
            result.append(mid)
        result.sort()
        return result

    def _load_card_thumb(self, mid):
        """加载回忆卡成品图（卡图 + 胶片卡框 + 稀有度徽章 + 收藏星标）"""
        favorite = bool(self.app.is_favorite_memory(mid))
        cache_key = (mid, favorite)
        if cache_key in self._thumb_cache:
            return self._thumb_cache[cache_key]
        mem = self.app.data_loader.get_memory(mid)
        rarity = getattr(mem, "rarity", 1) if mem else 1
        photo = load_memory_card_image(mid, rarity, (_CARD_W, _CARD_H), favorite=favorite)
        if photo is None:
            return None
        self._thumb_cache[cache_key] = photo
        return photo

    def _refresh_grid(self):
        """刷新网格视图（先显示占位符，再异步加载成品卡图）"""
        self._filtered_ids = self._get_filtered_ids()
        for child in self._grid_inner.winfo_children():
            child.destroy()

        COLS = getattr(self, "_cols", _DEFAULT_COLS)
        PAD = _CARD_PAD
        s = self.app._get_scheme()
        self._card_widgets = {}  # mid -> canvas

        # 空结果提示（收藏页首次打开多半是空的，要说清在哪儿收藏）
        if not self._filtered_ids:
            hint = ("尚无收藏回忆卡\n在「角色与回忆」Tab 的回忆图鉴里选中卡片，点名称栏的 ☆ 即可收藏"
                    if self._scope == _SCOPE_FAVORITE else "没有符合条件的回忆卡")
            tk.Label(self._grid_inner, text=hint, bg=s["surface"], fg=s["border"],
                     font=("Microsoft YaHei UI", 10), justify="center").grid(
                row=0, column=0, columnspan=max(1, COLS), pady=40)
            configure_uniform_columns(self._grid_inner, COLS)
            self._thumb_load_queue = []
            return

        try:
            for i, mid in enumerate(self._filtered_ids):
                mem = self.app.data_loader.get_memory(mid)
                if not mem:
                    continue
                row, col = divmod(i, COLS)
                card = tk.Frame(self._grid_inner, bg=s["surface"], bd=0,
                                highlightbackground=s["border"], highlightthickness=_CARD_BORDER,
                                cursor="hand2")
                card.grid(row=row, column=col, padx=PAD, pady=PAD)

                # 占位符画布（先不加载图片）
                card_canvas = tk.Canvas(card, width=_CARD_W, height=_CARD_H,
                                        bg=s["surface"], highlightthickness=0)
                card_canvas.pack()
                card_canvas.create_text(_CARD_W // 2, _CARD_H // 2, text="...",
                                        fill=s["border"], font=("Microsoft YaHei UI", 9))

                for widget in (card, card_canvas):
                    widget.bind("<Button-1>", lambda e, m=mid: self._on_select(m))

                self._card_widgets[mid] = card_canvas
        except Exception as e:
            print(f"[MemoryPicker] _refresh_grid error: {e}")
            import traceback
            traceback.print_exc()

        # 每列均分权重，使每行内容居中（并清掉更早布局留下的列，见 grid_layout）
        configure_uniform_columns(self._grid_inner, COLS)

        # 异步加载缩略图（每帧加载几张，避免卡顿）
        self._thumb_load_queue = list(self._filtered_ids)
        self._load_thumbs_async()

    def _load_thumbs_async(self):
        """异步逐批加载缩略图，每帧加载4张"""
        if not hasattr(self, '_thumb_load_queue') or not self._thumb_load_queue:
            return
        BATCH = 4
        for _ in range(BATCH):
            if not self._thumb_load_queue:
                break
            mid = self._thumb_load_queue.pop(0)
            if mid not in self._card_widgets:
                continue
            card_canvas = self._card_widgets[mid]
            photo = self._load_card_thumb(mid)
            if photo:
                card_canvas.delete("all")
                card_canvas.create_image(0, 0, image=photo, anchor="nw")
                card_canvas._card_photo = photo
        if self._thumb_load_queue:
            self.after(10, self._load_thumbs_async)

    def _on_select(self, mid):
        self.result = mid
        self.destroy()

    def _on_close(self):
        self.result = None
        self.destroy()
