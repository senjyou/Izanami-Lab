# -*- coding: utf-8 -*-
"""GUI 主题配色方案与解析。

从 gui_app.py 抽取。主题应用方法（apply_window_style / apply_ttk_style / refresh_native_widgets）
仍保留在主类中，将在阶段6随主类精简时迁移为本模块的模块级函数。
"""

from .constants import (
    THEME_SCHEMES,
    THEME_OPTIONS,
    _DEFAULT_SCHEME,
    _DARK_BG,
    _DARK_FG,
    _DARK_SURFACE,
    _DARK_BORDER,
    _DARK_ACCENT,
    _DARK_INPUT_BG,
    _DARK_SELECT_BG,
    _DARK_SELECT_FG,
)


def resolve_scheme(theme_name, is_system_dark=None):
    """将用户选择的主题名解析为配色方案 key

    Args:
        theme_name: 用户选择的主题名（"深色"/"浅色"/"跟随系统"）
        is_system_dark: 可选的系统是否为暗色模式判断函数/值；
                       当 theme_name == "跟随系统" 时使用，None 时默认为 True

    Returns:
        配色方案 key（"dark" 或 "light"）
    """
    if theme_name == "浅色":
        return "light"
    elif theme_name == "跟随系统":
        if is_system_dark is None:
            return "dark"
        return "dark" if is_system_dark else "light"
    else:
        return "dark"


def get_scheme(scheme_key):
    """根据 key 获取配色方案字典，未知 key 回退到 dark"""
    return THEME_SCHEMES.get(scheme_key, THEME_SCHEMES["dark"])
