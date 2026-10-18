# -*- coding: utf-8 -*-
"""游戏数据导入弹窗：选择游戏数据文件 → 预览差异 → 写入当前账号。

流程与安全约定：

* 只读快照文件，**应用前不落盘**（预览走 ``apply_payload(dry_run=True)``）；
* 应用时先备份账号配置，再原子写，并记录 ``game_import.json`` 审计；
* 未拥有角色不动、锁定角色默认跳过、账号不一致要二次确认。
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from gui.constants import _BASE_PATH
from gui.widgets.modal import _bind_modal_minimize_restore

from src.importer import apply as apply_mod
from src.importer import lut as lut_mod
from src.importer import map_user, snapshot


SCHOOL_ROWS = [
    [("physical_level", "物理"), ("en_level", "EN"), ("agility_level", "敏捷")],
    [("fire_level", "火"), ("water_level", "水"), ("wind_level", "风")],
    [("earth_level", "土"), ("light_level", "光"), ("dark_level", "暗")],
]
CT_LABELS = {1: "物理", 2: "EN", 3: "敏捷"}


class GameDataImportDialog(tk.Toplevel):
    """从游戏数据文件导入当前账号配置。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.registry = getattr(app, "account_registry", None)
        self.data_dir = Path(_BASE_PATH) / "data"

        self.loaded = None
        self.payload = None
        self.preview = None
        self._index = None

        self.title("从游戏导入数据")
        self.transient(parent)
        self.grab_set()
        _bind_modal_minimize_restore(self, parent)
        self.resizable(True, True)
        self.geometry("820x600")
        self.minsize(680, 480)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    # ─────────────────── UI ───────────────────

    def _build(self):
        scheme = self.app._get_scheme()
        self.configure(bg=scheme["bg"])

        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=12, pady=10)

        # 文件选择
        file_row = ttk.Frame(root)
        file_row.pack(fill="x")
        ttk.Label(file_row, text="数据文件：").pack(side="left")
        self.path_var = tk.StringVar(value="（未选择）")
        ttk.Entry(file_row, textvariable=self.path_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(file_row, text="选择文件…", command=self._choose_file).pack(side="left")
        ttk.Label(
            root,
            text="提示：用配套的浏览器脚本在游戏页导出数据文件（脚本私下分发，不在本程序内）。",
            foreground=scheme["fg"],
        ).pack(anchor="w", pady=(2, 8))

        # 导入范围
        options = ttk.LabelFrame(root, text="导入范围")
        options.pack(fill="x")
        self.var_school = tk.BooleanVar(value=True)
        self.var_equipment = tk.BooleanVar(value=True)
        self.var_characters = tk.BooleanVar(value=True)
        self.var_modules = tk.BooleanVar(value=True)
        self.var_gears = tk.BooleanVar(value=True)
        self.var_locked = tk.BooleanVar(value=False)
        self.var_backup = tk.BooleanVar(value=True)
        for var, text in (
            (self.var_school, "学园等级"),
            (self.var_equipment, "装备数值"),
            (self.var_characters, "角色等级/稀有度/好感/技能"),
            (self.var_modules, "模块 Tier/等级"),
            (self.var_gears, "模块词条"),
        ):
            ttk.Checkbutton(options, text=text, variable=var,
                            command=self._refresh_preview).pack(side="left", padx=6, pady=4)
        row2 = ttk.Frame(options)
        row2.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Checkbutton(row2, text="覆盖已锁定角色", variable=self.var_locked,
                        command=self._refresh_preview).pack(side="left")
        ttk.Checkbutton(row2, text="写入前备份当前配置", variable=self.var_backup).pack(
            side="left", padx=16
        )

        # 预览
        preview_frame = ttk.LabelFrame(root, text="预览（旧 → 新）")
        preview_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.preview_text = tk.Text(
            preview_frame, wrap="word", height=18,
            bg=scheme["input_bg"], fg=scheme["fg"],
            insertbackground=scheme["fg"], relief="flat", padx=8, pady=6,
        )
        scroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=scroll.set)
        self.preview_text.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        scroll.pack(side="right", fill="y", pady=4)
        self.preview_text.insert("1.0", "请选择游戏数据文件。")
        self.preview_text.configure(state="disabled")

        # 底部按钮
        bottom = ttk.Frame(root)
        bottom.pack(fill="x", pady=(10, 0))
        self.status_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.status_var, foreground=scheme["accent"]).pack(side="left")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right", padx=4)
        self.apply_btn = ttk.Button(bottom, text="导入到当前账号", command=self._apply,
                                    state="disabled")
        self.apply_btn.pack(side="right", padx=4)

    # ─────────────────── 读取与预览 ───────────────────

    def _account_dir(self) -> Path:
        if self.registry is not None:
            return Path(self.registry.get_active_dir())
        from gui.utils import get_user_data_path
        return Path(get_user_data_path())

    def _account_label(self) -> str:
        if self.registry is not None:
            return self.registry.get_current_name() or "（默认目录）"
        return "当前账号"

    def _choose_file(self):
        downloads = Path.home() / "Downloads"
        initial = str(downloads) if downloads.is_dir() else str(Path.home())
        path = filedialog.askopenfilename(
            parent=self,
            title="选择游戏数据文件",
            initialdir=initial,
            filetypes=[("游戏数据文件", "*.json *.har"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.path_var.set(path)
        self._load(Path(path))

    def _get_index(self):
        if self._index is None:
            cached = getattr(self.app, "_importer_index", None)
            if cached is None:
                cached = lut_mod.DataIndex.load(self.data_dir)
                self.app._importer_index = cached
            self._index = cached
        return self._index

    def _load(self, path: Path):
        try:
            self.loaded = snapshot.load(path)
            self.payload = map_user.build_payload(
                self.loaded.rows,
                self._get_index(),
                captured_at=self.loaded.captured_at,
                client_version=self.loaded.client_version,
                source_url=self.loaded.source_url,
            )
        except (snapshot.SnapshotError, lut_mod.LutError) as exc:
            self.loaded = self.payload = self.preview = None
            self.apply_btn.configure(state="disabled")
            self.status_var.set("读取失败")
            self._set_preview(f"读取失败：\n\n{exc}")
            messagebox.showerror("读取失败", str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001 - 弹窗兜底，避免半截状态
            self.loaded = self.payload = self.preview = None
            self.apply_btn.configure(state="disabled")
            self._set_preview(f"读取失败：\n\n{exc}")
            messagebox.showerror("读取失败", str(exc), parent=self)
            return

        self._refresh_preview()

    def _apply_options(self) -> apply_mod.ApplyOptions:
        return apply_mod.ApplyOptions(
            school=self.var_school.get(),
            equipment=self.var_equipment.get(),
            characters=self.var_characters.get(),
            modules=self.var_modules.get(),
            gears=self.var_gears.get(),
            overwrite_locked=self.var_locked.get(),
            backup=self.var_backup.get(),
        )

    def _refresh_preview(self):
        if not self.loaded or not self.payload:
            return
        try:
            self.preview = apply_mod.apply_payload(
                self._account_dir(), self.payload, self._apply_options(),
                source_name=self.loaded.source_name, source_sha256=self.loaded.sha256,
                dry_run=True, data_dir=self.data_dir,
            )
        except Exception as exc:  # noqa: BLE001
            self.apply_btn.configure(state="disabled")
            self._set_preview(f"预览失败：\n\n{exc}")
            return

        self._set_preview(self._render_preview())
        self.apply_btn.configure(state="normal" if self.preview.changed else "disabled")
        self.status_var.set("配置无变化（幂等）" if not self.preview.changed else "")

    def _render_preview(self) -> str:
        payload = self.payload
        loaded = self.loaded
        current_char, current_global = apply_mod.load_current_configs(
            self._account_dir(), self.data_dir
        )
        options = self._apply_options()
        lines = []

        account = payload.account or {}
        lines.append(f"快照　{loaded.source_name}（{loaded.raw_bytes:,} B，sha256 {loaded.sha256[:12]}…）")
        if account:
            lines.append(
                f"账号　{account.get('name')} / code {account.get('code')} / "
                f"world {account.get('world_master_id')} / 玩家等级 {account.get('player_rank')}"
            )
        lines.append(
            f"捕获　{payload.captured_at or '未知'}（客户端版本 {payload.client_version or '未知'}）"
        )
        lines.append(f"实体　{payload.stats.get('entity_rows', 0):,} 行")
        lines.append(f"目标　账号「{self._account_label()}」 → {self._account_dir()}")
        lines.append("")

        old_school = current_global.get("school_levels") or {}
        lines.append("学园等级" + ("" if options.school else "（本次不导入）"))
        for row in SCHOOL_ROWS:
            cells = []
            for key, label in row:
                old = old_school.get(key, "-")
                new = (payload.school_levels or {}).get(key)
                cells.append(f"{label} {old} → {new if new is not None else '-'}")
            lines.append("　" + "　".join(cells))
        lines.append("")

        old_equip = current_global.get("equipment") or {}
        lines.append("装备数值" + ("" if options.equipment else "（本次不导入）"))
        for ct in (1, 2, 3):
            old = old_equip.get(str(ct)) or old_equip.get(ct) or {}
            new = (payload.equipment or {}).get(ct) or {}
            lines.append(
                f"　{CT_LABELS[ct]}　HP {old.get('hp', 0)} → {new.get('hp', 0)}　"
                f"ATK {old.get('attack', 0)} → {new.get('attack', 0)}　"
                f"DEF {old.get('defense', 0)} → {new.get('defense', 0)}"
            )
        lines.append("")

        if options.characters and payload.link_level:
            old_level = current_global.get("character_level", "-")
            lines.append(
                f"角色等级（全局）　{old_level} → {payload.link_level}（游戏链接等级）"
            )
            lines.append("")

        stats = self.preview.stats if self.preview else {}
        lines.append(
            f"角色（导入 {payload.stats.get('characters_imported', 0)} / "
            f"拥有 {payload.stats.get('characters_owned', 0)}）"
        )
        lines.append(
            f"　将更新 {stats.get('characters_updated', 0)} 个；"
            f"锁定跳过 {stats.get('characters_locked_skipped', 0)}；"
            f"未拥有角色不改动"
        )
        if payload.link_level:
            lines.append(
                f"　链接等级 {payload.link_level}（{payload.linked_characters} 个角色共享；"
                f"含标准角色与被链接角色）；其余角色用各自独立等级"
            )
        if payload.characters:
            distribution = {}
            for character in payload.characters.values():
                distribution[character.level] = distribution.get(character.level, 0) + 1
            shown = "、".join(
                f"{level} 级 ×{count}"
                for level, count in sorted(distribution.items(), reverse=True)[:6]
            )
            lines.append(f"　等级分布：{shown}")
        lines.append(
            f"　模块 {payload.stats.get('module_rows', 0)} 行、"
            f"词条有效 {payload.stats.get('gear_effective', 0)} 条（已含道具损耗率）"
            + ("" if options.characters else "（本次不导入角色）")
        )

        audit = apply_mod.read_audit(self._account_dir())
        last = (audit.get("last_import") or {}).get("account") or {}
        if last.get("code") and account.get("code") and last["code"] != account["code"]:
            lines.append("")
            lines.append(
                f"⚠ 账号不一致：本账号上次导入的是 {last.get('name')}（{last['code']}），"
                f"本次快照是 {account.get('name')}（{account['code']}）。"
            )

        warnings = self.preview.warnings if self.preview else []
        lines.append("")
        if warnings:
            lines.append(f"⚠ 警告（{len(warnings)}）")
            for warning in warnings[:12]:
                lines.append(f"　- {warning}")
            if len(warnings) > 12:
                lines.append(f"　… 其余 {len(warnings) - 12} 条")
        else:
            lines.append("✔ 没有警告")
        return "\n".join(lines)

    def _set_preview(self, text: str):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", text)
        self.preview_text.configure(state="disabled")

    # ─────────────────── 应用 ───────────────────

    def _apply(self):
        if not self.loaded or not self.payload:
            return
        account_dir = self._account_dir()
        payload_code = (self.payload.account or {}).get("code")
        audit = apply_mod.read_audit(account_dir)
        last = (audit.get("last_import") or {}).get("account") or {}
        if account_dir.exists() and (account_dir / apply_mod.CHAR_CONFIG_FILE).exists():
            if payload_code is None:
                if not messagebox.askyesno(
                    "账号未确认",
                    "快照里没有账号身份信息，无法确认它属于当前账号。仍要导入吗？",
                    parent=self,
                ):
                    return
            elif last.get("code") and last["code"] != payload_code:
                if not messagebox.askyesno(
                    "账号不一致",
                    f"本账号上次导入的是 {last.get('name')}（{last['code']}），"
                    f"本次快照是 {(self.payload.account or {}).get('name')}（{payload_code}）。\n\n"
                    "确定要写入当前账号吗？",
                    parent=self,
                ):
                    return

        try:
            report = apply_mod.apply_payload(
                account_dir, self.payload, self._apply_options(),
                source_name=self.loaded.source_name, source_sha256=self.loaded.sha256,
                dry_run=False, data_dir=self.data_dir,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导入失败", str(exc), parent=self)
            return

        self._reload_app_state()
        stats = report.stats
        if report.changed:
            messagebox.showinfo(
                "导入完成",
                f"已导入到账号「{self._account_label()}」。\n\n"
                f"角色更新 {stats.get('characters_updated', 0)} 个（锁定跳过 {stats.get('characters_locked_skipped', 0)}）\n"
                f"模块 {stats.get('module_rows', 0)} 行，"
                f"词条 {stats.get('gear_effective', 0)} 条\n"
                f"备份：{report.backup_dir.name if report.backup_dir else '未备份'}",
                parent=self,
            )
        else:
            messagebox.showinfo("无变化", "配置与快照一致，没有需要写入的内容。", parent=self)
        self.destroy()

    def _reload_app_state(self):
        """把磁盘上的新配置同步回 GUI 内存与控件。"""
        app = self.app
        try:
            app._load_char_config()
        except Exception:  # noqa: BLE001
            pass
        try:
            app.global_tab._load_global_config()
        except Exception:  # noqa: BLE001
            pass
        try:
            app.char_tab.refresh_grid_cards()
        except Exception:  # noqa: BLE001
            pass
        try:
            app.global_tab.refresh_import_status()
        except Exception:  # noqa: BLE001
            pass
