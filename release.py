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
import time
from pathlib import Path
from datetime import datetime
from collections import OrderedDict

SCRIPT_DIR = Path(__file__).parent
DIST_DIR = SCRIPT_DIR / "dist"
APP_NAME = "Izanami Lab"
REPOSITORY = "senjyou/Izanami-Lab"
GH_EXE = r'C:\Program Files\GitHub CLI\gh.exe'

# ── 网络重试 ──────────────────────────────────────────────
# 实测事故（v1.1.2.3）：`gh release create` 报
#   "error checking for existing release: Head https://api.github.com/
#    repos/.../releases/tags/vX: net/http: TLS handshake timeout"
# 该步直接 sys.exit，release 从未被创建（tag/资产全无），只能手工重传。
# 这类失败是瞬时网络问题，重试即可成功，故在**网络命令**上加重试。
NETWORK_ATTEMPTS = 4         # 总尝试次数（含首次）
NETWORK_BACKOFF = 5          # 首次退避秒数，之后每次翻倍：5/10/20

# 判定为「瞬时网络故障」的关键字（小写匹配）。
# 只对这些做重试：语义性错误（参数错/权限不足/tag 已存在）重试没有意义，
# 且盲目重试可能造成重复副作用。
NETWORK_ERROR_MARKERS = (
    'tls handshake timeout',
    'net/http',
    'timeout',
    'timed out',
    'connection reset',
    'connection refused',
    'connection aborted',
    'connection attempt failed',
    'could not resolve host',
    'failed to connect',
    'temporary failure in name resolution',
    'unexpected eof',
    'eof occurred',
    'broken pipe',
    'server error',
    '502 bad gateway',
    '503 service unavailable',
    '504 gateway timeout',
    'the read operation timed out',
    'ssl',
)


def is_network_error(text: str) -> bool:
    """判断命令输出是否是瞬时网络故障（可安全重试）。"""
    if not text:
        return False
    low = text.lower()
    return any(m in low for m in NETWORK_ERROR_MARKERS)


def run_with_retry(cmd, cwd=None, attempts=None, backoff=None, label=None):
    """运行命令；仅对**瞬时网络故障**自动重试。

    返回 CompletedProcess（stdout/stderr 已按 utf-8 解码，失败为 ''）。
    非网络错误立即返回，由调用方决定如何处理（避免掩盖真实错误）。
    """
    attempts = attempts or NETWORK_ATTEMPTS
    backoff = NETWORK_BACKOFF if backoff is None else backoff
    name = label or (cmd if isinstance(cmd, str) else ' '.join(cmd))
    # git 命令以字符串形式传入（含 shell 语法），列表形式（gh）不能走 shell
    use_shell = isinstance(cmd, str)
    last = None
    for i in range(1, attempts + 1):
        res = subprocess.run(cmd, shell=use_shell, cwd=cwd, capture_output=True,
                             text=True, encoding='utf-8', errors='replace')
        if res.returncode == 0:
            if i > 1:
                print(f"  [重试成功] 第 {i}/{attempts} 次尝试成功")
            return res
        last = res
        blob = f"{res.stderr or ''}\n{res.stdout or ''}"
        if not is_network_error(blob):
            return res                      # 非网络问题：立即返回，不重试
        if i < attempts:
            wait = backoff * (2 ** (i - 1))
            print(f"  [网络重试] 第 {i}/{attempts} 次失败：{_short(blob)}")
            print(f"  等待 {wait}s 后重试...")
            time.sleep(wait)
    print(f"  [网络重试] 已尝试 {attempts} 次仍失败：{_short(name)}")
    return last


def _short(text: str, limit: int = 160) -> str:
    """压缩成一行短摘要，用于进度提示。"""
    one = ' '.join((text or '').split())
    return one[:limit] + ('...' if len(one) > limit else '')

# Feature 分类
FEATURE_CATEGORIES = OrderedDict([
    ('f', '新增功能'),
    ('x', '修复'),
    ('y', '优化'),
    ('o', '其他'),
])

# 严禁入库的工具/运行时产物前缀。
# 历史事故：
#   1. `.mimosa/` 被 `git add .` 扫入并推送（1142个文件/30MB）
#   2. `_analysis/` 被 `git add .` 扫入并提交入库（113个文件）——
#      **一旦被跟踪，`.gitignore` 就失效**，仅检查「未跟踪文件」拦不住，
#      此后每次发布都会继续带上它。故本脚本同时检查已跟踪路径并自动取消跟踪。
FORBIDDEN_PREFIXES = ('.mimosa/', '_backup', '_recycle_bin/', '.trae/',
                      '.agent/', '.zcode/', '.dbg/', '.pytest_cache/',
                      '__pycache__/', 'dist/', 'build/', '_analysis/')


def _norm(p: str) -> str:
    return p.strip().replace('\\', '/')


def find_forbidden_untracked(untracked_text: str) -> list:
    """从 `git ls-files --others --exclude-standard` 输出中挑出违禁文件。

    这些文件尚未被跟踪，`git add .` 会把它们扫进提交 -> 必须中止发布。
    """
    return [p.strip() for p in untracked_text.splitlines()
            if p.strip() and _norm(p).startswith(FORBIDDEN_PREFIXES)]


def find_forbidden_tracked_dirs(tracked_text: str) -> list:
    """从 `git ls-files` 输出中挑出「已被跟踪」的违禁顶层目录。

    `.gitignore` 对已跟踪文件无效，必须显式 `git rm -r --cached`。
    """
    return sorted({
        _norm(p).split('/')[0] for p in tracked_text.splitlines()
        if p.strip() and _norm(p).startswith(FORBIDDEN_PREFIXES)
    })


def run_cmd(cmd, cwd=None, retry_network=False):
    """运行命令并返回结果

    encoding='utf-8' 是必需的，原因见下方注释。
    另外这里**不再只依赖 returncode**：若子进程的 reader 线程仍然解码失败
    （例如未来换用别的 encoding 又被绕过），stdout/stderr 会变成 None，
    此时显式报错退出，避免"命令失败却被当成成功"继续往下发布。

    retry_network=True 时仅对瞬时网络故障重试（用于 git pull / git push 等
    联网命令）；本地命令保持原样，避免对非幂等操作做无意义重试。
    """
    print(f"  执行: {cmd}")
    # 注意: 必须显式指定 encoding='utf-8'。
    # 子进程（git / python / gh）输出的是 UTF-8，而 Windows 简体中文环境下
    # Python 的 locale 默认编码是 cp936(GBK)。若依赖 text=True 的默认解码，
    # subprocess 会在 **reader 线程** 里用 GBK 解码 UTF-8 字节并抛
    # UnicodeDecodeError —— 该异常不会传到主线程（脚本不崩），
    # 但这条命令的 stdout/stderr 会被静默丢弃（返回 None），
    # 使得 returncode 检查形同虚设。典型触发点：core.autocrlf=true 时
    # `git add` 对含中文文件名的工作区文件打印
    # "LF will be replaced by CRLF" 警告，警告里的路径是原样 UTF-8。
    if retry_network:
        result = run_with_retry(cmd, cwd=cwd, label=cmd)
    else:
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                                text=True, encoding='utf-8', errors='replace')
    if result.returncode != 0:
        print(f"  错误: {result.stderr}")
        sys.exit(result.returncode)
    if result.stdout is None or result.stderr is None:
        print("  错误: 命令输出解码失败（stdout/stderr 为 None），已中止。")
        print(f"  命令: {cmd}")
        sys.exit(1)
    if result.stderr:
        # 保留警告信息（如 git 的 LF/CRLF 警告），便于排查
        print(f"  {result.stderr.strip()}")
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


def _detect_code_changes(version: str) -> bool:
    """检测当前版本相比上一版本 tag 是否有代码文件变更

    通过 git diff 比较 HEAD 与上一版本 tag，检测 src/、gui_app.py、
    version.py、build.py 是否有变更。找不到上一 tag 或出错时保守视为有变更。
    """
    try:
        result = subprocess.run(
            ['git', 'tag', '--sort=-version:refname'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            cwd=SCRIPT_DIR
        )
        tags = [t.strip() for t in result.stdout.splitlines() if t.strip()]
        current_tag = version if version.startswith('v') else f'v{version}'
        prev_tag = None
        for i, t in enumerate(tags):
            if t == current_tag and i + 1 < len(tags):
                prev_tag = tags[i + 1]
                break
        if not prev_tag:
            return True  # 找不到上一版本 tag，保守视为有代码变更
        result = subprocess.run(
            ['git', 'diff', '--name-only', prev_tag, 'HEAD',
             '--', 'src/', 'gui_app.py', 'version.py', 'build.py'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            cwd=SCRIPT_DIR
        )
        return bool(result.stdout.strip())
    except Exception:
        return True  # 出错时保守处理


def generate_manifest(dist_dir: Path, version: str, features: list, zip_path: Path = None) -> dict:
    """生成版本清单（热更新用）"""
    app_dir = dist_dir / APP_NAME
    data_dir = app_dir / "data"
    files = []

    # 获取 git 跟踪的文件列表
    # jsDelivr 从 git 仓库提供文件，未跟踪的文件（运行时生成、用户配置等）会 404
    try:
        result = subprocess.run(
            ['git', 'ls-files', '--', 'data/'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            cwd=SCRIPT_DIR
        )
        git_tracked = set(line.strip() for line in result.stdout.splitlines() if line.strip())
    except Exception:
        git_tracked = None  # git 不可用时跳过此检查

    # 扫描 data 目录
    if data_dir.exists():
        for file_path in sorted(data_dir.rglob("*")):
            if not file_path.is_file() or file_path.name.endswith('.default.json'):
                continue
            rel_path = file_path.relative_to(app_dir)
            path_str = str(rel_path).replace('\\', '/')
            # 跳过未被 git 跟踪的文件（jsDelivr 无法提供）
            if git_tracked is not None and path_str not in git_tracked:
                continue
            # 跳过缓存文件（虽在 git 中，但属于本地缓存，不应分发）
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

    # 判断更新类型：有代码变更 → cold，仅 data/ 变更 → hot，无变更 → warm
    code_changed = _detect_code_changes(version)
    update_type = "cold" if code_changed else ("hot" if files else "warm")

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

    manifest = {
        "version": version.lstrip('v'),
        "build_timestamp": datetime.utcnow().isoformat() + "Z",
        "update_type": update_type,
        "files": files,
        "changelog": {
            "zh": changelog_zh,
            "en": changelog_en,
        },
    }

    # 冷更新时附带完整包信息
    if update_type == "cold":
        manifest["package_url"] = (
            f"https://github.com/{REPOSITORY}/releases/download/"
            f"{version}/Izanami-Lab_{version}.zip"
        )
        manifest["package_sha256"] = compute_sha256(zip_path) if zip_path else ""

    return manifest


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

        # 安全检查：提交前列出将被纳入的文件，拦截不该入库的工具产物
        # （前缀定义与判定函数见模块顶部 FORBIDDEN_PREFIXES / find_forbidden_*）
        # (a) 未跟踪且未被忽略的违禁文件：`git add .` 会把它们扫进去 -> 直接中止
        untracked = run_cmd("git ls-files --others --exclude-standard", cwd=SCRIPT_DIR)
        offenders = find_forbidden_untracked(untracked)
        if offenders:
            print(f"  错误: 检测到 {len(offenders)} 个不应入库的文件，已中止发布：")
            for p in offenders[:10]:
                print(f"    - {p}")
            if len(offenders) > 10:
                print(f"    ... 还有 {len(offenders) - 10} 个")
            print("  请将它们加入 .gitignore 后重试。")
            sys.exit(1)

        # (b) 已被跟踪的违禁路径：`.gitignore` 对已跟踪文件无效，
        #     所以必须显式取消跟踪，否则本次提交仍会带上它们。
        #     `git rm -r --cached` 只改索引，本地文件保留。
        tracked = run_cmd("git ls-files", cwd=SCRIPT_DIR)
        bad_tracked = find_forbidden_tracked_dirs(tracked)
        if bad_tracked:
            print(f"  警告: 检测到 {len(bad_tracked)} 个已被跟踪的违禁目录，"
                  f"将取消跟踪（本地文件保留）：")
            for p in bad_tracked:
                print(f"    - {p}")
            for p in bad_tracked:
                run_cmd(f"git rm -r --cached --quiet {p}", cwd=SCRIPT_DIR)
            print("  已取消跟踪；本次提交会把这些文件从仓库中删除。")

        run_cmd("git add .", cwd=SCRIPT_DIR)
        commit_msg = f"Release {version}"
        if new_features:
            features_preview = "\n".join([f['text'] for f in new_features[:3]])
            if len(new_features) > 3:
                features_preview += f"\n  ... 还有 {len(new_features) - 3} 条"
            commit_msg += f"\n\nFeatures:\n{features_preview}"
        run_cmd(f'git commit -m "{commit_msg.replace(chr(34), chr(34)+chr(34))}"', cwd=SCRIPT_DIR)

    print("  拉取远程更新...")
    run_cmd("git pull --rebase", cwd=SCRIPT_DIR, retry_network=True)

    print("  推送到 GitHub...")
    run_cmd("git push", cwd=SCRIPT_DIR, retry_network=True)

    # 7. 打包构建
    print("\n[4/7] 打包构建...")
    run_cmd("python build.py", cwd=SCRIPT_DIR)

    # 8. 创建 ZIP（必须在 manifest 之前，manifest 需计算 ZIP 的 SHA-256）
    print("\n[5/7] 创建压缩包...")
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

    # 9. 生成 manifest（传入 zip_path 以计算 package_sha256）
    print("\n[6/7] 生成 manifest.json...")
    manifest = generate_manifest(DIST_DIR, version, new_features, zip_path=zip_path)
    manifest_path = DIST_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    file_count = len(manifest["files"])
    print(f"  已生成 manifest.json（{file_count} 个文件，类型: {manifest['update_type']})")

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

    create_release_with_retry(version, assets, notes_file)

    print(f"\n{'='*60}")
    print(f"  发布完成!")
    print(f"  版本: {version}")
    print(f"  Release: https://github.com/{REPOSITORY}/releases/tag/{version}")
    print(f"  热更新文件: {file_count} 个")
    print(f"{'='*60}")


def _gh(args, attempts=None):
    """调用 gh CLI（UTF-8 解码，网络故障自动重试）。"""
    return run_with_retry([GH_EXE, *args], attempts=attempts,
                          label='gh ' + ' '.join(args[:2]))


def release_exists(version: str) -> bool:
    """Release 是否已存在（查询失败时保守返回 False，让 create 自己报错）。"""
    res = _gh(['release', 'view', version, '--repo', REPOSITORY], attempts=3)
    return res.returncode == 0


def create_release_with_retry(version: str, assets: list, notes_file: Path):
    """创建 Release 并上传资产，对瞬时网络故障自动重试。

    为什么不能简单重跑 `gh release create`：
      `gh release create` **不是幂等** 的。若上一次尝试其实已把 release 建好、
      只是在上传资产/查 tag 阶段断网，直接再 create 会报
      "release already exists" 而中止，资产仍然缺失。
    因此这里：先查 Release 是否存在 ——
      不存在 -> `gh release create`（带资产）
      已存在 -> `gh release upload --clobber` 补齐/覆盖资产（幂等）
    两者内部都靠 run_with_retry 扛住 TLS 握手超时这类瞬时故障。
    """
    create_args = ['release', 'create', version, *assets,
                   '--title', version,
                   '--notes-file', str(notes_file),
                   '--repo', REPOSITORY]

    if release_exists(version):
        print(f"  Release {version} 已存在，改为补齐/覆盖资产（upload --clobber）")
        res = _gh(['release', 'upload', version, *assets,
                   '--repo', REPOSITORY, '--clobber'])
        if res.returncode != 0:
            print(f"  错误: {res.stderr}")
            print(f"  提示: Release 已创建，仅资产上传失败。可手工补齐：")
            print(f'    gh release upload {version} {" ".join(assets)} '
                  f'--repo {REPOSITORY} --clobber')
            sys.exit(res.returncode)
        print(f"  Release: https://github.com/{REPOSITORY}/releases/tag/{version}")
        return

    res = _gh(create_args)

    # create 期间若恰好被别处抢先创建，退回 upload 补齐
    if res.returncode != 0 and 'already exists' in (res.stderr or '').lower():
        print(f"  Release {version} 已被创建，改为补齐/覆盖资产")
        res = _gh(['release', 'upload', version, *assets,
                   '--repo', REPOSITORY, '--clobber'])
        if res.returncode == 0:
            print(f"  Release: https://github.com/{REPOSITORY}/releases/tag/{version}")
            return

    if res.returncode != 0:
        print(f"  错误: {res.stderr}")
        # 关键提示：让用户不必重跑整个发布（build 很慢）
        print(f"  提示: 代码已推送，仅 Release 创建/上传失败（网络问题）。")
        print(f"  可直接重跑本脚本同版本号来补齐，或手工执行：")
        print(f'    gh release create {version} {" ".join(assets)} '
              f'--title {version} --notes-file "{notes_file}" --repo {REPOSITORY}')
        sys.exit(res.returncode)
    print(f"  Release: {res.stdout.strip()}")


if __name__ == "__main__":
    main()
