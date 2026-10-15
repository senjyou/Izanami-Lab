"""
Izanami-Lab 一键打包脚本
用法: python build.py
输出: dist/Izanami Lab/ 目录

注意: data/ 目录外置到 exe 同级，不嵌入 PyInstaller，以支持热更新
"""
import subprocess
import shutil
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DIST_DIR = SCRIPT_DIR / "dist"
BUILD_DIR = SCRIPT_DIR / "build"
ICON_FILE = SCRIPT_DIR / "icon.ico"
DATA_DIR = SCRIPT_DIR / "data"
ENTRY_POINT = "gui_app.py"
APP_NAME = "Izanami Lab"

# 打包配置（data 目录不再嵌入，改为外部复制）
PYINSTALLER_ARGS = [
    "--onedir",
    "--windowed",
    f"--name={APP_NAME}",
    f"--icon={ICON_FILE}",
    # data 目录不再通过 --add-data 嵌入，改为外部复制以支持热更新
    "--add-data", f"{ICON_FILE};.",
    "--hidden-import", "tkinter",
    "--hidden-import", "pywinstyles",
    "--hidden-import", "PIL",
    "--hidden-import", "PIL._tkinter_finder",
    "--hidden-import", "PIL.ImageTk",
    "--hidden-import", "requests",
    "--hidden-import", "version",
    "--hidden-import", "src.utils.batch_simulator",
    "--hidden-import", "src.utils.update_manager",
    "--hidden-import", "src.utils.update_daemon",
    "--hidden-import", "src.utils.version_checker",
    "--hidden-import", "src.utils.diff_calculator",
    "--hidden-import", "src.utils.download_scheduler",
    "--hidden-import", "src.utils.patch_engine",
    "--hidden-import", "src.utils.integrity_verifier",
    "--hidden-import", "src.utils.rollback_manager",
    "--hidden-import", "src.utils.update_state",
    "--hidden-import", "src.utils.cold_updater",
    "--hidden-import", "src.combat_v2.tactical_exercise_controller",
    "--clean",
    "--noconfirm",
    ENTRY_POINT,
]


def _running_instances():
    """列出正在运行的本程序进程。

    打包产物被正在运行的实例占用时，清理 dist/ 会以
    `PermissionError [WinError 5]` 失败（典型报错文件是 _internal 下的某个 .pyd）。
    """
    found = []
    try:
        import psutil
    except ImportError:
        return found
    target = f"{APP_NAME}.exe".lower()
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name == target:
                found.append(proc)
        except Exception:
            continue
    return found


def _close_running_instances():
    """先请求优雅关闭（会触发应用自己的保存逻辑），必要时再强制结束。"""
    procs = _running_instances()
    if not procs:
        return
    print(f"  检测到 {len(procs)} 个正在运行的 {APP_NAME}.exe："
          f" {', '.join('PID ' + str(p.pid) for p in procs)}")
    print("  正在请求关闭（先优雅关闭，以便应用保存配置）...")

    # taskkill 不带 /F 会向窗口发送关闭请求 -> 触发应用的 _on_close 保存流程
    for p in procs:
        subprocess.run(["taskkill", "/PID", str(p.pid)],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")

    try:
        import psutil
        _gone, alive = psutil.wait_procs(procs, timeout=12)
    except Exception:
        alive = [p for p in procs if p.is_running()]

    for p in alive:
        print(f"  PID {p.pid} 未在 12 秒内退出，强制结束")
        try:
            p.kill()
        except Exception:
            subprocess.run(["taskkill", "/F", "/PID", str(p.pid)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    try:
        import psutil
        psutil.wait_procs(alive, timeout=8)
    except Exception:
        pass
    time.sleep(0.5)


def _rmtree_robust(path: Path, retries: int = 4):
    """删除目录树：清只读属性 + 重试；仍失败时给出可操作的错误信息。"""
    last_err = None
    for attempt in range(1, retries + 1):
        if not path.exists():
            return
        # 只读属性会让 unlink 失败（WinError 5）
        for item in [path, *path.rglob("*")]:
            try:
                if item.is_file():
                    item.chmod(0o666)
            except OSError:
                pass
        try:
            shutil.rmtree(path)
            return
        except OSError as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.0)
    procs = _running_instances()
    hint = ""
    if procs:
        hint = ("\n  仍在运行: "
                + ", ".join(f"PID {p.pid}" for p in procs)
                + "\n  请先关闭程序（或再次运行本脚本，它会自动尝试关闭）。")
    print(f"\n[错误] 无法删除 {path}")
    print(f"  {type(last_err).__name__}: {last_err}")
    print("  常见原因：程序仍在运行并占用了 _internal 里的 DLL/PYD，"
          "或安全软件正在扫描这些文件。" + hint)
    sys.exit(1)


def clean():
    """清理旧的构建产物"""
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            _rmtree_robust(d)
            print(f"  已清理: {d.name}")
    # 清理 .spec 文件
    spec = SCRIPT_DIR / f"{APP_NAME}.spec"
    if spec.exists():
        spec.unlink()
        print(f"  已清理: {spec.name}")


def _count_low_integrity(root: Path) -> int:
    """统计 root 下带 Low 完整性标签的条目数（0 = 正常）。

    `icacls <dir> /T` 一次列出整棵树，比逐文件调用快得多；
    同时匹配英文与中文的标签文本。
    """
    try:
        r = subprocess.run(["icacls", str(root), "/T", "/C", "/Q"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = r.stdout or ""
        return out.count("Low Mandatory Level") + out.count("低强制级别")
    except Exception:
        return 0


def ensure_medium_integrity(root: Path):
    """确保发布产物不带 Low 完整性标签。

    **为什么必须做这一步**（实测事故）：
    仓库根目录曾被加上 `Low Mandatory Level` 标签，于是之后在其中创建的
    每个文件（含 PyInstaller 产出的 exe 与 _internal/）都继承了它。
    Windows 会以**低完整性**运行这个 exe，后果是：
      1. 它**无法写入 %APPDATA%（Medium 完整性）** —— 所有配置保存失败，
         表现为「打包版配置存不下来」；
      2. 启动时弹出「无法验证发布者 / 你确定要运行此软件吗」安全警告。
    两者都能通过重设标签解决，因此打包后强制校验并修正。
    """
    print("\n[4/5] 校验/修正文件完整性标签（Low 会导致配置无法保存）...")
    try:
        subprocess.run(["icacls", str(root), "/setintegritylevel", "Medium",
                        "/T", "/C", "/Q"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"  警告: 无法执行 icacls: {e}")

    low = _count_low_integrity(root)
    if low:
        print(f"  [错误] 仍有 {low} 个条目带 Low 完整性标签，"
              f"打包版将无法保存配置并会弹安全警告。")
        print("  请在有权限的终端对仓库根目录执行：")
        print(f'    icacls "{SCRIPT_DIR}" /setintegritylevel Medium /T /C /Q')
        sys.exit(1)
    print("  完整性标签正常（无 Low）")


def build():
    """执行 PyInstaller 打包"""
    print(f"\n{'='*50}")
    print(f"  {APP_NAME} 打包")
    print(f"{'='*50}\n")

    # 检查必要文件
    if not ICON_FILE.exists():
        print(f"[错误] 图标文件不存在: {ICON_FILE}")
        sys.exit(1)
    if not (SCRIPT_DIR / ENTRY_POINT).exists():
        print(f"[错误] 入口文件不存在: {ENTRY_POINT}")
        sys.exit(1)
    if not DATA_DIR.exists():
        print(f"[错误] 数据目录不存在: {DATA_DIR}")
        sys.exit(1)

    # 清理
    print("[1/5] 清理旧构建...")
    _close_running_instances()
    clean()

    # 打包
    print("\n[2/5] PyInstaller 打包中...")
    result = subprocess.run(
        ["pyinstaller"] + PYINSTALLER_ARGS,
        cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        print("[错误] 打包失败")
        sys.exit(result.returncode)

    # 输出结果
    output_dir = DIST_DIR / APP_NAME
    if not output_dir.exists():
        print("[错误] 输出目录不存在")
        sys.exit(1)

    # 复制 data 目录到输出目录（外置，支持热更新）
    print("\n[3/5] 复制 data 目录到输出目录...")
    data_dst = output_dir / "data"
    if data_dst.exists():
        shutil.rmtree(data_dst)
    shutil.copytree(DATA_DIR, data_dst)
    data_count = sum(1 for _ in data_dst.rglob("*") if _.is_file())
    print(f"  已复制 {data_count} 个数据文件")

    # 复制 SUPPORTED_CHARACTERS.md 到输出目录（用户模式己方白名单数据源）
    supported_md = SCRIPT_DIR / "SUPPORTED_CHARACTERS.md"
    if supported_md.exists():
        shutil.copy2(supported_md, output_dir / "SUPPORTED_CHARACTERS.md")
        print(f"  已复制: {supported_md.name}")

    # 校验完整性标签：Low 会让打包版无法保存配置并弹安全警告
    ensure_medium_integrity(output_dir)

    # 统计总大小
    total_size = sum(
        f.stat().st_size for f in output_dir.rglob("*") if f.is_file()
    )
    size_mb = round(total_size / 1024 / 1024, 1)

    print(f"\n[5/5] 打包完成!")
    print(f"  输出目录: {output_dir}")
    print(f"  总大小:   {size_mb} MB")
    print(f"\n  可运行: {output_dir / (APP_NAME + '.exe')}")


if __name__ == "__main__":
    build()
