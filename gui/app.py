#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MGG 战斗模拟器 GUI 主类（阶段6：从 gui_app.py 迁移）

包含 MGGBattleSimulatorGUI 主类，负责：
  1. 窗口/主题样式管理
  2. 各 Tab 的创建与协调
  3. 配置加载/保存
  4. 更新检查
  5. 角色单位构建（_create_unit）
"""

import sys
import json
import threading
import tkinter as tk
import pywinstyles
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Dict, List, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.data_loader import DataLoader
from src.config.panel_config import PanelConfig, ModuleConfig
from src.config.player_config import SchoolLevels
from src.entities_v2.unit_state import UnitState
from src.entities_v2.enums import Side
from version import __version__, __repository__, __release_url__
from src.utils.update_daemon import UpdateDaemon, UpdateProgress
from src.utils.version_checker import UpdateType
from src.utils.cold_updater import ColdUpdater

# ── gui 包：常量、工具函数、主题配色 ──
from gui.utils import (
    get_internal_path,
    _ensure_user_config,
    load_supported_ally_ids,
    get_module_type_ids,
)
from gui.constants import (
    _BASE_PATH,
    _USER_DATA,
    PRESET_DIR,
    TACTICAL_PRESET_DIR,
    GLOBAL_CONFIG_PATH,
    CHAR_CONFIG_PATH,
    UI_CONFIG_PATH,
    SUPPORTED_CHARACTERS_PATH,
    THEME_SCHEMES,
    THEME_OPTIONS,
)
from gui.widgets.result_table import ResultTablePanel
# ── gui 包：战斗 Tab（阶段4抽取） ──
from gui.tabs.team_battle import TeamBattleTab
from gui.tabs.tactical_exercise import TacticalExerciseTab
from gui.tabs.circle_battle import CircleBattleTab
from gui.tabs.composite_tactic import CompositeTacticExerciseTab
# ── gui 包：非战斗 Tab（阶段5抽取） ──
from gui.tabs.global_params import GlobalParamsTab
from gui.tabs.char_params import CharacterParamsTab
from gui.tabs.custom_dummy import CustomDummyTab
from gui.tabs.step_crit import StepCritTab


# ────────────────────────────── 主 GUI ──────────────────────────────

class MGGBattleSimulatorGUI:
    def format_char_name(self, char) -> str:
        base_name = None
        if hasattr(char, 'character_base_id') and char.character_base_id:
            base_name = self.data_loader.get_character_base_name(char.character_base_id)
        if base_name:
            return f"【{char.name}】{base_name}"
        return char.name

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Izanami Lab v{__version__}")
        self.root.geometry("1400x960")
        # 设置窗口图标
        _icon_path = get_internal_path() / "icon.ico"
        if not _icon_path.exists():
            _icon_path = _BASE_PATH / "icon.ico"
        if _icon_path.exists():
            self.root.iconbitmap(str(_icon_path))

        # 更新守护进程
        self.update_daemon = UpdateDaemon(
            app_data_dir=str(_BASE_PATH),
            user_data_dir=str(_USER_DATA),
            repository=__repository__,
            current_version=__version__,
            release_url=__release_url__,
            data_loader=None,  # DataLoader 尚未创建，后续设置
        )
        self.update_daemon.set_progress_callback(self._on_update_progress)
        self.update_daemon.set_refresh_callback(self._on_data_refresh)

        # 首次运行：从默认模板复制用户配置
        _ensure_user_config("global_config.default.json", GLOBAL_CONFIG_PATH)
        _ensure_user_config("char_config.default.json", CHAR_CONFIG_PATH)
        _ensure_user_config("ui_config.default.json", UI_CONFIG_PATH)
        PRESET_DIR.mkdir(parents=True, exist_ok=True)
        TACTICAL_PRESET_DIR.mkdir(parents=True, exist_ok=True)

        # 加载外观配置
        self._ui_config = self._load_ui_config()
        self._current_scheme = self._resolve_scheme(self._ui_config.get("theme", "深色"))

        self.root.configure(bg=self._get_scheme()["bg"])
        self._apply_window_style()
        self._apply_ttk_style()

        self.data_loader = DataLoader(base_path=str(_BASE_PATH), user_data_dir=str(_USER_DATA))
        self.data_loader.load_all()
        self.data_loader.load_custom_dummies()

        # 设置 UpdateDaemon 的 DataLoader 引用
        self.update_daemon._patch_engine._data_loader = self.data_loader

        chars_data = self.data_loader.load_characters()
        self.char_ids = sorted([int(k) for k in chars_data.keys()])
        self.char_config = {cid: {"override": False} for cid in self.char_ids}
        self._load_char_config()

        # 用户模式下己方编队可选角色白名单（来自 SUPPORTED_CHARACTERS.md）
        self.supported_ally_ids = load_supported_ally_ids(self.data_loader, SUPPORTED_CHARACTERS_PATH)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.global_tab = GlobalParamsTab(self.notebook, self)
        self.char_tab = CharacterParamsTab(self.notebook, self)
        self.dummy_tab = CustomDummyTab(self.notebook, self)
        self.team_tab = TeamBattleTab(self.notebook, self)
        self.step_crit_tab = StepCritTab(self.notebook, self)
        self.tactical_tab = TacticalExerciseTab(self.notebook, self)
        self.circle_tab = CircleBattleTab(self.notebook, self)
        self.composite_tab = CompositeTacticExerciseTab(self.notebook, self)

        self.notebook.add(self.global_tab, text="全局参数")
        self.notebook.add(self.char_tab, text="角色参数")
        self.notebook.add(self.dummy_tab, text="自定义木桩")
        self.notebook.add(self.team_tab, text="编队与战斗")
        self.notebook.add(self.step_crit_tab, text="逐步暴击")
        self.notebook.add(self.tactical_tab, text="战术演习")
        self.notebook.add(self.circle_tab, text="对抗压制战")
        self.notebook.add(self.composite_tab, text="复合战术演习")

        # 主题下拉框（置于 Notebook 标签行右侧）
        self._theme_var = tk.StringVar(value=self._ui_config.get("theme", "深色"))
        self._theme_combo = ttk.Combobox(self.root, textvariable=self._theme_var,
                                         values=THEME_OPTIONS, state="readonly", width=10)
        self._theme_combo.bind("<<ComboboxSelected>>", self._on_theme_change)
        self._theme_combo.place(relx=1.0, y=5, anchor="ne", x=-10)

        # 检查更新按钮
        self._update_btn = ttk.Button(self.root, text="检查更新", command=self._check_updates_ui)
        self._update_btn.place(relx=1.0, y=5, anchor="ne", x=-110)

        # 启动时刷新原生组件颜色（确保浅色主题等非默认主题生效）
        self._refresh_native_widgets()

        # 启动时异步检查更新
        self._start_update_check()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    @staticmethod
    def _is_system_dark():
        """检测 Windows 系统是否为深色模式"""
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        except Exception:
            return True

    def _resolve_scheme(self, theme_name):
        """将用户选择的主题名解析为配色方案 key"""
        if theme_name == "浅色":
            return "light"
        elif theme_name == "跟随系统":
            return "dark" if self._is_system_dark() else "light"
        else:
            return "dark"

    def _get_scheme(self):
        """获取当前配色方案"""
        return THEME_SCHEMES.get(self._current_scheme, THEME_SCHEMES["dark"])

    def is_developer_mode(self):
        """是否为开发者模式"""
        return self._ui_config.get("developer_mode", False)

    def _on_theme_change(self, event=None):
        """主题下拉框切换回调"""
        theme_name = self._theme_var.get()
        self._current_scheme = self._resolve_scheme(theme_name)
        self._apply_window_style()
        self._apply_ttk_style()
        self._refresh_native_widgets()
        # 刷新各Tab中动态颜色的原生tk组件
        self._refresh_tab_themed_widgets()
        self._save_ui_config()
        # 清除 Combobox 选中高亮
        self._theme_combo.selection_clear()
        self._theme_combo.select_clear()

    def _refresh_tab_themed_widgets(self):
        """主题切换后刷新各Tab中使用动态配色的组件"""
        s = self._get_scheme()
        # 角色参数Tab：刷新网格视图（如果在头像模式）
        if hasattr(self, 'char_tab') and getattr(self.char_tab, '_view_mode', None) == "grid":
            self.char_tab._refresh_grid_view()
        # 角色参数Tab：刷新属性筛选图标背景色
        if hasattr(self, 'char_tab'):
            for btn in getattr(self.char_tab, '_filter_buttons', []):
                try:
                    btn.config(bg=s["surface"])
                except Exception:
                    pass
        # 编队与战斗Tab：刷新所有槽位显示和框架背景
        if hasattr(self, 'team_tab'):
            for slot in self.team_tab.friend_slots + self.team_tab.enemy_slots:
                self.team_tab._update_slot_display(slot, slot["cid"])
            # 刷新编队框架容器背景（包括外层容器）
            for frame_name in ['_enemy_main', '_ally_main', '_enemy_form_frame', '_ally_form_frame', '_enemy_mem_frame', '_ally_mem_frame']:
                frame = getattr(self.team_tab, frame_name, None)
                if frame:
                    try:
                        frame.config(bg=s["bg"])
                    except Exception:
                        pass
            # 刷新编队框架背景（外层frame + 内层slot_frame）
            for slot in self.team_tab.friend_slots + self.team_tab.enemy_slots:
                try:
                    slot["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["frame"].config(bg=s["bg"])
                    slot["avatar_label"].config(bg=s["bg"])
                    slot["name_label"].config(bg=s["bg"], fg=s["fg"])
                    slot["clear_btn"].config(bg=s["bg"], fg=s["border"])
                except Exception:
                    pass
            # 刷新回忆卡槽位背景
            for slot in self.team_tab.mem_friend_slots + self.team_tab.mem_enemy_slots:
                try:
                    slot["frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["canvas"].config(bg=s["bg"])
                    # clear_btn 保持红底白字，不随主题变化
                    # 空槽位重绘占位文字（颜色随主题变化）
                    if slot["mid"] is None:
                        canvas = slot["canvas"]
                        CARD_W, CARD_H = 120, 68
                        canvas.delete("all")
                        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                           fill=s["border"], font=("Microsoft YaHei UI", 8))
                except Exception:
                    pass
        # 战术演习Tab：刷新所有槽位显示和框架背景
        if hasattr(self, 'tactical_tab'):
            for slot in self.tactical_tab.friend_slots:
                self.tactical_tab._update_slot_display(slot, slot["cid"])
            # 刷新编队框架容器背景（包括外层容器）
            for frame_name in ['_ally_main', '_ally_form_frame', '_ally_mem_frame']:
                frame = getattr(self.tactical_tab, frame_name, None)
                if frame:
                    try:
                        frame.config(bg=s["bg"])
                    except Exception:
                        pass
            # 刷新编队框架背景（外层frame + 内层slot_frame）
            for slot in self.tactical_tab.friend_slots:
                try:
                    slot["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["frame"].config(bg=s["bg"])
                    slot["avatar_label"].config(bg=s["bg"])
                    slot["name_label"].config(bg=s["bg"], fg=s["fg"])
                    slot["clear_btn"].config(bg=s["bg"], fg=s["border"])
                except Exception:
                    pass
            # 刷新回忆卡槽位背景
            for slot in self.tactical_tab.mem_friend_slots:
                try:
                    slot["frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["canvas"].config(bg=s["bg"])
                    # clear_btn 保持红底白字，不随主题变化
                    # 空槽位重绘占位文字（颜色随主题变化）
                    if slot["mid"] is None:
                        canvas = slot["canvas"]
                        CARD_W, CARD_H = 120, 68
                        canvas.delete("all")
                        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                           fill=s["border"], font=("Microsoft YaHei UI", 8))
                except Exception:
                    pass
        # 对抗压制战Tab：刷新所有槽位显示和框架背景
        if hasattr(self, 'circle_tab'):
            for slot in self.circle_tab.friend_slots:
                self.circle_tab._update_slot_display(slot, slot["cid"])
            for frame_name in ['_ally_main', '_ally_form_frame', '_ally_mem_frame']:
                frame = getattr(self.circle_tab, frame_name, None)
                if frame:
                    try:
                        frame.config(bg=s["bg"])
                    except Exception:
                        pass
            for slot in self.circle_tab.friend_slots:
                try:
                    slot["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["frame"].config(bg=s["bg"])
                    slot["avatar_label"].config(bg=s["bg"])
                    slot["name_label"].config(bg=s["bg"], fg=s["fg"])
                    slot["clear_btn"].config(bg=s["bg"], fg=s["border"])
                except Exception:
                    pass
            for slot in self.circle_tab.mem_friend_slots:
                try:
                    slot["frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["canvas"].config(bg=s["bg"])
                    if slot["mid"] is None:
                        canvas = slot["canvas"]
                        CARD_W, CARD_H = 120, 68
                        canvas.delete("all")
                        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                           fill=s["border"], font=("Microsoft YaHei UI", 8))
                except Exception:
                    pass
            # 敌方网格：刷新背景与槽位显示（含空位文字颜色）
            enemy_grid = getattr(self.circle_tab, '_enemy_grid_frame', None)
            if enemy_grid:
                try:
                    enemy_grid.config(bg=s["bg"])
                except Exception:
                    pass
            for i, widget in enumerate(getattr(self.circle_tab, '_enemy_grid_widgets', [])):
                try:
                    widget["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    widget["frame"].config(bg=s["bg"])
                    enemy_data = self.circle_tab._enemy_slots[i] if i < len(self.circle_tab._enemy_slots) else None
                    self.circle_tab._update_enemy_slot_display(widget, enemy_data)
                except Exception:
                    pass
        # 复合战术演习Tab：刷新当前队伍槽位显示和框架背景
        if hasattr(self, 'composite_tab'):
            ct = self.composite_tab
            # 只刷新当前队伍的显示（共享GUI组件，遍历所有队伍会导致覆盖）
            team_idx = ct._current_team_index
            for slot in ct._teams_slots[team_idx]:
                ct._update_slot_display(slot, slot["cid"])
            for slot in ct._teams_mem_slots[team_idx]:
                ct._update_mem_slot_display(slot, slot["mid"])
            # 刷新队伍管理区域所有 tk.Frame 容器背景
            for frame_name in ['_team_list_frame', '_team_detail_frame', '_order_btn_frame',
                               '_ally_main', '_ally_form_frame', '_ally_mem_frame']:
                frame = getattr(ct, frame_name, None)
                if frame:
                    try:
                        frame.config(bg=s["bg"])
                    except Exception:
                        pass
            # 刷新角色槽位框架背景（所有队伍共享GUI组件，只需刷新一套）
            for slot in ct._teams_slots[team_idx]:
                try:
                    slot["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["frame"].config(bg=s["bg"])
                    slot["avatar_label"].config(bg=s["bg"])
                    slot["name_label"].config(bg=s["bg"], fg=s["fg"])
                    slot["clear_btn"].config(bg=s["bg"], fg=s["border"])
                except Exception:
                    pass
            # 刷新回忆卡槽位背景
            for slot in ct._teams_mem_slots[team_idx]:
                try:
                    slot["frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["canvas"].config(bg=s["bg"])
                    if slot["mid"] is None:
                        canvas = slot["canvas"]
                        CARD_W, CARD_H = 120, 68
                        canvas.delete("all")
                        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                           fill=s["border"], font=("Microsoft YaHei UI", 8))
                except Exception:
                    pass
            # 敌方网格：刷新背景与槽位显示
            enemy_grid = getattr(ct, '_enemy_grid_frame', None)
            if enemy_grid:
                try:
                    enemy_grid.config(bg=s["bg"])
                except Exception:
                    pass
            for i, widget in enumerate(getattr(ct, '_enemy_grid_widgets', [])):
                try:
                    widget["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    widget["frame"].config(bg=s["bg"])
                    enemy_data = ct._enemy_slots[i] if i < len(ct._enemy_slots) else None
                    ct._update_enemy_slot_display(widget, enemy_data)
                except Exception:
                    pass
        # 战斗结果面板：刷新各Tab的ResultTablePanel主题（Text+Treeview配色）
        for tab_attr in ('team_tab', 'tactical_tab', 'circle_tab', 'composite_tab'):
            tab = getattr(self, tab_attr, None)
            if tab is not None and hasattr(tab, '_result_panel'):
                try:
                    tab._result_panel.apply_theme()
                except Exception:
                    pass

    def _start_update_check(self):
        """启动时启动更新守护进程"""
        self.update_daemon.start()

    def _check_updates_ui(self):
        """手动检查更新按钮回调"""
        self._update_btn.config(state="disabled", text="检查中...")
        def check():
            result = self.update_daemon.check_now()
            # 仅在无更新时恢复按钮（有更新时由进度回调管理按钮状态）
            if result is None:
                self.root.after(0, lambda: self._update_btn.config(state="normal", text="检查更新"))
                self.root.after(0, lambda: messagebox.showinfo("检查更新", f"当前已是最新版本 v{__version__}"))
            elif result.status == "COLD_UPDATE_REQUIRED":
                self.root.after(0, lambda: self._update_btn.config(state="normal", text="检查更新"))
                self.root.after(0, lambda: self._show_cold_update_dialog(result))
            else:
                # 有热/温更新，进度回调会管理按钮状态
                self.root.after(0, lambda: self._update_btn.config(state="normal"))
        threading.Thread(target=check, daemon=True).start()

    def _on_update_progress(self, progress: UpdateProgress):
        """更新进度回调（在后台线程中调用，需通过 root.after 回到主线程）"""
        self.root.after(0, lambda: self._handle_update_progress(progress))

    def _handle_update_progress(self, progress: UpdateProgress):
        """在主线程中处理更新进度"""
        status_text = {
            "IDLE": "检查更新",
            "CHECKING": "正在检查更新...",
            "READY": f"发现更新 v{progress.target_version}",
            "DOWNLOADING": f"正在更新 v{progress.target_version} ({progress.completed_files}/{progress.total_files})",
            "VERIFYING": "正在校验文件...",
            "APPLYING": "正在应用更新...",
            "COMPLETED": f"已更新至 v{progress.target_version}",
            "FAILED": f"更新失败",
            "ROLLING_BACK": "正在回滚...",
            "COLD_UPDATE_REQUIRED": f"发现新版本 v{progress.target_version}",
            "COLD_UPDATE_DOWNLOADED": f"更新已就绪 v{progress.target_version}",
        }.get(progress.status, "检查更新")

        self._update_btn.config(text=status_text[:20])

        # 冷更新下载进度（区别于热更新 DOWNLOADING）
        if progress.status == "DOWNLOADING" and progress.update_type == UpdateType.COLD:
            if progress.total_bytes and progress.total_bytes > 0:
                dl_mb = progress.downloaded_bytes // 1024 // 1024
                total_mb = progress.total_bytes // 1024 // 1024
                pct = progress.downloaded_bytes * 100 // progress.total_bytes
                self._update_btn.config(text=f"冷更新 {pct}% ({dl_mb}/{total_mb}MB)")
            else:
                self._update_btn.config(text="冷更新下载中...")
            return  # 冷更新不进入后续 COMPLETED/FAILED 判断

        if progress.status == "COMPLETED":
            warm_count = len(progress.warm_files) if progress.warm_files else 0
            hot_count = len(progress.hot_files) if progress.hot_files else 0
            msg = f"已成功更新至 v{progress.target_version}\n\n"
            if hot_count > 0:
                msg += f"数据更新: {hot_count} 个文件（已即时生效）\n"
            if warm_count > 0:
                msg += f"代码更新: {warm_count} 个文件（重启后生效）\n"
            if warm_count > 0:
                msg += "\n建议重启应用以完成更新。"
            messagebox.showinfo("更新完成", msg)
            self._update_btn.config(text="检查更新")

        elif progress.status == "FAILED":
            messagebox.showwarning("更新失败", progress.error_message or "未知错误")
            self._update_btn.config(text="检查更新")

        elif progress.status == "COLD_UPDATE_REQUIRED":
            self._show_cold_update_dialog(progress)

        elif progress.status == "COLD_UPDATE_DOWNLOADED":
            self._show_cold_update_ready_dialog(progress)

    def _show_cold_update_dialog(self, progress: UpdateProgress):
        """显示冷更新（完整包下载）对话框"""
        message = (
            f"检测到新版本 v{progress.target_version}（当前版本 v{progress.current_version}）\n\n"
            f"此更新包含重大变更，需要下载完整安装包。\n\n"
            f"是否前往下载更新？"
        )
        result = messagebox.askyesno("发现更新", message)
        if result:
            import webbrowser
            webbrowser.open(f"https://github.com/{__repository__}/releases")

    def _show_cold_update_ready_dialog(self, progress: UpdateProgress):
        """冷更新下载校验完成，询问用户是否立即重启应用"""
        message = (
            f"更新 v{progress.target_version} 已下载完成并通过校验。\n\n"
            f"是否立即重启应用以应用更新？\n"
            f"（选择「否」可继续使用当前版本，但需重新检查更新才能再次下载）"
        )
        result = messagebox.askyesno("冷更新已就绪", message)
        if result:
            # 用户确认，启动 updater.bat + os._exit(0)
            if not ColdUpdater.apply_pending():
                messagebox.showerror(
                    "更新失败",
                    "无法启动更新程序，请稍后重试或前往 GitHub 手动下载。",
                )
                self._update_btn.config(state="normal", text="检查更新")
        else:
            # 用户选择稍后，恢复按钮供下次检查
            self._update_btn.config(state="normal", text="检查更新")

    def _on_data_refresh(self, updated_files: list):
        """数据刷新回调（热更新后通知 UI 刷新）"""
        # 通知各 Tab 刷新数据
        if hasattr(self, 'char_tab'):
            # 清除角色相关缓存，触发重新加载
            pass  # 各 Tab 在下次访问时会自动从 DataLoader 重新加载

    def _apply_window_style(self):
        """应用 Windows 窗口样式"""
        s = self._get_scheme()
        try:
            is_dark = self._current_scheme == "dark"
            pywinstyles.apply_style(self.root, "dark" if is_dark else "normal")
            pywinstyles.change_header_color(self.root, color=s["header_color"])
            pywinstyles.change_title_color(self.root, color=s["header_text"])
            pywinstyles.change_border_color(self.root, color=s["border_color"])
        except Exception:
            pass

    def _apply_ttk_style(self):
        """配置 ttk 主题样式（根据当前配色方案）"""
        s = self._get_scheme()
        self.root.configure(bg=s["bg"])

        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=s["bg"], foreground=s["fg"],
                        fieldbackground=s["input_bg"], bordercolor=s["border"],
                        darkcolor=s["bg"], lightcolor=s["bg"],
                        troughcolor=s["surface"], focuscolor=s["accent"],
                        selectbackground=s["select_bg"], selectforeground=s["select_fg"],
                        insertcolor=s["fg"], font=("Microsoft YaHei UI", 9))
        style.map(".", background=[("active", s["surface"])])

        style.configure("TFrame", background=s["bg"])
        style.configure("TLabel", background=s["bg"], foreground=s["fg"])
        style.configure("TButton", background=s["surface"], foreground=s["fg"],
                        padding=6, relief="flat", borderwidth=0)
        style.map("TButton",
                  background=[("active", s["accent"]), ("pressed", s["accent"])],
                  foreground=[("active", s["accent_fg"])])
        style.configure("Accent.TButton", background=s["accent"], foreground=s["accent_fg"],
                        padding=8, font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Accent.TButton",
                  background=[("active", s["accent"]), ("pressed", s["accent"])])

        style.configure("TNotebook", background=s["bg"], borderwidth=0, relief="flat")
        style.configure("TNotebook.Tab",
                        background=s["surface"], foreground=s["fg"],
                        padding=[18, 8], font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", s["bg"]), ("active", s["tab_active_bg"])],
                  foreground=[("selected", s["accent"]), ("active", s["accent"])])

        style.configure("TLabelframe", background=s["bg"], foreground=s["fg"],
                        bordercolor=s["border"], relief="groove")
        style.configure("TLabelframe.Label", background=s["bg"], foreground=s["accent"],
                        font=("Microsoft YaHei UI", 10, "bold"))

        # 模块词条 LabelFrame 使用主文字色（非蓝色）
        style.configure("Gear.TLabelframe.Label", background=s["bg"], foreground=s["fg"],
                        font=("Microsoft YaHei UI", 9, "bold"))

        style.configure("TCombobox", fieldbackground=s["input_bg"], background=s["surface"],
                        foreground=s["fg"], selectbackground=s["select_bg"],
                        selectforeground=s["fg"], bordercolor=s["border"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", s["input_bg"])],
                  selectbackground=[("readonly", s["select_bg"])])

        style.configure("TSpinbox", fieldbackground=s["input_bg"], background=s["surface"],
                        foreground=s["fg"], bordercolor=s["border"],
                        arrowcolor=s["fg"])
        style.map("TSpinbox",
                  fieldbackground=[("readonly", s["input_bg"])])

        style.configure("TEntry", fieldbackground=s["input_bg"], foreground=s["fg"],
                        bordercolor=s["border"], insertcolor=s["fg"])

        style.configure("TCheckbutton", background=s["bg"], foreground=s["fg"],
                        indicatorcolor=s["surface"], indicatorforeground=s["fg"])
        style.map("TCheckbutton",
                  background=[("active", s["bg"])],
                  indicatorcolor=[("selected", s["accent"])])

        style.configure("TRadiobutton", background=s["bg"], foreground=s["fg"],
                        indicatorcolor=s["surface"], indicatorforeground=s["fg"])
        style.map("TRadiobutton",
                  background=[("active", s["bg"])],
                  indicatorcolor=[("selected", s["accent"])])

        style.configure("Treeview", background=s["surface"], foreground=s["fg"],
                        fieldbackground=s["surface"], borderwidth=0,
                        rowheight=28, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", background=s["border"], foreground=s["fg"],
                        font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Treeview",
                  background=[("selected", s["accent"])],
                  foreground=[("selected", s["accent_fg"])])

        style.configure("TSeparator", background=s["border"])

        style.configure("TScale", background=s["bg"], troughcolor=s["surface"])

        style.configure("Horizontal.TScrollbar", background=s["surface"],
                        troughcolor=s["bg"], bordercolor=s["bg"],
                        arrowcolor=s["fg"])
        style.configure("Vertical.TScrollbar", background=s["surface"],
                        troughcolor=s["bg"], bordercolor=s["bg"],
                        arrowcolor=s["fg"])
        style.map("Horizontal.TScrollbar", background=[("active", s["border"])])
        style.map("Vertical.TScrollbar", background=[("active", s["border"])])

        style.configure("TProgressbar", background=s["accent"], troughcolor=s["surface"])

    def _refresh_native_widgets(self):
        """刷新所有原生 tk 组件的颜色（主题切换后调用）"""
        s = self._get_scheme()

        # 递归刷新所有原生 tk 组件
        def _refresh_widget(widget):
            try:
                wclass = widget.winfo_class()
                if wclass == "Canvas":
                    if getattr(widget, '_is_avatar', False):
                        widget.configure(bg=s["surface"], highlightbackground=s["border"])
                    else:
                        widget.configure(bg=s["bg"], highlightthickness=0)
                elif wclass == "Listbox":
                    widget.configure(bg=s["input_bg"], fg=s["fg"],
                                     selectbackground=s["accent"],
                                     selectforeground=s["accent_fg"])
                elif wclass == "Text":
                    widget.configure(bg=s["input_bg"], fg=s["fg"],
                                     insertbackground=s["fg"],
                                     selectbackground=s["select_bg"],
                                     selectforeground=s["select_fg"])
                    # 刷新已有文字的颜色（tag 和默认文字）
                    try:
                        for tag_name in widget.tag_names():
                            widget.tag_configure(tag_name, foreground=s["fg"])
                    except Exception:
                        pass
            except Exception:
                pass
            for child in widget.winfo_children():
                _refresh_widget(child)

        _refresh_widget(self.root)

    def _load_ui_config(self):
        """加载外观配置"""
        if UI_CONFIG_PATH.exists():
            try:
                with open(UI_CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg.setdefault("developer_mode", False)
                return cfg
            except Exception:
                pass
        return {"theme": "深色", "developer_mode": False}

    def _save_ui_config(self):
        """保存外观配置"""
        try:
            UI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            config = {
                "theme": self._theme_var.get(),
                "developer_mode": self._ui_config.get("developer_mode", False),
            }
            with open(UI_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self):
        self.update_daemon.stop()
        self._save_char_config()
        self.data_loader.save_custom_dummies()
        self.root.destroy()

    def _save_char_config(self):
        try:
            CHAR_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            serializable = {}
            for cid, cfg in self.char_config.items():
                serializable[str(cid)] = cfg
            with open(CHAR_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to save char_config: %s", e)

    def _load_char_config(self):
        if not CHAR_CONFIG_PATH.exists():
            return
        try:
            with open(CHAR_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for cid_str, cfg in data.items():
                cid = int(cid_str)
                self.char_config[cid] = cfg
        except Exception:
            pass

    def _propagate_global_level_change(self, new_level: int):
        """全局等级变化时，同步更新所有 override 且非 1 级的角色等级。

        游戏的「链接等级系统」语义：
        - level == 1：角色锁定在 1 级（不加入链接系统），保持不变
        - level != 1：角色加入链接系统，跟随全局等级
        """
        changed_cids = []
        for cid, cfg in self.char_config.items():
            if not cfg.get("override"):
                continue
            saved_level = cfg.get("level")
            if saved_level is None or saved_level == 1:
                continue
            if saved_level != new_level:
                cfg["level"] = new_level
                changed_cids.append(cid)
        if changed_cids:
            self._save_char_config()
            # 若当前角色参数页正在显示受影响角色，刷新详情以同步 Spinbox 与预览
            char_tab = getattr(self, "char_tab", None)
            if char_tab is not None:
                current_cid = getattr(char_tab, "preview_cid", None)
                if current_cid in changed_cids:
                    char_tab._show_detail(current_cid)

    def _build_panel_config_from_gui(self, global_vals: Dict) -> PanelConfig:
        panel = PanelConfig(
            character_level=global_vals["character_level"],
            school_levels=SchoolLevels(**global_vals["school_levels"]),
            equipment_enabled=True,
            equipment_bonuses=global_vals["equipment"],
        )

        default_rarity = global_vals["default_rarity"]
        default_affection = global_vals["default_affection"]
        default_skill_lv = global_vals["default_skill_level"]
        # per-stat 模块 Tier/等级 (HP=0 / 攻击=1 / 防御=2)
        default_mod_tiers = [
            global_vals["default_mod_tier_hp"],
            global_vals["default_mod_tier_atk"],
            global_vals["default_mod_tier_def"],
        ]
        default_mod_levels = [
            global_vals["default_mod_level_hp"],
            global_vals["default_mod_level_atk"],
            global_vals["default_mod_level_def"],
        ]
        default_gear = global_vals["default_gear"]

        for cid in self.char_ids:
            if cid < 0:
                continue
            char = self.data_loader.get_character_by_id(cid)
            if not char:
                continue

            cc = self.char_tab.get_char_config(cid)
            if cc.get("override"):
                panel.rarities[cid] = cc["rarity"]
                panel.affection_levels[cid] = cc["affection"]
                panel.character_levels[cid] = cc["level"]
                tid = get_module_type_ids(char.character_type)
                per_stat_tiers = [cc["mod_tier_hp"], cc["mod_tier_atk"], cc["mod_tier_def"]]
                per_stat_levels = [cc["mod_level_hp"], cc["mod_level_atk"], cc["mod_level_def"]]
                panel.modules[cid] = [
                    ModuleConfig(module_id=mid, tier=per_stat_tiers[grp_idx], level=per_stat_levels[grp_idx],
                                 gear_effects=[g for g in cc["gear"] if g.get("group", 0) == grp_idx])
                    for grp_idx, mid in enumerate(tid)
                ]
                skill_ids = self.data_loader.load_character_skills().get(cid, [])
                saved_levels = cc.get("skill_levels", {})
                if saved_levels:
                    panel.skill_levels[cid] = {
                        sid: saved_levels.get(sid, saved_levels.get(str(sid), cc.get("skill_level", 15)))
                        for sid in skill_ids
                    }
                else:
                    panel.skill_levels[cid] = {sid: cc.get("skill_level", 15) for sid in skill_ids}
            else:
                panel.rarities[cid] = default_rarity
                panel.affection_levels[cid] = default_affection
                tid = get_module_type_ids(char.character_type)
                panel.modules[cid] = [
                    ModuleConfig(module_id=mid, tier=default_mod_tiers[grp_idx],
                                 level=default_mod_levels[grp_idx],
                                 gear_effects=[g for g in default_gear if g.get("group", 0) == grp_idx])
                    for grp_idx, mid in enumerate(tid)
                ]
                skill_ids = self.data_loader.load_character_skills().get(cid, [])
                panel.skill_levels[cid] = {sid: default_skill_lv for sid in skill_ids}

        return panel

    def _compute_max_extra_point(self, skill_ids: list) -> int:
        for sid in skill_ids:
            sk = self.data_loader.get_skill_by_id(sid)
            if sk and sk.skill_type == 3:
                return sk.resource_cost
        return 0  # 无EX技能的单位无EP条

    def _create_unit(self, panel_config, player_config, stat_calculator,
                     char_id, side, pos):
        char = self.data_loader.get_character_by_id(char_id)
        if not char:
            return None

        pt = getattr(char, 'position_type', 0)

        if char_id < 0:
            dummy_cfg = self.data_loader.get_custom_dummy_config(char_id)
            if not dummy_cfg:
                return None
            skill_ids = self.data_loader._custom_character_skills.get(char_id, [])
            max_extra_point = self._compute_max_extra_point(skill_ids)
            side_prefix = "D" if side == Side.ALLY else "E"
            hp = dummy_cfg.hp
            atk = dummy_cfg.attack
            defense = dummy_cfg.defense
            phys_shield = dummy_cfg.permanent_shield_value if dummy_cfg.permanent_shield_type == 1 else 0
            en_shld = dummy_cfg.permanent_shield_value if dummy_cfg.permanent_shield_type == 2 else 0
            all_shield = dummy_cfg.permanent_shield_value if dummy_cfg.permanent_shield_type == 3 else 0
            return UnitState(
                unit_id=f"{side_prefix}_{char_id}",
                name=char.name,
                side=side,
                position=pos,
                character_id=char_id,
                level=1,
                element=char.attribute,
                character_type=char.character_type,
                max_hp=hp,
                current_hp=hp,
                attack=atk,
                defense=defense,
                speed=dummy_cfg.speed,
                crit_rate=dummy_cfg.crit_rate,
                crit_damage=dummy_cfg.crit_damage - 1.5,
                advantage_damage=dummy_cfg.advantage_damage,
                initial_active_point=dummy_cfg.ap,
                initial_passive_point=dummy_cfg.pp,
                max_extra_point=max_extra_point,
                current_ap=dummy_cfg.ap,
                current_pp=dummy_cfg.pp,
                current_ep=0,
                shield=all_shield,
                physical_shield=phys_shield,
                en_shield=en_shld,
                skills=skill_ids,
                skill_levels={sid: 15 for sid in skill_ids},
                skill_cooldowns={},
                role_type=getattr(char, 'role_type', 0),
                position_type=pt,
            )

        char_config = panel_config.get_character_config(char_id, char.default_rarity)
        stats = stat_calculator.calculate_stats(char_config, player_config)
        skills = self.data_loader.load_character_skills().get(char_id, [])
        max_extra_point = self._compute_max_extra_point(skills)
        side_prefix = "F" if side == Side.ALLY else "E"
        hp = stats.hp
        atk = stats.attack
        defense = stats.defense
        return UnitState(
            unit_id=f"{side_prefix}_{char_id}",
            name=char.name,
            side=side,
            position=pos,
            character_id=char_id,
            level=char_config.level,
            element=char.attribute,
            character_type=char.character_type,
            max_hp=hp,
            current_hp=hp,
            attack=atk,
            defense=defense,
            speed=stats.speed,
            crit_rate=stats.critical_rate,
            crit_damage=stats.critical_damage - 1.5,
            advantage_damage=stats.advantage_damage - 1.25,
            initial_active_point=stats.initial_ap,
            initial_passive_point=stats.initial_pp,
            max_extra_point=max_extra_point,
            current_ap=stats.initial_ap,
            current_pp=stats.initial_pp,
            current_ep=0,
            skills=skills,
            skill_levels=char_config.skill_levels,
            skill_cooldowns={},
            role_type=getattr(char, 'role_type', 0),
            position_type=pt,
        )
