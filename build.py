"""
Izanami-Lab 一键打包脚本
用法: python build.py
输出: dist/Izanami-Lab/ 目录
"""
import subprocess
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DIST_DIR = SCRIPT_DIR / "dist"
BUILD_DIR = SCRIPT_DIR / "build"
ICON_FILE = SCRIPT_DIR / "icon.ico"
ENTRY_POINT = "gui_app.py"
APP_NAME = "Izanami Lab"

# 打包配置
PYINSTALLER_ARGS = [
    "--onedir",
    "--windowed",
    f"--name={APP_NAME}",
    f"--icon={ICON_FILE}",
    "--add-data", "data;data",
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
    "--hidden-import", "src.combat_v2.tactical_exercise_controller",
    "--clean",
    "--noconfirm",
    ENTRY_POINT,
]


def clean():
    """清理旧的构建产物"""
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  已清理: {d.name}")
    # 清理 .spec 文件
    spec = SCRIPT_DIR / f"{APP_NAME}.spec"
    if spec.exists():
        spec.unlink()
        print(f"  已清理: {spec.name}")


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

    # 清理
    print("[1/3] 清理旧构建...")
    clean()

    # 打包
    print("\n[2/3] PyInstaller 打包中...")
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

    total_size = sum(
        f.stat().st_size for f in output_dir.rglob("*") if f.is_file()
    )
    size_mb = round(total_size / 1024 / 1024, 1)

    print(f"\n[3/3] 打包完成!")
    print(f"  输出目录: {output_dir}")
    print(f"  总大小:   {size_mb} MB")
    print(f"\n  可运行: {output_dir / (APP_NAME + '.exe')}")


if __name__ == "__main__":
    build()
