"""
补丁应用引擎
src/utils/patch_engine.py

负责将 staging 目录中的文件应用到目标位置，包括：
- 文件替换（原子操作：临时文件 + rename）
- DataLoader 缓存刷新（热更新）
- 温更新标记（pending_restart）
- __pycache__ 清理
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

from .diff_calculator import DiffEntry, DiffType, DiffCalculator
from .update_state import UpdateStateStore


@dataclass
class ApplyResult:
    """应用结果"""
    success: bool
    hot_files: List[str] = field(default_factory=list)
    warm_files: List[str] = field(default_factory=list)
    deleted_files: List[str] = field(default_factory=list)
    failed_files: List[str] = field(default_factory=list)


class PatchEngine:
    """补丁应用引擎"""

    # JSON 文件名到 DataLoader 缓存属性的映射
    FILE_TO_CACHE_MAP = {
        'characters.json': '_characters',
        'skills.json': '_skills',
        'skill_effects_hybrid.json': '_parsed_skills',
        'character_skills.json': '_character_skills',
        'enemies.json': '_enemies',
        'enemy_skills.json': '_enemy_skills',
        'memories.json': '_memories',
        'equipment.json': '_equipment',
        'modules.json': '_modules',
        'module_status.json': '_module_status',
        'gear_effects.json': '_gear_effects',
        'level_lerp.json': '_level_lerp',
        'affection_bonuses.json': '_affection_bonuses',
        'rarity_bonuses.json': '_rarity_bonuses',
        'school_systems.json': '_school_systems_data',
        'character_stats_cache.json': None,  # 缓存文件，删除后自动重建
        'character_team_mapping.json': '_character_team_mapping',
        'skill_tag_values.json': None,
        'tactical_exercise_enemies.json': '_tactical_exercise_enemies',
        'custom_dummies.json': None,
    }

    def __init__(
        self,
        app_data_dir: Path,
        state_store: UpdateStateStore,
        data_loader=None,
        refresh_callback: Optional[Callable] = None,
    ):
        """
        Args:
            app_data_dir: 应用数据根目录（含 data/）
            state_store: 更新状态存储
            data_loader: DataLoader 实例（用于刷新缓存）
            refresh_callback: 数据刷新后的回调（通知 UI）
        """
        self._app_data_dir = app_data_dir
        self._state_store = state_store
        self._data_loader = data_loader
        self._refresh_callback = refresh_callback

    def apply(
        self,
        diff_list: List[DiffEntry],
        staging_dir: Path,
        target_version: str,
    ) -> ApplyResult:
        """应用补丁

        Args:
            diff_list: 差异文件列表
            staging_dir: staging 目录
            target_version: 目标版本号

        Returns:
            ApplyResult
        """
        categorized = DiffCalculator.categorize_diffs(diff_list)
        hot_files = []
        warm_files = []
        deleted_files = []
        failed_files = []

        # 处理热更新文件（data/）
        for entry in categorized["hot"]:
            try:
                self._apply_file(staging_dir / entry.path, self._app_data_dir / entry.path)
                hot_files.append(entry.path)
            except Exception as e:
                failed_files.append(entry.path)

        # 处理温更新文件（src/）
        for entry in categorized["warm"]:
            try:
                self._apply_file(staging_dir / entry.path, self._app_data_dir / entry.path)
                warm_files.append(entry.path)
                # 清理 __pycache__
                self._clean_pycache(self._app_data_dir / entry.path)
            except Exception as e:
                failed_files.append(entry.path)

        # 处理删除文件
        for entry in categorized["delete"]:
            try:
                target_path = self._app_data_dir / entry.path
                if target_path.exists():
                    target_path.unlink()
                deleted_files.append(entry.path)
            except Exception as e:
                failed_files.append(entry.path)

        # 热更新：刷新 DataLoader 缓存
        if hot_files and self._data_loader:
            self._refresh_data_loader(hot_files)

        # 温更新：标记 pending_restart
        if warm_files:
            self._state_store.mark_pending_restart(target_version, warm_files)

        # 更新 local_manifest
        if not failed_files:
            added_or_modified = {}
            for path in hot_files + warm_files:
                # 从 diff_list 中找到对应条目
                for entry in diff_list:
                    if entry.path == path:
                        added_or_modified[path] = {
                            "sha256": entry.sha256,
                            "size": entry.size,
                        }
                        break
            self._state_store.update_local_manifest(
                target_version,
                added_or_modified,
                deleted=deleted_files if deleted_files else None,
            )

        # 通知 UI
        if hot_files and self._refresh_callback:
            self._refresh_callback(hot_files)

        return ApplyResult(
            success=len(failed_files) == 0,
            hot_files=hot_files,
            warm_files=warm_files,
            deleted_files=deleted_files,
            failed_files=failed_files,
        )

    def _apply_file(self, source: Path, target: Path):
        """原子替换文件

        先写入临时文件，再重命名，确保不会出现半写状态
        """
        if not source.exists():
            raise FileNotFoundError(f"源文件不存在: {source}")

        # 确保目标目录存在
        target.parent.mkdir(parents=True, exist_ok=True)

        # 原子替换：先写临时文件再重命名
        temp_path = target.with_suffix(target.suffix + '.tmp')
        shutil.copy2(source, temp_path)
        temp_path.replace(target)

    def _refresh_data_loader(self, updated_files: List[str]):
        """根据更新的文件刷新 DataLoader 对应的缓存"""
        if not self._data_loader:
            return

        for filepath in updated_files:
            filename = Path(filepath).name
            cache_attr = self.FILE_TO_CACHE_MAP.get(filename)
            if cache_attr and hasattr(self._data_loader, cache_attr):
                # 清除对应缓存，下次访问时自动重新加载
                setattr(self._data_loader, cache_attr, None)

    def _clean_pycache(self, file_path: Path):
        """清理 Python 文件对应的 __pycache__"""
        pycache = file_path.parent / "__pycache__"
        if pycache.exists():
            # 只删除对应模块的 .pyc 文件
            module_name = file_path.stem
            for pyc in pycache.glob(f"{module_name}*.pyc"):
                pyc.unlink(missing_ok=True)
