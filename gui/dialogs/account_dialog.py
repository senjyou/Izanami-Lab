# -*- coding: utf-8 -*-
"""账号管理弹窗：账号列表 + 新建/重命名/删除/导入/导出/切换。

账号数据操作全部委托 src/utils/account_manager.AccountRegistry，
本弹窗只负责交互与结果反馈。
"""

import os
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk

from gui.widgets.modal import _bind_modal_minimize_restore


class AccountManagerDialog(tk.Toplevel):
    """账号管理二级弹窗"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.registry = app.account_registry

        self.title("账号管理")
        self.transient(parent)
        self.grab_set()
        _bind_modal_minimize_restore(self, parent)
        self.resizable(True, True)
        self.geometry("640x430")
        self.minsize(560, 380)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    # ─────────────────── UI 构建 ───────────────────

    def _build(self):
        s = self.app._get_scheme()
        self.configure(bg=s["bg"])

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=8)

        # ── 账号列表 ──
        columns = ("status", "name", "note", "last_used")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        self.tree.heading("status", text="当前")
        self.tree.heading("name", text="账号名")
        self.tree.heading("note", text="备注")
        self.tree.heading("last_used", text="最后使用")
        self.tree.column("status", width=44, anchor="center", stretch=False)
        self.tree.column("name", width=130, anchor="w")
        self.tree.column("note", width=220, anchor="w")
        self.tree.column("last_used", width=120, anchor="center", stretch=False)
        self.tree.tag_configure("current", foreground=s["accent"])

        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._switch())

        # ── 反馈行 ──
        self._status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._status_var, foreground=s["accent"]
                  ).pack(fill="x", padx=12, pady=(0, 4))

        # ── 按钮区（两行：账号操作 | 切换/关闭；导入导出） ──
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        row1 = ttk.Frame(btn_frame)
        row1.pack(fill="x")
        left1 = ttk.Frame(row1)
        left1.pack(side="left")
        right1 = ttk.Frame(row1)
        right1.pack(side="right")

        ttk.Button(left1, text="新建", command=self._create).pack(side="left", padx=3)
        ttk.Button(left1, text="重命名", command=self._rename).pack(side="left", padx=3)
        ttk.Button(left1, text="修改备注", command=self._edit_note).pack(side="left", padx=3)
        ttk.Button(left1, text="删除", command=self._delete).pack(side="left", padx=3)

        ttk.Button(right1, text="关闭", command=self.destroy).pack(side="right", padx=3)
        ttk.Button(right1, text="切换到此账号", command=self._switch).pack(side="right", padx=3)

        row2 = ttk.Frame(btn_frame)
        row2.pack(fill="x", pady=(4, 0))
        ttk.Button(row2, text="打开文件夹", command=self._open_folder).pack(side="left", padx=3)
        ttk.Button(row2, text="导出账号包", command=self._export).pack(side="left", padx=3)
        ttk.Button(row2, text="导入账号包", command=self._import_bundle).pack(side="left", padx=3)
        ttk.Button(row2, text="导入旧版文件夹", command=self._import_legacy).pack(side="left", padx=3)

        self._refresh()

    def _refresh(self):
        current = self.registry.get_current_name()
        self.tree.delete(*self.tree.get_children())
        for acc in self.registry.list_accounts():
            is_current = acc.get("name") == current
            self.tree.insert("", "end", iid=acc["name"], tags=("current",) if is_current else (),
                             values=("✓" if is_current else "", acc.get("name", ""),
                                     acc.get("note", ""), acc.get("last_used") or "—"))
        self.app._refresh_account_combo()

    def _set_status(self, text):
        self._status_var.set(text)

    def _selected_name(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _selected_or_current(self):
        name = self._selected_name()
        return name if name is not None else self.registry.get_current_name()

    # ─────────────────── 操作 ───────────────────

    def _create(self):
        name = simpledialog.askstring("新建账号", "请输入新账号名称：", parent=self)
        if not name or not name.strip():
            return
        try:
            final = self.registry.create_account(name)
        except Exception as e:
            messagebox.showerror("新建失败", str(e), parent=self)
            return
        self._refresh()
        self.tree.selection_set(final)
        self._set_status(f"已新建账号「{final}」（切换后首次启动会自动补默认配置）")

    def _rename(self):
        name = self._selected_name()
        if name is None:
            messagebox.showinfo("重命名", "请先在列表中选择一个账号。", parent=self)
            return
        new = simpledialog.askstring("重命名账号", f"将「{name}」重命名为：",
                                     initialvalue=name, parent=self)
        if not new or not new.strip():
            return
        try:
            final = self.registry.rename_account(name, new)
        except Exception as e:
            messagebox.showerror("重命名失败", str(e), parent=self)
            return
        self._refresh()
        self.tree.selection_set(final)
        self._set_status(f"已重命名为「{final}」")

    def _edit_note(self):
        name = self._selected_name()
        if name is None:
            messagebox.showinfo("修改备注", "请先在列表中选择一个账号。", parent=self)
            return
        current = next((a.get("note", "") for a in self.registry.list_accounts()
                        if a.get("name") == name), "")
        new = simpledialog.askstring("修改备注", f"账号「{name}」的备注（留空即清除）：",
                                     initialvalue=current, parent=self)
        if new is None:
            return
        try:
            self.registry.set_note(name, new)
        except Exception as e:
            messagebox.showerror("修改失败", str(e), parent=self)
            return
        self._refresh()
        self.tree.selection_set(name)
        self._set_status(f"已更新「{name}」的备注")

    def _delete(self):
        name = self._selected_name()
        if name is None:
            messagebox.showinfo("删除", "请先在列表中选择一个账号。", parent=self)
            return
        if not messagebox.askyesno(
                "删除账号",
                f"确定删除账号「{name}」吗？\n其配置目录及全部预设将被永久删除，此操作不可恢复。",
                parent=self):
            return
        try:
            self.registry.delete_account(name)
        except Exception as e:
            messagebox.showerror("删除失败", str(e), parent=self)
            return
        self._refresh()
        self._set_status(f"已删除账号「{name}」")

    def _open_folder(self):
        name = self._selected_or_current()
        if not name:
            return
        try:
            acc_dir = self.registry.get_account_dir(name)
            acc_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(acc_dir))
        except Exception as e:
            messagebox.showerror("打开失败", str(e), parent=self)

    def _export(self):
        name = self._selected_or_current()
        if not name:
            messagebox.showinfo("导出", "没有可导出的账号。", parent=self)
            return
        default_name = f"{name}_{datetime.now():%Y%m%d}.account.json"
        dest = filedialog.asksaveasfilename(
            parent=self, title="导出账号包", initialfile=default_name,
            defaultextension=".account.json",
            filetypes=[("账号包", "*.account.json"), ("JSON 文件", "*.json"), ("所有文件", "*.*")])
        if not dest:
            return
        try:
            path = self.registry.export_account(name, dest)
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self)
            return
        self._set_status(f"已导出「{name}」→ {path}")

    def _import_bundle(self):
        src = filedialog.askopenfilename(
            parent=self, title="导入账号包",
            filetypes=[("账号包", "*.account.json"), ("JSON 文件", "*.json"), ("所有文件", "*.*")])
        if not src:
            return
        try:
            final = self.registry.import_account(src)
        except Exception as e:
            messagebox.showerror("导入失败", str(e), parent=self)
            return
        self._refresh()
        self.tree.selection_set(final)
        self._set_status(f"已导入为账号「{final}」")

    def _import_legacy(self):
        src = filedialog.askdirectory(
            parent=self, title="选择旧版账号文件夹（含 global_config.json 的目录）",
            initialdir=str(self.registry.app_root.parent))
        if not src:
            return
        try:
            final = self.registry.import_legacy_folder(src)
        except Exception as e:
            messagebox.showerror("导入失败", str(e), parent=self)
            return
        self._refresh()
        self.tree.selection_set(final)
        self._set_status(f"已从旧版文件夹导入为账号「{final}」（源目录校验无误后已移除）")

    def _switch(self):
        target = self._selected_name()
        if target is None:
            messagebox.showinfo("切换账号", "请先在列表中选择一个账号。", parent=self)
            return
        if target == self.registry.get_current_name():
            messagebox.showinfo("切换账号", f"「{target}」已经是当前账号。", parent=self)
            return
        if not messagebox.askyesno(
                "切换账号",
                f"切换到账号「{target}」将重启应用，\n运行中的战斗任务将会中止。是否继续？",
                parent=self):
            return
        self.destroy()
        self.app._switch_account_and_restart(target)
