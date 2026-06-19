"""
Izanami Lab 一键发布脚本
用法: python release.py [版本号]
示例: python release.py v1.0.1

功能:
1. 交互式输入版本信息（版本号、分类Features）
2. 更新 CHANGELOG.md
3. 检查 Git 状态并推送代码
4. 运行 build.py 打包
5. 生成 manifest.json（热更新清单）
6. 创建 ZIP 压缩包
7. 创建 GitHub Release 并上传（含 manifest + 变更文件）
"""
import subprocess
import sys
import os
import json
import hashlib
import zipfile
from pathlib import Path
from datetime import datetime
from collections import OrderedDict

SCRIPT_DIR = Path(__file__).parent
DIST_DIR = SCRIPT_DIR / "dist"
APP_NAME = "Izanami Lab"
REPOSITORY = "senjyou/Izanami-Lab"

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


def compute_sha256(file_path: Path) -> str:
    """计算文件 SHA-256"""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def generate_manifest(dist_dir: Path, version: str, features: list) -> dict:
    """生成版本清单（热更新用）"""
    app_dir = dist_dir / APP_NAME
    data_dir = app_dir / "data"
    files = []

    # 扫描 data 目录
    if data_dir.exists():
        for file_path in sorted(data_dir.rglob("*")):
            if not file_path.is_file() or file_path.name.endswith('.default.json'):
                continue
            rel_path = file_path.relative_to(app_dir)
            path_str = str(rel_path).replace('\\', '/')
            # 跳过运行时生成的文件（不在 git 仓库中，无法通过 CDN 分发）
            if path_str.startswith('data/battle_logs/'):
                continue
            if path_str == 'data/character_stats_cache.json':
                continue
            sha256 = compute_sha256(file_path)
            size = file_path.stat().st_size
            # 与 git blob 保持一致：文本文件使用 LF 行尾
            # (autocrlf=true 时 git 在 commit 时将 CRLF 转为 LF，jsDelivr 从 git blob 提供文件)
            # 若不归一化，客户端下载后 SHA-256 校验会失败
            if file_path.suffix.lower() in ('.json', '.txt'):
                content = file_path.read_bytes().replace(b'\r\n', b'\n')
                sha256 = hashlib.sha256(content).hexdigest()
                size = len(content)
            category = "hot"  # data 目录下的文件都是热更新
            files.append({
                "path": path_str,
                "sha256": sha256,
                "size": size,
                "category": category,
                # 通过 jsDelivr CDN 从 git tag 分发，无需上传单个文件到 Release 资产
                "url": f"https://cdn.jsdelivr.net/gh/{REPOSITORY}@{version}/{path_str}",
            })

    # 判断更新类型
    update_type = "hot" if files else "warm"

    # 生成 changelog
    changelog_zh = ""
    changelog_en = ""
    if features:
        grouped = OrderedDict([(k, []) for k in FEATURE_CATEGORIES])
        for f in features:
            grouped[f['category']].append(f['text'])
        zh_lines = []
        for cat_key, cat_name in FEATURE_CATEGORIES.items():
            items = grouped[cat_key]
            if items:
                for item in items:
                    zh_lines.append(f"- {item}")
        changelog_zh = "\n".join(zh_lines)

    return {
        "version": version.lstrip('v'),
        "build_timestamp": datetime.utcnow().isoformat() + "Z",
        "update_type": update_type,
        "files": files,
        "changelog": {
            "zh": changelog_zh,
            "en": changelog_en,
        },
    }


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

    # 4. 更新本地版本号（必须在构建前完成，否则打包的程序版本号不对）
    print("\n[1/6] 更新本地版本号...")
    version_file = SCRIPT_DIR / "version.py"
    version_num = version.lstrip('v')
    new_content = f'__version__ = "{version_num}"\n__repository__ = "senjyou/Izanami-Lab"\n__release_url__ = "https://github.com/senjyou/Izanami-Lab/releases"'
    version_file.write_text(new_content, encoding='utf-8')
    print(f"  已更新 version.py 为 v{version_num}")

    # 5. 更新 CHANGELOG.md
    print("\n[2/6] 更新 CHANGELOG.md...")
    changelog_path = SCRIPT_DIR / "CHANGELOG.md"
    today = datetime.now().strftime("%Y-%m-%d")
    
    changelog_lines = [f"## {version} ({today})", ""]
    if new_features:
        grouped = OrderedDict([(k, []) for k in FEATURE_CATEGORIES])
        for f in new_features:
            grouped[f['category']].append(f['text'])
        for cat_key, cat_name in FEATURE_CATEGORIES.items():
            items = grouped[cat_key]
            if items:
                for item in items:
                    changelog_lines.append(f"- {item}")
                changelog_lines.append("")
    else:
        changelog_lines.append("- 无更新内容")
        changelog_lines.append("")
    
    changelog_new_section = "\n".join(changelog_lines)
    
    if changelog_path.exists():
        existing_content = changelog_path.read_text(encoding='utf-8')
        new_content = changelog_new_section + existing_content
    else:
        new_content = "# Changelog\n\n" + changelog_new_section
    
    changelog_path.write_text(new_content, encoding='utf-8')
    print(f"  已更新 CHANGELOG.md")

    # 6. 检查并推送代码
    print("\n[3/6] 检查并推送代码...")
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

    # 7. 打包构建
    print("\n[4/7] 打包构建...")
    run_cmd("python build.py", cwd=SCRIPT_DIR)

    # 8. 生成 manifest
    print("\n[5/7] 生成 manifest.json...")
    manifest = generate_manifest(DIST_DIR, version, new_features)
    manifest_path = DIST_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    file_count = len(manifest["files"])
    print(f"  已生成 manifest.json（{file_count} 个文件）")

    # 9. 创建 ZIP
    print("\n[6/7] 创建压缩包...")
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

    # 10. 创建 Release（上传 ZIP + manifest + 变更文件）
    print("\n[7/7] 创建 GitHub Release...")

    notes = format_release_notes(version, new_features)
    notes_file = DIST_DIR / "release_notes.md"
    notes_file.write_text(notes, encoding='utf-8')

    print("\nRelease Notes 内容:")
    print("-" * 40)
    print(notes)
    print("-" * 40)

    # 只上传 ZIP + manifest.json（热更新文件已在 ZIP 中）
    assets = [str(zip_path), str(manifest_path)]
    print(f"  上传资产: {len(assets)} 个文件")

    # 使用 gh CLI 创建 Release
    gh_cmd = [
        'C:\\Program Files\\GitHub CLI\\gh.exe', 'release', 'create',
        version,
        *assets,
        '--title', version,
        '--notes-file', str(notes_file),
        '--repo', REPOSITORY,
    ]
    result = subprocess.run(gh_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  错误: {result.stderr}")
        sys.exit(result.returncode)
    print(f"  Release: {result.stdout.strip()}")

    print(f"\n{'='*60}")
    print(f"  发布完成!")
    print(f"  版本: {version}")
    print(f"  Release: https://github.com/{REPOSITORY}/releases/tag/{version}")
    print(f"  热更新文件: {file_count} 个")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
