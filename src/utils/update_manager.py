import requests
import re
import time
from dataclasses import dataclass
from typing import Optional, Tuple
from pathlib import Path


@dataclass
class UpdateInfo:
    has_update: bool
    current_version: str
    latest_version: str
    release_url: str
    release_notes: str = ""
    published_at: str = ""


class UpdateManager:
    def __init__(self, repository: str, current_version: str, release_url: str):
        self.repository = repository
        self.current_version = current_version.lstrip('v')
        self.release_url = release_url
        self.api_url = f"https://api.github.com/repos/{repository}/releases/latest"
        self._last_check_time = 0
        self._check_interval = 86400

    def _parse_version(self, version_str: str) -> Tuple[int, int, int]:
        version_str = version_str.lstrip('v')
        parts = version_str.split('.')
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)

    def _compare_versions(self, latest: str) -> bool:
        current = self._parse_version(self.current_version)
        latest_parsed = self._parse_version(latest)
        return latest_parsed > current

    def check_for_updates(self, force: bool = False) -> Optional[UpdateInfo]:
        now = time.time()
        if not force and now - self._last_check_time < self._check_interval:
            return None

        self._last_check_time = now

        try:
            response = requests.get(self.api_url, timeout=10)
            response.raise_for_status()
            data = response.json()

            latest_version = data.get('tag_name', '').lstrip('v')
            release_notes = data.get('body', '')
            published_at = data.get('published_at', '')
            html_url = data.get('html_url', self.release_url)

            has_update = self._compare_versions(latest_version)

            return UpdateInfo(
                has_update=has_update,
                current_version=self.current_version,
                latest_version=latest_version,
                release_url=html_url,
                release_notes=release_notes,
                published_at=published_at
            )
        except requests.exceptions.RequestException as e:
            return None
        except (KeyError, ValueError) as e:
            return None