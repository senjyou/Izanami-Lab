# -*- coding: utf-8 -*-
"""批量模拟的纯统计函数（无 Tk 依赖，便于单测与其他 Tab 复用）。

背景
----
「战术演习」页早已有一套完整的批量统计口径（场均 / 最高 / 最低 / Q1 / Q3 /
标准差 / Roll5期望 / 区间分布），「编队与战斗」页此前只有胜率与回合数。
把公式抽到这里，两个 Tab 用同一份实现，避免出现两套互相漂移的 Roll5。

口径（与战术演习保持一致）
------------------------
Roll5 期望 = 每日 5 次取最高分的期望。按经验分布，把样本升序排列后：

    E[max of 5] = Σ_i x_(i) · [(i/N)^5 − ((i−1)/N)^5]

这是**对样本经验分布**的精确求值（不是正态近似），与战术演习页原实现逐位一致。
"""

from typing import Dict, List, Sequence, Tuple


# 得分/伤害区间分布的默认档宽（1kw，与战术演习页一致）
DEFAULT_BUCKET_SIZE = 10_000_000


def mean(values: Sequence[float]) -> float:
    """算术平均；空序列返回 0.0。"""
    if not values:
        return 0.0
    return sum(values) / len(values)


def stdev(values: Sequence[float], mean_value: float = None) -> float:
    """样本标准差（n−1 分母）；样本不足 2 个时返回 0.0。"""
    n = len(values)
    if n < 2:
        return 0.0
    if mean_value is None:
        mean_value = mean(values)
    variance = sum((x - mean_value) ** 2 for x in values) / (n - 1)
    return variance ** 0.5


def quantile(sorted_values: Sequence[float], q: float) -> float:
    """分位数（线性插值法）。

    Args:
        sorted_values: **已升序**排列的数值列表
        q: 分位点 0.0~1.0
    """
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    if n == 1:
        return float(sorted_values[0])
    if n < 4:
        # 样本不足 4 个时，下分位取最小、上分位取最大（避免插值给出无意义值）
        return float(sorted_values[0]) if q <= 0.5 else float(sorted_values[-1])
    pos = (n - 1) * q
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def roll5_expectation(scores: Sequence[float]) -> float:
    """Roll5 期望：5 次独立抽样取最大值的期望（对经验分布精确求值）。"""
    if not scores:
        return 0.0
    xs = sorted(scores)
    n = len(xs)
    total = 0.0
    for i, x in enumerate(xs, start=1):
        p_max = (i / n) ** 5 - ((i - 1) / n) ** 5
        total += x * p_max
    return total


def distribution(values: Sequence[float],
                 bucket_size: int = DEFAULT_BUCKET_SIZE) -> List[Tuple[float, int]]:
    """按固定档宽统计区间分布，返回 [(档下界, 场数), ...]（连续、升序）。

    区间从最低档连续铺到最高档，中间没有样本的档也保留（计数为 0），
    这样输出可以直接画成直方图，不会出现「跳档」。
    """
    if not values:
        return []
    bucket_counts: Dict[int, int] = {}
    for v in values:
        b = int(v // bucket_size)
        bucket_counts[b] = bucket_counts.get(b, 0) + 1
    lo, hi = min(bucket_counts), max(bucket_counts)
    return [(b * bucket_size, bucket_counts.get(b, 0)) for b in range(lo, hi + 1)]


def compute_value_stats(values: Sequence[float],
                        bucket_size: int = DEFAULT_BUCKET_SIZE) -> Dict[str, object]:
    """一次性算出批量模拟需要的全部统计量。

    返回键：
        mean / max / min / q1 / q3 / stdev / roll5_mean / distribution / bucket_size / count
    """
    if not values:
        return {
            "count": 0, "mean": 0.0, "max": 0, "min": 0,
            "q1": 0.0, "q3": 0.0, "stdev": 0.0, "roll5_mean": 0.0,
            "distribution": [], "bucket_size": bucket_size,
        }
    vals = list(values)
    sorted_vals = sorted(vals)
    m = mean(vals)
    return {
        "count": len(vals),
        "mean": m,
        "max": max(vals),
        "min": min(vals),
        "q1": quantile(sorted_vals, 0.25),
        "q3": quantile(sorted_vals, 0.75),
        "stdev": stdev(vals, m),
        "roll5_mean": roll5_expectation(vals),
        "distribution": distribution(vals, bucket_size),
        "bucket_size": bucket_size,
    }


# ── 数值格式化（中文习惯的万/亿） ──────────────────────────────────

def format_short_count(value: float) -> str:
    """把大数格式化成中文可读单位（万/亿），用于区间标签。"""
    if value >= 100_000_000:
        return f"{value / 100_000_000:g}亿"
    return f"{int(value) // 10_000:,}万"


def format_bucket_label(low: float, bucket_size: int) -> str:
    """区间标签，如 `0万~1,000万` / `1.2亿~1.3亿`。"""
    return f"{format_short_count(low)}~{format_short_count(low + bucket_size)}"


def format_avg(value: float) -> str:
    """场均数值：保留 1 位小数并加千分位。"""
    return f"{value:,.1f}"
