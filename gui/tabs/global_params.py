# -*- coding: utf-8 -*-
"""全局参数 Tab（学园等级、装备数值、角色等级、默认稀有度/模块/好感度/技能）。

从 gui_app.py 抽取，通过 self.app 访问主类。
"""

import json
from typing import Any, Dict

import tkinter as tk
from tkinter import ttk, messagebox

from src.config.player_config import SchoolLevels

from gui.constants import (
    GEAR_EFFECT_DISPLAY,
    GEAR_EFFECT_OPTIONS_DISPLAY,
    GEAR_EFFECT_REVERSE,
    GLOBAL_CONFIG_PATH,
    RARITY_NAMES,
    SCHOOL_LABELS,
)


class GlobalParamsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build()

    def _build(self):
        f = ttk.Frame(self)
        f.pack(fill=tk.BOTH, expand=True)
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)

        # ── 左栏：等级、学园、装备 ──
        left_col = ttk.Frame(f)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)

        # ── 角色等级 ──
        ttk.Label(left_col, text="角色等级", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 2))
        lf = ttk.LabelFrame(left_col, text="等级设置")
        lf.pack(fill="x", pady=2)
        ttk.Label(lf, text="角色等级:").grid(row=0, column=0, padx=5, pady=5)
        self.var_level = tk.IntVar(value=355)
        ttk.Spinbox(lf, from_=1, to=999, textvariable=self.var_level, width=8).grid(row=0, column=1, padx=5)

        # ── 学园等级 ──
        ttk.Label(left_col, text="学园等级", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        lf = ttk.LabelFrame(left_col, text="类型等级")
        lf.pack(fill="x", pady=2)
        self.vars_school = {}
        for i, (label, key) in enumerate(SCHOOL_LABELS):
            r, c = divmod(i, 3)
            ttk.Label(lf, text=label, width=6).grid(row=r, column=c * 2, padx=2, pady=2)
            v = tk.IntVar(value=getattr(SchoolLevels(), key))
            self.vars_school[key] = v
            ttk.Spinbox(lf, from_=0, to=999, textvariable=v, width=5).grid(row=r, column=c * 2 + 1, padx=2, pady=2)

        # ── 装备数值 ──
        ttk.Label(left_col, text="装备数值 (按角色类型填写 HP/ATK/DEF 总值)", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        lf = ttk.LabelFrame(left_col, text="装备加成 (同类型所有装备总加成)")
        lf.pack(fill="x", pady=2)
        headers = ["类型", "HP加成", "ATK加成", "DEF加成"]
        for j, h in enumerate(headers):
            ttk.Label(lf, text=h, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=j, padx=6, pady=3)
        self.equip_vars: Dict[int, Dict[str, tk.IntVar]] = {}
        equip_types = [(1, "物理"), (2, "EN"), (3, "敏捷")]
        for i, (ct, ct_name) in enumerate(equip_types, start=1):
            ttk.Label(lf, text=ct_name).grid(row=i, column=0, padx=6, pady=2)
            self.equip_vars[ct] = {}
            for j, key in enumerate(["hp", "attack", "defense"]):
                v = tk.IntVar(value=0)
                self.equip_vars[ct][key] = v
                ttk.Spinbox(lf, from_=0, to=999999, textvariable=v, width=9).grid(row=i, column=1 + j, padx=3, pady=2)

        # ── 右栏：角色默认参数、战斗设置、保存重置 ──
        right_col = ttk.Frame(f)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)

        # ── 角色默认参数 ──
        ttk.Label(right_col, text="角色默认参数 (一键套用至所有角色)", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 2))
        lf = ttk.LabelFrame(right_col, text="通用角色设置")
        lf.pack(fill="x", pady=2)

        ttk.Label(lf, text="稀有度:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.var_rarity = tk.IntVar(value=14)
        cb = ttk.Combobox(lf, textvariable=self.var_rarity, values=list(range(5, 15)), state="readonly", width=5)
        cb.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.rarity_name_label = ttk.Label(lf, text=RARITY_NAMES[14])
        self.rarity_name_label.grid(row=0, column=2, padx=5, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_rarity_change())
        # 备注：全局默认稀有度仍提供5-14全范围，角色参数页会根据角色类型限制上限

        ttk.Label(lf, text="好感度:").grid(row=0, column=3, padx=5, pady=5, sticky="e")
        self.var_affection = tk.IntVar(value=40)
        ttk.Spinbox(lf, from_=1, to=40, textvariable=self.var_affection, width=5).grid(row=0, column=4, padx=5)

        ttk.Label(lf, text="技能等级:").grid(row=0, column=5, padx=5, pady=5, sticky="e")
        self.var_skill_lv = tk.IntVar(value=15)
        self.skill_lv_spinbox = ttk.Spinbox(lf, from_=1, to=15, textvariable=self.var_skill_lv, width=5)
        self.skill_lv_spinbox.grid(row=0, column=6, padx=5)

        ttk.Label(lf, text="模块Tier/等级:").grid(row=1, column=0, padx=5, pady=(5, 0), sticky="e")
        mod_tl_frame = ttk.Frame(lf)
        mod_tl_frame.grid(row=1, column=1, columnspan=4, padx=5, pady=(5, 0), sticky="w")

        # 表头
        ttk.Label(mod_tl_frame, text="").grid(row=0, column=0)
        ttk.Label(mod_tl_frame, text="Tier", width=5).grid(row=0, column=1, padx=2)
        ttk.Label(mod_tl_frame, text="等级", width=5).grid(row=0, column=2, padx=2)

        # HP / 攻击 / 防御 三行
        self.var_mod_tier_hp = tk.IntVar(value=9)
        self.var_mod_level_hp = tk.IntVar(value=50)
        self.var_mod_tier_atk = tk.IntVar(value=9)
        self.var_mod_level_atk = tk.IntVar(value=50)
        self.var_mod_tier_def = tk.IntVar(value=9)
        self.var_mod_level_def = tk.IntVar(value=50)

        mod_stat_rows = [
            ("HP",   self.var_mod_tier_hp,   self.var_mod_level_hp),
            ("攻击", self.var_mod_tier_atk,  self.var_mod_level_atk),
            ("防御", self.var_mod_tier_def,  self.var_mod_level_def),
        ]
        for idx, (stat_label, tier_var, lv_var) in enumerate(mod_stat_rows, start=1):
            ttk.Label(mod_tl_frame, text=stat_label, width=5).grid(row=idx, column=0, padx=2, pady=1, sticky="e")
            ttk.Combobox(mod_tl_frame, textvariable=tier_var, values=list(range(1, 10)),
                         state="readonly", width=5).grid(row=idx, column=1, padx=2, pady=1, sticky="w")
            ttk.Spinbox(mod_tl_frame, from_=1, to=50, textvariable=lv_var,
                        width=5).grid(row=idx, column=2, padx=2, pady=1, sticky="w")

        self._build_gear_defaults(lf)

        # ── 战斗设置 ──
        ttk.Label(right_col, text="战斗设置", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        lf = ttk.LabelFrame(right_col, text="模拟参数")
        lf.pack(fill="x", pady=2)

        ttk.Label(lf, text="默认模拟场数:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.var_runs = tk.IntVar(value=1)
        ttk.Spinbox(lf, from_=1, to=10000, textvariable=self.var_runs, width=8).grid(row=0, column=1, padx=5, sticky="w")

        ttk.Label(lf, text="最大回合数:").grid(row=0, column=2, padx=5, pady=5, sticky="e")
        self.var_max_turns = tk.IntVar(value=30)
        ttk.Spinbox(lf, from_=5, to=999, textvariable=self.var_max_turns, width=8).grid(row=0, column=3, padx=5, sticky="w")

        self.var_enable_rdps = tk.BooleanVar(value=True)
        rdps_frame = ttk.Frame(lf)
        rdps_frame.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="w")
        ttk.Label(rdps_frame, text="RDPS统计:").pack(side="left")
        ttk.Radiobutton(rdps_frame, text="开启", variable=self.var_enable_rdps,
                        value=True).pack(side="left", padx=5)
        ttk.Radiobutton(rdps_frame, text="关闭", variable=self.var_enable_rdps,
                        value=False).pack(side="left")

        btn_frame = ttk.Frame(right_col)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="保存全局设置", command=self._save_global_config_with_feedback).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="重置全局设置", command=self._reset_global_config).pack(side=tk.LEFT, padx=5)

        self._load_global_config()

    def _on_rarity_change(self):
        r = self.var_rarity.get()
        self.rarity_name_label.config(text=RARITY_NAMES.get(r, ""))
        # 稀有度变化时联动技能等级上限：>=9(LR)为15，否则为10
        new_max = 15 if r >= 9 else 10
        self.skill_lv_spinbox.config(to=new_max)
        if self.var_skill_lv.get() > new_max:
            self.var_skill_lv.set(new_max)

    def _build_gear_defaults(self, parent):
        ttk.Label(parent, text="模块词条 (每角色共9槽，分3组对应3个模块，同组不可复选相同类型):", font=("Microsoft YaHei UI", 8)).grid(
            row=2, column=0, columnspan=7, sticky="w", padx=5, pady=(10, 2))

        self.gear_vars = []
        module_names = ["模块1 (HP)", "模块2 (攻击)", "模块3 (防御)"]
        gear_frame = ttk.Frame(parent)
        gear_frame.grid(row=3, column=0, columnspan=7, sticky="ew", padx=5, pady=2)

        for grp_idx in range(3):
            grp_frame = ttk.LabelFrame(gear_frame, text=module_names[grp_idx], style="Gear.TLabelframe")
            grp_frame.grid(row=0, column=grp_idx, padx=5, pady=3, sticky="n")

            for slot_idx in range(3):
                slot_frame = ttk.Frame(grp_frame)
                slot_frame.pack(pady=1, padx=3)

                et_var = tk.StringVar(value="无效果")
                cb = ttk.Combobox(slot_frame, textvariable=et_var, values=GEAR_EFFECT_OPTIONS_DISPLAY,
                                  state="readonly", width=12)
                cb.pack()

                slot_grp = grp_idx
                slot_idx_in_grp = slot_idx
                cb.bind("<<ComboboxSelected>>",
                        lambda e, g=slot_grp, s_idx=slot_idx_in_grp: self._validate_gear_group(g, s_idx))

                pct_frame = ttk.Frame(slot_frame)
                pct_frame.pack()
                v_var = tk.DoubleVar(value=0.0)
                ttk.Spinbox(pct_frame, from_=0, to=100, increment=0.5, textvariable=v_var, width=5).pack(side=tk.LEFT)
                ttk.Label(pct_frame, text="%", font=("Microsoft YaHei UI", 7)).pack(side=tk.LEFT)

                self.gear_vars.append({"et": et_var, "val": v_var, "group": grp_idx, "slot": slot_idx})

    def _validate_gear_group(self, group_idx, changed_slot_idx):
        group_slots = [(i, gv) for i, gv in enumerate(self.gear_vars) if gv["group"] == group_idx]
        used_types = {}
        for abs_idx, gv in group_slots:
            et_val = gv["et"].get()
            if et_val != "无效果":
                if et_val in used_types:
                    gv["et"].set("无效果")
                    gv["val"].set(0.0)
                    messagebox.showwarning("词条冲突",
                        f"模块{group_idx+1}中词条类型重复，已自动清除冲突槽位")
                else:
                    used_types[et_val] = abs_idx

    def _save_global_config(self):
        try:
            GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            values = self.get_values()
            with open(GLOBAL_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(values, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _save_global_config_with_feedback(self):
        self._save_global_config()
        # 传播全局等级到所有 override 且非 1 级的角色（链接等级系统语义）
        self.app._propagate_global_level_change(self.var_level.get())
        messagebox.showinfo("保存", "全局参数已保存")

    def _load_global_config(self):
        if not GLOBAL_CONFIG_PATH.exists():
            return
        try:
            with open(GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                values = json.load(f)
            self.var_level.set(values.get("character_level", 355))
            sl = values.get("school_levels", {})
            for key, v in self.vars_school.items():
                v.set(sl.get(key, 0))
            eq = values.get("equipment", {})
            for ct_str, vs in eq.items():
                ct = int(ct_str)
                if ct in self.equip_vars:
                    self.equip_vars[ct]["hp"].set(vs.get("hp", 0))
                    self.equip_vars[ct]["attack"].set(vs.get("attack", 0))
                    self.equip_vars[ct]["defense"].set(vs.get("defense", 0))
            self.var_rarity.set(values.get("default_rarity", 14))
            self.rarity_name_label.config(text=RARITY_NAMES.get(self.var_rarity.get(), ""))
            self.var_affection.set(values.get("default_affection", 40))
            # 联动技能等级上限
            r = self.var_rarity.get()
            skill_max = 15 if r >= 9 else 10
            self.skill_lv_spinbox.config(to=skill_max)
            raw_skill_lv = values.get("default_skill_level", 15)
            self.var_skill_lv.set(min(raw_skill_lv, skill_max))
            # 模块Tier/等级 (向后兼容: 旧单值 → 三模块统一)
            old_tier = values.get("default_mod_tier", 9)
            old_level = values.get("default_mod_level", 50)
            self.var_mod_tier_hp.set(values.get("default_mod_tier_hp", old_tier))
            self.var_mod_level_hp.set(values.get("default_mod_level_hp", old_level))
            self.var_mod_tier_atk.set(values.get("default_mod_tier_atk", old_tier))
            self.var_mod_level_atk.set(values.get("default_mod_level_atk", old_level))
            self.var_mod_tier_def.set(values.get("default_mod_tier_def", old_tier))
            self.var_mod_level_def.set(values.get("default_mod_level_def", old_level))
            saved_gear = values.get("default_gear", [])
            saved_gear_map = {}
            for g in saved_gear:
                saved_gear_map[(g["group"], g["slot"])] = g
            for gv in self.gear_vars:
                sg = saved_gear_map.get((gv["group"], gv["slot"]), {})
                gv["et"].set(GEAR_EFFECT_DISPLAY.get(sg.get("effect_type", 0), "无效果"))
                gv["val"].set(sg.get("value", 0.0))
            self.var_runs.set(values.get("runs", 1))
            self.var_max_turns.set(values.get("max_turns", 30))
            self.var_enable_rdps.set(values.get("enable_rdps", True))
        except Exception as e:
            messagebox.showerror("加载配置失败", str(e))

    def _reset_global_config(self):
        self.var_level.set(355)
        for key, v in self.vars_school.items():
            v.set(getattr(SchoolLevels(), key))
        for ct in self.equip_vars:
            self.equip_vars[ct]["hp"].set(0)
            self.equip_vars[ct]["attack"].set(0)
            self.equip_vars[ct]["defense"].set(0)
        self.var_rarity.set(14)
        self.rarity_name_label.config(text=RARITY_NAMES[14])
        self.var_affection.set(40)
        self.skill_lv_spinbox.config(to=15)
        self.var_skill_lv.set(15)
        self.var_mod_tier_hp.set(9)
        self.var_mod_level_hp.set(50)
        self.var_mod_tier_atk.set(9)
        self.var_mod_level_atk.set(50)
        self.var_mod_tier_def.set(9)
        self.var_mod_level_def.set(50)
        for gv in self.gear_vars:
            gv["et"].set("无效果")
            gv["val"].set(0.0)
        self.var_runs.set(1)
        self.var_max_turns.set(30)
        self.var_enable_rdps.set(True)
        messagebox.showinfo("重置", "全局参数已重置为默认值")
        self._save_global_config()
        # 重置后同样传播等级（355）到所有 override 且非 1 级的角色
        self.app._propagate_global_level_change(self.var_level.get())

    def _bind_mousewheel(self, canvas):
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_canvas(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_canvas(event):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bind_canvas)
        canvas.bind("<Leave>", _unbind_canvas)

    def get_values(self) -> Dict[str, Any]:
        return {
            "character_level": self.var_level.get(),
            "school_levels": {key: v.get() for key, v in self.vars_school.items()},
            "equipment": {ct: {"hp": vs["hp"].get(), "attack": vs["attack"].get(), "defense": vs["defense"].get()}
                          for ct, vs in self.equip_vars.items()},
            "default_rarity": self.var_rarity.get(),
            "default_affection": self.var_affection.get(),
            "default_skill_level": self.var_skill_lv.get(),
            "default_mod_tier_hp": self.var_mod_tier_hp.get(),
            "default_mod_level_hp": self.var_mod_level_hp.get(),
            "default_mod_tier_atk": self.var_mod_tier_atk.get(),
            "default_mod_level_atk": self.var_mod_level_atk.get(),
            "default_mod_tier_def": self.var_mod_tier_def.get(),
            "default_mod_level_def": self.var_mod_level_def.get(),
            "default_gear": [{"effect_type": GEAR_EFFECT_REVERSE[gv["et"].get()], "value": gv["val"].get(),
                              "group": gv["group"], "slot": gv["slot"]}
                             for gv in self.gear_vars if gv["et"].get() != "无效果"],
            "runs": self.var_runs.get(),
            "max_turns": self.var_max_turns.get(),
            "enable_rdps": self.var_enable_rdps.get(),
        }
