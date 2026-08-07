# -*- coding: utf-8 -*-
"""敌方选择弹窗：头像网格选择，区分当期/往期演习敌方。

从 gui_app.py 抽取。
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict

from gui.constants import (
    ALLOWED_ENEMY_IDS,
    CURRENT_EXERCISE_ENEMY_COUNT,
    ENEMY_AVATAR_MAP,
    AVATAR_DIR,
)
from gui.widgets.modal import _bind_modal_minimize_restore


class EnemyPickerDialog(tk.Toplevel):
    """敌方选择二级弹窗：头像网格选择"""

    def __init__(self, parent, app, title="选择敌方单位"):
        super().__init__(parent)
        self.app = app
        self.result: Optional[int] = None  # 选中的敌方ID
        self._thumb_cache: Dict[int, tk.PhotoImage] = {}

        self.title(title)
        self.transient(parent)
        self.grab_set()
        _bind_modal_minimize_restore(self, parent)
        self.resizable(True, True)
        self.geometry("440x320")
        self.minsize(300, 280)

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

        # 顶栏：标题（左）+ 显示/隐藏往期敌方按钮（右）
        self._show_past = False
        top_bar = ttk.Frame(self)
        top_bar.pack(fill=tk.X, padx=10, pady=(10, 5))
        ttk.Label(top_bar, text="选择敌方单位", font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT)
        self._toggle_past_btn = ttk.Button(top_bar, text="显示往期敌方", command=self._toggle_past, width=14)
        self._toggle_past_btn.pack(side=tk.RIGHT)

        # 网格视图
        grid_frame = tk.Frame(self, bg=s["bg"])
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

        # 底部取消按钮
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="取消", command=self._on_close, width=10).pack()

        self._refresh_grid()

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

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
        """刷新网格视图：当期敌方始终显示，往期敌方仅在_show_past为True时显示"""
        s = self.app._get_scheme()
        for child in self._grid_inner.winfo_children():
            child.destroy()

        dev_mode = self.app.is_developer_mode()

        # 当期敌方 = JSON文件最后添加的 CURRENT_EXERCISE_ENEMY_COUNT 个
        all_eids = list(self._enemy_data().keys())
        current_eids = set(all_eids[-CURRENT_EXERCISE_ENEMY_COUNT:]) if all_eids else set()

        # 按当期/往期分组，并过滤白名单
        current_enemies = []
        past_enemies = []
        for eid, data in self._enemy_data().items():
            if not dev_mode and eid not in ALLOWED_ENEMY_IDS:
                continue
            if eid in current_eids:
                current_enemies.append((eid, data))
            else:
                past_enemies.append((eid, data))

        # 各组按角色名排序
        current_enemies.sort(key=lambda x: x[1]["character_name"])
        past_enemies.sort(key=lambda x: x[1]["character_name"])

        COLS = 4
        PAD = 4
        THUMB_W, THUMB_H = 70, 90

        row = 0

        # 当期敌方
        if current_enemies:
            header = tk.Label(self._grid_inner, text="当期演习敌方", bg=s["bg"], fg=s["fg"],
                              font=("Microsoft YaHei UI", 9, "bold"), anchor="w")
            header.grid(row=row, column=0, columnspan=COLS, sticky="ew", padx=PAD, pady=(6, 4))
            row += 1
            for i, (eid, data) in enumerate(current_enemies):
                r, c = divmod(i, COLS)
                self._render_enemy_card(eid, data, row + r, c, s, THUMB_W, THUMB_H, PAD, dev_mode)
            row += (len(current_enemies) + COLS - 1) // COLS

        # 往期敌方（仅当_show_past为True时显示）
        if self._show_past and past_enemies:
            header = tk.Label(self._grid_inner, text="往期演习敌方", bg=s["bg"], fg=s["fg"],
                              font=("Microsoft YaHei UI", 9, "bold"), anchor="w")
            header.grid(row=row, column=0, columnspan=COLS, sticky="ew", padx=PAD, pady=(10, 4))
            row += 1
            for i, (eid, data) in enumerate(past_enemies):
                r, c = divmod(i, COLS)
                self._render_enemy_card(eid, data, row + r, c, s, THUMB_W, THUMB_H, PAD, dev_mode)
            row += (len(past_enemies) + COLS - 1) // COLS

        # 每列均分权重
        for c in range(COLS):
            self._grid_inner.grid_columnconfigure(c, weight=1, uniform="col")

        # 重置滚动位置到顶部
        self._canvas.yview_moveto(0.0)

    def _render_enemy_card(self, eid, data, row, col, s, THUMB_W, THUMB_H, PAD, dev_mode):
        """渲染单个敌方卡片"""
        card = tk.Frame(self._grid_inner, bg=s["surface"], bd=0,
                       highlightbackground=s["border"], highlightthickness=2,
                       cursor="hand2")
        card.grid(row=row, column=col, padx=PAD, pady=PAD)

        # 头像
        avatar_cid = ENEMY_AVATAR_MAP.get(eid)
        photo = None
        if avatar_cid:
            photo = self._load_thumb(avatar_cid)
        if photo:
            avatar_label = tk.Label(card, image=photo, bg=s["surface"], bd=0)
            avatar_label.image = photo
            avatar_label.pack()
        else:
            placeholder_text = f"[{eid}]" if dev_mode else "???"
            placeholder = tk.Label(card, text=placeholder_text, bg=s["surface"], fg=s["border"],
                                   width=THUMB_W // 8, height=THUMB_H // 16,
                                   font=("Microsoft YaHei UI", 8))
            placeholder.pack()

        # 名称
        pos_name = ["", "左前", "中前", "右前", "左后", "中后", "右后"][data.get("position", 2)]
        if dev_mode:
            name_text = f"[{eid}] {data['character_name']}"
        else:
            name_text = f"{data['character_name']}"
        name_label = tk.Label(card, text=name_text, bg=s["surface"], fg=s["fg"],
                              font=("Microsoft YaHei UI", 8), wraplength=THUMB_W + 10,
                              height=2, justify="center")
        name_label.pack(pady=(2, 0))

        # 站位
        pos_label = tk.Label(card, text=f"({pos_name})", bg=s["surface"], fg=s["border"],
                              font=("Microsoft YaHei UI", 7))
        pos_label.pack()

        # 绑定点击事件
        for widget in [card] + list(card.winfo_children()):
            widget.bind("<Button-1>", lambda e, eid=eid: self._on_select(eid))

    def _toggle_past(self):
        """切换往期敌方的显示/隐藏"""
        self._show_past = not self._show_past
        self._toggle_past_btn.config(text="隐藏往期敌方" if self._show_past else "显示往期敌方")
        self._refresh_grid()

    def _enemy_data(self):
        """获取敌方数据"""
        return self.app.data_loader.get_tactical_exercise_enemies()

    def _on_select(self, eid):
        self.result = eid
        self.destroy()

    def _on_close(self):
        self.result = None
        self.destroy()
