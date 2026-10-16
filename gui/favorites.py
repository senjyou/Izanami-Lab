# -*- coding: utf-8 -*-
"""收藏（角色 / 回忆卡）持久化。

为什么单独一个文件而不是塞进 char_config
----------------------------------------
收藏是「浏览/选取的便捷标记」，不是出战参数。char_config[cid] 会在多处被
整体替换（重置选中角色、全部重置、全部应用全局，见 char_params.py），
锁定状态就在那 4 处逐个手工保留；收藏若也放进去，任何一处漏改都会让用户
的收藏静默消失。独立存放后，重置参数永远动不到收藏。

文件随账号走（_USER_DATA），与 presets 同级；格式：

    {"characters": [100301, 101302], "memories": [30035]}

写入走 atomic_write_text（与账号注册表同一原语），避免半截文件。
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Set

from src.utils.account_manager import atomic_write_text

from gui.constants import FAVORITES_PATH

log = logging.getLogger(__name__)

KIND_CHARACTERS = "characters"
KIND_MEMORIES = "memories"


class FavoritesStore:
    """角色 / 回忆卡收藏集合（内存 + JSON 落盘）。

    读取宽容、写入原子：脏数据只跳过该条，不影响其余收藏。
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else FAVORITES_PATH
        self._characters: Set[int] = set()
        self._memories: Set[int] = set()
        self.load()

    # ─────────────────── 读写 ───────────────────

    def load(self) -> None:
        """从磁盘读取收藏；文件缺失/损坏时退化为空集合（不抛异常）。"""
        self._characters = set()
        self._memories = set()
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("收藏文件读取失败（按空收藏处理）%s: %s", self.path, e)
            return
        if not isinstance(data, dict):
            log.warning("收藏文件格式异常（按空收藏处理）%s", self.path)
            return
        self._characters = self._parse_ids(data.get(KIND_CHARACTERS))
        self._memories = self._parse_ids(data.get(KIND_MEMORIES))

    @staticmethod
    def _parse_ids(raw) -> Set[int]:
        ids: Set[int] = set()
        if not isinstance(raw, (list, tuple, set)):
            return ids
        for item in raw:
            try:
                ids.add(int(item))
            except (TypeError, ValueError):
                continue
        return ids

    def save(self) -> None:
        """原子落盘；失败只记日志（收藏丢失不该阻断 GUI 操作）。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                KIND_CHARACTERS: sorted(self._characters),
                KIND_MEMORIES: sorted(self._memories),
            }
            atomic_write_text(self.path, json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception as e:
            log.warning("收藏保存失败（%s）: %s", self.path, e)

    # ─────────────────── 角色 ───────────────────

    def is_char(self, cid: int) -> bool:
        return int(cid) in self._characters

    def toggle_char(self, cid: int) -> bool:
        """切换收藏状态并落盘，返回切换后的状态（True=已收藏）。"""
        cid = int(cid)
        if cid in self._characters:
            self._characters.discard(cid)
            now_favorite = False
        else:
            self._characters.add(cid)
            now_favorite = True
        self.save()
        return now_favorite

    def char_ids(self) -> Set[int]:
        return set(self._characters)

    # ─────────────────── 回忆卡 ───────────────────

    def is_memory(self, mid: int) -> bool:
        return int(mid) in self._memories

    def toggle_memory(self, mid: int) -> bool:
        mid = int(mid)
        if mid in self._memories:
            self._memories.discard(mid)
            now_favorite = False
        else:
            self._memories.add(mid)
            now_favorite = True
        self.save()
        return now_favorite

    def memory_ids(self) -> Set[int]:
        return set(self._memories)
