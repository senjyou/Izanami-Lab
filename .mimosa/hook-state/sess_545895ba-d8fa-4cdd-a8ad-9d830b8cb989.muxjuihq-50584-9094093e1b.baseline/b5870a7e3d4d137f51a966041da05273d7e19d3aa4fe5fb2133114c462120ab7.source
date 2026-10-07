# -*- coding: utf-8 -*-
"""GUI 工具函数：CJK 文本对齐、路径辅助、业务工具。

从 gui_app.py 抽取，供 gui 包内各模块复用。
"""

import os
import sys
import unicodedata
from pathlib import Path
from typing import List


# ─────────────────── CJK 文本视觉宽度对齐工具 ───────────────────

def _str_visual_width(s: str) -> int:
    """计算字符串视觉宽度：CJK全角字符=2，ASCII半角=1"""
    w = 0
    for c in s:
        w += 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
    return w


def _cjk_ljust(s: str, width: int) -> str:
    """左对齐到指定视觉宽度"""
    return s + ' ' * max(0, width - _str_visual_width(s))


def _cjk_rjust(s: str, width: int) -> str:
    """右对齐到指定视觉宽度"""
    return ' ' * max(0, width - _str_visual_width(s)) + s


def _cjk_truncate(s: str, max_width: int, ellipsis: str = "…") -> str:
    """按视觉宽度截断字符串，超出时末尾添加省略号"""
    if _str_visual_width(s) <= max_width:
        return s
    result = []
    width = 0
    ellipsis_w = _str_visual_width(ellipsis)
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
        if width + cw > max_width - ellipsis_w:
            break
        result.append(c)
        width += cw
    return ''.join(result) + ellipsis


def _cjk_fit(s: str, width: int) -> str:
    """截断到指定视觉宽度后左对齐填充，保证输出宽度恒定"""
    return _cjk_ljust(_cjk_truncate(s, width), width)


# ─────────────────── 路径辅助（PyInstaller 兼容） ───────────────────

def get_base_path():
    """获取应用根目录（打包后为 exe 所在目录，开发环境为脚本所在目录）

    注意：本函数在 gui_app.py 顶层调用时 __file__ 指向 gui_app.py，
    其 parent 即 MGGBattleSimulation/，与原行为一致。
    """
    if getattr(sys, 'frozen', False):
        # 打包模式：exe 同级目录（data/ 外置在 exe 旁边）
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent  # gui/utils.py -> gui/ -> MGGBattleSimulation/


def get_internal_path():
    """获取 PyInstaller 内部资源路径（icon 等）"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_user_data_path():
    """获取用户可写数据目录（配置、日志、预设等）"""
    path = Path(os.environ.get('APPDATA', Path.home() / '.config')) / 'Izanami Lab'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_user_config(src_name, dst_path, base_path=None):
    """如果用户配置不存在，从默认模板复制

    Args:
        src_name: data/ 下的源文件名
        dst_path: 目标路径
        base_path: 可选的基础路径（用于定位 data/ 目录），默认使用 get_base_path()
    """
    if dst_path.exists():
        return
    base = base_path if base_path is not None else get_base_path()
    # 优先从外置 data 目录查找，回退到内部资源
    default_src = base / "data" / src_name
    if not default_src.exists():
        default_src = get_internal_path() / "data" / src_name
    if default_src.exists():
        import shutil
        shutil.copy(default_src, dst_path)


# ─────────────────── 业务工具 ───────────────────

def load_supported_ally_ids(data_loader, supported_chars_path) -> set:
    """解析 SUPPORTED_CHARACTERS.md 的"## 己方角色"section，
    提取"称号"列并匹配 characters.json 中 name 字段，返回允许的 character_id 集合。
    解析失败或文件缺失时返回空集合（调用方应在用户模式下回退到"无白名单"以避免锁死）。
    """
    ids: set = set()
    try:
        if not supported_chars_path.exists():
            return ids
        with open(supported_chars_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        # 定位 "## 己方角色" section
        start_idx = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("## 己方角色"):
                start_idx = i + 1
                break
        if start_idx < 0:
            return ids

        # 收集该 section 内的表格行（跳过表头和分隔行），直到遇到 <br />/下一个 ## 或非表格行
        # section 标题与表格之间可能存在空行，跳过空行
        titles: List[str] = []
        for line in lines[start_idx:]:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("## "):
                break
            if stripped.startswith("<br"):
                break
            if not stripped.startswith("|"):
                break
            # 跳过表头分隔行（如 | --- | --- |）
            cells = [c.strip() for c in stripped.split("|")]
            # split("|") 首尾为空字符串，cells[0]=""，cells[1]=称号, cells[2]=角色, cells[3]=简称
            if len(cells) < 2:
                continue
            first_cell = cells[1]
            if not first_cell or set(first_cell) <= {"-", ":"}:
                continue
            if first_cell == "称号":
                continue
            titles.append(first_cell)

        if not titles:
            return ids

        # 匹配 characters.json 中 name 字段
        chars = data_loader.load_characters()
        title_set = set(titles)
        for cid, char in chars.items():
            if getattr(char, "name", None) in title_set:
                ids.add(cid)
    except Exception:
        return ids
    return ids


def get_max_rarity_for(default_rarity: int) -> int:
    """根据默认稀有度计算最大稀有度上限"""
    if default_rarity <= 1:
        return 5
    elif default_rarity <= 3:
        return 7
    else:
        return 14


def get_module_type_ids(char_type):
    """根据角色类型生成模块ID列表"""
    return [int(f"{char_type}1"), int(f"{char_type}2"), int(f"{char_type}3")]


# ─────────────────── 特殊备注信息（心色見つめるムードメーカー EX追踪） ───────────────────

def _format_special_notes_single(notes) -> list:
    """格式化单次模拟的特殊备注信息，返回行列表。

    notes 结构:
        {
            "char_name": str,
            "ex_skill_name": str,
            "ex_uses": [{"targets": [str, ...]}, ...],
            "died": bool,
            "used_ex": bool,
        }
    若 notes 为 None（角色不在己方阵容）则返回空列表。
    """
    if not notes:
        return []
    lines = []
    char_name = notes.get("char_name", "心色見つめるムードメーカー")
    ex_name = notes.get("ex_skill_name", "あったかいの、どうぞ♪")
    lines.append(f"  【备注信息】")
    if notes.get("used_ex"):
        ex_uses = notes.get("ex_uses", [])
        lines.append(f"    {char_name} EX「{ex_name}」目标选择:")
        for i, use in enumerate(ex_uses, 1):
            targets = use.get("targets", [])
            lines.append(f"      第{i}次: {targets}")
    else:
        lines.append(f"    {char_name}未使用EX。")
    return lines


def _format_special_notes_multi(notes_list, n_battles) -> list:
    """格式化多次模拟的特殊备注信息，返回行列表。

    notes_list: 每场战斗的 special_notes（可能为 None）
    n_battles: 总场次数
    """
    # 收集所有非 None 的 notes
    valid_notes = [n for n in notes_list if n]
    if not valid_notes:
        return []

    lines = []
    char_name = valid_notes[0].get("char_name", "心色見つめるムードメーカー")
    ex_name = valid_notes[0].get("ex_skill_name", "あったかいの、どうぞ♪")

    # 统计
    total_ex_uses = 0
    target_counts = {}  # target_name -> selection count
    no_ex_battles = 0    # 角色在场但未使用EX的场次数

    for notes in valid_notes:
        ex_uses = notes.get("ex_uses", [])
        if ex_uses:
            total_ex_uses += len(ex_uses)
            for use in ex_uses:
                for t in use.get("targets", []):
                    target_counts[t] = target_counts.get(t, 0) + 1
        else:
            no_ex_battles += 1

    lines.append(f"  【备注信息】")
    if total_ex_uses > 0:
        lines.append(f"    {char_name} EX「{ex_name}」目标选择概率 (共{total_ex_uses}次EX):")
        # 按概率降序排列，只输出非0概率
        sorted_targets = sorted(target_counts.items(), key=lambda x: -x[1])
        for tname, count in sorted_targets:
            pct = count / total_ex_uses * 100
            lines.append(f"      {tname}: {pct:.1f}% ({count}/{total_ex_uses})")
    else:
        lines.append(f"    {char_name}未使用EX。")

    if no_ex_battles > 0:
        lines.append(f"    (其中{no_ex_battles}场未使用EX)")

    return lines

