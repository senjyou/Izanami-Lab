"""
更新守护进程
src/utils/update_daemon.py

热更新系统的主入口，整合所有子模块：
- VersionChecker: 版本检测
- DiffCalculator: 差异计算
- DownloadScheduler: 文件下载
- IntegrityVerifier: 完整性校验
- PatchEngine: 补丁应用
- RollbackManager: 回滚管理
- UpdateStateStore: 状态持久化

提供统一接口供 GUI 调用
"""

import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Callable, Dict, Any

from .version_checker import VersionChecker, UpdateInfo, UpdateType
from .diff_calculator import DiffCalculator, DiffEntry
from .download_scheduler import DownloadScheduler, DownloadResult
from .integrity_verifier import IntegrityVerifier, VerifyResult
from .patch_engine import PatchEngine, ApplyResult
from .rollback_manager import RollbackManager, SnapshotInfo
from .update_state import UpdateStateStore
from .cold_updater import ColdUpdater


@dataclass
class UpdateProgress:
    """更新进度"""
    status: str                    # IDLE/CHECKING/READY/DOWNLOADING/VERIFYING/APPLYING/COMPLETED/FAILED/ROLLING_BACK
    target_version: Optional[str] = None
    current_version: str = ""
    total_files: int = 0
    completed_files: int = 0
    total_bytes: int = 0
    downloaded_bytes: int = 0
    error_message: Optional[str] = None
    hot_files: List[str] = None
    warm_files: List[str] = None
    update_type: UpdateType = UpdateType.WARM

    def __post_init__(self):
        if self.hot_files is None:
            self.hot_files = []
        if self.warm_files is None:
            self.warm_files = []


class UpdateDaemon:
    """热更新守护进程 — 应用层唯一入口"""

    # 检测间隔（秒）
    CHECK_INTERVAL = 14400  # 4小时
    # 启动后延迟检测（秒）
    STARTUP_DELAY = 5

    def __init__(
        self,
        app_data_dir: str,
        user_data_dir: str,
        repository: str,
        current_version: str,
        release_url: str,
        data_loader=None,
    ):
        """
        Args:
            app_data_dir: 应用数据根目录（含 data/），如 "F:/Izanami Lab/"
            user_data_dir: 用户数据目录，如 "%APPDATA%/Izanami Lab/"
            repository: GitHub 仓库，如 "senjyou/Izanami-Lab"
            current_version: 当前版本号
            release_url: Release 页面 URL
            data_loader: DataLoader 实例
        """
        self._app_data_dir = Path(app_data_dir)
        self._user_data_dir = Path(user_data_dir)
        self._current_version = current_version.lstrip('v')

        # 初始化子模块
        self._state_store = UpdateStateStore(self._user_data_dir)
        self._version_checker = VersionChecker(repository, current_version, release_url)
        self._download_scheduler = DownloadScheduler()
        self._patch_engine = PatchEngine(
            self._app_data_dir,
            self._state_store,
            data_loader=data_loader,
        )
        self._rollback_manager = RollbackManager(self._app_data_dir, self._state_store)

        # 回调
        self._progress_callback: Optional[Callable[[UpdateProgress], None]] = None
        self._refresh_callback: Optional[Callable[[List[str]], None]] = None

        # 线程控制
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._lock = threading.Lock()

        # 当前更新信息
        self._current_update_info: Optional[UpdateInfo] = None
        self._current_diff_list: List[DiffEntry] = []

    # ── 公开接口 ──

    def start(self):
        """启动后台检测（应用启动时调用）"""
        self._running = True

        # 崩溃检测与自动回滚
        self._rollback_manager.check_and_auto_rollback()

        # 确认启动成功
        self._state_store.confirm_startup()

        # 延迟检测
        self._schedule_check(self.STARTUP_DELAY)

    def stop(self):
        """停止后台检测（应用退出时调用）"""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def check_now(self) -> Optional[UpdateProgress]:
        """立即检查更新（手动触发）"""
        return self._do_check(force=True)

    def get_state(self) -> UpdateProgress:
        """获取当前更新状态"""
        state = self._state_store.load_state()
        return UpdateProgress(
            status=state.get("status", "IDLE"),
            target_version=state.get("target_version"),
            current_version=state.get("current_version", self._current_version),
            total_files=state.get("total_files", 0),
            completed_files=state.get("completed_files", 0),
            total_bytes=state.get("total_bytes", 0),
            downloaded_bytes=state.get("downloaded_bytes", 0),
            error_message=state.get("error_message"),
        )

    def pause_download(self):
        """暂停下载"""
        self._download_scheduler.cancel()

    def resume_download(self):
        """恢复下载（重新触发下载流程）"""
        if self._current_update_info and self._current_diff_list:
            threading.Thread(
                target=self._do_download_and_apply,
                daemon=True,
            ).start()

    def cancel_update(self):
        """取消当前更新"""
        self._download_scheduler.cancel()
        self._state_store.update_state_field(status="IDLE")
        if self._current_update_info:
            self._state_store.clean_staging(self._current_update_info.latest_version)

    def rollback(self, version: Optional[str] = None) -> bool:
        """回滚到指定版本"""
        self._state_store.update_state_field(status="ROLLING_BACK")
        self._notify_progress()

        # 查找匹配的快照
        if version:
            snapshots = self._rollback_manager.list_snapshots()
            target = None
            for s in snapshots:
                if s.to_version == version:
                    target = s.snapshot_id
                    break
            success = self._rollback_manager.rollback(target)
        else:
            success = self._rollback_manager.rollback()

        if success:
            self._state_store.update_state_field(status="IDLE")
        else:
            self._state_store.update_state_field(status="FAILED", error_message="回滚失败")
        self._notify_progress()
        return success

    def get_available_rollbacks(self) -> List[SnapshotInfo]:
        """获取可回滚版本列表"""
        return self._rollback_manager.list_snapshots()

    def set_progress_callback(self, callback: Callable[[UpdateProgress], None]):
        """设置进度回调"""
        self._progress_callback = callback

    def set_refresh_callback(self, callback: Callable[[List[str]], None]):
        """设置数据刷新回调"""
        self._refresh_callback = callback
        self._patch_engine._refresh_callback = callback

    # ── 内部方法 ──

    def _schedule_check(self, delay: float):
        """调度下次检测"""
        if not self._running:
            return
        self._timer = threading.Timer(delay, self._periodic_check)
        self._timer.daemon = True
        self._timer.start()

    def _periodic_check(self):
        """定时检测"""
        if not self._running:
            return
        self._do_check(force=False)
        self._schedule_check(self.CHECK_INTERVAL)

    def _do_check(self, force: bool = False) -> Optional[UpdateProgress]:
        """执行版本检测"""
        self._state_store.update_state_field(status="CHECKING")
        self._notify_progress()

        try:
            update_info = self._version_checker.check_for_updates(force=force)
        except Exception as e:
            self._state_store.update_state_field(status="IDLE")
            return None

        if not update_info or not update_info.has_update:
            self._state_store.update_state_field(status="IDLE")
            self._notify_progress()
            return None

        # 冷更新：尝试自动下载完整包
        if update_info.update_type == UpdateType.COLD:
            manifest = update_info.manifest or {}
            zip_url = manifest.get("package_url")
            package_sha256 = manifest.get("package_sha256", "")

            if zip_url and package_sha256:
                # 有完整包信息，执行自动冷更新
                progress = UpdateProgress(
                    status="DOWNLOADING",
                    target_version=update_info.latest_version,
                    current_version=self._current_version,
                    update_type=UpdateType.COLD,
                    total_bytes=1,
                )
                self._notify_progress(progress)

                success = ColdUpdater.execute(
                    zip_url, package_sha256, self._app_data_dir,
                    on_progress=lambda d, t: self._notify_cold_progress(
                        d, t, update_info.latest_version),
                )
                if success:
                    # 下载校验完成，等待用户确认是否重启应用
                    progress = UpdateProgress(
                        status="COLD_UPDATE_DOWNLOADED",
                        target_version=update_info.latest_version,
                        current_version=self._current_version,
                        update_type=UpdateType.COLD,
                    )
                    self._notify_progress(progress)
                else:
                    # 自动冷更新失败，回退到手动下载提示
                    progress = UpdateProgress(
                        status="COLD_UPDATE_REQUIRED",
                        target_version=update_info.latest_version,
                        current_version=self._current_version,
                        update_type=UpdateType.COLD,
                        error_message="完整包下载或校验失败",
                    )
                    self._notify_progress(progress)
            else:
                # 无完整包信息，提示手动下载
                progress = UpdateProgress(
                    status="COLD_UPDATE_REQUIRED",
                    target_version=update_info.latest_version,
                    current_version=self._current_version,
                    update_type=UpdateType.COLD,
                )
                self._notify_progress(progress)
            return progress

        # 有热/温更新
        self._current_update_info = update_info

        # 计算差异
        if update_info.manifest:
            remote_files = DiffCalculator.from_remote_manifest(update_info.manifest)
            local_manifest = self._state_store.load_local_manifest()

            # 如果没有本地 manifest，构建一个（首次更新）
            if not local_manifest:
                local_manifest = self._build_local_manifest()

            self._current_diff_list = DiffCalculator.calculate(local_manifest, remote_files)
        else:
            # 没有 manifest，无法增量更新，降级为完整包下载提示
            progress = UpdateProgress(
                status="COLD_UPDATE_REQUIRED",
                target_version=update_info.latest_version,
                current_version=self._current_version,
                update_type=UpdateType.COLD,
            )
            if self._progress_callback:
                self._progress_callback(progress)
            return progress

        if not self._current_diff_list:
            self._state_store.update_state_field(status="IDLE")
            self._notify_progress()
            return None

        # 自动开始下载
        progress = UpdateProgress(
            status="READY",
            target_version=update_info.latest_version,
            current_version=self._current_version,
            total_files=len(self._current_diff_list),
            update_type=update_info.update_type,
            hot_files=[e.path for e in self._current_diff_list if e.category == "hot" and e.type.value != "delete"],
            warm_files=[e.path for e in self._current_diff_list if e.category == "warm" and e.type.value != "delete"],
        )
        self._notify_progress(progress)

        # 后台下载
        threading.Thread(target=self._do_download_and_apply, daemon=True).start()

        return progress

    def _do_download_and_apply(self):
        """执行下载和应用"""
        if not self._current_update_info or not self._current_diff_list:
            return

        version = self._current_update_info.latest_version
        staging_dir = self._state_store.get_staging_dir(version)

        # ── 下载阶段 ──
        self._state_store.update_state_field(
            status="DOWNLOADING",
            target_version=version,
            total_files=len(self._current_diff_list),
            total_bytes=sum(e.size for e in self._current_diff_list),
        )
        self._notify_progress()

        # 断点续传：获取已下载文件
        already_completed = self._state_store.get_download_progress(version)

        def on_download_progress(completed, total, dl_bytes, total_bytes):
            self._state_store.update_state_field(
                completed_files=completed,
                downloaded_bytes=dl_bytes,
            )
            self._notify_progress()

        download_result: DownloadResult = self._download_scheduler.download_files(
            self._current_diff_list,
            staging_dir,
            already_completed=already_completed,
            on_progress=on_download_progress,
        )

        # 保存下载进度
        self._state_store.save_download_progress(version, download_result.completed_files)

        if not download_result.success:
            self._state_store.update_state_field(
                status="FAILED",
                error_message=f"下载失败: {len(download_result.failed_files)} 个文件",
            )
            self._notify_progress()
            return

        # ── 校验阶段 ──
        self._state_store.update_state_field(status="VERIFYING")
        self._notify_progress()

        manifest_files = [
            {"path": e.path, "sha256": e.sha256}
            for e in self._current_diff_list
            if e.type.value != "delete"
        ]
        verify_result: VerifyResult = IntegrityVerifier.verify_manifest(manifest_files, staging_dir)

        if not verify_result.success:
            self._state_store.update_state_field(
                status="FAILED",
                error_message=f"校验失败: {', '.join(verify_result.failed_files[:5])}",
            )
            self._notify_progress()
            return

        # ── 创建回滚快照 ──
        self._rollback_manager.snapshot(
            self._current_diff_list,
            self._current_version,
            version,
        )

        # ── 应用阶段 ──
        self._state_store.update_state_field(status="APPLYING")
        self._notify_progress()

        apply_result: ApplyResult = self._patch_engine.apply(
            self._current_diff_list,
            staging_dir,
            version,
        )

        if not apply_result.success:
            # 应用失败，自动回滚
            self._rollback_manager.rollback()
            self._state_store.update_state_field(
                status="FAILED",
                error_message=f"应用失败: {', '.join(apply_result.failed_files[:5])}",
            )
            self._notify_progress()
            return

        # ── 完成 ──
        self._state_store.update_state_field(status="COMPLETED")
        self._state_store.clear_download_progress(version)
        self._state_store.clean_staging(version)
        self._rollback_manager.cleanup_old_snapshots(keep=2)

        progress = UpdateProgress(
            status="COMPLETED",
            target_version=version,
            current_version=self._current_version,
            hot_files=apply_result.hot_files,
            warm_files=apply_result.warm_files,
        )
        self._notify_progress(progress)

        # 清理当前更新信息
        self._current_update_info = None
        self._current_diff_list = []

    def _build_local_manifest(self) -> Dict[str, Dict[str, Any]]:
        """构建本地文件清单（首次更新时）"""
        manifest = {}
        data_dir = self._app_data_dir / "data"
        if not data_dir.exists():
            return manifest

        for file_path in sorted(data_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.name.endswith('.default.json'):
                continue
            rel_path = file_path.relative_to(self._app_data_dir)
            path_str = str(rel_path).replace('\\', '/')
            try:
                sha256 = IntegrityVerifier.compute_sha256(file_path)
                manifest[path_str] = {
                    "sha256": sha256,
                    "size": file_path.stat().st_size,
                }
            except OSError:
                continue

        return manifest

    def _notify_cold_progress(self, downloaded_bytes: int, total_bytes: int, target_version: str):
        """通知冷更新下载进度"""
        progress = UpdateProgress(
            status="DOWNLOADING",
            target_version=target_version,
            current_version=self._current_version,
            update_type=UpdateType.COLD,
            downloaded_bytes=downloaded_bytes,
            total_bytes=total_bytes,
        )
        self._notify_progress(progress)

    def _notify_progress(self, progress: UpdateProgress = None):
        """通知进度回调"""
        if not self._progress_callback:
            return
        if progress is None:
            progress = self.get_state()
        try:
            self._progress_callback(progress)
        except Exception:
            pass
