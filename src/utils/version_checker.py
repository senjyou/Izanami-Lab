"""
版本检测器
src/utils/version_checker.py

升级自 UpdateManager，增加：
- 四段式版本号比较（major.minor.patch.build）
- 远程 manifest 获取
- 更新类型判断（hot/warm/cold）
"""

import re
import time
import requests
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, Dict, Any


class UpdateType(Enum):
    """更新类型"""
    HOT = "hot"      # 数据更新，即时生效
    WARM = "warm"    # 代码更新，重启生效
    COLD = "cold"    # 完整包更新


@dataclass
class UpdateInfo:
    """更新信息"""
    has_update: bool
    current_version: str
    latest_version: str
    release_url: str
    release_notes: str = ""
    published_at: str = ""
    update_type: UpdateType = UpdateType.WARM
    manifest: Optional[Dict[str, Any]] = None


def parse_version(version_str: str) -> Tuple[int, int, int, int]:
    """解析四段式版本号

    Args:
        version_str: 版本号字符串，如 "1.0.4.1" 或 "v1.0.4.1"

    Returns:
        (major, minor, patch, build) 四元组
    """
    version_str = version_str.lstrip('v')
    parts = version_str.split('.') if version_str else []
    return (
        int(parts[0]) if len(parts) > 0 and parts[0] else 0,
        int(parts[1]) if len(parts) > 1 and parts[1] else 0,
        int(parts[2]) if len(parts) > 2 and parts[2] else 0,
        int(parts[3]) if len(parts) > 3 and parts[3] else 0,
    )


class VersionChecker:
    """版本检测器"""

    def __init__(self, repository: str, current_version: str, release_url: str):
        self.repository = repository
        self.current_version = current_version.lstrip('v')
        self.release_url = release_url
        self.api_url = f"https://api.github.com/repos/{repository}/releases/latest"
        self.html_url = f"https://github.com/{repository}/releases"
        self._last_check_time = 0
        self._check_interval = 14400  # 4小时
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': f'Izanami-Lab/{current_version}',
            'Accept': 'application/vnd.github.v3+json',
        })

    def _compare_versions(self, latest: str) -> bool:
        """比较版本号，判断是否有更新"""
        current = parse_version(self.current_version)
        latest_parsed = parse_version(latest)
        return latest_parsed > current

    def _determine_update_type(self, latest: str, manifest: Optional[Dict] = None) -> UpdateType:
        """判断更新类型

        规则：
        - major 变化 → cold
        - minor 变化 → warm
        - patch/build 变化 → 由 manifest 中的 update_type 决定，默认 warm
        """
        current = parse_version(self.current_version)
        remote = parse_version(latest)

        if remote[0] > current[0]:  # major 变化
            return UpdateType.COLD
        if remote[1] > current[1]:  # minor 变化
            return UpdateType.WARM

        # patch/build 变化，由 manifest 决定
        if manifest and "update_type" in manifest:
            try:
                return UpdateType(manifest["update_type"])
            except ValueError:
                pass
        return UpdateType.WARM

    def _fetch_via_api(self) -> Optional[Dict[str, Any]]:
        """通过 GitHub API 获取最新 Release 信息"""
        try:
            response = self._session.get(self.api_url, timeout=10)
            if response.status_code == 403:
                return None
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.RequestException, KeyError, ValueError):
            return None

    def _fetch_via_html(self) -> Optional[Tuple[str, str]]:
        """通过 HTML 页面解析获取最新版本号和 URL"""
        try:
            response = requests.get(self.html_url, timeout=10, headers={
                'User-Agent': f'Izanami-Lab/{self.current_version}',
            })
            response.raise_for_status()
            html = response.text

            match = re.search(r'/releases/tag/(v[\d.]+)"', html)
            if not match:
                return None

            latest_version = match.group(1).lstrip('v')
            return latest_version, self.html_url
        except (requests.exceptions.RequestException, AttributeError):
            return None

    def _fetch_manifest(self, release_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """从 Release 资产中获取 manifest.json"""
        assets = release_data.get("assets", [])
        for asset in assets:
            if asset.get("name") == "manifest.json":
                url = asset.get("browser_download_url") or asset.get("url")
                if not url:
                    continue
                try:
                    # 使用 browser_download_url 直接下载
                    resp = self._session.get(url, timeout=15)
                    resp.raise_for_status()
                    return resp.json()
                except (requests.exceptions.RequestException, ValueError):
                    continue
        return None

    def check_for_updates(self, force: bool = False) -> Optional[UpdateInfo]:
        """检查更新

        Args:
            force: 是否强制检查（忽略频率限制）

        Returns:
            UpdateInfo 或 None（检查失败时）
        """
        now = time.time()
        if not force and now - self._last_check_time < self._check_interval:
            return None

        self._last_check_time = now

        # 优先 API 方式
        release_data = self._fetch_via_api()
        if release_data is not None:
            latest_version = release_data.get('tag_name', '').lstrip('v')
            release_notes = release_data.get('body', '')
            published_at = release_data.get('published_at', '')
            html_url = release_data.get('html_url', self.release_url)

            if not latest_version:
                return None

            has_update = self._compare_versions(latest_version)
            manifest = self._fetch_manifest(release_data) if has_update else None
            update_type = self._determine_update_type(latest_version, manifest) if has_update else UpdateType.WARM

            return UpdateInfo(
                has_update=has_update,
                current_version=self.current_version,
                latest_version=latest_version,
                release_url=html_url,
                release_notes=release_notes,
                published_at=published_at,
                update_type=update_type,
                manifest=manifest,
            )

        # 回退 HTML 方式（无法获取 manifest）
        html_result = self._fetch_via_html()
        if html_result is not None:
            latest_version, url = html_result
            has_update = self._compare_versions(latest_version)
            update_type = self._determine_update_type(latest_version) if has_update else UpdateType.WARM

            return UpdateInfo(
                has_update=has_update,
                current_version=self.current_version,
                latest_version=latest_version,
                release_url=url,
                update_type=update_type,
            )

        return None
