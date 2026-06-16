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