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
)

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
        f = ttk.Frame(self)
        f.pack(fill=tk.BOTH, expand=True)

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

        self._refresh_list()

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
            row_data["trigger_timing"] = tk.StringVar(value=TRIGGER_TIMING_OPTIONS[0][0])
            cb = ttk.Combobox(ps_extra, textvariable=row_data["trigger_timing"],
                              values=[t[0] for t in TRIGGER_TIMING_OPTIONS], state="readonly", width=16)
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

    def _register_dummy(self):
        cfg = self._build_config_from_gui()
        char_id = self.app.data_loader.register_custom_dummy(cfg, self._dummy_index)
        self._refresh_list()
        self._dummy_index += 1
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
        trig_rev = {t[0]: t[1] for t in TRIGGER_TIMING_OPTIONS}

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
            as_skills=as_skills,
            ps_skills=ps_skills,
        )

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
                trig_display = next((t[0] for t in TRIGGER_TIMING_OPTIONS if t[1] == ps_cfg.trigger_timing), "被攻击前")
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
            self._dummy_listbox.insert(tk.END, f"[{cid}] {char_data.name}")
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
        old_cfg = self.app.data_loader.get_custom_dummy_config(cid)
        if not old_cfg:
            return

        new_cfg = self._build_config_from_gui()
        saved_configs = []
        for old_id in self._registered_ids:
            saved = self.app.data_loader.get_custom_dummy_config(old_id)
            saved_configs.append((old_id, saved))

        self.app.data_loader.clear_custom_dummies()
        for (old_id, saved) in saved_configs:
            if saved is None:
                continue
            target_cfg = new_cfg if old_id == cid else saved
            self.app.data_loader.register_custom_dummy(target_cfg, abs(old_id) - 1)
        self._registered_ids = self.app.data_loader.get_custom_dummy_ids()
        self._refresh_list()
        self.app.team_tab._refresh_char_options()
        messagebox.showinfo("更新成功", f"木桩 [{cid}] 已更新")

    def _delete_selected(self):
        sel = self._dummy_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        cid = self._registered_ids[idx]

        saved_configs = []
        for old_id in self._registered_ids:
            saved = self.app.data_loader.get_custom_dummy_config(old_id)
            saved_configs.append(saved)

        self.app.data_loader.clear_custom_dummies()
        new_index = 0
        for i, saved in enumerate(saved_configs):
            if i == idx:
                continue
            if saved is None:
                continue
            self.app.data_loader.register_custom_dummy(saved, new_index)
            new_index += 1
        self._registered_ids = self.app.data_loader.get_custom_dummy_ids()
        self._refresh_list()
        self.app.team_tab._refresh_char_options()

    def _clear_all(self):
        self.app.data_loader.clear_custom_dummies()
        self._registered_ids.clear()
        self._clear_skill_rows()
        self._refresh_list()
        self.app.team_tab._refresh_char_options()
        self._dummy_index = 0


