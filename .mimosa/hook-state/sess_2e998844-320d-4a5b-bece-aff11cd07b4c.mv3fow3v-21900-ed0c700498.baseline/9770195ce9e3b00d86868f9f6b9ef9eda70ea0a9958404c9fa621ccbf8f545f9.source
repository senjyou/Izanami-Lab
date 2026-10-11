"""
更新状态持久化
src/utils/update_state.py

管理热更新系统的状态存储，包括：
- 更新状态（IDLE/CHECKING/DOWNLOADING/VERIFYING/APPLYING/COMPLETED/FAILED）
- 本地文件清单（local_manifest.json）
- 下载进度（断点续传）
- 待重启标记（温更新）
- 崩溃检测标记
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any


@dataclass
class UpdateState:
    """更新状态数据类"""
    status: str = "IDLE"  # IDLE/CHECKING/READY/DOWNLOADING/VERIFYING/APPLYING/COMPLETED/FAILED/ROLLING_BACK
    target_version: Optional[str] = None
    current_version: str = ""
    total_files: int = 0
    completed_files: int = 0
    total_bytes: int = 0
    downloaded_bytes: int = 0
    error_message: Optional[str] = None
    started_at: Optional[float] = None
    updated_at: Optional[float] = None


@dataclass
class FileEntry:
    """文件清单条目"""
    sha256: str
    size: int


class UpdateStateStore:
    """更新状态持久化管理器"""

    STATE_FILE = "update_state.json"
    MANIFEST_FILE = "local_manifest.json"

    def __init__(self, user_data_dir: Path):
        """
        Args:
            user_data_dir: 用户数据目录（如 %APPDATA%/Izanami Lab/）
        """
        self._dir = user_data_dir / "update"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self._dir / self.STATE_FILE
        self._manifest_path = self._dir / self.MANIFEST_FILE

    # ── 更新状态 ──

    def load_state(self) -> Dict[str, Any]:
        """加载更新状态"""
        if not self._state_path.exists():
            return self._default_state()
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return self._default_state()

    def save_state(self, state: Dict[str, Any]):
        """保存更新状态"""
        state["updated_at"] = time.time()
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def update_state_field(self, **kwargs):
        """更新状态中的指定字段"""
        state = self.load_state()
        state.update(kwargs)
        self.save_state(state)

    def _default_state(self) -> Dict[str, Any]:
        """默认状态"""
        return {
            "status": "IDLE",
            "target_version": None,
            "current_version": "",
            "total_files": 0,
            "completed_files": 0,
            "total_bytes": 0,
            "downloaded_bytes": 0,
            "error_message": None,
            "started_at": None,
            "updated_at": None,
            "downloads": {},
            "pending_restart": None,
            "just_updated": False,
            "startup_confirmed": True,
        }

    # ── 下载进度（断点续传） ──

    def save_download_progress(self, version: str, completed_files: List[str]):
        """保存下载进度"""
        state = self.load_state()
        if "downloads" not in state:
            state["downloads"] = {}
        state["downloads"][version] = {
            "completed_files": completed_files,
            "timestamp": time.time(),
        }
        self.save_state(state)

    def get_download_progress(self, version: str) -> List[str]:
        """获取已下载文件列表（用于断点续传）"""
        state = self.load_state()
        return state.get("downloads", {}).get(version, {}).get("completed_files", [])

    def clear_download_progress(self, version: str):
        """清除指定版本的下载进度"""
        state = self.load_state()
        state.get("downloads", {}).pop(version, None)
        self.save_state(state)

    # ── 待重启标记 ──

    def mark_pending_restart(self, version: str, files: List[str]):
        """标记温更新待重启"""
        state = self.load_state()
        state["pending_restart"] = {
            "version": version,
            "files": files,
            "timestamp": time.time(),
        }
        state["just_updated"] = True
        state["startup_confirmed"] = False
        self.save_state(state)

    def get_pending_restart(self) -> Optional[Dict]:
        """获取待重启信息"""
        state = self.load_state()
        return state.get("pending_restart")

    def clear_pending_restart(self):
        """清除待重启标记"""
        state = self.load_state()
        state["pending_restart"] = None
        self.save_state(state)

    # ── 崩溃检测 ──

    def mark_just_updated(self):
        """标记刚完成更新（用于崩溃检测）"""
        state = self.load_state()
        state["just_updated"] = True
        state["startup_confirmed"] = False
        self.save_state(state)

    def confirm_startup(self):
        """确认启动成功（崩溃检测用）"""
        state = self.load_state()
        state["startup_confirmed"] = True
        self.save_state(state)

    def is_crash_detected(self) -> bool:
        """检测是否因更新后崩溃"""
        state = self.load_state()
        return state.get("just_updated", False) and not state.get("startup_confirmed", True)

    def clear_just_updated(self):
        """清除 just_updated 标记"""
        state = self.load_state()
        state["just_updated"] = False
        state["startup_confirmed"] = True
        self.save_state(state)

    # ── 本地文件清单 ──

    def load_local_manifest(self) -> Dict[str, Dict[str, Any]]:
        """加载本地文件清单"""
        if not self._manifest_path.exists():
            return {}
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("files", {})
        except (json.JSONDecodeError, OSError):
            return {}

    def save_local_manifest(self, version: str, files: Dict[str, Dict[str, Any]]):
        """保存本地文件清单"""
        manifest = {
            "version": version,
            "files": files,
            "updated_at": time.time(),
        }
        with open(self._manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    def update_local_manifest(self, version: str, added_or_modified: Dict[str, Dict[str, Any]],
                              deleted: List[str] = None):
        """增量更新本地文件清单"""
        files = self.load_local_manifest()
        # 添加/修改
        files.update(added_or_modified)
        # 删除
        if deleted:
            for path in deleted:
                files.pop(path, None)
        self.save_local_manifest(version, files)

    def get_local_version(self) -> str:
        """获取本地清单中的版本号"""
        if not self._manifest_path.exists():
            return ""
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("version", "")
        except (json.JSONDecodeError, OSError):
            return ""

    # ── Staging 目录 ──

    def get_staging_dir(self, version: str) -> Path:
        """获取指定版本的 staging 目录"""
        d = self._dir / "staging" / version
        d.mkdir(parents=True, exist_ok=True)
        return d

    def clean_staging(self, version: str = None):
        """清理 staging 目录"""
        staging = self._dir / "staging"
        if version:
            target = staging / version
            if target.exists():
                import shutil
                shutil.rmtree(target, ignore_errors=True)
        else:
            if staging.exists():
                import shutil
                shutil.rmtree(staging, ignore_errors=True)

    # ── Rollback 目录 ──

    def get_rollback_dir(self) -> Path:
        """获取回滚快照根目录"""
        d = self._dir / "rollback"
        d.mkdir(parents=True, exist_ok=True)
        return d
