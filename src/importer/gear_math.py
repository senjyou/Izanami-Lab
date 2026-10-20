# -*- coding: utf-8 -*-
"""词条数值的精度还原（纯 Python，零依赖）。

## 游戏侧的反编译证据

二进制：``dump/GameAssembly.dll``（IL2CPP，x64）
类：``Assets.GameUi.Services.GearCustomValueService``（dump.cs L60632）

该类声明 ``private const int DecimalPlaces = 4;``（dump.cs L60635）。

### A. ``GetActualGearCustomEffectValue(float baseEffectValue, float lossRate)``
    RVA 0x12B4930（dump.cs L60647）：

        0x12B4983  movss  xmm6, [1.0f]        ; xmm8 = baseEffectValue, xmm7 = lossRate
        0x12B498B  subss  xmm6, xmm7          ; 1 - lossRate         （float32）
        0x12B498F  mulss  xmm6, xmm8          ; * baseEffectValue    （float32）
        0x12B49B0  cvtps2pd xmm6, xmm6        ; → double
        0x12B49C7  mov    edx, 4              ; decimalPlaces = 4
        0x12B49CF  call   System.Math::Round(double, int)   ; ToEven
        0x12B49E4  cvtsd2ss xmm0, xmm0        ; → float
    ⇒ ``f32(1-loss) → f32*base → double → Round(…, 4) → float``

### B. ``GetGearCustomEffectValue(ModuleGear, ValueType)`` 的 Percentage 分支
    RVA 0x12B4B1D..0x12B4B3A（dump.cs L60644；``ValueType``：Percentage=0, Actual=1）：

        0x12B4B1D  movss  xmm0, [1.0f]
        0x12B4B25  subss  xmm0, xmm7         ; 1 - lossRate        （float32）
        0x12B4B29  mulss  xmm0, xmm6         ; * baseEffectValue   （float32）
        0x12B4B2D  mulss  xmm0, [10000.0f]   ; ×10000              （float32）
        0x12B4B35  call   0x180798330        ; MathF.Floor（见下）
        0x12B4B3A  divss  xmm0, [100.0f]     ; /100                （float32）

    0x180798330 即 ``System.MathF::Round`` 的 SSE4.1 分支
    （``roundss xmm0, xmm0, imm8=9`` → 向 -inf；软件回退路径在 |x|<1 且 x<0 时
    直接返回 -1.0f，正是 floor；truncate 会返回 0）。

同一 UI 显示链在 ``GearResultWindowController.<>c.<GetAfterCustomAbilities>b__17_0/_2``
（RVA 0x1931250 / 0x1931270）被内联复用：

    0x19312CE  mulss  xmm6, [10000.0f]
    0x19312D9  call   0x180798330
    0x19312DE  divss  xmm0, [100.0f]

## 两套口径分别用在哪（2026-10-19/20 用户真机实测确认）

| | 公式 | 速度彩S | 游戏里用在哪 |
|---|---|---|---|
| A ``GetActualGearCustomEffectValue`` | ``Math.Round(f32(1-loss)×base, 4)`` | 7.2 | **属性面板**（用户实测：只有用 2.5/7.2 才算得完全对） |
| B ``GetGearCustomEffectValue(Percentage)`` | ``floor(f32(1-loss)×base×10000)/100`` | 7.19 | **词条显示**（用户实测：词条里写 2.49/7.19） |

两者只在「×10000 后略微小于整数」时分叉，差值恒为 ``0.01``：

    速度彩S 无损耗：f32×10000 = 719.9999389648438
      A：Math.Round(0.0719999969, 4) = 0.072  → 7.2
      B：floor(719.9999389648438) = 719 → /100 → 7.19

## 模拟器怎么用（2026-10-20 用户决定）

**战斗采用 B 口径**（词条显示口径）。理由：战斗在服务端结算，客户端这两个方法
都只反映客户端自己的显示，不代表服务端算法；B 是玩家能在游戏里直接看到、
也是唯一可核对的口径。因此 :func:`gear_value_percent` 与
:func:`gear_display_percent` 当前同值，配置里仍分开存两个字段，
以便将来若拿到服务端证据可以只改战斗口径而不动界面。

旧实现用 Python double 精确计算再 ``round(…, 4)``，会得出 12.375 / 2.4975 / 7.2 这类
"数学上干净"的值；游戏因为 float32 的表示误差，`速度彩S` 的 ×10000 落在
``719.9999389648438``，被 floor 成 ``719``，显示 **7.19%**（不是 7.2%）。
本账号 292 条有效词条中 **66 条**因此不符。

用户实测对照（2026-10-19）：

| 词条 | 游戏显示 | 旧实现（错） | 现在 |
|---|---|---|---|
| 攻击力 彩S（25% 损耗） | 2.49% | 2.4975% | **2.49%** |
| 速度 彩S（无损耗） | 7.19% | 7.2% | **7.19%** |
"""
from __future__ import annotations

import math
import struct
from typing import Tuple

__all__ = [
    "to_float32",
    "round_half_even",
    "actual_ratio",
    "actual_percent",
    "display_percent",
    "gear_value_percent",
    "gear_display_percent",
    "GEAR_VALUE_DECIMALS",
]

#: 游戏 ``GearCustomValueService.DecimalPlaces``
GEAR_VALUE_DECIMALS = 4


def to_float32(value: float) -> float:
    """按 IEEE-754 binary32 舍入（复现 C# ``float`` 的运算/存储）。"""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def round_half_even(value: float, digits: int) -> float:
    """复现 .NET ``Math.Round(double, digits)``（默认 MidpointRounding.ToEven）。

    先按 ``10**digits`` 缩放，再"四舍六入五取偶"，最后缩回。
    """
    scale = 10 ** digits
    scaled = value * scale
    floor = math.floor(scaled)
    diff = scaled - floor
    if diff > 0.5:
        rounded = floor + 1
    elif diff < 0.5:
        rounded = floor
    else:
        rounded = floor if int(floor) % 2 == 0 else floor + 1
    return rounded / scale


def actual_ratio(base_effect_value: float, loss_rate: float) -> float:
    """A 口径：``GetActualGearCustomEffectValue`` → 实际比率（如 0.1238）。"""
    value = to_float32(to_float32(1.0) - to_float32(loss_rate))
    value = to_float32(value * to_float32(base_effect_value))
    return to_float32(round_half_even(value, GEAR_VALUE_DECIMALS))


def actual_percent(base_effect_value: float, loss_rate: float) -> float:
    """A 口径的百分数（战斗实际生效值，如 7.2）。"""
    return round(actual_ratio(base_effect_value, loss_rate) * 100.0, 2)


def display_percent(base_effect_value: float, loss_rate: float) -> float:
    """B 口径：``GetGearCustomEffectValue(Percentage)`` / UI 显示 → 百分数（如 2.49）。

    这就是游戏**显示**词条数值的那条链：``f32 链 → ×10000 → floor → /100``。
    注意中间没有 ``Math.Round(…, 4)``——加上它会把 719.9999 拉回 720（显示 7.2），
    而游戏实际显示 7.19。
    """
    value = to_float32(to_float32(1.0) - to_float32(loss_rate))
    value = to_float32(value * to_float32(base_effect_value))
    scaled = to_float32(value * to_float32(10000.0))
    return to_float32(to_float32(math.floor(scaled)) / to_float32(100.0))


def gear_value_percent(base_effect_value: float, loss_rate: float) -> float:
    """写入模拟器配置的主数值（**战斗口径 = B 口径**，2 位小数）。

    用户在 2026-10-20 决定：**战斗采用词条显示口径 B**，而不是客户端
    ``GetActualGearCustomEffectValue`` 的 A 口径。

    理由：战斗在服务端结算，客户端那两个方法都只反映客户端自己的显示/属性面板，
    并不代表服务端算法；而 B 是玩家能在游戏里直接看到、也是唯一可核对的口径。

    模拟器 ``stat_calculator`` 内部会再 ``/100``，所以这里给"百分数"。
    公式与 :func:`gear_display_percent` 相同（见该函数说明）。
    """
    return round(display_percent(base_effect_value, loss_rate), 2)


def gear_display_percent(base_effect_value: float, loss_rate: float) -> float:
    """写入配置的"显示值"（**显示口径** = B 口径，2 位小数）。

    与游戏 UI 一致：``floor(×10000)/100``。与 :func:`gear_value_percent`
    当前同值（战斗也采用 B）；保留独立字段是为了将来若确认服务端用 A，
    可以只改 :func:`gear_value_percent` 而不动界面展示。
    """
    return round(display_percent(base_effect_value, loss_rate), 2)

