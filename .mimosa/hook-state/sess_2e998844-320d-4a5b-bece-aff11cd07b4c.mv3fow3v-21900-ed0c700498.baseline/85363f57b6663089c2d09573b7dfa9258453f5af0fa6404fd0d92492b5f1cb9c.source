#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MGG 战斗模拟器 GUI 入口（保留原文件名以兼容启动脚本）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.account_manager import AccountRegistry


def _show_message(func, title, message):
    """在隐藏的临时 Tk 根上弹原生消息框（主窗口尚未创建）。"""
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        return getattr(messagebox, func)(title, message, parent=root)
    finally:
        root.destroy()


def _pre_start_migration():
    """旧版账号目录迁移。

    必须在导入 gui.app（其常量在导入期解析活动账号目录）之前完成：
    无注册表时把应用根的旧版账号文件收进 accounts/主号，再询问是否导入
    检测到的旧版兄弟账号文件夹。迁移失败不阻断启动（回退应用根，下次重试）。
    """
    registry = AccountRegistry()
    try:
        pending = registry.ensure_root_migrated()
    except Exception as e:
        _show_message("showwarning", "账号迁移失败",
                      f"旧版账号目录迁移失败，本次按旧版目录启动：\n{e}")
        return
    if not pending:
        return

    names = "\n".join(f"  · {p.name}" for p in pending)
    ok = _show_message(
        "askyesno", "检测到旧版账号文件夹",
        f"检测到 {len(pending)} 个旧版账号文件夹：\n{names}\n\n"
        "是否导入到账号管理？\n"
        "（先复制并校验，无误后才移除源文件夹；失败会保留原样）\n\n"
        "注意：迁移后旧文件夹名不再参与任何逻辑，"
        "引用旧路径的脚本请改读 accounts.json 定位当前账号目录。")
    if not ok:
        registry.dismiss_legacy_import()
        return

    lines = []
    for p in pending:
        try:
            name = registry.import_legacy_folder(p)
            lines.append(f"  ✓ {p.name} → 账号「{name}」")
        except Exception as e:
            lines.append(f"  ✗ {p.name} 导入失败（已保留原文件夹）：{e}")
    _show_message("showinfo", "导入完成", "\n".join(lines))


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    _pre_start_migration()
    from gui.app import MGGBattleSimulatorGUI
    MGGBattleSimulatorGUI()
