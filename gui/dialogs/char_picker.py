# -*- coding: utf-8 -*-
"""角色选择弹窗：头像网格 + 属性筛选 + 搜索。

从 gui_app.py 抽取。
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict, List

from gui.constants import (
    ATTR_ICON_DIR,
    ATTR_ICON_MAP,
    AVATAR_DIR,
)
from gui.widgets.modal import _bind_modal_minimize_restore


class CharacterPickerDialog(tk.Toplevel):
    """角色选择二级弹窗：头像网格 + 属性筛选 + 搜索"""

    def __init__(self, parent, app, title="选择角色", for_ally: bool = True):
        super().__init__(parent)
        self.app = app
        self.result: Optional[int] = None  # 选中的角色ID
        self._current_filter = 0
        self._filtered_ids: List[int] = []
        self._thumb_cache: Dict[int, tk.PhotoImage] = {}
        # for_ally=True 时在用户模式下应用己方白名单过滤；敌方场景传 False 不过滤
        self._for_ally = for_ally

        self.title(title)
        self.transient(parent)
        self.grab_set()
        _bind_modal_minimize_restore(self, parent)
        self.resizable(True, True)
        self.geometry("520x620")
        self.minsize(400, 400)

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

        # ── 顶部：搜索框 + 属性筛选 ──
        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", padx=10, pady=5)

        # 搜索框
        search_frame = ttk.Frame(top_frame)
        search_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(search_frame, text="搜索:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._refresh_grid())
        search_entry = ttk.Entry(search_frame, textvariable=self._search_var, width=20)
        search_entry.pack(side=tk.LEFT, padx=5, fill="x", expand=True)
        search_entry.bind("<Return>", lambda e: self._refresh_grid())

        # 属性筛选
        filter_frame = ttk.Frame(top_frame)
        filter_frame.pack(fill="x")
        self._filter_buttons: List[tk.Label] = []
        ICON_SIZE = 24
        s = self.app._get_scheme()
        for attr_id in range(7):
            icon_path = ATTR_ICON_DIR / f"{ATTR_ICON_MAP[attr_id]}.png"
            try:
                photo = tk.PhotoImage(file=str(icon_path))
                if photo.width() > ICON_SIZE:
                    photo = photo.subsample(photo.width() // ICON_SIZE, photo.width() // ICON_SIZE)
            except Exception:
                photo = None

            btn = tk.Label(filter_frame, image=photo, cursor="hand2", bd=0, highlightthickness=0, bg=s["surface"])
            btn.pack(side=tk.LEFT, padx=1)
            btn.image = photo
            btn.bind("<Button-1>", lambda e, aid=attr_id: self._apply_filter(aid))
            self._filter_buttons.append(btn)

        self._update_filter_highlight()

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

    def _apply_filter(self, attr_id):
        self._current_filter = attr_id
        self._update_filter_highlight()
        self._refresh_grid()
        # 切换筛选后滚动到顶部
        self._canvas.yview_moveto(0)

    def _update_filter_highlight(self):
        s = self.app._get_scheme()
        for i, btn in enumerate(self._filter_buttons):
            if i == self._current_filter:
                btn.config(bd=2, relief="sunken", bg=s["accent"])
            else:
                btn.config(bd=0, relief="raised", bg=s["surface"])

    def _get_filtered_ids(self):
        """获取过滤后的角色ID列表（包含自定义木桩）"""
        search_text = self._search_var.get().strip().lower()
        # 用户模式 + 己方场景：仅显示 SUPPORTED_CHARACTERS.md 白名单中的角色
        # 开发者模式 / 敌方场景：不做白名单限制；自定义木桩（cid<0）始终不受限
        restrict_to_supported = (
            self._for_ally
            and not self.app.is_developer_mode()
            and getattr(self.app, "supported_ally_ids", None)
        )
        result = []
        for cid in self.app.char_ids:
            if restrict_to_supported and cid not in self.app.supported_ally_ids:
                continue
            char = self.app.data_loader.get_character_by_id(cid)
            if not char:
                continue
            if self._current_filter != 0 and char.attribute != self._current_filter:
                continue
            if search_text:
                char_name = self.app.format_char_name(char).lower()
                if search_text not in str(cid) and search_text not in char_name:
                    continue
            result.append(cid)
        # 追加自定义木桩（属性筛选为"全部"或木桩属性匹配时显示）
        for cid, char_data in self.app.data_loader.get_all_custom_dummies().items():
            if self._current_filter != 0 and char_data.attribute != self._current_filter:
                continue
            if search_text:
                dummy_name = char_data.name.lower()
                if search_text not in str(cid) and search_text not in dummy_name:
                    continue
            result.append(cid)
        return result

    def _load_thumb(self, cid):
        """加载缩略图（缓存）"""
        if cid in self._thumb_cache:
            return self._thumb_cache[cid]
        from PIL import Image, ImageTk
        THUMB_W, THUMB_H = 70, 90
        avatar_path = AVATAR_DIR / f"{cid}.png"
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            pil_img = pil_img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
            photo = ImageTk.PhotoImage(pil_img)
            self._thumb_cache[cid] = photo
            return photo
        except Exception:
            return None

    def _refresh_grid(self):
        """刷新网格视图"""
        self._filtered_ids = self._get_filtered_ids()
        for child in self._grid_inner.winfo_children():
            child.destroy()

        COLS = 6
        PAD = 2
        s = self.app._get_scheme()

        for i, cid in enumerate(self._filtered_ids):
            char = self.app.data_loader.get_character_by_id(cid)
            if not char:
                continue
            row, col = divmod(i, COLS)
            card = tk.Frame(self._grid_inner, bg=s["surface"], bd=0,
                            highlightbackground=s["border"], highlightthickness=2,
                            cursor="hand2")
            card.grid(row=row, column=col, padx=PAD, pady=PAD)

            photo = self._load_thumb(cid)
            if photo:
                avatar_label = tk.Label(card, image=photo, bg=s["surface"], bd=0)
                avatar_label.image = photo
                avatar_label.pack()
            else:
                # 木桩等无头像角色显示名称占位
                is_dummy = cid < 0
                if is_dummy:
                    placeholder_text = "木桩"
                elif self.app.is_developer_mode():
                    placeholder_text = f"[{cid}]"
                else:
                    placeholder_text = "???"
                placeholder = tk.Label(card, text=placeholder_text, bg=s["surface"], fg=s["border"],
                                       width=10, height=6, font=("Microsoft YaHei UI", 8))
                placeholder.pack()

            name = self.app.format_char_name(char)
            if len(name) > 12:
                name = name[:11] + "…"
            # 木桩名称前加标记
            if cid < 0:
                name = "▣ " + name
            name_label = tk.Label(card, text=name, bg=s["surface"], fg=s["fg"],
                                  font=("Microsoft YaHei UI", 8), wraplength=90,
                                  height=2, justify="center")
            name_label.pack(pady=(2, 0))

            for widget in [card] + list(card.winfo_children()):
                widget.bind("<Button-1>", lambda e, c=cid: self._on_select(c))

        # 每列均分权重，使每行内容居中
        for c in range(COLS):
            self._grid_inner.grid_columnconfigure(c, weight=1, uniform="col")

    def _on_select(self, cid):
        self.result = cid
        self.destroy()

    def _on_close(self):
        self.result = None
        self.destroy()
