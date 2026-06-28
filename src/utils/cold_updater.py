"""
冷更新器
src/utils/cold_updater.py

负责完整包自动更新流程：
- 下载 ZIP 完整包（带进度回调）
- 校验 SHA-256
- 解压到 staging
- 生成 updater.bat（结束 exe → xcopy 替换 → 重启 → 清理）
- execute() 下载校验完成后返回 True（不退出进程），等待用户确认
- apply_pending() 由 GUI 主线程调用，启动 bat + os._exit(0)

成功路径不返回（进程已退出），仅失败时返回 False。
"""

import os
import sys
import shutil
import zipfile
import subprocess
import requests
from pathlib import Path
from typing import Callable, Optional

from .integrity_verifier import IntegrityVerifier


class ColdUpdater:
    """冷更新器 — 自动下载完整包并替换"""

    DOWNLOAD_TIMEOUT = 300  # 5 分钟
    CHUNK_SIZE = 65536       # 64KB
    RETRY_COUNT = 3
    RETRY_DELAY = 2.0
    EXE_NAME = "Izanami Lab.exe"
    APP_DIR_NAME = "Izanami Lab"  # ZIP 内顶层目录名

    # 待应用的冷更新信息（execute 完成后存储，apply_pending 使用）
    _pending_staging: Optional[Path] = None
    _pending_bat: Optional[Path] = None

    @staticmethod
    def execute(
        zip_url: str,
        expected_sha256: str,
        app_dir: Path,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """执行冷更新下载与校验（不退出进程）

        下载 ZIP → 校验 SHA-256 → 解压 → 生成 updater.bat。
        完成后存储 staging 信息到类变量，等待 apply_pending() 应用。

        Args:
            zip_url: ZIP 包下载地址
            expected_sha256: 预期的 ZIP SHA-256
            app_dir: 应用目录（exe 所在目录）
            on_progress: 下载进度回调(downloaded_bytes, total_bytes)

        Returns:
            True 表示下载校验完成，更新已就绪（等待 apply_pending 应用）；
            False 表示下载或校验失败。
        """
        app_dir = Path(app_dir)

        # 准备 staging 目录
        appdata = os.environ.get('APPDATA', str(Path.home()))
        staging = Path(appdata) / "Izanami Lab" / "update" / "cold_staging"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)

        zip_path = staging / "update.zip"
        extract_dir = staging / "extracted"

        # 1. 下载 ZIP
        if not ColdUpdater._download_zip(zip_url, zip_path, on_progress):
            return False

        # 2. 校验 SHA-256
        if expected_sha256:
            actual = IntegrityVerifier.compute_sha256(zip_path)
            if actual.lower() != expected_sha256.lower():
                return False

        # 3. 解压
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
        except (zipfile.BadZipFile, OSError):
            return False

        # 验证解压目录中包含预期的应用目录
        extracted_app = extract_dir / ColdUpdater.APP_DIR_NAME
        if not extracted_app.exists():
            return False

        # 4. 生成 updater.bat
        bat_path = ColdUpdater._generate_updater_bat(extract_dir, app_dir, staging)

        # 5. 存储待应用信息，等待用户确认后由 apply_pending() 应用
        ColdUpdater._pending_staging = staging
        ColdUpdater._pending_bat = bat_path
        return True

    @staticmethod
    def apply_pending() -> bool:
        """应用已就绪的冷更新（启动 updater.bat + os._exit）

        由 GUI 主线程在用户确认后调用。

        Returns:
            True 表示已启动 updater.bat 并即将退出（实际不会返回，os._exit）；
            False 表示无待应用更新或启动失败。
        """
        bat_path = ColdUpdater._pending_bat
        if not bat_path or not bat_path.exists():
            return False

        try:
            subprocess.Popen(
                ["cmd", "/c", str(bat_path)],
                creationflags=subprocess.CREATE_NEW_CONSOLE
                if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0,
                close_fds=True,
            )
        except OSError:
            return False

        # 立即退出（不等待清理，避免文件锁定）
        os._exit(0)
        # 不可达

    @staticmethod
    def has_pending() -> bool:
        """是否存在待应用的冷更新"""
        return bool(ColdUpdater._pending_bat and ColdUpdater._pending_bat.exists())

    @staticmethod
    def _download_zip(
        url: str,
        dest: Path,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """下载 ZIP 文件（带重试和进度回调）"""
        import time

        for attempt in range(ColdUpdater.RETRY_COUNT):
            try:
                with requests.get(
                    url,
                    stream=True,
                    timeout=ColdUpdater.DOWNLOAD_TIMEOUT,
                    headers={'User-Agent': 'Izanami-Lab-ColdUpdater'},
                ) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get('content-length', 0))
                    downloaded = 0
                    with open(dest, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=ColdUpdater.CHUNK_SIZE):
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            if on_progress:
                                try:
                                    on_progress(downloaded, total)
                                except Exception:
                                    pass
                return True
            except (requests.exceptions.RequestException, OSError):
                if attempt < ColdUpdater.RETRY_COUNT - 1:
                    time.sleep(ColdUpdater.RETRY_DELAY * (2 ** attempt))
                    continue
                return False
        return False

    @staticmethod
    def _generate_updater_bat(
        extract_dir: Path,
        app_dir: Path,
        staging_dir: Path,
    ) -> Path:
        """生成 updater.bat

        Args:
            extract_dir: 解压目录（含 "Izanami Lab/" 子目录）
            app_dir: 应用安装目录（exe 所在目录）
            staging_dir: staging 目录（用于清理）

        Returns:
            bat 文件路径
        """
        bat_path = staging_dir / "updater.bat"

        # bat 中路径含空格需用双引号包裹，反斜杠无需转义
        extracted_app = extract_dir / ColdUpdater.APP_DIR_NAME
        exe_path = app_dir / ColdUpdater.EXE_NAME

        bat_content = f"""@echo off
chcp 65001 >nul
echo 正在更新 Izanami Lab...

:: 强制结束 exe
taskkill /im "{ColdUpdater.EXE_NAME}" /f 2>nul

:: 等待 exe 完全退出
:wait_exit
tasklist /fi "imagename eq {ColdUpdater.EXE_NAME}" 2>nul | find /i "{ColdUpdater.EXE_NAME}" >nul
if %errorlevel% equ 0 (
    timeout /t 1 /nobreak >nul
    goto wait_exit
)

:: 替换文件（从解压目录复制到应用目录）
xcopy /E /Y /I "{extracted_app}" "{app_dir}"

:: 重启应用
start "" "{exe_path}"

:: 清理 staging 与自身
rmdir /S /Q "{staging_dir}"
del "%~f0"
"""

        bat_path.write_text(bat_content, encoding='utf-8')
        return bat_path
