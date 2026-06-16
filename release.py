"""
Izanami Lab 一键发布脚本
用法: python release.py [版本号]
示例: python release.py v1.0.1

功能:
1. 交互式输入版本信息（版本号、分类Features）
2. 检查 Git 状态并推送代码
3. 运行 build.py 打包
4. 创建 ZIP 压缩包
5. 创建 GitHub Release 并上传
"""
import subprocess
import sys
import os
import zipfile
from pathlib import Path
from collections import OrderedDict

SCRIPT_DIR = Path(__file__).parent
DIST_DIR = SCRIPT_DIR / "dist"
APP_NAME = "Izanami Lab"

# Feature 分类
FEATURE_CATEGORIES = OrderedDict([
    ('f', '新增功能'),
    ('x', '修复'),
    ('y', '优化'),
    ('o', '其他'),
])


def run_cmd(cmd, cwd=None):
    """运行命令并返回结果"""
    print(f"  执行: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  错误: {result.stderr}")
        sys.exit(result.returncode)
    return result.stdout


def input_version():
    """交互式输入版本号"""
    while True:
        version = input("请输入版本号（如 v1.0.1）: ").strip()
        if not version:
            print("  版本号不能为空，请重新输入")
            continue
        if not version.startswith('v'):
            print("  提示: 版本号建议以 'v' 开头，如 v1.0.1")
            confirm = input("  是否以此版本号继续？(y/n): ").strip().lower()
            if confirm != 'y':
                continue
        return version


def input_new_features():
    """交互式输入新版本的 Features，支持分类"""
    print("\n请输入新版本的更新内容:")
    print("  - 每行输入一条，按 Enter 确认")
    print("  - 输入空行结束输入")
    print(f"  - 分类选项: {', '.join([f'{k}={v}' for k, v in FEATURE_CATEGORIES.items()])}")
    print()

    features = []
    line_num = 1
    while True:
        line = input(f"  [{line_num}] 更新内容: ").strip()
        if not line:
            break

        category = ''
        while category not in FEATURE_CATEGORIES:
            cat_input = input(f"        分类 ({'/'.join(FEATURE_CATEGORIES.keys())}): ").strip().lower()
            if not cat_input:
                cat_input = 'o'
            category = cat_input

        features.append({
            'text': line,
            'category': category,
            'category_name': FEATURE_CATEGORIES[category],
        })
        line_num += 1

    return features


def format_release_notes(version, features):
    """格式化 Release Notes"""
    # 按分类分组
    grouped = OrderedDict([(k, []) for k in FEATURE_CATEGORIES])
    for f in features:
        grouped[f['category']].append(f['text'])

    lines = [f"## {version} Release", ""]

    # 添加分类内容
    for cat_key, cat_name in FEATURE_CATEGORIES.items():
        items = grouped[cat_key]
        if items:
            lines.append(f"### {cat_name}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")

    # 添加使用说明
    lines.append("### 使用方法")
    lines.append(f"1. 下载并解压 `Izanami-Lab_{version}.zip`")
    lines.append("2. 运行 `Izanami Lab.exe`")
    lines.append("")
    lines.append("### 支持角色")
    lines.append("See [SUPPORTED_CHARACTERS.md](https://github.com/senjyou/Izanami-Lab/blob/master/SUPPORTED_CHARACTERS.md)")

    return "\n".join(lines)


def main():
    # 1. 获取版本号
    if len(sys.argv) >= 2:
        version = sys.argv[1]
    else:
        version = input_version()

    # 2. 获取新 Features
    new_features = input_new_features()

    print(f"\n{'='*60}")
    print(f"  Izanami Lab 发布脚本")
    print(f"  版本: {version}")
    if new_features:
        print(f"  更新内容: {len(new_features)} 条")
    print(f"{'='*60}\n")

    # 3. 预览更新内容
    if new_features:
        print("更新内容预览:")
        print("-" * 40)
        grouped = OrderedDict([(k, []) for k in FEATURE_CATEGORIES])
        for f in new_features:
            grouped[f['category']].append(f['text'])

        for cat_key, cat_name in FEATURE_CATEGORIES.items():
            items = grouped[cat_key]
            if items:
                print(f"\n  {cat_name}:")
                for i, item in enumerate(items, 1):
                    print(f"    {i}. {item}")
        print("-" * 40)
    else:
        print("警告: 未输入任何更新内容，将创建空 Release")

    # 确认发布
    print()
    confirm = input("确认发布？(y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消发布")
        sys.exit(0)

    # 4. 检查并推送代码
    print("\n[1/5] 检查并推送代码...")
    print("  检查 Git 状态...")
    status = run_cmd("git status --short", cwd=SCRIPT_DIR)
    if status:
        print("  有未提交的更改，先提交...")
        run_cmd("git add .", cwd=SCRIPT_DIR)
        commit_msg = f"Release {version}"
        if new_features:
            features_preview = "\n".join([f['text'] for f in new_features[:3]])
            if len(new_features) > 3:
                features_preview += f"\n  ... 还有 {len(new_features) - 3} 条"
            commit_msg += f"\n\nFeatures:\n{features_preview}"
        run_cmd(f'git commit -m "{commit_msg.replace(chr(34), chr(34)+chr(34))}"', cwd=SCRIPT_DIR)

    print("  拉取远程更新...")
    run_cmd("git pull --rebase", cwd=SCRIPT_DIR)

    print("  推送到 GitHub...")
    run_cmd("git push", cwd=SCRIPT_DIR)

    # 5. 打包构建
    print("\n[2/5] 打包构建...")
    run_cmd("python build.py", cwd=SCRIPT_DIR)

    # 6. 创建 ZIP
    print("\n[3/5] 创建压缩包...")
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

    # 7. 创建 Release
    print("\n[4/5] 创建 GitHub Release...")

    notes = format_release_notes(version, new_features)
    notes_file = DIST_DIR / "release_notes.md"
    notes_file.write_text(notes, encoding='utf-8')

    print("\nRelease Notes 内容:")
    print("-" * 40)
    print(notes)
    print("-" * 40)

    result = subprocess.run(
        ['C:\\Program Files\\GitHub CLI\\gh.exe', 'release', 'create', version, str(zip_path), '--title', version, '--notes-file', str(notes_file), '--repo', 'senjyou/Izanami-Lab'],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"  错误: {result.stderr}")
        sys.exit(result.returncode)
    print(f"  Release: {result.stdout.strip()}")

    # 8. 更新本地版本号
    print("\n[5/5] 更新本地版本号...")
    version_file = SCRIPT_DIR / "version.py"
    if version_file.exists():
        version_num = version.lstrip('v')
        new_content = f'__version__ = "{version_num}"\n__repository__ = "senjyou/Izanami-Lab"\n__release_url__ = "https://github.com/senjyou/Izanami-Lab/releases"'
        version_file.write_text(new_content, encoding='utf-8')
        print(f"  已更新 version.py 为 v{version_num}")
        run_cmd("git add version.py", cwd=SCRIPT_DIR)
        run_cmd('git commit -m "chore: bump version"', cwd=SCRIPT_DIR)
        run_cmd("git push", cwd=SCRIPT_DIR)
        print("  已推送版本号更新")

    print(f"\n{'='*60}")
    print(f"  发布完成!")
    print(f"  版本: {version}")
    print(f"  Release: https://github.com/senjyou/Izanami-Lab/releases/tag/{version}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()