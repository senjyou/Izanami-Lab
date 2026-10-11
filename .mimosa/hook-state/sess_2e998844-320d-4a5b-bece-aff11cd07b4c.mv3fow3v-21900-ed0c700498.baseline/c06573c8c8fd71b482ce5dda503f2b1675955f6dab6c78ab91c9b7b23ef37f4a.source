#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
战斗模拟器共享日志模块
src/combat_v2/battle_logger.py

提供统一的 logger 实例，所有战斗核心服务通过此模块输出日志。
"""

import logging
import sys


def setup_logger(name: str = "MGGBattleSim", level: int = logging.DEBUG) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    fmt = logging.Formatter(
        "[%(levelname)-5s] %(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)

    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str = "MGGBattleSim") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger


_BATTLE_LOGGER = None


def battle_logger() -> logging.Logger:
    global _BATTLE_LOGGER
    if _BATTLE_LOGGER is None:
        _BATTLE_LOGGER = setup_logger("MGGBattleSim", logging.INFO)
    return _BATTLE_LOGGER


class MemoryLogHandler(logging.Handler):
    """将日志记录缓存到内存，供逐步暴击页在暴击决策点中途导出命令台日志。

    挂到 battle_logger() 单例上即可捕获所有战斗服务的命令台输出。
    级别默认 NOTSET，仅捕获 logger 实际 emit 的记录（logger 为 INFO，故收 INFO+），
    与 StreamHandler 输出一致。logging.Handler 自带锁，emit 线程安全。
    """

    def __init__(self):
        super().__init__()
        self._records = []
        self._formatter = logging.Formatter(
            "[%(levelname)-5s] %(asctime)s | %(message)s",
            datefmt="%H:%M:%S",
        )

    def emit(self, record):
        self._records.append(record)

    def get_lines(self):
        """返回格式化后的日志行列表（与 StreamHandler 格式一致）。"""
        lines = []
        for r in self._records:
            try:
                lines.append(self._formatter.format(r))
            except Exception as e:
                lines.append(f"[FORMAT_ERROR] {e} | msg={r.msg!r} args={r.args!r}")
        return lines

    def clear(self):
        self._records.clear()

    def count(self):
        return len(self._records)