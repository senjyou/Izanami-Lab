# -*- coding: utf-8 -*-
"""RDPS 表格构建辅助函数。

从 gui_app.py 抽取，供 team/tactical/circle/composite 等 Tab 复用。
"""

from datetime import datetime


def _fmt_rdps_val(v) -> str:
    """格式化 RDPS 数值：浮点保留1位小数，整数无小数"""
    if isinstance(v, float) and v != int(v):
        return f"{v:,.1f}"
    return f"{int(v):,}"


def _build_rdps_tables(rdps_data: dict) -> list:
    """从 RDPS 结果数据构建表格列表

    返回:
        [角色RDPS汇总表, 回忆卡RDPS表(可选), RDPS乘区细分表]
    """
    if not rdps_data:
        return []

    battle_count = rdps_data.get("battle_count", 0)
    suffix = "(场均)" if battle_count and battle_count > 1 else ""

    tables = []
    unit_stats = rdps_data.get("unit_stats", {})
    ally_units = {uid: s for uid, s in unit_stats.items() if s.get("side") == "ally"}

    # 1. 角色 RDPS 汇总表
    if ally_units:
        cols = ["角色", "直接伤害", "增益贡献", "减益贡献", "附魔贡献", "总RDPS"]
        widths = [130, 100, 100, 100, 100, 110]
        aligns = ["w", "e", "e", "e", "e", "e"]
        rows = []
        sorted_units = sorted(ally_units.items(),
                              key=lambda x: x[1].get("total_rdps", 0), reverse=True)
        for uid, s in sorted_units:
            rows.append([
                s.get("name", uid)[:18],
                _fmt_rdps_val(s.get('direct_damage', 0)),
                _fmt_rdps_val(s.get('buff_contribution', 0)),
                _fmt_rdps_val(s.get('debuff_contribution', 0)),
                _fmt_rdps_val(s.get('enchant_contribution', 0)),
                _fmt_rdps_val(s.get('total_rdps', 0)),
            ])
        # 合计行
        rows.append([
            "合计",
            _fmt_rdps_val(sum(s.get('direct_damage', 0) for s in ally_units.values())),
            _fmt_rdps_val(sum(s.get('buff_contribution', 0) for s in ally_units.values())),
            _fmt_rdps_val(sum(s.get('debuff_contribution', 0) for s in ally_units.values())),
            _fmt_rdps_val(sum(s.get('enchant_contribution', 0) for s in ally_units.values())),
            _fmt_rdps_val(sum(s.get('total_rdps', 0) for s in ally_units.values())),
        ])
        tables.append({"title": f"角色RDPS{suffix}", "columns": cols, "rows": rows,
                       "col_widths": widths, "col_aligns": aligns})

    # 2. 回忆卡 RDPS 表
    card_stats = rdps_data.get("memory_card_stats", {})
    if card_stats:
        cols = ["回忆卡", "增益贡献", "减益贡献", "总RDPS"]
        widths = [150, 100, 100, 110]
        aligns = ["w", "e", "e", "e"]
        rows = []
        sorted_cards = sorted(card_stats.items(),
                              key=lambda x: x[1].get("total_rdps", 0), reverse=True)
        for cid, s in sorted_cards:
            rows.append([
                s.get("card_name", str(cid))[:20],
                _fmt_rdps_val(s.get('buff_contribution', 0)),
                _fmt_rdps_val(s.get('debuff_contribution', 0)),
                _fmt_rdps_val(s.get('total_rdps', 0)),
            ])
        tables.append({"title": f"回忆卡RDPS{suffix}", "columns": cols, "rows": rows,
                       "col_widths": widths, "col_aligns": aligns})

    # 3. RDPS 乘区细分表
    if ally_units:
        cols = ["角色", "ATK增益", "DEF减益", "给予伤害", "受击伤害", "暴击", "穿透"]
        widths = [130, 90, 90, 90, 90, 90, 90]
        aligns = ["w", "e", "e", "e", "e", "e", "e"]
        rows = []
        for uid, s in sorted_units:
            detail = s.get("detail", {})
            rows.append([
                s.get("name", uid)[:18],
                _fmt_rdps_val(detail.get('atk_buff', 0)),
                _fmt_rdps_val(detail.get('def_debuff', 0)),
                _fmt_rdps_val(detail.get('dealt_dmg', 0)),
                _fmt_rdps_val(detail.get('received_dmg', 0)),
                _fmt_rdps_val(detail.get('crit', 0)),
                _fmt_rdps_val(detail.get('penetrate', 0)),
            ])
        tables.append({"title": f"RDPS乘区细分{suffix}", "columns": cols, "rows": rows,
                       "col_widths": widths, "col_aligns": aligns})

    return tables


def _build_rdps_summary(rdps_data: dict) -> str:
    """构建 RDPS 守恒验证摘要文本"""
    if not rdps_data:
        return ""
    total = rdps_data.get("total_damage_to_enemies", 0)
    sum_unit = rdps_data.get("sum_unit_rdps", 0)
    sum_card = rdps_data.get("sum_memory_rdps", 0)
    discrepancy = rdps_data.get("discrepancy", 0)
    battle_count = rdps_data.get("battle_count", 0)
    label = f"(场均, {battle_count}场)" if battle_count and battle_count > 1 else ""
    return (f"\n  【RDPS验证{label}】\n"
            f"    对敌方总伤害: {_fmt_rdps_val(total)}\n"
            f"    角色RDPS合计: {_fmt_rdps_val(sum_unit)}\n"
            f"    记忆卡RDPS合计: {_fmt_rdps_val(sum_card)}\n"
            f"    差异: {_fmt_rdps_val(discrepancy)}\n")


def _export_rdps_tracking_log(parent, log_lines):
    """导出 RDPS 追踪日志到文件

    Args:
        parent: tk 父窗口（用于 messagebox/alert）
        log_lines: List[str] 追踪日志行
    """
    if not log_lines:
        from tkinter import messagebox
        messagebox.showinfo("提示", "当前无 RDPS 追踪日志。请先运行单次模拟（需启用RDPS统计）。",
                            parent=parent)
        return

    from tkinter import filedialog, messagebox
    default_name = f"rdps_tracking_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    path = filedialog.asksaveasfilename(
        parent=parent,
        title="导出 RDPS 追踪日志",
        defaultextension=".txt",
        initialfile=default_name,
        filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
    )
    if not path:
        return
    try:
        from src.combat_v2.rdps_tracker import RDPSTracker
        verifier = RDPSTracker()
        verifier._tracking_log = list(log_lines)
        violations = verifier.verify_tracking_log_conservation()

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines))
            f.write("\n\n")
            f.write("=" * 60 + "\n")
            f.write("守恒性验证结果\n")
            f.write("=" * 60 + "\n")
            if not violations:
                f.write("PASS: 所有 track 守恒性检查通过\n")
                f.write("(direct + buff + debuff + enchant == actual_damage for each track)\n")
            else:
                f.write(f"FAIL: {len(violations)} 个 track 违反守恒性\n")
                for v in violations[:20]:
                    f.write(f"  Track #{v['track']}: actual={v['actual']} "
                            f"direct={v['direct']:.1f} buff={v['buff']:.1f} "
                            f"debuff={v['debuff']:.1f} enchant={v['enchant']:.1f} "
                            f"total={v['total']:.1f} diff={v['diff']:.1f}\n")
                if len(violations) > 20:
                    f.write(f"  ... 还有 {len(violations) - 20} 个违反\n")

        msg = f"RDPS 追踪日志已导出：\n{path}\n共 {len(log_lines)} 行。"
        if violations:
            msg += f"\n\n警告：{len(violations)} 个 track 违反守恒性！"
        else:
            msg += "\n\n守恒性验证通过。"
        messagebox.showinfo("完成", msg, parent=parent)
    except Exception as e:
        messagebox.showerror("错误", f"导出失败：{e}", parent=parent)
