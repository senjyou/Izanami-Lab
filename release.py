"""
Izanami Lab 一键发布脚本
用法: python release.py [版本号]
示例: python release.py v1.0.1

功能:
1. 检查 Git 状态并推送代码
2. 运行 build.py 打包
3. 创建 ZIP 压缩包
4. 创建 GitHub Release 并上传
"""
import subprocess
import sys
import os
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DIST_DIR = SCRIPT_DIR / "dist"
APP_NAME = "Izanami Lab"


def run_cmd(cmd, cwd=None):
    """运行命令并返回结果"""
    print(f"  执行: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  错误: {result.stderr}")
        sys.exit(result.returncode)
    return result.stdout


def main():
    # 获取版本号
    if len(sys.argv) >= 2:
        version = sys.argv[1]
    else:
        print("请指定版本号，如: python release.py v1.0.1")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"  Izanami Lab 发布脚本")
    print(f"  版本: {version}")
    print(f"{'='*50}\n")

    # 1. 检查并推送代码
    print("[1/4] 检查并推送代码...")
    print("  检查 Git 状态...")
    status = run_cmd("git status --short", cwd=SCRIPT_DIR)
    if status:
        print("  有未提交的更改，先提交...")
        run_cmd("git add .", cwd=SCRIPT_DIR)
        run_cmd(f'git commit -m "Release {version}"', cwd=SCRIPT_DIR)
    
    print("  拉取远程更新...")
    run_cmd("git pull --rebase", cwd=SCRIPT_DIR)
    
    print("  推送到 GitHub...")
    run_cmd("git push", cwd=SCRIPT_DIR)

    # 2. 打包构建
    print("\n[2/4] 打包构建...")
    run_cmd("python build.py", cwd=SCRIPT_DIR)

    # 3. 创建 ZIP
    print("\n[3/4] 创建压缩包...")
    app_dir = DIST_DIR / APP_NAME
    zip_path = DIST_DIR / f"Izanami-Lab_{version}.zip"
    
    if not app_dir.exists():
        print(f"  错误: 打包输出目录不存在: {app_dir}")
        sys.exit(1)

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file in app_dir.rglob("*"):
            arcname = file.relative_to(app_dir.parent)
            zf.write(file, arcname)
    
    size_mb = (zip_path.stat().st_size / 1024 / 1024)
    print(f"  压缩包: {zip_path} ({size_mb:.1f} MB)")

    # 4. 创建 Release
    print("\n[4/4] 创建 GitHub Release...")
    notes = f"""## {version} Release

### Features
- Global parameter configuration (school levels, equipment, character levels, rarity, modules, affection, skills)
- Character parameter override system
- Custom dummy enemy creation
- Team formation (2x3 grid) and battle simulation
- Step-by-step crit simulation
- Tactical exercise mode
- Preset management
- Dark/light/system theme support
- Batch simulation with statistics
- Battle log export

### How to Use
1. Download and extract `Izanami-Lab_{version}.zip`
2. Run `Izanami Lab.exe`

### Supported Characters
See [SUPPORTED_CHARACTERS.md](https://github.com/senjyou/Izanami-Lab/blob/master/SUPPORTED_CHARACTERS.md)
"""
    notes_file = DIST_DIR / "release_notes.md"
    notes_file.write_text(notes, encoding='utf-8')
    
    result = subprocess.run(
        ['C:\\Program Files\\GitHub CLI\\gh.exe', 'release', 'create', version, str(zip_path), '--title', version, '--notes-file', str(notes_file), '--repo', 'senjyou/Izanami-Lab'],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"  错误: {result.stderr}")
        sys.exit(result.returncode)
    print(f"  Release: {result.stdout.strip()}")

    print(f"\n{'='*50}")
    print(f"  发布完成!")
    print(f"  版本: {version}")
    print(f"  Release: https://github.com/senjyou/Izanami-Lab/releases/tag/{version}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
