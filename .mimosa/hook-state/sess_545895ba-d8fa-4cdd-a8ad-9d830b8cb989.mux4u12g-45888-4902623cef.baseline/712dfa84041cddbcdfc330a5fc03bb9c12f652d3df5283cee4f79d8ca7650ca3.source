"""
差异计算器
src/utils/diff_calculator.py

基于本地和远程 manifest 的文件清单，计算需要下载/删除的文件差异列表
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Any


class DiffType(Enum):
    """差异类型"""
    ADD = "add"          # 新增文件
    MODIFY = "modify"    # 修改文件
    DELETE = "delete"    # 删除文件


@dataclass
class DiffEntry:
    """差异条目"""
    path: str
    type: DiffType
    sha256: str = ""
    size: int = 0
    category: str = "hot"  # hot/warm
    url: str = ""


class DiffCalculator:
    """差异计算器"""

    @staticmethod
    def calculate(
        local_manifest: Dict[str, Dict[str, Any]],
        remote_manifest: Dict[str, Dict[str, Any]],
    ) -> List[DiffEntry]:
        """计算本地与远程 manifest 的差异

        Args:
            local_manifest: 本地文件清单 {path: {sha256, size}}
            remote_manifest: 远程文件清单 {path: {sha256, size, category, url}}

        Returns:
            差异条目列表
        """
        diff_list = []
        local_paths = set(local_manifest.keys())
        remote_paths = set(remote_manifest.keys())

        # 新增文件：remote 有，local 无
        for path in sorted(remote_paths - local_paths):
            entry = remote_manifest[path]
            diff_list.append(DiffEntry(
                path=path,
                type=DiffType.ADD,
                sha256=entry.get("sha256", ""),
                size=entry.get("size", 0),
                category=entry.get("category", "hot"),
                url=entry.get("url", ""),
            ))

        # 修改文件：两者都有，sha256 不同
        for path in sorted(local_paths & remote_paths):
            local_hash = local_manifest[path].get("sha256", "")
            remote_hash = remote_manifest[path].get("sha256", "")
            if local_hash != remote_hash:
                entry = remote_manifest[path]
                diff_list.append(DiffEntry(
                    path=path,
                    type=DiffType.MODIFY,
                    sha256=entry.get("sha256", ""),
                    size=entry.get("size", 0),
                    category=entry.get("category", "hot"),
                    url=entry.get("url", ""),
                ))

        # 删除文件：local 有，remote 无
        for path in sorted(local_paths - remote_paths):
            entry = local_manifest[path]
            diff_list.append(DiffEntry(
                path=path,
                type=DiffType.DELETE,
                sha256=entry.get("sha256", ""),
                size=entry.get("size", 0),
            ))

        return diff_list

    @staticmethod
    def from_remote_manifest(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """从远程 manifest 的 files 数组构建字典

        Args:
            manifest: 远程 manifest（含 files 数组）

        Returns:
            {path: {sha256, size, category, url}} 字典
        """
        result = {}
        for file_entry in manifest.get("files", []):
            path = file_entry["path"]
            result[path] = {
                "sha256": file_entry.get("sha256", ""),
                "size": file_entry.get("size", 0),
                "category": file_entry.get("category", "hot"),
                "url": file_entry.get("url", ""),
            }
        return result

    @staticmethod
    def categorize_diffs(diff_list: List[DiffEntry]) -> Dict[str, List[DiffEntry]]:
        """按更新类型分组差异列表

        Returns:
            {"hot": [...], "warm": [...], "delete": [...]}
        """
        result = {"hot": [], "warm": [], "delete": []}
        for entry in diff_list:
            if entry.type == DiffType.DELETE:
                result["delete"].append(entry)
            elif entry.category == "warm":
                result["warm"].append(entry)
            else:
                result["hot"].append(entry)
        return result
