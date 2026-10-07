# -*- coding: utf-8 -*-
"""账号管理：注册表、活动账号目录解析、旧版目录迁移、账号包导入导出。

目录模型：
    %APPDATA%/Izanami Lab/          应用根（固定，不存放账号数据）
      accounts.json                 注册表（唯一事实来源）
      ui_config.json                全局（主题/开发者模式）
      update/                       更新状态（全局）
      accounts/<dir>/               每账号一个目录，内部结构与旧版单目录一致

纯逻辑模块（不依赖 tkinter / gui 包），供 GUI、入口脚本与外部工具共用。

安全约定：
- accounts.json 的 dir 字段与账号包内的相对路径视为不可信输入，拼接前必须
  通过 _safe_dir_name / _safe_rel 校验，导入文件另做 resolve 包含性校验。
- 所有文件写入走 _atomic_write_bytes（mkstemp + fdopen + os.replace），
  目标路径永不出现写模式 open()，同时保证写坏一半不会破坏原文件。
"""

import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath

REGISTRY_VERSION = 1
BUNDLE_SCHEMA = "izanami-account"
BUNDLE_VERSION = 1
DEFAULT_APP_DIR_NAME = "Izanami Lab"
ACCOUNTS_SUBDIR = "accounts"

# 账号目录内的全局性内容：不随账号迁移/导出
NON_ACCOUNT_ENTRIES = {"ui_config.json", "update"}

# 新建空白账号时预创建的标准子目录
STANDARD_ACCOUNT_DIRS = [
    "presets", "tactical_presets", "circle_presets", "composite_presets", "crit_sequences",
]

_WINDOWS_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def sanitize_account_name(name: str) -> str:
    """账号显示名清洗：过滤 Windows 非法字符与首尾空白/点，非法输入回退 'account'。"""
    name = (name or "").strip()
    name = _WINDOWS_ILLEGAL.sub("_", name)
    name = name.rstrip(". ")
    return name or "account"


def atomic_write_bytes(target: Path, data: bytes) -> None:
    """把字节内容原子写入 target：同目录 mkstemp 临时文件 + os.replace。

    写失败时清理临时文件且不触碰原文件；目标路径的父目录必须已存在。
    """
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(target: Path, text: str) -> None:
    atomic_write_bytes(target, text.encode("utf-8"))


class AccountError(Exception):
    """账号操作失败（携带可直接展示给用户的消息）。"""


class AccountRegistry:
    def __init__(self, app_root: Path = None):
        self.app_root = Path(app_root) if app_root else self.default_app_root()
        self.accounts_file = self.app_root / "accounts.json"
        self.accounts_root = self.app_root / ACCOUNTS_SUBDIR

    # ─────────────────── 基础 ───────────────────

    @staticmethod
    def default_app_root() -> Path:
        base = Path(os.environ.get("APPDATA", Path.home() / ".config"))
        return base / DEFAULT_APP_DIR_NAME

    @staticmethod
    def _safe_dir_name(dir_name) -> bool:
        """注册表 dir 字段校验：必须是单个合法目录名，不含任何路径分隔符。"""
        return (isinstance(dir_name, str) and dir_name not in ("", ".", "..")
                and not _WINDOWS_ILLEGAL.search(dir_name))

    @staticmethod
    def _safe_rel(rel) -> bool:
        """账号包内相对路径校验：posix 相对路径，禁绝对路径/.. /反斜杠。"""
        if not isinstance(rel, str) or not rel.strip():
            return False
        if "\\" in rel:
            return False
        p = PurePosixPath(rel)
        return not p.is_absolute() and ".." not in p.parts

    def _default_registry(self) -> dict:
        return {"version": REGISTRY_VERSION, "current": None, "accounts": [],
                "legacy_import_dismissed": False}

    def _read(self) -> dict:
        """读注册表；损坏时隔离为 .corrupt-<时间戳> 备份并返回空注册表。"""
        if not self.accounts_file.exists():
            return self._default_registry()
        try:
            with open(self.accounts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("registry is not a dict")
            data.setdefault("accounts", [])
            data.setdefault("current", None)
            data.setdefault("legacy_import_dismissed", False)
            return data
        except Exception:
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.move(str(self.accounts_file),
                            str(self.accounts_file.with_name(f"accounts.json.corrupt-{stamp}")))
            except OSError:
                pass
            return self._default_registry()

    def _write(self, data: dict) -> None:
        self.app_root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.accounts_file, json.dumps(data, ensure_ascii=False, indent=2))

    def _account_path(self, acc: dict) -> Path:
        """注册表条目 → 账号目录路径；dir 字段非法时抛错（防路径穿越）。"""
        d = acc.get("dir")
        if not self._safe_dir_name(d):
            raise AccountError(f"注册表中的账号目录名非法：{d!r}")
        return self.accounts_root / d

    # ─────────────────── 查询 ───────────────────

    def list_accounts(self) -> list:
        """返回账号条目列表（dict 副本，按注册表顺序）。"""
        return [dict(a) for a in self._read()["accounts"]]

    def get_current_name(self):
        return self._read().get("current")

    @staticmethod
    def _find(data: dict, name) -> dict:
        for acc in data["accounts"]:
            if acc.get("name") == name:
                return acc
        return None

    def get_account_dir(self, name) -> Path:
        acc = self._find(self._read(), name)
        if acc is None:
            raise AccountError(f"账号「{name}」不存在。")
        return self._account_path(acc)

    def get_active_dir(self) -> Path:
        """当前账号的配置目录；注册表缺失/损坏/为空时回退应用根（旧版行为）。"""
        try:
            data = self._read()
            candidates = [self._find(data, data.get("current"))]
            if data["accounts"]:
                candidates.append(data["accounts"][0])
            for acc in candidates:
                if acc is not None and self._safe_dir_name(acc.get("dir")):
                    return self.accounts_root / acc["dir"]
        except Exception:
            pass
        return self.app_root

    # ─────────────────── 切换 / 使用记录 ───────────────────

    def set_current(self, name) -> None:
        data = self._read()
        acc = self._find(data, name)
        if acc is None:
            raise AccountError(f"账号「{name}」不存在。")
        data["current"] = name
        acc["last_used"] = _now_str()
        self._write(data)

    def touch_current(self) -> None:
        """启动时刷新当前账号的 last_used，失败静默（不影响启动）。"""
        try:
            data = self._read()
            acc = self._find(data, data.get("current"))
            if acc is not None:
                acc["last_used"] = _now_str()
                self._write(data)
        except Exception:
            pass

    def dismiss_legacy_import(self) -> None:
        data = self._read()
        data["legacy_import_dismissed"] = True
        self._write(data)

    # ─────────────────── 增删改名 ───────────────────

    def _unique_name(self, data: dict, name: str) -> str:
        if not self._find(data, name):
            return name
        i = 2
        while self._find(data, f"{name}({i})"):
            i += 1
        return f"{name}({i})"

    def _unique_dir(self, name: str) -> str:
        d = sanitize_account_name(name)
        candidate, i = d, 2
        while (self.accounts_root / candidate).exists():
            candidate = f"{d}({i})"
            i += 1
        return candidate

    def create_account(self, name: str) -> str:
        name = sanitize_account_name(name)
        data = self._read()
        if self._find(data, name):
            raise AccountError(f"账号「{name}」已存在。")
        acc_dir = self.accounts_root / self._unique_dir(name)
        acc_dir.mkdir(parents=True, exist_ok=True)
        for sub in STANDARD_ACCOUNT_DIRS:
            (acc_dir / sub).mkdir(exist_ok=True)
        # 配置文件留空：GUI 启动时的 _ensure_user_config 会自动补默认模板
        data["accounts"].append({"name": name, "dir": acc_dir.name, "note": "",
                                 "created_at": _now_str(), "last_used": ""})
        self._write(data)
        return name

    def rename_account(self, old: str, new: str) -> str:
        new = sanitize_account_name(new)
        data = self._read()
        acc = self._find(data, old)
        if acc is None:
            raise AccountError(f"账号「{old}」不存在。")
        if new == old:
            return old
        if self._find(data, new):
            raise AccountError(f"账号「{new}」已存在。")
        acc["name"] = new
        if data.get("current") == old:
            data["current"] = new
        self._write(data)
        return new

    def set_note(self, name: str, note: str) -> None:
        """设置账号备注（空字符串表示清除）。"""
        data = self._read()
        acc = self._find(data, name)
        if acc is None:
            raise AccountError(f"账号「{name}」不存在。")
        acc["note"] = (note or "").strip()
        self._write(data)

    def delete_account(self, name: str) -> None:
        data = self._read()
        acc = self._find(data, name)
        if acc is None:
            raise AccountError(f"账号「{name}」不存在。")
        if data.get("current") == name:
            raise AccountError("不能删除当前使用的账号，请先切换到其他账号。")
        if len(data["accounts"]) <= 1:
            raise AccountError("至少保留一个账号，无法删除。")
        shutil.rmtree(self._account_path(acc))
        data["accounts"].remove(acc)
        self._write(data)

    # ─────────────────── 旧版迁移 ───────────────────

    def scan_legacy_folders(self) -> list:
        """扫描 %APPDATA% 下 Izanami Lab* 兄弟目录（含账号配置文件即认定）。"""
        found = []
        try:
            candidates = sorted(self.app_root.parent.glob(f"{DEFAULT_APP_DIR_NAME}*"))
        except OSError:
            return []
        for p in candidates:
            if p == self.app_root or not p.is_dir():
                continue
            if (p / "global_config.json").exists() or (p / "char_config.json").exists():
                found.append(p)
        return found

    @staticmethod
    def legacy_folder_display_name(src: Path) -> str:
        m = re.fullmatch(re.escape(DEFAULT_APP_DIR_NAME) + r"【(.+)】", src.name)
        return m.group(1) if m else src.name

    def ensure_root_migrated(self) -> list:
        """首次运行迁移：把应用根的旧版账号文件收进 accounts/主号 并创建注册表。

        返回仍待导入的旧版兄弟目录列表（用户曾拒绝导入则返回 []）。
        迁移中途失败时抛出异常且不写注册表，下次启动自动重试。
        """
        data = self._read()
        if self.accounts_file.exists():
            if data.get("legacy_import_dismissed"):
                return []
            return self.scan_legacy_folders()

        self.accounts_root.mkdir(parents=True, exist_ok=True)
        name = self._unique_name(data, "主号")
        acc_dir = self.accounts_root / self._unique_dir(name)
        acc_dir.mkdir(parents=True, exist_ok=True)
        # 根目录除全局项外的所有内容都属于首个账号，逐项移动（目标已存在则保留原文件跳过）
        for entry in self.app_root.iterdir():
            if entry.name in NON_ACCOUNT_ENTRIES or entry.name == ACCOUNTS_SUBDIR:
                continue
            dst = acc_dir / entry.name
            if dst.exists():
                continue
            shutil.move(str(entry), str(dst))
        data["accounts"].append({"name": name, "dir": acc_dir.name,
                                 "note": "由旧版目录迁移", "created_at": _now_str(),
                                 "last_used": _now_str()})
        data["current"] = name
        self._write(data)
        return [] if data.get("legacy_import_dismissed") else self.scan_legacy_folders()

    def import_legacy_folder(self, src: Path, name: str = None) -> str:
        """导入旧版账号文件夹：复制 → 逐文件校验 → 删除源目录；失败保留源目录。"""
        src = Path(src)
        if not src.is_dir():
            raise AccountError(f"目录不存在：{src}")
        src_resolved = src.resolve()
        root_resolved = self.app_root.resolve()
        if src_resolved == root_resolved or root_resolved in src_resolved.parents:
            raise AccountError("不能导入应用根目录本身。")
        display = sanitize_account_name(name or self.legacy_folder_display_name(src))
        data = self._read()
        final_name = self._unique_name(data, display)
        acc_dir = self.accounts_root / self._unique_dir(final_name)
        try:
            acc_dir.mkdir(parents=True, exist_ok=True)
            self._copy_tree(src, acc_dir)
            self._verify_copy(src, acc_dir)
        except Exception as e:
            shutil.rmtree(acc_dir, ignore_errors=True)
            if isinstance(e, AccountError):
                raise
            raise AccountError(f"导入「{src.name}」失败：{e}")
        shutil.rmtree(src)
        data = self._read()
        data["accounts"].append({"name": final_name, "dir": acc_dir.name,
                                 "note": "从旧版文件夹导入", "created_at": _now_str(),
                                 "last_used": ""})
        self._write(data)
        return final_name

    @staticmethod
    def _copy_tree(src: Path, dst: Path) -> None:
        """目录树复制（排除全局项）：逐目录 mkdir + 逐文件 copyfile。"""
        for dirpath, dirnames, filenames in os.walk(src):
            rel = os.path.relpath(dirpath, src)
            if rel != "." and Path(rel).parts[0] in NON_ACCOUNT_ENTRIES:
                dirnames[:] = []
                continue
            dst_dir = dst / rel if rel != "." else dst
            dst_dir.mkdir(parents=True, exist_ok=True)
            for fn in filenames:
                # 顶层全局文件（如 ui_config.json）不随账号复制
                if rel == "." and fn in NON_ACCOUNT_ENTRIES:
                    continue
                shutil.copyfile(os.path.join(dirpath, fn), os.path.join(str(dst_dir), fn))

    @staticmethod
    def _verify_copy(src: Path, dst: Path) -> None:
        """校验复制完整性：源中每个文件（除排除项）在目标中存在且大小一致。"""
        for p in src.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(src)
            if rel.parts[0] in NON_ACCOUNT_ENTRIES:
                continue
            target = dst / rel
            if not target.exists() or target.stat().st_size != p.stat().st_size:
                raise AccountError(f"复制校验失败：{rel}")

    # ─────────────────── 账号包导入导出 ───────────────────

    def export_account(self, name: str, dest: Path) -> Path:
        """把账号导出为单文件 JSON 账号包（账号数据均为 JSON 文本，无二进制）。"""
        data = self._read()
        acc = self._find(data, name)
        if acc is None:
            raise AccountError(f"账号「{name}」不存在。")
        src = self._account_path(acc)
        if not src.is_dir():
            raise AccountError(f"账号目录缺失：{src}")
        files = {}
        for p in sorted(src.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(src).as_posix()
            if rel.split("/", 1)[0] in NON_ACCOUNT_ENTRIES:
                continue
            try:
                files[rel] = p.read_text(encoding="utf-8")
            except UnicodeDecodeError as e:
                raise AccountError(f"文件 {rel} 不是 UTF-8 文本，无法导出：{e}")
        bundle = {
            "schema": BUNDLE_SCHEMA,
            "schema_version": BUNDLE_VERSION,
            "name": name,
            "exported_at": _now_str(),
            "app_version": self._app_version(),
            "files": files,
        }
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dest, json.dumps(bundle, ensure_ascii=False, indent=2))
        return dest

    def import_account(self, bundle_path: Path, name: str = None) -> str:
        """导入账号包，创建新账号（重名自动加后缀），返回最终账号名。"""
        bundle_path = Path(bundle_path)
        try:
            with open(bundle_path, "r", encoding="utf-8") as f:
                bundle = json.load(f)
        except Exception as e:
            raise AccountError(f"账号包读取失败：{e}")
        if not isinstance(bundle, dict) or bundle.get("schema") != BUNDLE_SCHEMA:
            raise AccountError("不是有效的账号包文件（schema 不匹配）。")
        files = bundle.get("files")
        if not isinstance(files, dict):
            raise AccountError("账号包缺少 files 数据。")
        for rel in files:
            if not self._safe_rel(rel):
                raise AccountError(f"账号包包含非法路径：{rel}")

        data = self._read()
        display = sanitize_account_name(name or bundle.get("name") or "导入账号")
        final_name = self._unique_name(data, display)
        acc_dir = self.accounts_root / self._unique_dir(final_name)
        try:
            acc_dir.mkdir(parents=True, exist_ok=True)
            root_str = os.path.normcase(str(acc_dir.resolve()))
            for rel, content in files.items():
                target = acc_dir.joinpath(*PurePosixPath(rel).parts)
                # 包含性校验：规范化后的目标必须位于账号目录内
                if not os.path.normcase(str(target.resolve())).startswith(root_str + os.sep):
                    raise AccountError(f"账号包包含非法路径：{rel}")
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(target, content)
        except BaseException:
            shutil.rmtree(acc_dir, ignore_errors=True)
            raise
        data["accounts"].append({"name": final_name, "dir": acc_dir.name,
                                 "note": f"由账号包导入（{bundle.get('exported_at', '?')}）",
                                 "created_at": _now_str(), "last_used": ""})
        self._write(data)
        return final_name

    @staticmethod
    def _app_version() -> str:
        try:
            from version import __version__
            return __version__
        except Exception:
            return "unknown"
