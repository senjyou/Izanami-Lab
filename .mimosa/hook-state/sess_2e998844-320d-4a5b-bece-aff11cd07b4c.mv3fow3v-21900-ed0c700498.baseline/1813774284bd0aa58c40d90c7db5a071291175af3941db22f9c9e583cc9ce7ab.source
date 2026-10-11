"""
回滚管理器
src/utils/rollback_manager.py

负责：
- 更新前创建文件快照
- 回滚到指定版本
- 清理旧快照
- 崩溃检测与自动回滚
"""

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any

from .diff_calculator import DiffEntry, DiffType
from .update_state import UpdateStateStore


@dataclass
class SnapshotInfo:
    """快照信息"""
    snapshot_id: str       # 如 "v1.0.4.1_to_v1.0.5.0"
    from_version: str
    to_version: str
    timestamp: float
    file_count: int


class RollbackManager:
    """回滚管理器"""

    def __init__(self, app_data_dir: Path, state_store: UpdateStateStore):
        """
        Args:
            app_data_dir: 应用数据根目录
            state_store: 更新状态存储
        """
        self._app_data_dir = app_data_dir
        self._state_store = state_store

    def snapshot(
        self,
        diff_list: List[DiffEntry],
        from_version: str,
        to_version: str,
    ) -> str:
        """创建回滚快照

        仅备份将被替换或删除的文件（ADD 类型不需要备份）

        Args:
            diff_list: 差异文件列表
            from_version: 当前版本
            to_version: 目标版本

        Returns:
            快照 ID
        """
        snapshot_id = f"{from_version}_to_{to_version}"
        snapshot_dir = self._state_store.get_rollback_dir() / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        backed_up_files = []
        for entry in diff_list:
            if entry.type in (DiffType.MODIFY, DiffType.DELETE):
                source_path = self._app_data_dir / entry.path
                if source_path.exists():
                    # 复制到快照目录，保持相对路径结构
                    dest_path = snapshot_dir / entry.path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, dest_path)
                    backed_up_files.append({
                        "path": entry.path,
                        "sha256": entry.sha256,
                    })

        # 写入快照元信息
        meta = {
            "from_version": from_version,
            "to_version": to_version,
            "timestamp": time.time(),
            "files": backed_up_files,
        }
        meta_path = snapshot_dir / "snapshot_meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return snapshot_id

    def rollback(self, snapshot_id: Optional[str] = None) -> bool:
        """回滚到指定版本

        Args:
            snapshot_id: 快照 ID，None 则使用最近的快照

        Returns:
            是否成功
        """
        rollback_dir = self._state_store.get_rollback_dir()

        if snapshot_id is None:
            # 查找最近的快照
            snapshots = self.list_snapshots()
            if not snapshots:
                return False
            snapshot_id = snapshots[-1].snapshot_id

        snapshot_dir = rollback_dir / snapshot_id
        if not snapshot_dir.exists():
            return False

        # 读取快照元信息
        meta_path = snapshot_dir / "snapshot_meta.json"
        if not meta_path.exists():
            return False

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False

        from_version = meta.get("from_version", "")
        files = meta.get("files", [])

        # 恢复文件
        for file_entry in files:
            path = file_entry["path"]
            source = snapshot_dir / path
            target = self._app_data_dir / path

            if source.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                # 原子替换
                temp_path = target.with_suffix(target.suffix + '.rbtmp')
                shutil.copy2(source, temp_path)
                temp_path.replace(target)

        # 更新 local_manifest 版本号
        local_manifest = self._state_store.load_local_manifest()
        self._state_store.save_local_manifest(from_version, local_manifest)

        # 清除 pending_restart 和 just_updated
        self._state_store.clear_pending_restart()
        self._state_store.clear_just_updated()

        # 清理该快照
        shutil.rmtree(snapshot_dir, ignore_errors=True)

        return True

    def list_snapshots(self) -> List[SnapshotInfo]:
        """列出所有可回滚的版本快照"""
        rollback_dir = self._state_store.get_rollback_dir()
        if not rollback_dir.exists():
            return []

        snapshots = []
        for snapshot_path in sorted(rollback_dir.iterdir()):
            if not snapshot_path.is_dir():
                continue
            meta_path = snapshot_path / "snapshot_meta.json"
            if not meta_path.exists():
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                snapshots.append(SnapshotInfo(
                    snapshot_id=snapshot_path.name,
                    from_version=meta.get("from_version", ""),
                    to_version=meta.get("to_version", ""),
                    timestamp=meta.get("timestamp", 0),
                    file_count=len(meta.get("files", [])),
                ))
            except (json.JSONDecodeError, OSError):
                continue

        # 按时间排序
        snapshots.sort(key=lambda s: s.timestamp)
        return snapshots

    def cleanup_old_snapshots(self, keep: int = 2):
        """清理旧快照，保留最近 N 个"""
        snapshots = self.list_snapshots()
        if len(snapshots) <= keep:
            return

        rollback_dir = self._state_store.get_rollback_dir()
        to_remove = snapshots[:-keep]
        for snapshot in to_remove:
            snapshot_dir = rollback_dir / snapshot.snapshot_id
            if snapshot_dir.exists():
                shutil.rmtree(snapshot_dir, ignore_errors=True)

    def check_and_auto_rollback(self) -> bool:
        """检查崩溃并自动回滚

        Returns:
            是否执行了回滚
        """
        if not self._state_store.is_crash_detected():
            return False

        snapshots = self.list_snapshots()
        if not snapshots:
            self._state_store.clear_just_updated()
            return False

        # 回滚到最近一个快照
        latest = snapshots[-1]
        success = self.rollback(latest.snapshot_id)
        if success:
            self._state_store.clear_just_updated()
        return success
