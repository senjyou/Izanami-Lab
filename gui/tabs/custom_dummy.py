# -*- coding: utf-8 -*-
"""自定义木桩 Tab（创建/编辑/删除自定义木桩配置）。

从 gui_app.py 抽取，通过 self.app 访问主类。
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional

from src.entities_v2.custom_dummy import (
    CustomDummyConfig, CustomASConfig, CustomPSConfig, CustomEffectConfig,
    EFFECT_TYPE_DISPLAY, EFFECT_DISPLAY_REVERSE, EFFECT_FIELD_FLAGS,
    STATUS_TYPE_DISPLAY, STATUS_DISPLAY_REVERSE,
    DURATION_TYPE_DISPLAY, DURATION_DISPLAY_REVERSE,
    EFFECT_CATEGORIES,
    MAX_DUMMY_REVIVES,
    dummy_revive_plan_text,
    validate_dummy_config,
    filter_trigger_timings,
)
from src.entities_v2.dummy_presets import builtin_presets

from gui.constants import (
    CHAR_TYPE_NAMES,
    COOLDOWN_TIMING_NAMES,
    ELEMENT_NAMES,
    POSITION_TYPE_NAMES,
    ROLE_TYPE_NAMES,
    SHIELD_TYPE_NAMES,
    SHIELD_TYPE_REV,
    TARGET_PRIORITY_NAMES,
    TARGET_RANGE_NAMES,
    TARGET_TYPE_NAMES,
    TRIGGER_TIMING_OPTIONS,
    _DARK_ACCENT,
    _DARK_FG,
    _DARK_INPUT_BG,
)


class CustomDummyTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._dummy_index = 0
        self._registered_ids: List[int] = []
        self._as_rows: List[Dict[str, Any]] = []
        self._ps_rows: List[Dict[str, Any]] = []
        self._build()

    def _build(self):
        """构建界面：整体套 Canvas + 纵向（必要时横向）滚动条。

        低分辨率（如 1366x768 / 缩放 125%）下页面高度远超窗口，没有滚动条会
        导致「注册/更新木桩」按钮被挤出可视区。与战术演习/编队页同口径：
        scroll_frame 内全部控件按原 grid 布局，外层 Canvas 负责滚动。

        额外处理（本页控件列数多，窄屏会横向溢出）：
        - 横向滚动条仅在内容自然宽度 > 可视宽度时自动出现（`_sync_hscrollbar`）；
        - 两段长「说明」文字的 wraplength 跟随可视宽度，避免被裁切；
        - 鼠标滚轮仅在指针进入本 Tab 时绑定，离开即卸载（不抢其他 Tab 的滚轮）。
        """
        scheme = self.app._get_scheme()

        canvas = tk.Canvas(self, bg=scheme["bg"], highlightthickness=0)
        vbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        hbar = ttk.Scrollbar(self, orient="horizontal", command=canvas.xview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>",
                          lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        self._scroll_window_id = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        # 横向滚动条默认不占位（低分辨率下纵向像素很宝贵），需要时才 pack
        self._scroll_canvas = canvas
        self._scroll_vbar = vbar
        self._scroll_hbar = hbar
        self._hbar_visible = False

        def _bind_canvas_width(event):
            # 内容自然宽度更大时不压缩（否则列会被裁掉），改为允许横向滚动
            natural = scroll_frame.winfo_reqwidth()
            width = max(event.width, natural)
            canvas.itemconfig(self._scroll_window_id, width=width)
            self._apply_wraplength(event.width)
            self.after_idle(self._sync_scrollbars)

        canvas.bind("<Configure>", _bind_canvas_width)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self._mousewheel_handler = _on_mousewheel
        # 绑定到整个 Tab 而不是 Canvas：控件铺满可视区时指针很难只停在 Canvas 上
        self.bind("<Enter>", self._on_scroll_enter)
        self.bind("<Leave>", self._on_scroll_leave)
        self._scroll_frame = scroll_frame

        f = scroll_frame

        row = 0

        ttk.Label(f, text="自定义木桩管理", font=("Microsoft YaHei UI", 12, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 5), padx=10)
        row += 1

        reg_lf = ttk.LabelFrame(f, text="已注册木桩")
        reg_lf.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=2)
        self._dummy_listbox = tk.Listbox(reg_lf, height=4,
                                         bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                         selectbackground=_DARK_ACCENT, selectforeground="#1e1e2e",
                                         borderwidth=0, highlightthickness=0,
                                         font=("Microsoft YaHei UI", 9))
        self._dummy_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._dummy_listbox.bind("<<ListboxSelect>>", self._on_select_dummy)
        btn_f = ttk.Frame(reg_lf)
        btn_f.pack(side=tk.RIGHT, padx=5, pady=5)
        ttk.Button(btn_f, text="编辑", command=self._edit_selected).pack(fill="x", pady=2)
        ttk.Button(btn_f, text="复制", command=self._duplicate_selected).pack(fill="x", pady=2)
        ttk.Button(btn_f, text="删除", command=self._delete_selected).pack(fill="x", pady=2)
        ttk.Button(btn_f, text="清空", command=self._clear_all).pack(fill="x", pady=2)
        row += 1

        ttk.Label(f, text="木桩属性编辑", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 5), padx=10)
        row += 1

        basic_lf = ttk.LabelFrame(f, text="基础属性")
        basic_lf.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=2)

        self._var_name = tk.StringVar(value="木桩")
        self._var_element = tk.StringVar(value=ELEMENT_NAMES[1])
        self._var_char_type = tk.StringVar(value=CHAR_TYPE_NAMES[1])
        self._var_position_type = tk.StringVar(value=POSITION_TYPE_NAMES[3])
        self._var_role_type = tk.StringVar(value=ROLE_TYPE_NAMES[1])
        self._var_hp = tk.IntVar(value=10000)
        self._var_atk = tk.IntVar(value=1000)
        self._var_def = tk.IntVar(value=500)
        self._var_crit_rate = tk.DoubleVar(value=0.15)
        self._var_crit_dmg = tk.DoubleVar(value=1.5)
        self._var_spd = tk.IntVar(value=500)
        self._var_adv_dmg = tk.DoubleVar(value=0.0)
        self._var_ap = tk.IntVar(value=5)
        self._var_pp = tk.IntVar(value=5)
        self._var_shield_type = tk.StringVar(value="无")
        self._var_shield_value = tk.IntVar(value=0)
        # ── v2 新增字段 ──
        self._var_level = tk.IntVar(value=280)
        self._var_sub_element = tk.StringVar(value="无")
        self._var_init_ep = tk.DoubleVar(value=0.0)
        self._var_max_ep = tk.IntVar(value=0)
        self._var_note = tk.StringVar(value="")
        self._var_extra_skills = tk.StringVar(value="")
        self._var_preset = tk.StringVar(value="")
        # ── v3 新增字段：木桩复活（机制参照战术演习 boss 换阶段）──
        self._var_revive_count = tk.IntVar(value=0)
        self._var_revive_mult_start = tk.DoubleVar(value=1.0)
        self._var_revive_mult_step = tk.DoubleVar(value=0.0)
        self._var_revive_preview = tk.StringVar(value="")

        r = 0
        # 第一列：名称、属性、类型、定位、位置、永久盾类型
        ttk.Label(basic_lf, text="名称:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_name, width=20).grid(row=r, column=1, padx=5, sticky="w")
        # 第二列：HP、ATK、DEF、暴击率、速度、永久盾值
        ttk.Label(basic_lf, text="HP:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_hp, width=10).grid(row=r, column=3, padx=5, sticky="w")
        # 第三列：暴击伤害、有利加成、AP、PP
        ttk.Label(basic_lf, text="暴击伤害:").grid(row=r, column=4, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_crit_dmg, width=10).grid(row=r, column=5, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="属性:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        cb_elem = ttk.Combobox(basic_lf, textvariable=self._var_element,
                                values=list(ELEMENT_NAMES.values()), state="readonly", width=8)
        cb_elem.grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="ATK:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_atk, width=10).grid(row=r, column=3, padx=5, sticky="w")
        ttk.Label(basic_lf, text="有利加成:").grid(row=r, column=4, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_adv_dmg, width=10).grid(row=r, column=5, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="类型:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        cb_ctype = ttk.Combobox(basic_lf, textvariable=self._var_char_type,
                                 values=list(CHAR_TYPE_NAMES.values()), state="readonly", width=8)
        cb_ctype.grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="DEF:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_def, width=10).grid(row=r, column=3, padx=5, sticky="w")
        ttk.Label(basic_lf, text="AP:").grid(row=r, column=4, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_ap, width=10).grid(row=r, column=5, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="定位:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        cb_role = ttk.Combobox(basic_lf, textvariable=self._var_role_type,
                                values=list(ROLE_TYPE_NAMES.values()), state="readonly", width=8)
        cb_role.grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="暴击率:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_crit_rate, width=10).grid(row=r, column=3, padx=5, sticky="w")
        ttk.Label(basic_lf, text="PP:").grid(row=r, column=4, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_pp, width=10).grid(row=r, column=5, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="位置:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        cb_position = ttk.Combobox(basic_lf, textvariable=self._var_position_type,
                                     values=list(POSITION_TYPE_NAMES.values()), state="readonly", width=8)
        cb_position.grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="速度:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_spd, width=10).grid(row=r, column=3, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="永久盾类型:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        cb_shield = ttk.Combobox(basic_lf, textvariable=self._var_shield_type,
                                  values=list(SHIELD_TYPE_NAMES.values()), state="readonly", width=10)
        cb_shield.grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="永久盾值:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_shield_value, width=10).grid(row=r, column=3, padx=5, sticky="w")
        r += 1

        # ── v2 新增：等级 / 副属性 / EP ──
        ttk.Label(basic_lf, text="等级(仅记录):").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_level, width=10).grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="副属性:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        cb_sub = ttk.Combobox(basic_lf, textvariable=self._var_sub_element,
                               values=["无"] + list(ELEMENT_NAMES.values()), state="readonly", width=8)
        cb_sub.grid(row=r, column=3, padx=5, sticky="w")
        ttk.Label(basic_lf, text="初始EP:").grid(row=r, column=4, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_init_ep, width=10).grid(row=r, column=5, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="EP上限:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_max_ep, width=10).grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="追加技能ID:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_extra_skills, width=16).grid(
            row=r, column=3, columnspan=3, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="备注:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_note, width=64).grid(
            row=r, column=1, columnspan=5, padx=5, sticky="w")
        r += 1

        # ── v3：木桩复活（HP 归零后满血复活，机制同战术演习 boss 换阶段）──
        ttk.Label(basic_lf, text="复活次数:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        ttk.Spinbox(basic_lf, textvariable=self._var_revive_count, from_=0, to=MAX_DUMMY_REVIVES,
                    width=8).grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="首次倍率:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_revive_mult_start, width=10).grid(
            row=r, column=3, padx=5, sticky="w")
        ttk.Label(basic_lf, text="每次增量:").grid(row=r, column=4, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_revive_mult_step, width=10).grid(
            row=r, column=5, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="复活倍率预览:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        ttk.Label(basic_lf, textvariable=self._var_revive_preview, foreground="#9cc4ff").grid(
            row=r, column=1, columnspan=5, padx=5, sticky="w", pady=(0, 2))
        r += 1

        self._revive_hint_label = ttk.Label(
            basic_lf,
            text=("说明：复活机制同战术演习换阶段——血量归零后满血复活、清除非回忆卡buff/debuff、"
                  "AP/PP/EP保持不变；倍率作用于 HP/ATK/DEF/SPD（暴击率不变），"
                  "基准是第一条命的进场属性。1.0+0/次 = 完全不膨胀（照搬第一条命）。"),
            foreground="#888888", wraplength=980, justify="left")
        self._revive_hint_label.grid(
            row=r, column=0, columnspan=6, padx=5, pady=(0, 4), sticky="w")
        r += 1

        # ── 预设 ──
        ttk.Label(basic_lf, text="预设:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        self._preset_combo = ttk.Combobox(basic_lf, textvariable=self._var_preset,
                                          values=[], state="readonly", width=28)
        self._preset_combo.grid(row=r, column=1, columnspan=2, padx=5, sticky="w")
        ttk.Button(basic_lf, text="应用预设", command=self._apply_preset, width=10).grid(
            row=r, column=3, padx=5, sticky="w")
        self._refresh_presets()
        r += 1

        self._calc_hint_label = ttk.Label(
            basic_lf,
            text="说明：暴击伤害填倍率（1.5=无额外）；有利加成填额外值（0.255=3条彩S=克制1.505）；EP上限0=按EX技能自动推断",
            foreground="#888888", wraplength=980, justify="left")
        self._calc_hint_label.grid(
            row=r, column=0, columnspan=6, padx=5, pady=(0, 4), sticky="w")
        r += 1

        row += 1

        self._as_frame = ttk.LabelFrame(f, text="AS技能 (0~4个)")
        self._as_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
        self._as_container = ttk.Frame(self._as_frame)
        self._as_container.pack(fill="x", padx=5, pady=5)
        ttk.Button(self._as_frame, text="+ 添加AS技能", command=self._add_as_row).pack(anchor="w", padx=5, pady=(0, 5))
        row += 1

        self._ps_frame = ttk.LabelFrame(f, text="PS技能 (0~4个)")
        self._ps_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
        self._ps_container = ttk.Frame(self._ps_frame)
        self._ps_container.pack(fill="x", padx=5, pady=5)
        ttk.Button(self._ps_frame, text="+ 添加PS技能", command=self._add_ps_row).pack(anchor="w", padx=5, pady=(0, 5))
        row += 1

        btn_row = ttk.Frame(f)
        btn_row.grid(row=row, column=0, columnspan=2, pady=10, padx=10, sticky="w")
        ttk.Button(btn_row, text="注册/更新木桩", command=self._register_dummy, width=18).pack(side=tk.LEFT, padx=5)
        row += 1

        # 复活倍率预览随三个输入框实时刷新
        for _var in (self._var_revive_count, self._var_revive_mult_start,
                     self._var_revive_mult_step):
            _var.trace_add("write", lambda *_: self._refresh_revive_preview())
        self._refresh_revive_preview()

        self._refresh_list()

    def _sync_hscrollbar(self) -> None:
        """内容自然宽度 > 可视宽度时显示横向滚动条，否则收起（省纵向像素）。"""
        canvas = getattr(self, "_scroll_canvas", None)
        if canvas is None:
            return
        need = canvas.bbox("all")
        if not need:
            return
        content_w = need[2] - need[0]
        view_w = canvas.winfo_width()
        wanted = content_w > view_w + 1
        if wanted and not getattr(self, "_hbar_visible", False):
            # 先让纵向滚动条在右侧；横向条占据底部
            self._scroll_hbar.pack(side=tk.BOTTOM, fill=tk.X, before=self._scroll_vbar)
            self._hbar_visible = True
        elif not wanted and getattr(self, "_hbar_visible", False):
            self._scroll_hbar.pack_forget()
            self._hbar_visible = False
            canvas.xview_moveto(0.0)

    def _sync_scrollbars(self) -> None:
        """按当前可视尺寸刷新滚动条显隐（横向条按需出现，纵向条常驻）。"""
        self._sync_hscrollbar()

    # ── 滚轮绑定（指针进出本页时装卸，避免抢其他 Tab 的滚轮）──────────

    def _on_scroll_enter(self, _event=None) -> None:
        """指针进入本页 → 全局绑定滚轮（控件铺满可视区，不能只绑 Canvas）。"""
        handler = getattr(self, "_mousewheel_handler", None)
        if handler is None:
            return
        self.bind_all("<MouseWheel>", handler)

    def _on_scroll_leave(self, event=None) -> None:
        """指针真正离开本页 → 解绑滚轮。

        指针移到本页子控件时 Tk 发的是 <Leave>(NotifyInferior)，这种「离开」
        必须忽略，否则鼠标一放到输入框上滚轮就失效。
        """
        if getattr(event, "detail", "") == "NotifyInferior":
            return
        self.unbind_all("<MouseWheel>")

    def _refresh_scroll_theme(self) -> None:
        """主题切换后刷新滚动 Canvas 底色（Canvas 是原生 tk 组件，吃不到 ttk style）。"""
        canvas = getattr(self, "_scroll_canvas", None)
        if canvas is None:
            return
        try:
            canvas.configure(bg=self.app._get_scheme()["bg"])
        except Exception:
            pass


    def _apply_wraplength(self, view_width: int) -> None:
        """两段长说明文字的换行宽度跟随可视宽度，避免在窄屏被横向裁切。"""
        wrap = max(320, int(view_width) - 60)
        for attr in ("_revive_hint_label", "_calc_hint_label"):
            label = getattr(self, attr, None)
            if label is not None:
                label.configure(wraplength=wrap)

    def _refresh_revive_preview(self):
        """刷新「复活倍率预览」标签（解析失败时显示占位，不弹窗）。"""
        try:
            count = int(self._var_revive_count.get())
            start = float(self._var_revive_mult_start.get())
            step = float(self._var_revive_mult_step.get())
        except (tk.TclError, ValueError):
            self._var_revive_preview.set("（输入无效）")
            return
        text = dummy_revive_plan_text(count, start, step)
        if count > 0 and abs(start) < 1e-9 and abs(step) < 1e-9:
            text += "  ⚠ 倍率为 0 会把 HP 压到 1，请确认口径"
        self._var_revive_preview.set(text)

    def _add_as_row(self) -> Optional[Dict[str, Any]]:
        if len(self._as_rows) >= 4:
            messagebox.showwarning("上限", "最多添加4个AS技能")
            return None
        row_data = self._make_skill_row(self._as_container, self._as_rows, is_ps=False)
        if row_data:
            self._as_rows.append(row_data)
        return row_data

    def _add_ps_row(self) -> Optional[Dict[str, Any]]:
        if len(self._ps_rows) >= 4:
            messagebox.showwarning("上限", "最多添加4个PS技能")
            return None
        row_data = self._make_skill_row(self._ps_container, self._ps_rows, is_ps=True)
        if row_data:
            self._ps_rows.append(row_data)
        return row_data

    def _make_skill_row(self, parent: ttk.Frame, rows: list, is_ps: bool = False) -> Optional[Dict[str, Any]]:
        idx = len(rows)
        prefix = "PS" if is_ps else "AS"
        frame = ttk.LabelFrame(parent, text=f"{prefix}[{idx + 1}]")
        frame.pack(fill="x", pady=2)

        row_data: Dict[str, Any] = {"frame": frame, "effects": []}

        # ── 第一行：名称 + 消耗 + 冷却 + 删除 ──
        vars_row = ttk.Frame(frame)
        vars_row.pack(fill="x", padx=3, pady=2)

        ttk.Label(vars_row, text="名称:").pack(side=tk.LEFT)
        row_data["name"] = tk.StringVar(value=f"自定义{prefix}")
        ttk.Entry(vars_row, textvariable=row_data["name"], width=12).pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(vars_row, text="消耗:").pack(side=tk.LEFT)
        row_data["resource_cost"] = tk.IntVar(value=1)
        ttk.Entry(vars_row, textvariable=row_data["resource_cost"], width=4).pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(vars_row, text="冷却:").pack(side=tk.LEFT)
        row_data["cooldown"] = tk.IntVar(value=0)
        ttk.Entry(vars_row, textvariable=row_data["cooldown"], width=4).pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(vars_row, text="冷却计时:").pack(side=tk.LEFT)
        row_data["cooldown_timing"] = tk.StringVar(value=COOLDOWN_TIMING_NAMES[1])
        ttk.Combobox(vars_row, textvariable=row_data["cooldown_timing"],
                      values=list(COOLDOWN_TIMING_NAMES.values()), state="readonly", width=8).pack(
            side=tk.LEFT, padx=(2, 8))

        ttk.Button(vars_row, text="✕", width=2,
                   command=lambda: (frame.destroy(), rows.remove(row_data))).pack(side=tk.RIGHT, padx=3)

        # ── 第二行：目标设置 ──
        target_row = ttk.Frame(frame)
        target_row.pack(fill="x", padx=3, pady=2)

        ttk.Label(target_row, text="目标类型:").pack(side=tk.LEFT)
        row_data["target_type"] = tk.StringVar(value=TARGET_TYPE_NAMES[3])
        ttk.Combobox(target_row, textvariable=row_data["target_type"],
                      values=list(TARGET_TYPE_NAMES.values()), state="readonly", width=10).pack(
            side=tk.LEFT, padx=(2, 8))

        ttk.Label(target_row, text="范围:").pack(side=tk.LEFT)
        row_data["target_range"] = tk.StringVar(value=TARGET_RANGE_NAMES[1])
        ttk.Combobox(target_row, textvariable=row_data["target_range"],
                      values=list(TARGET_RANGE_NAMES.values()), state="readonly", width=8).pack(
            side=tk.LEFT, padx=(2, 8))

        ttk.Label(target_row, text="优先级:").pack(side=tk.LEFT)
        row_data["target_priority"] = tk.StringVar(value=TARGET_PRIORITY_NAMES[0])
        ttk.Combobox(target_row, textvariable=row_data["target_priority"],
                      values=list(TARGET_PRIORITY_NAMES.values()), state="readonly", width=10).pack(
            side=tk.LEFT, padx=(2, 8))

        # ── PS触发时机 ──
        if is_ps:
            ps_extra = ttk.Frame(frame)
            ps_extra.pack(fill="x", padx=3, pady=2)
            ttk.Label(ps_extra, text="触发时机:").pack(side=tk.LEFT)
            _trig_opts = filter_trigger_timings(TRIGGER_TIMING_OPTIONS)
            row_data["trigger_timing"] = tk.StringVar(value=_trig_opts[0][0])
            cb = ttk.Combobox(ps_extra, textvariable=row_data["trigger_timing"],
                              values=[t[0] for t in _trig_opts], state="readonly", width=16)
            cb.pack(side=tk.LEFT, padx=(2, 8))

        # ── 效果列表区域 ──
        effects_lf = ttk.LabelFrame(frame, text="效果列表")
        effects_lf.pack(fill="x", padx=3, pady=2)
        row_data["effects_container"] = effects_lf
        row_data["effects_frame"] = ttk.Frame(effects_lf)
        row_data["effects_frame"].pack(fill="x", padx=2, pady=2)

        ttk.Button(effects_lf, text="+ 添加效果", width=10,
                   command=lambda: self._add_effect_row(row_data)).pack(anchor="w", padx=5, pady=(0, 3))

        # 默认添加一个伤害效果
        self._add_effect_row(row_data)

        return row_data

    def _add_effect_row(self, skill_row_data: Dict[str, Any]):
        """向技能行添加一个效果配置行"""
        effects_list = skill_row_data["effects"]
        effects_frame = skill_row_data["effects_frame"]
        idx = len(effects_list)

        ef_frame = ttk.Frame(effects_frame, relief="groove", borderwidth=1)
        ef_frame.pack(fill="x", pady=1, padx=2)

        ef_data: Dict[str, Any] = {"frame": ef_frame}

        # 第一行：效果类型 + 数值 + 段数 + 删除
        row1 = ttk.Frame(ef_frame)
        row1.pack(fill="x", padx=2, pady=1)

        ttk.Label(row1, text="类型:").pack(side=tk.LEFT)
        # 构建分类显示的效果选项列表
        effect_options = []
        for cat, types in EFFECT_CATEGORIES.items():
            for t in types:
                effect_options.append(f"[{cat}] {EFFECT_TYPE_DISPLAY[t]}")
        ef_data["effect_type_display"] = tk.StringVar(value=f"[伤害] {EFFECT_TYPE_DISPLAY['damage']}")
        cb_type = ttk.Combobox(row1, textvariable=ef_data["effect_type_display"],
                                values=effect_options, state="readonly", width=16)
        cb_type.pack(side=tk.LEFT, padx=(2, 4))

        # 数值
        ef_data["value_label"] = ttk.Label(row1, text="威力%:")
        ef_data["value_label"].pack(side=tk.LEFT)
        ef_data["value"] = tk.DoubleVar(value=100.0)
        ef_data["value_entry"] = ttk.Entry(row1, textvariable=ef_data["value"], width=6)
        ef_data["value_entry"].pack(side=tk.LEFT, padx=(2, 4))

        # 段数（仅damage显示）
        ef_data["hit_count_label"] = ttk.Label(row1, text="段数:")
        ef_data["hit_count_label"].pack(side=tk.LEFT)
        ef_data["hit_count"] = tk.IntVar(value=1)
        ef_data["hit_count_entry"] = ttk.Entry(row1, textvariable=ef_data["hit_count"], width=3)
        ef_data["hit_count_entry"].pack(side=tk.LEFT, padx=(2, 4))

        # 删除按钮
        ttk.Button(row1, text="✕", width=2,
                   command=lambda: (ef_frame.destroy(), effects_list.remove(ef_data))).pack(side=tk.RIGHT, padx=2)

        # 第二行：持续时间 + 持续类型 + 状态名（动态显示）
        row2 = ttk.Frame(ef_frame)
        row2.pack(fill="x", padx=2, pady=1)

        ef_data["duration_label"] = ttk.Label(row2, text="持续:")
        ef_data["duration_label"].pack(side=tk.LEFT)
        ef_data["duration"] = tk.IntVar(value=2)
        ef_data["duration_entry"] = ttk.Entry(row2, textvariable=ef_data["duration"], width=3)
        ef_data["duration_entry"].pack(side=tk.LEFT, padx=(2, 4))

        ef_data["duration_type_label"] = ttk.Label(row2, text="计时:")
        ef_data["duration_type_label"].pack(side=tk.LEFT)
        ef_data["duration_type_display"] = tk.StringVar(value=DURATION_TYPE_DISPLAY["turn"])
        ef_data["duration_type_cb"] = ttk.Combobox(row2, textvariable=ef_data["duration_type_display"],
                                                     values=list(DURATION_TYPE_DISPLAY.values()),
                                                     state="readonly", width=5)
        ef_data["duration_type_cb"].pack(side=tk.LEFT, padx=(2, 4))

        ef_data["status_label"] = ttk.Label(row2, text="状态:")
        ef_data["status_label"].pack(side=tk.LEFT)
        ef_data["status_name_display"] = tk.StringVar(value=STATUS_TYPE_DISPLAY["stun"])
        ef_data["status_cb"] = ttk.Combobox(row2, textvariable=ef_data["status_name_display"],
                                              values=list(STATUS_TYPE_DISPLAY.values()),
                                              state="readonly", width=6)
        ef_data["status_cb"].pack(side=tk.LEFT, padx=(2, 4))

        # 效果类型变化时更新字段可见性
        def _on_type_change(*args):
            display_val = ef_data["effect_type_display"].get()
            # 从显示名提取效果类型key
            effect_key = None
            for k, v in EFFECT_TYPE_DISPLAY.items():
                if display_val.endswith(v):
                    effect_key = k
                    break
            if not effect_key:
                return
            flags = EFFECT_FIELD_FLAGS.get(effect_key, {})

            # 数值字段
            if flags.get("value", False):
                ef_data["value_label"].pack(side=tk.LEFT)
                ef_data["value_entry"].pack(side=tk.LEFT, padx=(2, 4))
                # 更新数值标签
                if effect_key == "damage":
                    ef_data["value_label"].config(text="威力%:")
                elif effect_key in ("add_ap", "remove_ap"):
                    ef_data["value_label"].config(text="数值:")
                elif effect_key == "add_ep":
                    ef_data["value_label"].config(text="EP值:")
                elif effect_key == "shield":
                    ef_data["value_label"].config(text="盾值:")
                elif effect_key == "hp_ratio_damage":
                    ef_data["value_label"].config(text="HP%:")
                else:
                    ef_data["value_label"].config(text="数值%:")
            else:
                ef_data["value_label"].pack_forget()
                ef_data["value_entry"].pack_forget()

            # 段数字段
            if flags.get("hit_count", False):
                ef_data["hit_count_label"].pack(side=tk.LEFT)
                ef_data["hit_count_entry"].pack(side=tk.LEFT, padx=(2, 4))
            else:
                ef_data["hit_count_label"].pack_forget()
                ef_data["hit_count_entry"].pack_forget()

            # 持续时间字段
            if flags.get("duration", False):
                ef_data["duration_label"].pack(side=tk.LEFT)
                ef_data["duration_entry"].pack(side=tk.LEFT, padx=(2, 4))
            else:
                ef_data["duration_label"].pack_forget()
                ef_data["duration_entry"].pack_forget()

            # 持续类型字段
            if flags.get("duration_type", False):
                ef_data["duration_type_label"].pack(side=tk.LEFT)
                ef_data["duration_type_cb"].pack(side=tk.LEFT, padx=(2, 4))
                # 状态异常默认用action计时
                if effect_key == "add_status":
                    ef_data["duration_type_display"].set(DURATION_TYPE_DISPLAY["action"])
            else:
                ef_data["duration_type_label"].pack_forget()
                ef_data["duration_type_cb"].pack_forget()

            # 状态名字段
            if flags.get("status_name", False):
                ef_data["status_label"].pack(side=tk.LEFT)
                ef_data["status_cb"].pack(side=tk.LEFT, padx=(2, 4))
            else:
                ef_data["status_label"].pack_forget()
                ef_data["status_cb"].pack_forget()

        ef_data["effect_type_display"].trace_add("write", _on_type_change)
        # 初始化可见性
        _on_type_change()

        effects_list.append(ef_data)

    def _next_free_index(self) -> int:
        """返回一个未被占用的木桩序号（负ID = -(index+1)）。

        旧实现用递增计数器，删除后再新增可能与既有ID冲突；
        v2 改为「扫描已注册ID取最小空位」，保证 ID 稳定且不重复。
        """
        used = {abs(cid) - 1 for cid in self.app.data_loader.get_custom_dummy_ids()}
        idx = 0
        while idx in used:
            idx += 1
        return idx

    def _refresh_presets(self):
        try:
            presets = builtin_presets(self.app.data_loader)
        except Exception:
            presets = builtin_presets(None)
        self._preset_map = {p.label: p.key for p in presets}
        self._preset_combo.configure(values=[p.label for p in presets])
        if presets and not self._var_preset.get():
            self._var_preset.set(presets[0].label)

    def _apply_preset(self):
        label = self._var_preset.get()
        key = getattr(self, "_preset_map", {}).get(label)
        if not key:
            messagebox.showwarning("未选择预设", "请先选择一个预设")
            return
        try:
            preset = next(p for p in builtin_presets(self.app.data_loader) if p.key == key)
            cfg = preset.build()
        except Exception as exc:  # noqa: BLE001 - 预设构建失败不应让 Tab 崩溃
            messagebox.showerror("预设应用失败", f"{label}：{exc}")
            return
        if messagebox.askyesno("应用预设", f"将用预设「{label}」覆盖当前编辑区的属性与技能，继续？"):
            self._load_config_to_gui(cfg, self._next_free_index())

    def _parse_extra_skills(self) -> List[int]:
        raw = (self._var_extra_skills.get() or "").replace("，", ",")
        ids: List[int] = []
        for part in raw.replace(";", ",").replace(" ", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                raise ValueError(f"追加技能ID 必须是整数：{part}")
        return ids

    def _register_dummy(self):
        try:
            cfg = self._build_config_from_gui()
        except ValueError as exc:
            messagebox.showerror("配置有误", str(exc))
            return
        issues = validate_dummy_config(cfg)
        errors = [m for lv, m in issues if lv == "error"]
        if errors:
            messagebox.showerror("配置有误", "无法注册：\n- " + "\n- ".join(errors))
            return
        warnings = [m for lv, m in issues if lv == "warning"]
        if warnings and not messagebox.askyesno(
                "配置警告", "存在以下警告，仍要注册吗？\n- " + "\n- ".join(warnings)):
            return
        char_id = self.app.data_loader.register_custom_dummy(cfg, self._next_free_index())
        self._refresh_list()
        self.app.team_tab._refresh_char_options()
        messagebox.showinfo("注册成功", f"木桩 [{char_id}] {cfg.name} 已注册，可在编队Tab中选择")

    def _build_config_from_gui(self) -> CustomDummyConfig:
        elem_rev = {v: k for k, v in ELEMENT_NAMES.items()}
        ctype_rev = {v: k for k, v in CHAR_TYPE_NAMES.items()}
        ptype_rev = {v: k for k, v in POSITION_TYPE_NAMES.items()}
        rtype_rev = {v: k for k, v in ROLE_TYPE_NAMES.items()}
        ttype_rev = {v: k for k, v in TARGET_TYPE_NAMES.items()}
        trange_rev = {v: k for k, v in TARGET_RANGE_NAMES.items()}
        tprio_rev = {v: k for k, v in TARGET_PRIORITY_NAMES.items()}
        cdtiming_rev = {v: k for k, v in COOLDOWN_TIMING_NAMES.items()}
        trig_rev = {t[0]: t[1] for t in filter_trigger_timings(TRIGGER_TIMING_OPTIONS)}

        def _parse_effect_type(display_val: str) -> str:
            """从显示名解析效果类型key"""
            for k, v in EFFECT_TYPE_DISPLAY.items():
                if display_val.endswith(v):
                    return k
            return "damage"

        def _build_effects(effects_list: list) -> List[CustomEffectConfig]:
            result = []
            for ef_data in effects_list:
                effect_key = _parse_effect_type(ef_data["effect_type_display"].get())
                try:
                    val = ef_data["value"].get()
                except (tk.TclError, ValueError):
                    val = 100.0
                try:
                    hc = ef_data["hit_count"].get()
                except (tk.TclError, ValueError):
                    hc = 1
                try:
                    dur = ef_data["duration"].get()
                except (tk.TclError, ValueError):
                    dur = 2
                dur_type_disp = ef_data["duration_type_display"].get()
                dur_type = DURATION_DISPLAY_REVERSE.get(dur_type_disp, "turn")
                status_disp = ef_data["status_name_display"].get()
                status_key = STATUS_DISPLAY_REVERSE.get(status_disp, "stun")
                result.append(CustomEffectConfig(
                    effect_type=effect_key,
                    value=val,
                    hit_count=hc,
                    duration=dur,
                    duration_type=dur_type,
                    status_name=status_key,
                ))
            return result

        as_skills = []
        for row in self._as_rows:
            effects = _build_effects(row.get("effects", []))
            as_skills.append(CustomASConfig(
                name=row["name"].get(),
                effects=effects,
                cooldown=row["cooldown"].get(),
                cooldown_update_timing=cdtiming_rev.get(row["cooldown_timing"].get(), 1),
                target_type=ttype_rev.get(row["target_type"].get(), 3),
                target_range=trange_rev.get(row["target_range"].get(), 1),
                target_priority=tprio_rev.get(row["target_priority"].get(), 0),
                resource_cost=row["resource_cost"].get(),
            ))

        ps_skills = []
        for row in self._ps_rows:
            effects = _build_effects(row.get("effects", []))
            ps_skills.append(CustomPSConfig(
                name=row["name"].get(),
                effects=effects,
                cooldown=row["cooldown"].get(),
                cooldown_update_timing=cdtiming_rev.get(row["cooldown_timing"].get(), 1),
                target_type=ttype_rev.get(row["target_type"].get(), 3),
                target_range=trange_rev.get(row["target_range"].get(), 1),
                target_priority=tprio_rev.get(row["target_priority"].get(), 0),
                resource_cost=row["resource_cost"].get(),
                trigger_timing=trig_rev.get(row["trigger_timing"].get(), "BeforeAsAttacked"),
            ))

        return CustomDummyConfig(
            name=self._var_name.get(),
            element=elem_rev.get(self._var_element.get(), 1),
            character_type=ctype_rev.get(self._var_char_type.get(), 1),
            position_type=ptype_rev.get(self._var_position_type.get(), 3),
            role_type=rtype_rev.get(self._var_role_type.get(), 1),
            hp=self._var_hp.get(),
            attack=self._var_atk.get(),
            defense=self._var_def.get(),
            crit_rate=self._var_crit_rate.get(),
            crit_damage=self._var_crit_dmg.get(),
            speed=self._var_spd.get(),
            advantage_damage=self._var_adv_dmg.get(),
            ap=self._var_ap.get(),
            pp=self._var_pp.get(),
            permanent_shield_type=SHIELD_TYPE_REV.get(self._var_shield_type.get(), 0),
            permanent_shield_value=self._var_shield_value.get(),
            level=self._var_level.get(),
            sub_element=elem_rev.get(self._var_sub_element.get(), 0),
            initial_ep=float(self._var_init_ep.get()),
            max_extra_point=self._var_max_ep.get(),
            note=self._var_note.get(),
            extra_skill_ids=self._parse_extra_skills(),
            revive_count=self._parse_revive_count(),
            revive_mult_start=self._parse_revive_float(self._var_revive_mult_start, "首次复活倍率"),
            revive_mult_step=self._parse_revive_float(self._var_revive_mult_step, "每次膨胀增量"),
            as_skills=as_skills,
            ps_skills=ps_skills,
        )

    def _parse_revive_count(self) -> int:
        try:
            value = int(self._var_revive_count.get())
        except (tk.TclError, ValueError):
            raise ValueError("复活次数必须是整数")
        if value < 0:
            raise ValueError(f"复活次数不能为负（当前 {value}）")
        if value > MAX_DUMMY_REVIVES:
            raise ValueError(f"复活次数最多 {MAX_DUMMY_REVIVES}（当前 {value}）")
        return value

    def _parse_revive_float(self, var, label: str) -> float:
        """解析倍率输入；空/非法时抛 ValueError（交由 _register_dummy 弹窗提示）。"""
        try:
            return float(var.get())
        except (tk.TclError, ValueError):
            raise ValueError(f"{label} 必须是数字")

    def _load_config_to_gui(self, cfg: CustomDummyConfig, dummy_index: int):
        self._dummy_index = dummy_index
        self._var_name.set(cfg.name)
        self._var_element.set(ELEMENT_NAMES.get(cfg.element, ELEMENT_NAMES[1]))
        self._var_char_type.set(CHAR_TYPE_NAMES.get(cfg.character_type, CHAR_TYPE_NAMES[1]))
        self._var_position_type.set(POSITION_TYPE_NAMES.get(cfg.position_type, POSITION_TYPE_NAMES[3]))
        self._var_role_type.set(ROLE_TYPE_NAMES.get(cfg.role_type, ROLE_TYPE_NAMES[1]))
        self._var_hp.set(cfg.hp)
        self._var_atk.set(cfg.attack)
        self._var_def.set(cfg.defense)
        self._var_crit_rate.set(cfg.crit_rate)
        self._var_crit_dmg.set(cfg.crit_damage)
        self._var_spd.set(cfg.speed)
        self._var_adv_dmg.set(cfg.advantage_damage)
        self._var_ap.set(cfg.ap)
        self._var_pp.set(cfg.pp)
        self._var_shield_type.set(SHIELD_TYPE_NAMES.get(cfg.permanent_shield_type, "无"))
        self._var_shield_value.set(cfg.permanent_shield_value)
        # v2 字段
        self._var_level.set(cfg.level)
        self._var_sub_element.set(ELEMENT_NAMES.get(cfg.sub_element, "无"))
        self._var_init_ep.set(cfg.initial_ep)
        self._var_max_ep.set(cfg.max_extra_point)
        self._var_note.set(cfg.note)
        self._var_extra_skills.set(", ".join(str(x) for x in cfg.extra_skill_ids))
        # v3 复活字段
        self._var_revive_count.set(int(cfg.revive_count or 0))
        self._var_revive_mult_start.set(float(cfg.revive_mult_start))
        self._var_revive_mult_step.set(float(cfg.revive_mult_step))
        self._refresh_revive_preview()

        self._clear_skill_rows()
        for as_cfg in cfg.as_skills:
            row = self._add_as_row()
            if row:
                row["name"].set(as_cfg.name)
                row["cooldown"].set(as_cfg.cooldown)
                row["cooldown_timing"].set(COOLDOWN_TIMING_NAMES.get(as_cfg.cooldown_update_timing, COOLDOWN_TIMING_NAMES[1]))
                row["target_type"].set(TARGET_TYPE_NAMES.get(as_cfg.target_type, TARGET_TYPE_NAMES[3]))
                row["target_range"].set(TARGET_RANGE_NAMES.get(as_cfg.target_range, TARGET_RANGE_NAMES[1]))
                row["target_priority"].set(TARGET_PRIORITY_NAMES.get(as_cfg.target_priority, TARGET_PRIORITY_NAMES[0]))
                row["resource_cost"].set(as_cfg.resource_cost)
                # 加载效果列表
                self._load_effects_to_row(row, as_cfg.get_effects())
        for ps_cfg in cfg.ps_skills:
            row = self._add_ps_row()
            if row:
                row["name"].set(ps_cfg.name)
                row["cooldown"].set(ps_cfg.cooldown)
                row["cooldown_timing"].set(COOLDOWN_TIMING_NAMES.get(ps_cfg.cooldown_update_timing, COOLDOWN_TIMING_NAMES[1]))
                row["target_type"].set(TARGET_TYPE_NAMES.get(ps_cfg.target_type, TARGET_TYPE_NAMES[3]))
                row["target_range"].set(TARGET_RANGE_NAMES.get(ps_cfg.target_range, TARGET_RANGE_NAMES[1]))
                row["target_priority"].set(TARGET_PRIORITY_NAMES.get(ps_cfg.target_priority, TARGET_PRIORITY_NAMES[0]))
                row["resource_cost"].set(ps_cfg.resource_cost)
                trig_display = next((t[0] for t in filter_trigger_timings(TRIGGER_TIMING_OPTIONS) if t[1] == ps_cfg.trigger_timing), "被攻击前")
                row["trigger_timing"].set(trig_display)
                # 加载效果列表
                self._load_effects_to_row(row, ps_cfg.get_effects())

    def _load_effects_to_row(self, row: Dict[str, Any], effects: List[CustomEffectConfig]):
        """将效果配置列表加载到技能行的效果区域"""
        # 清除默认效果
        for ef_data in row["effects"]:
            ef_data["frame"].destroy()
        row["effects"].clear()

        # 添加配置的效果
        for efg in effects:
            self._add_effect_row(row)
            ef_data = row["effects"][-1]
            # 设置效果类型
            display_name = EFFECT_TYPE_DISPLAY.get(efg.effect_type, "伤害")
            cat_name = next((cat for cat, types in EFFECT_CATEGORIES.items() if efg.effect_type in types), "伤害")
            ef_data["effect_type_display"].set(f"[{cat_name}] {display_name}")
            ef_data["value"].set(efg.value)
            ef_data["hit_count"].set(efg.hit_count)
            ef_data["duration"].set(efg.duration)
            ef_data["duration_type_display"].set(DURATION_TYPE_DISPLAY.get(efg.duration_type, DURATION_TYPE_DISPLAY["turn"]))
            ef_data["status_name_display"].set(STATUS_TYPE_DISPLAY.get(efg.status_name, STATUS_TYPE_DISPLAY["stun"]))

    def _clear_skill_rows(self):
        for row in self._as_rows:
            row["frame"].destroy()
        self._as_rows.clear()
        for row in self._ps_rows:
            row["frame"].destroy()
        self._ps_rows.clear()

    def _refresh_list(self):
        self._dummy_listbox.delete(0, tk.END)
        self._registered_ids.clear()
        dummies = self.app.data_loader.get_all_custom_dummies()
        for cid, char_data in dummies.items():
            cfg = self.app.data_loader.get_custom_dummy_config(cid)
            tag = ""
            if cfg is not None and int(cfg.revive_count or 0) > 0:
                tag = (f"  ♻×{cfg.revive_count}"
                       f"({cfg.revive_mult_start:.2f}+{cfg.revive_mult_step:.2f}/次)")
            self._dummy_listbox.insert(tk.END, f"[{cid}] {char_data.name}{tag}")
            self._registered_ids.append(cid)

    def _on_select_dummy(self, event):
        sel = self._dummy_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        cid = self._registered_ids[idx]
        cfg = self.app.data_loader.get_custom_dummy_config(cid)
        if cfg:
            dummy_idx = abs(cid) - 1
            self._load_config_to_gui(cfg, dummy_idx)

    def _edit_selected(self):
        sel = self._dummy_listbox.curselection()
        if not sel:
            messagebox.showwarning("未选择", "请先在列表中选中一个木桩")
            return
        idx = sel[0]
        cid = self._registered_ids[idx]
        if self.app.data_loader.get_custom_dummy_config(cid) is None:
            return

        try:
            new_cfg = self._build_config_from_gui()
        except ValueError as exc:
            messagebox.showerror("配置有误", str(exc))
            return
        issues = validate_dummy_config(new_cfg)
        errors = [m for lv, m in issues if lv == "error"]
        if errors:
            messagebox.showerror("配置有误", "无法更新：\n- " + "\n- ".join(errors))
            return
        # 保持原 ID 不变（ID 稳定性是编队/预设引用的前提）
        self.app.data_loader.register_custom_dummy(new_cfg, abs(cid) - 1)
        self._refresh_list()
        self.app.team_tab._refresh_char_options()
        messagebox.showinfo("更新成功", f"木桩 [{cid}] 已更新")

    def _duplicate_selected(self):
        sel = self._dummy_listbox.curselection()
        if not sel:
            messagebox.showwarning("未选择", "请先在列表中选中一个木桩")
            return
        idx = sel[0]
        cid = self._registered_ids[idx]
        src = self.app.data_loader.get_custom_dummy_config(cid)
        if src is None:
            return
        cfg = CustomDummyConfig.from_dict(src.to_dict())
        cfg.name = f"{cfg.name} 副本"
        new_id = self.app.data_loader.register_custom_dummy(cfg, self._next_free_index())
        self._refresh_list()
        self.app.team_tab._refresh_char_options()
        messagebox.showinfo("复制成功", f"已复制为 [{new_id}] {cfg.name}")

    def _delete_selected(self):
        sel = self._dummy_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        cid = self._registered_ids[idx]
        if not messagebox.askyesno("确认删除", f"删除木桩 [{cid}]？此操作不可撤销。"):
            return

        # v2：删除后不再重排其余木桩的 ID（旧实现会把后续木桩全部重新编号，
        # 导致已保存的编队/预设引用指向错误对象）。
        kept = []
        for old_id in self._registered_ids:
            saved = self.app.data_loader.get_custom_dummy_config(old_id)
            if saved is not None and old_id != cid:
                kept.append((abs(old_id) - 1, saved))

        self.app.data_loader.clear_custom_dummies()
        for dummy_index, saved in kept:
            self.app.data_loader.register_custom_dummy(saved, dummy_index)
        self._refresh_list()
        self.app.team_tab._refresh_char_options()

    def _clear_all(self):
        self.app.data_loader.clear_custom_dummies()
        self._registered_ids.clear()
        self._clear_skill_rows()
        self._refresh_list()
        self.app.team_tab._refresh_char_options()
        self._dummy_index = 0


