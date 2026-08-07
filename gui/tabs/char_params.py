# -*- coding: utf-8 -*-
"""角色参数 Tab（个人覆盖优先于全局默认）。

从 gui_app.py 抽取，通过 self.app 访问主类。
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional

from src.data.stat_calculator import StatCalculator
from src.config.panel_config import PanelConfig, ModuleConfig
from src.config.player_config import SchoolLevels

from gui.constants import (
    ATTR_ICON_DIR,
    ATTR_ICON_MAP,
    AVATAR_DIR,
    GEAR_EFFECT_DISPLAY,
    GEAR_EFFECT_OPTIONS_DISPLAY,
    GEAR_EFFECT_REVERSE,
    RARITY_NAMES,
    _DARK_ACCENT,
    _DARK_BORDER,
    _DARK_FG,
    _DARK_INPUT_BG,
)
from gui.utils import get_max_rarity_for, get_module_type_ids


class CharacterParamsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.char_override_vars: Dict[int, Dict[str, Any]] = {}
        self._current_filter = 0  # 0=全部, 1-6=属性
        self._filtered_char_ids: List[int] = []
        self._attr_icons: Dict[int, tk.PhotoImage] = {}  # 缓存属性图标
        self._build()

    def _build(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        ttk.Label(left, text="角色列表", font=("Microsoft YaHei UI", 10, "bold")).pack(pady=(5, 0))

        # ── 属性筛选栏 + 视图切换 ──
        filter_frame = ttk.Frame(left)
        filter_frame.pack(fill="x", padx=5, pady=5)

        self._filter_buttons: List[tk.Label] = []
        ICON_SIZE = 24
        s = self.app._get_scheme()
        for attr_id in range(7):  # 0=全部, 1-6=属性
            icon_path = ATTR_ICON_DIR / f"{ATTR_ICON_MAP[attr_id]}.png"
            try:
                photo = tk.PhotoImage(file=str(icon_path))
                if photo.width() > ICON_SIZE:
                    photo = photo.subsample(photo.width() // ICON_SIZE, photo.width() // ICON_SIZE)
                self._attr_icons[attr_id] = photo
            except Exception:
                photo = None

            btn = tk.Label(filter_frame, image=photo, cursor="hand2",
                           bd=0, highlightthickness=0, bg=s["surface"])
            btn.pack(side=tk.LEFT, padx=1)
            btn.image = photo
            btn.bind("<Button-1>", lambda e, aid=attr_id: self._apply_filter(aid))
            self._filter_buttons.append(btn)

        self._update_filter_highlight()

        # 视图切换按钮
        self._view_mode = "grid"
        self._list_btn = ttk.Button(filter_frame, text="列表", width=4,
                                     command=self._switch_to_list_view)
        self._list_btn.pack(side=tk.RIGHT, padx=1)
        self._grid_btn = ttk.Button(filter_frame, text="头像", width=4,
                                     command=self._switch_to_grid_view)
        self._grid_btn.pack(side=tk.RIGHT, padx=1)

        # ── 列表视图 ──
        self._list_frame = ttk.Frame(left)
        list_scrollbar = ttk.Scrollbar(self._list_frame)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.char_listbox = tk.Listbox(self._list_frame, yscrollcommand=list_scrollbar.set,
                                       exportselection=False,
                                       bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                       selectbackground=_DARK_ACCENT, selectforeground="#1e1e2e",
                                       borderwidth=0, highlightthickness=0,
                                       font=("Microsoft YaHei UI", 11))
        self.char_listbox.pack(fill=tk.BOTH, expand=True)
        list_scrollbar.config(command=self.char_listbox.yview)
        self.char_listbox.bind("<<ListboxSelect>>", self._on_char_select)

        # ── 网格视图（默认显示） ──
        self._grid_frame = ttk.Frame(left)
        self._grid_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        self._grid_canvas = tk.Canvas(self._grid_frame, bg=self.app._get_scheme()["bg"], highlightthickness=0)
        self._grid_scrollbar = ttk.Scrollbar(self._grid_frame, orient="vertical",
                                              command=self._grid_canvas.yview)
        self._grid_canvas.configure(yscrollcommand=self._grid_scrollbar.set)
        self._grid_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._grid_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        s = self.app._get_scheme()
        self._grid_inner = tk.Frame(self._grid_canvas, bg=s["surface"])
        self._grid_canvas_window = self._grid_canvas.create_window((0, 0), window=self._grid_inner, anchor="nw")
        self._grid_inner.bind("<Configure>",
                              lambda e: self._grid_canvas.configure(scrollregion=self._grid_canvas.bbox("all")))
        self._grid_canvas.bind("<Configure>", self._on_grid_canvas_resize)

        def _bind_grid_mousewheel(e):
            self._grid_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _enter_grid(e):
            self._grid_canvas.bind_all("<MouseWheel>", _bind_grid_mousewheel)

        def _leave_grid(e):
            self._grid_canvas.unbind_all("<MouseWheel>")

        self._grid_canvas.bind("<Enter>", _enter_grid)
        self._grid_canvas.bind("<Leave>", _leave_grid)

        self._grid_cards: Dict[int, tk.Frame] = {}  # cid -> card frame
        self._selected_grid_cid: Optional[int] = None

        self._refresh_list()

        btn_frame = ttk.Frame(left)
        btn_frame.pack(pady=5)
        ttk.Button(btn_frame, text="重置选中角色", command=self._reset_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_frame, text="全部重置", command=self._reset_all).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_frame, text="全部应用全局", command=self._apply_global_all).pack(side=tk.LEFT, padx=3)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)

        s = self.app._get_scheme()
        right_canvas = tk.Canvas(right, bg=s["bg"], highlightthickness=0)
        right_scrollbar = ttk.Scrollbar(right, orient="vertical", command=right_canvas.yview)
        self.detail_frame = ttk.Frame(right_canvas)
        self.detail_frame.bind("<Configure>",
                               lambda e: right_canvas.configure(scrollregion=right_canvas.bbox("all")))
        right_canvas.create_window((0, 0), window=self.detail_frame, anchor="nw")
        right_canvas.configure(yscrollcommand=right_scrollbar.set)
        right_canvas.pack(side="left", fill="both", expand=True)
        right_scrollbar.pack(side="right", fill="y")

        def _bind_right_width(event):
            right_canvas.itemconfig(1, width=event.width)

        right_canvas.bind("<Configure>", _bind_right_width)

        def _on_right_mousewheel(e):
            right_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _enter_right(e):
            right_canvas.bind_all("<MouseWheel>", _on_right_mousewheel)

        def _leave_right(e):
            right_canvas.unbind_all("<MouseWheel>")

        right_canvas.bind("<Enter>", _enter_right)
        right_canvas.bind("<Leave>", _leave_right)

        ttk.Label(self.detail_frame, text="选择左侧角色查看/编辑参数", font=("Microsoft YaHei UI", 10)).pack(pady=20)

    def _on_char_select(self, event):
        sel = self.char_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._filtered_char_ids):
            cid = self._filtered_char_ids[idx]
            self._show_detail(cid)

    def _on_grid_canvas_resize(self, event):
        """Canvas宽度变化时调整inner frame宽度"""
        self._grid_canvas.itemconfig(self._grid_canvas_window, width=event.width)

    def _refresh_list(self):
        """根据当前筛选条件刷新角色列表"""
        self._filtered_char_ids = []
        for cid in self.app.char_ids:
            char = self.app.data_loader.get_character_by_id(cid)
            if not char:
                continue
            if self._current_filter != 0 and char.attribute != self._current_filter:
                continue
            self._filtered_char_ids.append(cid)

        if self._view_mode == "list":
            self.char_listbox.delete(0, tk.END)
            for cid in self._filtered_char_ids:
                char = self.app.data_loader.get_character_by_id(cid)
                is_locked = self.app.char_config.get(cid, {}).get("locked", False)
                lock_mark = "🔒 " if is_locked else ""
                if self.app.is_developer_mode():
                    self.char_listbox.insert(tk.END, f"{lock_mark}[{cid}] {self.app.format_char_name(char)}")
                else:
                    self.char_listbox.insert(tk.END, f"{lock_mark}{self.app.format_char_name(char)}")
        else:
            self._refresh_grid_view()

    def _switch_to_list_view(self):
        """切换到列表视图"""
        self._view_mode = "list"
        self._grid_frame.pack_forget()
        self._list_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        self._refresh_list()

    def _switch_to_grid_view(self):
        """切换到网格视图"""
        self._view_mode = "grid"
        self._list_frame.pack_forget()
        self._grid_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        self._refresh_grid_view()

    def _load_avatar_thumbnail(self, cid):
        """加载角色头像缩略图（用于网格视图），返回 tk.PhotoImage 或 None"""
        from PIL import Image, ImageTk
        THUMB_W, THUMB_H = 70, 90
        avatar_path = AVATAR_DIR / f"{cid}.png"
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            pil_img = pil_img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
            return ImageTk.PhotoImage(pil_img)
        except Exception:
            return None

    def _refresh_grid_view(self):
        """刷新网格视图"""
        self._selected_grid_cid = None
        s = self.app._get_scheme()
        # 刷新容器背景色（画布与内容载体均使用整体背景色，保持一致）
        self._grid_canvas.config(bg=s["bg"])
        self._grid_inner.config(bg=s["bg"])
        for child in self._grid_inner.winfo_children():
            child.destroy()
        self._grid_cards.clear()

        COLS = 6
        PAD = 2
        THUMB_W, THUMB_H = 70, 90
        s = self.app._get_scheme()

        for i, cid in enumerate(self._filtered_char_ids):
            char = self.app.data_loader.get_character_by_id(cid)
            if not char:
                continue
            row, col = divmod(i, COLS)
            # 使用highlightthickness作为选中边框，bd固定为0避免点击时尺寸变化
            card = tk.Frame(self._grid_inner, bg=s["surface"], bd=0,
                            highlightbackground=s["border"], highlightthickness=2,
                            cursor="hand2")
            card.grid(row=row, column=col, padx=PAD, pady=PAD, sticky="ew")

            # 头像
            photo = self._load_avatar_thumbnail(cid)
            if photo:
                avatar_label = tk.Label(card, image=photo, bg=s["surface"], bd=0)
                avatar_label.image = photo
                avatar_label.pack()
            else:
                placeholder_text = f"[{cid}]" if self.app.is_developer_mode() else "???"
                placeholder = tk.Label(card, text=placeholder_text, bg=s["surface"], fg=s["border"],
                                       width=THUMB_W // 8, height=THUMB_H // 16,
                                       font=("Microsoft YaHei UI", 8))
                placeholder.pack()

            # 角色名（锁定角色显示🔒标识）
            name = self.app.format_char_name(char)
            is_locked = self.app.char_config.get(cid, {}).get("locked", False)
            if is_locked:
                name = "🔒" + name
            # 截断过长名字
            if len(name) > 12:
                name = name[:11] + "…"
            name_label = tk.Label(card, text=name, bg=s["surface"], fg=s["fg"],
                                  font=("Microsoft YaHei UI", 8), wraplength=THUMB_W + 10,
                                  height=2, justify="center")
            name_label.pack(pady=(2, 0))

            # 绑定点击事件
            for widget in [card] + list(card.winfo_children()):
                widget.bind("<Button-1>", lambda e, c=cid: self._on_grid_card_click(c))

            self._grid_cards[cid] = card

        # 每列均分权重，使每行内容居中
        for c in range(COLS):
            self._grid_inner.grid_columnconfigure(c, weight=1, uniform="col")

    def _on_grid_card_click(self, cid):
        """网格视图卡片点击"""
        s = self.app._get_scheme()
        accent = s["accent"]
        surface = s["surface"]
        # 仅恢复上一个选中卡片的边框，再高亮新卡片（避免遍历全部卡片）
        prev = self._selected_grid_cid
        if prev is not None and prev in self._grid_cards:
            self._grid_cards[prev].config(highlightbackground=surface)
        self._selected_grid_cid = cid
        if cid in self._grid_cards:
            self._grid_cards[cid].config(highlightbackground=accent)
        self._show_detail(cid)

    def _apply_filter(self, attr_id: int):
        """应用属性筛选"""
        self._current_filter = attr_id
        self._update_filter_highlight()
        self._refresh_list()
        # 切换筛选后回到页面顶部（网格视图和列表视图均处理）
        if self._view_mode == "grid":
            self._grid_canvas.yview_moveto(0)
        else:
            self.char_listbox.yview_moveto(0)
        # 清空右侧详情
        for w in self.detail_frame.winfo_children():
            w.destroy()
        ttk.Label(self.detail_frame, text="选择左侧角色查看/编辑参数",
                  font=("Microsoft YaHei UI", 10)).pack(pady=20)

    def _update_filter_highlight(self):
        """更新筛选按钮高亮状态"""
        for i, btn in enumerate(self._filter_buttons):
            btn.config(bd=2, relief="raised")
            if i == self._current_filter:
                btn.config(bd=2, relief="sunken")

    def _show_detail(self, cid):
        for w in self.detail_frame.winfo_children():
            w.destroy()

        char = self.app.data_loader.get_character_by_id(cid)
        if not char:
            return

        f = self.detail_frame

        # 标题上方留白
        ttk.Label(f, text="").pack()

        type_name = ["", "物理", "EN", "敏捷"][char.character_type] if char.character_type <= 3 else "?"
        attr_name = ["", "火", "水", "风", "土", "光", "暗"][char.attribute] if char.attribute <= 6 else "?"
        role_names = {0: "未设定", 1: "物理攻击手", 2: "EN攻击手", 3: "坦克", 4: "辅助", 5: "控制"}
        role_name = role_names.get(char.role_type, "?")
        pos_names = {0: "未设定", 1: "前排", 2: "后排", 3: "灵活"}
        pos_name = pos_names.get(char.position_type, "?")

        # ── 顶部区域：头像(左) + 基本信息+面板预览(右) ──
        top_frame = ttk.Frame(f)
        top_frame.pack(fill="x", padx=5, pady=5)

        # 头像（左上）
        self._build_avatar_preview(top_frame, cid)

        # 右侧区域：基本信息 + 面板预览（上下居中于头像高度）
        right_frame = ttk.Frame(top_frame)
        right_frame.pack(side="left", fill="both", expand=True, padx=(10, 0))
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        # 基本信息区域（上半部分，上下居中，紧凑行距）
        info_frame = ttk.Frame(right_frame)
        info_frame.grid(row=0, column=0, sticky="s")

        char_display_name = f"{self.app.format_char_name(char)} [{cid}]" if self.app.is_developer_mode() else self.app.format_char_name(char)
        name_row = ttk.Frame(info_frame)
        name_row.pack(fill="x", pady=(0, 2))
        ttk.Label(name_row, text=char_display_name,
                  font=("Microsoft YaHei UI", 14, "bold"), anchor="center").pack(side="left", fill="x", expand=True)

        # 锁定按钮
        is_locked = self.app.char_config.get(cid, {}).get("locked", False)
        lock_btn = ttk.Button(name_row, width=3,
                              text="🔒" if is_locked else "🔓",
                              command=lambda c=cid: self._toggle_lock(c))
        lock_btn.pack(side="right", padx=(5, 0))
        lock_tooltip = "已锁定 - 点击解锁" if is_locked else "未锁定 - 点击锁定"
        self._create_tooltip(lock_btn, lock_tooltip)
        ttk.Label(info_frame, text=f"类型: {type_name} | 属性: {attr_name} | 默认稀有度: {char.default_rarity}",
                  font=("Microsoft YaHei UI", 11), anchor="center").pack(fill="x", pady=1)
        ttk.Label(info_frame, text=f"定位: {role_name} | 位置适应性: {pos_name}",
                  font=("Microsoft YaHei UI", 11), anchor="center").pack(fill="x", pady=(1, 4))

        # 角色面板预览（下半部分，上下居中）
        self._build_preview_inline(right_frame, cid, char)

        # ── 预计算技能等级上限（必须在_build_skill_preview之前）──
        cfg = self.app.char_config.get(cid, {"override": False})
        init_rarity_for_skill = cfg.get("rarity", self.app.global_tab.var_rarity.get()) if cfg.get("override") else self.app.global_tab.var_rarity.get()
        max_rarity_for_skill = get_max_rarity_for(char.default_rarity)
        if init_rarity_for_skill > max_rarity_for_skill:
            init_rarity_for_skill = max_rarity_for_skill
        self._current_skill_max = 15 if init_rarity_for_skill >= 9 else 10

        # ── 技能效果预览 ──
        self._build_skill_preview(f, cid, char)

        # ── 参数配置（左侧基础参数1/3，右侧模块设置2/3）──
        cfg = self.app.char_config.get(cid, {"override": False})
        is_locked = self.app.char_config.get(cid, {}).get("locked", False)
        config_title = "参数配置 🔒 已锁定" if is_locked else "参数配置"
        config_frame = ttk.LabelFrame(f, text=config_title)
        config_frame.pack(fill="x", padx=5, pady=5)

        # 左侧：基础参数（1/3宽度，上下分割）
        basic_frame = ttk.Frame(config_frame)
        basic_frame.pack(side="left", fill="y", padx=10, pady=5)

        # 基础参数区上下分割：上方2/3内容，下方1/3按钮
        basic_frame.grid_rowconfigure(0, weight=2)
        basic_frame.grid_rowconfigure(1, weight=1)

        # 上方：原有内容（稀有度、好感度、技能等级）
        basic_content = ttk.Frame(basic_frame)
        basic_content.grid(row=0, column=0, sticky="nsew")

        ttk.Label(basic_content, text="基础参数", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(0, 5))

        init_level = cfg.get("level", self.app.global_tab.var_level.get()) if cfg.get("override") else self.app.global_tab.var_level.get()
        level_row = ttk.Frame(basic_content)
        level_row.pack(fill="x", pady=3)
        ttk.Label(level_row, text="角色等级:", width=8).pack(side="left")
        level_var = tk.IntVar(value=init_level)
        ttk.Spinbox(level_row, from_=1, to=999, textvariable=level_var, width=5).pack(side="left", padx=3)

        init_rarity = cfg.get("rarity", self.app.global_tab.var_rarity.get()) if cfg.get("override") else self.app.global_tab.var_rarity.get()
        max_rarity = get_max_rarity_for(char.default_rarity)
        min_rarity = char.default_rarity
        # 截断到 [min_rarity, max_rarity] 范围内
        if init_rarity > max_rarity:
            init_rarity = max_rarity
        elif init_rarity < min_rarity:
            init_rarity = min_rarity
        rarity_row = ttk.Frame(basic_content)
        rarity_row.pack(fill="x", pady=3)
        ttk.Label(rarity_row, text="稀有度:", width=8).pack(side="left")
        rarity_var = tk.IntVar(value=init_rarity)
        cb = ttk.Combobox(rarity_row, textvariable=rarity_var, values=list(range(min_rarity, max_rarity + 1)), state="readonly", width=5)
        cb.pack(side="left", padx=3)
        rarity_name_var = tk.StringVar(value=RARITY_NAMES.get(rarity_var.get(), ""))
        ttk.Label(rarity_row, textvariable=rarity_name_var, width=6).pack(side="left", padx=3)

        def _update_rarity_label(*a):
            rarity_name_var.set(RARITY_NAMES.get(rarity_var.get(), ""))
        rarity_var.trace_add("write", _update_rarity_label)

        init_aff = cfg.get("affection", self.app.global_tab.var_affection.get()) if cfg.get("override") else self.app.global_tab.var_affection.get()
        aff_row = ttk.Frame(basic_content)
        aff_row.pack(fill="x", pady=3)
        ttk.Label(aff_row, text="好感度:", width=8).pack(side="left")
        aff_var = tk.IntVar(value=init_aff)
        ttk.Spinbox(aff_row, from_=1, to=40, textvariable=aff_var, width=5).pack(side="left", padx=3)

        # 技能等级不再统一设置，改为在每个技能卡片中单独设置
        # _current_skill_max 已在 _build_skill_preview 之前预计算
        self._current_rarity_var = rarity_var

        def _update_skill_max_on_rarity_change(*a):
            """稀有度变化时动态调整所有技能等级Spinbox上限"""
            r = rarity_var.get()
            new_max = 15 if r >= 9 else 10
            self._current_skill_max = new_max
            # 更新所有技能等级Spinbox的上限
            if hasattr(self, '_skill_level_spinboxes'):
                for spinbox in self._skill_level_spinboxes:
                    try:
                        spinbox.config(to=new_max)
                    except Exception:
                        pass
            # 更新超出上限的等级值
            if hasattr(self, '_skill_level_vars'):
                for sid, lv_var in self._skill_level_vars.items():
                    try:
                        if lv_var.get() > new_max:
                            lv_var.set(new_max)
                    except Exception:
                        pass
        rarity_var.trace_add("write", _update_skill_max_on_rarity_change)

        # 下方：按钮区（两个按钮分两行）
        btn_frame = ttk.Frame(basic_frame)
        btn_frame.grid(row=1, column=0, sticky="nsew")

        ttk.Button(btn_frame, text="应用设置", command=lambda: self._apply_detail(cid, char, v)).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="重置为全局默认", command=lambda: self._reset_to_global(cid, char)).pack(fill="x", pady=2)

        # 右侧：模块设置（2/3宽度）
        mod_frame = ttk.Frame(config_frame)
        mod_frame.pack(side="left", fill="both", expand=True, padx=10, pady=5)

        # 标题行：模块设置 + 三个模块组同行
        title_row = ttk.Frame(mod_frame)
        title_row.pack(fill="x", pady=(0, 3))

        # 左1/4：Tier和等级竖排
        mod_left = ttk.Frame(title_row)
        mod_left.pack(side="left", fill="y", padx=(0, 10))

        ttk.Label(mod_left, text="模块设置", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(0, 3))

        # 表头 + 3 行 HP/攻击/防御 Tier/等级
        mod_tl_grid = ttk.Frame(mod_left)
        mod_tl_grid.pack(fill="x", pady=2)
        ttk.Label(mod_tl_grid, text="", width=4).grid(row=0, column=0)
        ttk.Label(mod_tl_grid, text="Tier", width=5).grid(row=0, column=1, padx=2)
        ttk.Label(mod_tl_grid, text="等级", width=5).grid(row=0, column=2, padx=2)

        gv = self.app.global_tab.get_values()
        if cfg.get("override"):
            old_tier = cfg.get("mod_tier", 9)
            old_level = cfg.get("mod_level", 50)
            init_tier_hp = cfg.get("mod_tier_hp", old_tier)
            init_lv_hp = cfg.get("mod_level_hp", old_level)
            init_tier_atk = cfg.get("mod_tier_atk", old_tier)
            init_lv_atk = cfg.get("mod_level_atk", old_level)
            init_tier_def = cfg.get("mod_tier_def", old_tier)
            init_lv_def = cfg.get("mod_level_def", old_level)
        else:
            init_tier_hp = gv["default_mod_tier_hp"]
            init_lv_hp = gv["default_mod_level_hp"]
            init_tier_atk = gv["default_mod_tier_atk"]
            init_lv_atk = gv["default_mod_level_atk"]
            init_tier_def = gv["default_mod_tier_def"]
            init_lv_def = gv["default_mod_level_def"]

        mod_tier_hp_var = tk.IntVar(value=init_tier_hp)
        mod_lv_hp_var = tk.IntVar(value=init_lv_hp)
        mod_tier_atk_var = tk.IntVar(value=init_tier_atk)
        mod_lv_atk_var = tk.IntVar(value=init_lv_atk)
        mod_tier_def_var = tk.IntVar(value=init_tier_def)
        mod_lv_def_var = tk.IntVar(value=init_lv_def)

        mod_stat_rows = [
            ("HP",   mod_tier_hp_var,  mod_lv_hp_var),
            ("攻击", mod_tier_atk_var, mod_lv_atk_var),
            ("防御", mod_tier_def_var, mod_lv_def_var),
        ]
        for idx, (stat_label, tier_var, lv_var) in enumerate(mod_stat_rows, start=1):
            ttk.Label(mod_tl_grid, text=stat_label, width=4).grid(row=idx, column=0, padx=2, pady=1, sticky="e")
            ttk.Combobox(mod_tl_grid, textvariable=tier_var, values=list(range(1, 10)),
                         state="readonly", width=5).grid(row=idx, column=1, padx=2, pady=1, sticky="w")
            ttk.Spinbox(mod_tl_grid, from_=1, to=50, textvariable=lv_var,
                        width=5).grid(row=idx, column=2, padx=2, pady=1, sticky="w")

        # 右3/4：9个模块词条（与"模块设置"同行高度）
        mod_right = ttk.Frame(title_row)
        mod_right.pack(side="left", fill="both", expand=True)

        self._build_detail_gears_inline(mod_right, cid, cfg)

        v = {
            "level": level_var,
            "rarity": rarity_var, "affection": aff_var,
            "mod_tier_hp": mod_tier_hp_var, "mod_lv_hp": mod_lv_hp_var,
            "mod_tier_atk": mod_tier_atk_var, "mod_lv_atk": mod_lv_atk_var,
            "mod_tier_def": mod_tier_def_var, "mod_lv_def": mod_lv_def_var,
        }
        self.char_override_vars[cid] = v

        self._refresh_preview(cid)

    def _build_preview(self, parent, cid, char):
        preview_frame = ttk.LabelFrame(parent, text="角色面板预览")
        preview_frame.pack(fill="x", padx=5, pady=5)

        self.preview_labels: Dict[str, ttk.Label] = {}
        rows_info = [
            ("角色等级", "level"), ("稀有度", "rarity"), ("好感度", "affection"),
            ("HP", "hp"), ("攻击力", "attack"), ("防御力", "defense"),
            ("暴击率(%)", "crit_rate"), ("暴伤(%)", "crit_dmg"), ("速度", "speed"),
            ("有利加成(%)", "adv_dmg"), ("AP", "ap"), ("PP", "pp"),
        ]
        for i, (label_text, key) in enumerate(rows_info):
            r, c = divmod(i, 4)
            inner = ttk.Frame(preview_frame)
            inner.grid(row=r, column=c, padx=8, pady=2, sticky="w")
            ttk.Label(inner, text=label_text + ":", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
            lbl = ttk.Label(inner, text="--", font=("Microsoft YaHei UI", 9, "bold"))
            lbl.pack(side=tk.LEFT, padx=(3, 0))
            self.preview_labels[key] = lbl

        self.preview_cid = cid
        self.preview_char = char

    def _build_preview_inline(self, parent, cid, char):
        """构建角色面板预览（内嵌于头像右侧，紧凑排版）"""
        preview_frame = ttk.Frame(parent)
        preview_frame.grid(row=1, column=0, sticky="n")

        self.preview_labels: Dict[str, ttk.Label] = {}
        rows_info = [
            ("等级", "level"), ("稀有度", "rarity"), ("好感度", "affection"),
            ("HP", "hp"), ("攻击力", "attack"), ("防御力", "defense"),
            ("暴击率%", "crit_rate"), ("暴伤%", "crit_dmg"), ("速度", "speed"),
            ("有利%", "adv_dmg"), ("AP", "ap"), ("PP", "pp"),
        ]
        for i, (label_text, key) in enumerate(rows_info):
            r, c = divmod(i, 4)
            inner = ttk.Frame(preview_frame)
            inner.grid(row=r, column=c, padx=6, pady=1, sticky="w")
            ttk.Label(inner, text=label_text + ":", font=("Microsoft YaHei UI", 11)).pack(side=tk.LEFT)
            lbl = ttk.Label(inner, text="--", font=("Microsoft YaHei UI", 11, "bold"))
            lbl.pack(side=tk.LEFT, padx=(2, 0))
            self.preview_labels[key] = lbl

        self.preview_cid = cid
        self.preview_char = char

    def _get_skill_level(self, cid):
        """获取角色的技能等级"""
        cfg = self.app.char_config.get(cid, {"override": False})
        if cfg.get("override"):
            return cfg.get("skill_level", self.app.global_tab.var_skill_lv.get())
        return self.app.global_tab.var_skill_lv.get()

    def _format_skill_description(self, skill, level):
        """格式化技能描述，替换模板标签为实际数值"""
        template = skill.get_description_at_level(level)
        if not template:
            return "(无描述)"
        result = template
        for tag_name, tag in skill.template_tags.items():
            val = tag.get_value_at_level(level)
            if val == int(val):
                val_str = str(int(val))
            else:
                val_str = f"{val:.2f}".rstrip('0').rstrip('.')
            result = result.replace(f"{{{tag_name}}}", val_str)
        return result

    def _build_skill_preview(self, parent, cid, char):
        """构建技能效果预览区域"""
        skills = self.app.data_loader.get_character_skills(cid)
        if not skills:
            return

        frame = ttk.LabelFrame(parent, text="技能效果预览")
        frame.pack(fill="x", padx=5, pady=5)

        # 保存引用以便动态刷新
        self._skill_preview_frame = frame
        self._skill_preview_cid = cid
        self._skill_preview_char = char
        self._skill_preview_skills = skills

        # 构建每个技能的独立等级变量
        cfg = self.app.char_config.get(cid, {"override": False})
        skill_level_vars: Dict[int, tk.IntVar] = {}
        skill_max = getattr(self, '_current_skill_max', 15)
        global_skill_lv = self.app.global_tab.var_skill_lv.get()

        for skill in skills:
            # 读取已保存的各技能等级，向后兼容旧的统一skill_level
            saved_levels = cfg.get("skill_levels", {}) if cfg.get("override") else {}
            if saved_levels and str(skill.skill_id) in saved_levels:
                init_lv = saved_levels[str(skill.skill_id)]
            elif saved_levels and skill.skill_id in saved_levels:
                init_lv = saved_levels[skill.skill_id]
            elif cfg.get("override") and "skill_level" in cfg:
                # 向后兼容：旧配置使用统一skill_level
                init_lv = min(cfg["skill_level"], skill_max)
            else:
                init_lv = min(global_skill_lv, skill_max)
            skill_level_vars[skill.skill_id] = tk.IntVar(value=init_lv)

        self._skill_level_vars = skill_level_vars

        self._render_skill_cards(frame, skills)

    def _render_skill_cards(self, frame, skills):
        """渲染技能卡片到指定frame"""
        CARD_HEIGHT = 40
        skill_max = getattr(self, '_current_skill_max', 15)
        self._skill_desc_widgets = {}
        self._skill_level_spinboxes = []

        for skill in skills:
            card_frame = ttk.Frame(frame, relief="groove", borderwidth=1)
            card_frame.pack(fill="x", padx=3, pady=2)

            # 技能名称和属性信息
            info_frame = ttk.Frame(card_frame)
            info_frame.pack(fill="x", padx=3, pady=(3, 0))

            skill_type_names = {1: "AS", 2: "PS", 3: "EX"}
            stype = skill_type_names.get(skill.skill_type, str(skill.skill_type))
            ttk.Label(info_frame, text=f"[{stype}] {skill.name}",
                      font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")

            # 等级Spinbox（每个技能独立）
            lv_var = self._skill_level_vars.get(skill.skill_id)
            if lv_var:
                lv_frame = ttk.Frame(info_frame)
                lv_frame.pack(side="left", padx=(8, 0))
                ttk.Label(lv_frame, text="Lv.", font=("Microsoft YaHei UI", 8)).pack(side="left")
                lv_spinbox = ttk.Spinbox(lv_frame, from_=1, to=skill_max, textvariable=lv_var, width=3,
                                         font=("Microsoft YaHei UI", 8))
                lv_spinbox.pack(side="left", padx=1)
                self._skill_level_spinboxes.append(lv_spinbox)
                # 等级变化时刷新该技能的描述
                lv_var.trace_add("write", lambda *a, sid=skill.skill_id: self._refresh_single_skill_desc(sid))

            # 消耗点数（AS→AP, PS→PP, EX→EP）
            cost_unit = {1: "AP", 2: "PP", 3: "EP"}.get(skill.skill_type, "AP")
            ttk.Label(info_frame, text=f" | 消耗: {skill.resource_cost}{cost_unit}",
                      font=("Microsoft YaHei UI", 8)).pack(side="left", padx=(5, 0))

            # 冷却信息（1=技能结束→行动, 2=行动结束→回合）
            if skill.cooldown:
                if skill.cooldown_update_timing == 1:
                    cd_text = f" | 冷却: {skill.cooldown}回合"
                elif skill.cooldown_update_timing == 2:
                    cd_text = f" | 冷却: {skill.cooldown}行动"
                else:
                    cd_text = f" | 冷却: {skill.cooldown}无"
            else:
                cd_text = " | 冷却: 无"
            ttk.Label(info_frame, text=cd_text, font=("Microsoft YaHei UI", 8)).pack(side="left", padx=(5, 0))

            # 描述区域（带滚动条）
            lv_var = self._skill_level_vars.get(skill.skill_id)
            skill_lv = lv_var.get() if lv_var else 1
            desc_text = self._format_skill_description(skill, skill_lv)
            desc_outer = ttk.Frame(card_frame, height=CARD_HEIGHT)
            desc_outer.pack(fill="x", padx=5, pady=3)
            desc_outer.pack_propagate(False)

            s = self.app._get_scheme()
            desc_text_widget = tk.Text(desc_outer, wrap=tk.WORD, font=("Microsoft YaHei UI", 9),
                                       state="disabled", relief="flat",
                                       borderwidth=0, padx=2, pady=2,
                                       bg=s["input_bg"], fg=s["fg"],
                                       insertbackground=s["fg"],
                                       selectbackground=s["select_bg"],
                                       selectforeground=s["select_fg"])
            desc_scrollbar = ttk.Scrollbar(desc_outer, orient="vertical",
                                           command=desc_text_widget.yview)
            desc_text_widget.configure(yscrollcommand=desc_scrollbar.set)

            desc_scrollbar.pack(side="right", fill="y")
            desc_text_widget.pack(side="left", fill="both", expand=True)

            desc_text_widget.config(state="normal")
            desc_text_widget.insert("1.0", desc_text)
            desc_text_widget.config(state="disabled")

            # 保存desc widget引用以便单独刷新
            if not hasattr(self, '_skill_desc_widgets'):
                self._skill_desc_widgets = {}
            self._skill_desc_widgets[skill.skill_id] = desc_text_widget

    def _refresh_single_skill_desc(self, skill_id):
        """单个技能等级变化时刷新该技能的描述"""
        if not hasattr(self, '_skill_desc_widgets') or not hasattr(self, '_skill_preview_skills'):
            return
        desc_widget = self._skill_desc_widgets.get(skill_id)
        if not desc_widget or not desc_widget.winfo_exists():
            return
        # 找到对应的skill对象
        skill = None
        for s in self._skill_preview_skills:
            if s.skill_id == skill_id:
                skill = s
                break
        if not skill:
            return
        lv_var = self._skill_level_vars.get(skill_id)
        try:
            skill_lv = lv_var.get() if lv_var else 1
        except (tk.TclError, ValueError):
            return
        desc_text = self._format_skill_description(skill, skill_lv)
        desc_widget.config(state="normal")
        desc_widget.delete("1.0", tk.END)
        desc_widget.insert("1.0", desc_text)
        desc_widget.config(state="disabled")

    def _load_avatar_image(self, cid):
        """加载角色头像并等比例缩放至目标尺寸，返回 tk.PhotoImage 或 None"""
        AVATAR_W = 141
        AVATAR_H = 180
        avatar_path = AVATAR_DIR / f"{cid}.png"
        if not avatar_path.exists():
            return None
        try:
            img = tk.PhotoImage(file=str(avatar_path))
            # 等比例缩放：计算缩放因子
            orig_w = img.width()
            orig_h = img.height()
            if orig_w > 0 and orig_h > 0:
                scale_x = AVATAR_W / orig_w
                scale_y = AVATAR_H / orig_h
                scale = min(scale_x, scale_y)
                if scale < 1.0:
                    # 缩小：使用subsample（整数近似）
                    factor = max(1, int(1.0 / scale))
                    img = img.subsample(factor, factor)
                elif scale > 1.0:
                    # 放大：使用zoom（整数近似）
                    factor = max(1, int(scale))
                    img = img.zoom(factor, factor)
                # 如果缩放后仍偏大，再次subsample微调
                if img.width() > AVATAR_W or img.height() > AVATAR_H:
                    factor2 = max(1, max(img.width() // AVATAR_W, img.height() // AVATAR_H))
                    img = img.subsample(factor2, factor2)
            return img
        except Exception:
            return None

    def _build_avatar_preview(self, parent, cid):
        """构建角色头像预览区域（7:9 比例），作为顶部左侧内嵌组件"""
        AVATAR_W = 140   # 宽度: 7 * 20
        AVATAR_H = 180   # 高度: 9 * 20
        s = self.app._get_scheme()

        # 头像画布（直接pack到parent的左侧）
        self._avatar_canvas = tk.Canvas(parent, width=AVATAR_W, height=AVATAR_H,
                                        bg=s["surface"], highlightthickness=1,
                                        highlightbackground=s["border"])
        self._avatar_canvas._is_avatar = True
        self._avatar_canvas.pack(side="left", padx=(0, 10))

        # 加载头像或显示占位
        avatar_img = self._load_avatar_image(cid)
        if avatar_img:
            self._avatar_canvas.create_image(AVATAR_W // 2, AVATAR_H // 2,
                                             image=avatar_img, anchor="center")
            # 保持引用防止被GC回收
            self._avatar_canvas._photo_ref = avatar_img
        else:
            self._avatar_canvas.create_text(AVATAR_W // 2, AVATAR_H // 2,
                                            text=f"{cid}",
                                            font=("Microsoft YaHei UI", 8), fill=_DARK_BORDER,
                                            justify="center")

    def _build_detail_gears_inline(self, parent, cid, cfg):
        """构建模块词条（内联版本，使用pack布局）"""
        saved_gears = cfg.get("gear", []) if cfg.get("override") else self.app.global_tab.get_values()["default_gear"]
        saved_map = {}
        for g in saved_gears:
            saved_map[(g.get("group", 0), g.get("slot", 0))] = g

        self.detail_gear_vars = []
        module_names = ["模块1 (HP)", "模块2 (攻击)", "模块3 (防御)"]
        gear_frame = ttk.Frame(parent)
        gear_frame.pack(fill="x")

        for grp_idx in range(3):
            grp_frame = ttk.LabelFrame(gear_frame, text=module_names[grp_idx], style="Gear.TLabelframe")
            grp_frame.pack(side="left", padx=3, pady=0, fill="y")

            for slot_idx in range(3):
                slot_frame = ttk.Frame(grp_frame)
                slot_frame.pack(pady=1, padx=3)

                saved = saved_map.get((grp_idx, slot_idx), {})
                init_et = GEAR_EFFECT_DISPLAY.get(saved.get("effect_type", 0), "无效果")
                init_val = saved.get("value", 0.0)

                et_var = tk.StringVar(value=init_et)
                cb = ttk.Combobox(slot_frame, textvariable=et_var, values=GEAR_EFFECT_OPTIONS_DISPLAY,
                                  state="readonly", width=10)
                cb.pack()

                g_idx = grp_idx
                s_idx = slot_idx
                cb.bind("<<ComboboxSelected>>",
                        lambda e, g=g_idx, s=s_idx: self._validate_detail_gear_group(g, s))

                pct_frame = ttk.Frame(slot_frame)
                pct_frame.pack()
                v_var = tk.DoubleVar(value=init_val)
                ttk.Spinbox(pct_frame, from_=0, to=100, increment=0.5, textvariable=v_var, width=5).pack(side=tk.LEFT)
                ttk.Label(pct_frame, text="%", font=("Microsoft YaHei UI", 7)).pack(side=tk.LEFT)

                self.detail_gear_vars.append(
                    {"et": et_var, "val": v_var, "group": grp_idx, "slot": slot_idx})

    def _build_detail_gears(self, parent, cid, cfg):
        ttk.Label(parent, text="模块词条 (每角色共9槽，分3组，同组不可复选相同类型):", font=("Microsoft YaHei UI", 8)).grid(
            row=1, column=0, columnspan=6, sticky="w", padx=5, pady=(10, 2))

        saved_gears = cfg.get("gear", []) if cfg.get("override") else self.app.global_tab.get_values()["default_gear"]
        saved_map = {}
        for g in saved_gears:
            saved_map[(g.get("group", 0), g.get("slot", 0))] = g

        self.detail_gear_vars = []
        module_names = ["模块1 (HP)", "模块2 (攻击)", "模块3 (防御)"]
        gear_frame = ttk.Frame(parent)
        gear_frame.grid(row=2, column=0, columnspan=6, sticky="ew", padx=5, pady=2)

        for grp_idx in range(3):
            grp_frame = ttk.LabelFrame(gear_frame, text=module_names[grp_idx], style="Gear.TLabelframe")
            grp_frame.grid(row=0, column=grp_idx, padx=5, pady=3, sticky="n")

            for slot_idx in range(3):
                slot_frame = ttk.Frame(grp_frame)
                slot_frame.pack(pady=1, padx=3)

                saved = saved_map.get((grp_idx, slot_idx), {})
                init_et = GEAR_EFFECT_DISPLAY.get(saved.get("effect_type", 0), "无效果")
                init_val = saved.get("value", 0.0)

                et_var = tk.StringVar(value=init_et)
                cb = ttk.Combobox(slot_frame, textvariable=et_var, values=GEAR_EFFECT_OPTIONS_DISPLAY,
                                  state="readonly", width=10)
                cb.pack()

                g_idx = grp_idx
                s_idx = slot_idx
                cb.bind("<<ComboboxSelected>>",
                        lambda e, g=g_idx, s=s_idx: self._validate_detail_gear_group(g, s))

                pct_frame = ttk.Frame(slot_frame)
                pct_frame.pack()
                v_var = tk.DoubleVar(value=init_val)
                ttk.Spinbox(pct_frame, from_=0, to=100, increment=0.5, textvariable=v_var, width=5).pack(side=tk.LEFT)
                ttk.Label(pct_frame, text="%", font=("Microsoft YaHei UI", 7)).pack(side=tk.LEFT)

                self.detail_gear_vars.append(
                    {"et": et_var, "val": v_var, "group": grp_idx, "slot": slot_idx})

    def _validate_detail_gear_group(self, group_idx, changed_slot):
        group_slots = [gv for gv in self.detail_gear_vars if gv["group"] == group_idx]
        used_types = {}
        for gv in group_slots:
            et_val = gv["et"].get()
            if et_val != "无效果":
                if et_val in used_types:
                    gv["et"].set("无效果")
                    gv["val"].set(0.0)
                    messagebox.showwarning("词条冲突",
                        f"模块{group_idx+1}中词条类型重复，已自动清除冲突槽位")
                else:
                    used_types[et_val] = True

    def _get_detail_gears(self) -> list:
        return [{"effect_type": GEAR_EFFECT_REVERSE[gv["et"].get()], "value": gv["val"].get(),
                 "group": gv["group"], "slot": gv["slot"]}
                for gv in self.detail_gear_vars if gv["et"].get() != "无效果"]

    def _apply_detail(self, cid, char, v):
        config = self.app.char_config.setdefault(cid, {"override": False})
        config["override"] = True
        config["level"] = v["level"].get()
        config["rarity"] = v["rarity"].get()
        config["affection"] = v["affection"].get()
        # 保存每个技能的独立等级
        skill_levels = {}
        if hasattr(self, '_skill_level_vars'):
            for sid, lv_var in self._skill_level_vars.items():
                try:
                    skill_levels[sid] = lv_var.get()
                except Exception:
                    pass
        config["skill_levels"] = skill_levels
        # 向后兼容：同时保存统一skill_level（取所有技能中的最大值）
        if skill_levels:
            config["skill_level"] = max(skill_levels.values())
        config["mod_tier_hp"] = v["mod_tier_hp"].get()
        config["mod_level_hp"] = v["mod_lv_hp"].get()
        config["mod_tier_atk"] = v["mod_tier_atk"].get()
        config["mod_level_atk"] = v["mod_lv_atk"].get()
        config["mod_tier_def"] = v["mod_tier_def"].get()
        config["mod_level_def"] = v["mod_lv_def"].get()
        config["gear"] = self._get_detail_gears()
        self._refresh_preview(cid)
        self.app._save_char_config()

    def _reset_to_global(self, cid, char):
        if self.app.char_config.get(cid, {}).get("locked"):
            messagebox.showwarning("操作被阻止", f"角色 [{self._get_char_display_name(cid)}] 已锁定，无法重置。\n请先解锁后再操作。")
            return
        # 保留锁定状态
        was_locked = self.app.char_config.get(cid, {}).get("locked", False)
        self.app.char_config[cid] = {"override": False}
        if was_locked:
            self.app.char_config[cid]["locked"] = True
        self._show_detail(cid)
        self.app._save_char_config()

    def _refresh_preview(self, cid):
        try:
            from src.data.stat_calculator import StatCalculator
            from src.config.panel_config import PanelConfig, ModuleConfig
            from src.config.player_config import SchoolLevels

            gv = self.app.global_tab.get_values()
            cfg = self.app.char_config.get(cid, {"override": False})
            char = self.app.data_loader.get_character_by_id(cid)

            panel = PanelConfig(
                character_level=gv["character_level"],
                school_levels=SchoolLevels(**gv["school_levels"]),
                equipment_enabled=True,
                equipment_bonuses=gv["equipment"],
            )

            if cfg.get("override"):
                panel.rarities[cid] = cfg.get("rarity", char.default_rarity)
                panel.affection_levels[cid] = cfg.get("affection", 40)
                panel.character_levels[cid] = cfg.get("level", gv["character_level"])
            else:
                panel.rarities[cid] = gv["default_rarity"]
                panel.affection_levels[cid] = gv["default_affection"]

            # 根据角色default_rarity限制稀有度上限
            max_rarity = get_max_rarity_for(char.default_rarity)
            panel.rarities[cid] = min(panel.rarities[cid], max_rarity)

            # 技能等级上限：稀有度>=9(LR)为15，否则为10
            skill_max = 15 if panel.rarities[cid] >= 9 else 10

            skill_ids = self.app.data_loader.load_character_skills().get(cid, [])
            if cfg.get("override"):
                saved_levels = cfg.get("skill_levels", {})
                if saved_levels:
                    # 使用各技能独立等级
                    panel.skill_levels[cid] = {}
                    for sid in skill_ids:
                        lv = saved_levels.get(sid, saved_levels.get(str(sid), None))
                        if lv is not None:
                            panel.skill_levels[cid][sid] = min(lv, skill_max)
                        else:
                            # 向后兼容：旧配置使用统一skill_level
                            raw_skill_lv = cfg.get("skill_level", 15)
                            panel.skill_levels[cid][sid] = min(raw_skill_lv, skill_max)
                else:
                    # 向后兼容：旧配置使用统一skill_level
                    raw_skill_lv = cfg.get("skill_level", 15)
                    panel.skill_levels[cid] = {sid: min(raw_skill_lv, skill_max) for sid in skill_ids}
            else:
                raw_skill_lv = gv["default_skill_level"]
                panel.skill_levels[cid] = {sid: min(raw_skill_lv, skill_max) for sid in skill_ids}

            tid = get_module_type_ids(char.character_type)
            if cfg.get("override"):
                # 向后兼容: 旧单值 mod_tier/mod_level 作为三模块统一回退
                old_tier = cfg.get("mod_tier", 9)
                old_level = cfg.get("mod_level", 50)
                per_stat_tiers = [
                    cfg.get("mod_tier_hp", old_tier),
                    cfg.get("mod_tier_atk", old_tier),
                    cfg.get("mod_tier_def", old_tier),
                ]
                per_stat_levels = [
                    cfg.get("mod_level_hp", old_level),
                    cfg.get("mod_level_atk", old_level),
                    cfg.get("mod_level_def", old_level),
                ]
                gear_list = cfg.get("gear", [])
                panel.modules[cid] = [ModuleConfig(
                    module_id=mid,
                    tier=per_stat_tiers[grp_idx],
                    level=per_stat_levels[grp_idx],
                    gear_effects=[g for g in gear_list if g.get("group", 0) == grp_idx],
                ) for grp_idx, mid in enumerate(tid)]
            else:
                per_stat_tiers = [
                    gv["default_mod_tier_hp"],
                    gv["default_mod_tier_atk"],
                    gv["default_mod_tier_def"],
                ]
                per_stat_levels = [
                    gv["default_mod_level_hp"],
                    gv["default_mod_level_atk"],
                    gv["default_mod_level_def"],
                ]
                panel.modules[cid] = [ModuleConfig(
                    module_id=mid,
                    tier=per_stat_tiers[grp_idx],
                    level=per_stat_levels[grp_idx],
                    gear_effects=[g for g in gv["default_gear"] if g.get("group", 0) == grp_idx],
                ) for grp_idx, mid in enumerate(tid)]

            lerp_data = self.app.data_loader.load_level_lerp_data()
            sc = StatCalculator(lerp_data, data_loader=self.app.data_loader)
            player_config = panel.get_player_config()
            cc = panel.get_character_config(cid, char.default_rarity)
            stats = sc.calculate_stats(cc, player_config)

            r_name = RARITY_NAMES.get(panel.rarities[cid], "")
            effective_level = panel.character_levels.get(cid, gv["character_level"])
            self.preview_labels["level"].config(text=str(effective_level))
            self.preview_labels["rarity"].config(text=f"{panel.rarities[cid]} ({r_name})")
            self.preview_labels["affection"].config(text=str(panel.affection_levels[cid]))
            self.preview_labels["hp"].config(text=str(int(stats.hp)))
            self.preview_labels["attack"].config(text=str(int(stats.attack)))
            self.preview_labels["defense"].config(text=str(int(stats.defense)))
            self.preview_labels["crit_rate"].config(text=f"{(stats.critical_rate * 100):.2f}")
            self.preview_labels["crit_dmg"].config(text=f"{(stats.critical_damage * 100):.2f}")
            self.preview_labels["speed"].config(text=str(int(stats.speed)))
            self.preview_labels["adv_dmg"].config(text=f"{(stats.advantage_damage * 100):.2f}")
            self.preview_labels["ap"].config(text=str(stats.initial_ap))
            self.preview_labels["pp"].config(text=str(stats.initial_pp))

        except Exception as e:
            import traceback
            traceback.print_exc()
            for lbl in self.preview_labels.values():
                lbl.config(text="ERR")

    def _reset_selected(self):
        sel = self.char_listbox.curselection()
        if not sel:
            return
        cid = self._filtered_char_ids[sel[0]]
        if self.app.char_config.get(cid, {}).get("locked"):
            messagebox.showwarning("操作被阻止", f"角色 [{self._get_char_display_name(cid)}] 已锁定，无法重置。\n请先解锁后再操作。")
            return
        if not messagebox.askyesno("确认重置",
                f"确定要重置角色 [{self._get_char_display_name(cid)}] 的配置吗？\n\n"
                "该操作将清除该角色的所有自定义参数\n"
                "（稀有度、好感度、技能等级、模块等级、模块词条等），\n"
                "恢复为全局默认参数。此操作不可撤销。",
                icon="warning"):
            return
        if cid in self.char_override_vars:
            del self.char_override_vars[cid]
        # 保留锁定状态
        was_locked = self.app.char_config.get(cid, {}).get("locked", False)
        self.app.char_config[cid] = {"override": False}
        if was_locked:
            self.app.char_config[cid]["locked"] = True
        self._show_detail(cid)
        self.app._save_char_config()

    def _reset_all(self):
        locked_cids = [cid for cid in self.app.char_ids if self.app.char_config.get(cid, {}).get("locked")]
        if locked_cids:
            locked_names = "、".join(self._get_char_display_name(cid) for cid in locked_cids[:5])
            if len(locked_cids) > 5:
                locked_names += f" 等{len(locked_cids)}个角色"
            suffix = f"\n\n以下角色已锁定，将不会被重置：\n{locked_names}"
        else:
            suffix = ""
        if not messagebox.askyesno("确认全部重置",
                f"确定要重置所有角色的配置吗？\n\n"
                "该操作将清除所有角色的自定义参数\n"
                "（稀有度、好感度、技能等级、模块等级、模块词条等），\n"
                "恢复为全局默认参数。此操作不可撤销。" + suffix,
                icon="warning"):
            return
        for cid in self.app.char_ids:
            if self.app.char_config.get(cid, {}).get("locked"):
                continue
            if cid in self.char_override_vars:
                del self.char_override_vars[cid]
            self.app.char_config[cid] = {"override": False}
        messagebox.showinfo("重置", "所有未锁定角色已恢复为全局默认参数")
        if self._filtered_char_ids:
            self._show_detail(self._filtered_char_ids[0])
        self._refresh_list()
        self.app._save_char_config()

    def _apply_global_all(self):
        locked_cids = [cid for cid in self.app.char_ids if self.app.char_config.get(cid, {}).get("locked")]
        if locked_cids:
            locked_names = "、".join(self._get_char_display_name(cid) for cid in locked_cids[:5])
            if len(locked_cids) > 5:
                locked_names += f" 等{len(locked_cids)}个角色"
            suffix = f"\n\n以下角色已锁定，将不会被应用全局参数：\n{locked_names}"
        else:
            suffix = ""
        if not messagebox.askyesno("确认全部应用全局",
                f"确定要将所有角色应用全局默认参数吗？\n\n"
                "该操作将清除所有角色的自定义参数\n"
                "（稀有度、好感度、技能等级、模块等级、模块词条等），\n"
                "统一使用全局默认参数。此操作不可撤销。" + suffix,
                icon="warning"):
            return
        for cid in self.app.char_ids:
            if self.app.char_config.get(cid, {}).get("locked"):
                continue
            if cid in self.char_override_vars:
                del self.char_override_vars[cid]
            self.app.char_config[cid] = {"override": False}
        messagebox.showinfo("应用", "所有未锁定角色已应用全局默认参数")
        if self._filtered_char_ids:
            self._show_detail(self._filtered_char_ids[0])
        self._refresh_list()
        self.app._save_char_config()

    def _get_char_display_name(self, cid):
        """获取角色的显示名称"""
        char = self.app.data_loader.get_character_by_id(cid)
        if char:
            return self.app.format_char_name(char)
        return str(cid)

    def _toggle_lock(self, cid):
        """切换角色的锁定状态"""
        cfg = self.app.char_config.setdefault(cid, {"override": False})
        new_locked = not cfg.get("locked", False)
        cfg["locked"] = new_locked
        self.app._save_char_config()
        # 刷新详情页以更新锁定按钮状态
        self._show_detail(cid)
        # 刷新列表/网格视图以更新锁定标识
        self._refresh_list()

    def _create_tooltip(self, widget, text):
        """为控件创建简单的悬浮提示"""
        def _show(event):
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
            s = self.app._get_scheme()
            label = tk.Label(tooltip, text=text, bg=s["surface"], fg=s["fg"],
                             relief="solid", borderwidth=1,
                             font=("Microsoft YaHei UI", 9), padx=4, pady=2)
            label.pack()
            widget._tooltip = tooltip

        def _hide(event):
            tooltip = getattr(widget, '_tooltip', None)
            if tooltip:
                tooltip.destroy()
                widget._tooltip = None

        widget.bind("<Enter>", _show)
        widget.bind("<Leave>", _hide)

    def get_char_config(self, cid) -> Dict[str, Any]:
        cfg = self.app.char_config.get(cid, {"override": False})
        if not cfg.get("override"):
            return {"override": False}
        return {
            "override": True,
            "level": cfg.get("level", self.app.global_tab.var_level.get()),
            "rarity": cfg.get("rarity", 14),
            "affection": cfg.get("affection", 40),
            "skill_level": cfg.get("skill_level", 15),
            "skill_levels": cfg.get("skill_levels", {}),
            # 向后兼容: 旧单值 mod_tier/mod_level 作为三模块统一回退
            "mod_tier_hp": cfg.get("mod_tier_hp", cfg.get("mod_tier", 9)),
            "mod_tier_atk": cfg.get("mod_tier_atk", cfg.get("mod_tier", 9)),
            "mod_tier_def": cfg.get("mod_tier_def", cfg.get("mod_tier", 9)),
            "mod_level_hp": cfg.get("mod_level_hp", cfg.get("mod_level", 50)),
            "mod_level_atk": cfg.get("mod_level_atk", cfg.get("mod_level", 50)),
            "mod_level_def": cfg.get("mod_level_def", cfg.get("mod_level", 50)),
            "gear": cfg.get("gear", []),
        }


