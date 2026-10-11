"""
下载调度器
src/utils/download_scheduler.py

负责并发下载差异文件，支持：
- 线程池并发下载
- 断点续传（跳过已下载文件）
- 进度回调
- 取消下载
- 失败重试
"""

import time
import shutil
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Callable, Optional

from .diff_calculator import DiffEntry, DiffType
from .integrity_verifier import IntegrityVerifier


@dataclass
class DownloadResult:
    """下载结果"""
    success: bool
    completed_files: List[str] = field(default_factory=list)
    failed_files: List[str] = field(default_factory=list)
    total_bytes: int = 0
    elapsed: float = 0.0


class DownloadScheduler:
    """下载调度器"""

    def __init__(
        self,
        max_concurrent: int = 3,
        chunk_size: int = 8192,
        timeout: int = 30,
        retry_count: int = 3,
        retry_delay: float = 2.0,
    ):
        self._max_concurrent = max_concurrent
        self._chunk_size = chunk_size
        self._timeout = timeout
        self._retry_count = retry_count
        self._retry_delay = retry_delay
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Izanami-Lab-Update-Client',
        })
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._downloaded_bytes = 0
        self._completed_count = 0

    def download_files(
        self,
        diff_list: List[DiffEntry],
        staging_dir: Path,
        already_completed: Optional[List[str]] = None,
        on_progress: Optional[Callable] = None,
    ) -> DownloadResult:
        """下载差异文件到 staging 目录

        Args:
            diff_list: 差异文件列表（仅处理 ADD 和 MODIFY，跳过 DELETE）
            staging_dir: staging 目录
            already_completed: 已下载的文件路径列表（断点续传）
            on_progress: 进度回调 callable(completed, total, downloaded_bytes, total_bytes)

        Returns:
            DownloadResult
        """
        start_time = time.time()
        self._cancel_event.clear()
        self._downloaded_bytes = 0
        self._completed_count = 0

        # 过滤出需要下载的条目（ADD/MODIFY），跳过 DELETE
        download_entries = [e for e in diff_list if e.type in (DiffType.ADD, DiffType.MODIFY)]

        # 断点续传：跳过已完成的文件
        completed_set = set(already_completed or [])
        pending_entries = [e for e in download_entries if e.path not in completed_set]

        total_files = len(download_entries)
        total_bytes = sum(e.size for e in download_entries)

        completed_files = list(completed_set)
        failed_files = []

        # 按文件大小升序排序（小文件优先，快速减少待下载数量）
        pending_entries.sort(key=lambda e: e.size)

        # 初始进度回调
        if on_progress:
            on_progress(len(completed_files), total_files, 0, total_bytes)

        # 使用线程池并发下载
        with ThreadPoolExecutor(max_workers=self._max_concurrent) as executor:
            future_to_entry = {}
            for entry in pending_entries:
                if self._cancel_event.is_set():
                    break
                future = executor.submit(
                    self._download_single,
                    entry,
                    staging_dir,
                )
                future_to_entry[future] = entry

            for future in as_completed(future_to_entry):
                if self._cancel_event.is_set():
                    break

                entry = future_to_entry[future]
                try:
                    success = future.result()
                    if success:
                        with self._lock:
                            completed_files.append(entry.path)
                            self._completed_count += 1
                    else:
                        failed_files.append(entry.path)
                except Exception:
                    failed_files.append(entry.path)

                if on_progress:
                    with self._lock:
                        on_progress(
                            len(completed_files),
                            total_files,
                            self._downloaded_bytes,
                            total_bytes,
                        )

        elapsed = time.time() - start_time
        return DownloadResult(
            success=len(failed_files) == 0,
            completed_files=completed_files,
            failed_files=failed_files,
            total_bytes=self._downloaded_bytes,
            elapsed=elapsed,
        )

    def _download_single(self, entry: DiffEntry, staging_dir: Path) -> bool:
        """下载单个文件（含重试和校验）

        Returns:
            是否成功
        """
        for attempt in range(self._retry_count):
            if self._cancel_event.is_set():
                return False

            try:
                # 确保目标目录存在
                target_path = staging_dir / entry.path
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # 下载文件
                response = self._session.get(entry.url, timeout=self._timeout, stream=True)
                response.raise_for_status()

                # 写入临时文件
                temp_path = target_path.with_suffix(target_path.suffix + '.downloading')
                downloaded = 0
                with open(temp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=self._chunk_size):
                        if self._cancel_event.is_set():
                            temp_path.unlink(missing_ok=True)
                            return False
                        f.write(chunk)
                        downloaded += len(chunk)

                with self._lock:
                    self._downloaded_bytes += downloaded

                # 校验 SHA-256
                if entry.sha256:
                    if not IntegrityVerifier.verify_file(temp_path, entry.sha256):
                        temp_path.unlink(missing_ok=True)
                        if attempt < self._retry_count - 1:
                            time.sleep(self._retry_delay * (2 ** attempt))
                            continue
                        return False

                # 重命名为最终文件名
                temp_path.replace(target_path)
                return True

            except (requests.exceptions.RequestException, OSError) as e:
                if attempt < self._retry_count - 1:
                    time.sleep(self._retry_delay * (2 ** attempt))
                    continue
                return False

        return False

    def cancel(self):
        """取消所有下载"""
        self._cancel_event.set()
