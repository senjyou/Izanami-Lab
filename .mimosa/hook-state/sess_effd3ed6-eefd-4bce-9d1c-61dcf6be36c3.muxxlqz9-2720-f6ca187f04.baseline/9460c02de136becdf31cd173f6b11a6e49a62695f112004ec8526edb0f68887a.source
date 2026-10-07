"""
完整性校验器
src/utils/integrity_verifier.py

提供 SHA-256 文件校验功能，用于：
- 下载后校验文件完整性
- 生成 manifest 中的文件哈希
- 全量校验 staging 目录
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class VerifyResult:
    """校验结果"""
    success: bool
    failed_files: List[str]


class IntegrityVerifier:
    """完整性校验器"""

    # 缓冲区大小（8KB，平衡内存和速度）
    _CHUNK_SIZE = 8192

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        """计算文件 SHA-256 哈希值

        Args:
            file_path: 文件路径

        Returns:
            SHA-256 哈希的十六进制字符串（小写）
        """
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(IntegrityVerifier._CHUNK_SIZE), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def verify_file(file_path: Path, expected_sha256: str) -> bool:
        """校验单个文件的 SHA-256

        Args:
            file_path: 文件路径
            expected_sha256: 预期的 SHA-256 哈希值

        Returns:
            校验是否通过
        """
        if not file_path.exists():
            return False
        try:
            actual = IntegrityVerifier.compute_sha256(file_path)
            return actual == expected_sha256.lower()
        except OSError:
            return False

    @staticmethod
    def verify_manifest(manifest_files: List[dict], staging_dir: Path) -> VerifyResult:
        """校验 staging 目录中的所有文件

        Args:
            manifest_files: manifest 中的文件列表，每项含 path 和 sha256
            staging_dir: staging 目录路径

        Returns:
            VerifyResult 包含校验结果和失败文件列表
        """
        failed = []
        for file_entry in manifest_files:
            rel_path = file_entry["path"]
            expected_hash = file_entry["sha256"]
            local_path = staging_dir / rel_path

            if not IntegrityVerifier.verify_file(local_path, expected_hash):
                failed.append(rel_path)

        return VerifyResult(
            success=len(failed) == 0,
            failed_files=failed,
        )

    @staticmethod
    def compute_file_entry(file_path: Path, rel_path: str = None) -> dict:
        """计算文件条目（用于生成 manifest）

        Args:
            file_path: 文件绝对路径
            rel_path: 相对路径（默认使用文件名）

        Returns:
            包含 path, sha256, size 的字典
        """
        sha256 = IntegrityVerifier.compute_sha256(file_path)
        size = file_path.stat().st_size
        return {
            "path": rel_path or file_path.name,
            "sha256": sha256,
            "size": size,
        }
