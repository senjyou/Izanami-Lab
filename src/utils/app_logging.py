# -*- coding: utf-8 -*-
"""应用日志：把 logging 输出写到确实可写的位置，便于排查启动/保存类故障。

为什么需要它
------------
GUI 里的配置保存大多写成 `except Exception: pass`（或只 `logging.warning`），
而应用从来没有配置过 logging —— 于是「设置保存不上」「点关闭没反应」这类问题
在现场完全没有线索，只能靠猜。

本模块把根 logger 指到第一个可写的 logs/ 目录，顺序为：
    1. exe 同级 logs/（打包版，用户最容易找到）
    2. %APPDATA%/Izanami Lab/logs/（用户侧，一般可写）
    3. 系统临时目录 /IzanamiLab-logs/
全部失败也不影响启动（整体 try/except，且不抛异常）。
"""

import logging
import os
import sys
import tempfile
from pathlib import Path

_CONFIGURED = False


def _candidates():
    out = []
    if getattr(sys, "frozen", False):
        # 打包版：exe 同级
        try:
            out.append(Path(sys.executable).parent / "logs")
        except Exception:
            pass
    else:
        # 开发环境：仓库根
        out.append(Path(__file__).resolve().parent.parent.parent / "logs")
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "Izanami Lab" / "logs")
    out.append(Path(tempfile.gettempdir()) / "IzanamiLab-logs")
    return out


def _writable(directory: Path) -> bool:
    """目录能否真的创建文件（os.access 在 Windows 上不可靠，实测会误报）。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def log_write_probe(paths) -> None:
    """探测并记录关键路径的可写性。

    用于排查「设置保存不上 / 关不掉窗口」：直接把每个配置路径的探测结果写进日志，
    不必再靠猜。传 dict：{名称: 路径}。绝不抛异常。
    """
    lg = logging.getLogger("write_probe")
    for name, p in (paths or {}).items():
        try:
            path = Path(p)
            directory = path.parent if path.suffix else path
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            lg.info("路径可写  OK   %-26s %s", name, path)
        except Exception as e:
            lg.warning("路径不可写 !!  %-26s %s  (%s: %s)",
                       name, p, type(e).__name__, e)


def setup_file_logging(level=logging.INFO):
    """配置日志；返回日志文件路径（无可用位置时返回 None）。绝不抛异常。"""
    global _CONFIGURED
    if _CONFIGURED:
        return getattr(setup_file_logging, "_path", None)
    _CONFIGURED = True
    setup_file_logging._path = None
    try:
        path = None
        for d in _candidates():
            if _writable(d):
                path = d / "app.log"
                break
        handlers = []
        if path is not None:
            try:
                handlers.append(logging.FileHandler(path, encoding="utf-8"))
            except OSError:
                path = None
        if sys.stderr is not None:
            handlers.append(logging.StreamHandler(sys.stderr))
        logging.basicConfig(
            level=level, handlers=handlers, force=True,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        setup_file_logging._path = path
        logging.getLogger(__name__).info("日志已启用: %s", path)
    except Exception:
        pass
    return getattr(setup_file_logging, "_path", None)
