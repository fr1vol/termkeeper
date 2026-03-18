#!/usr/bin/env python3
"""
TermKeeper (tk) V1.0 - Claude Code 项目管理工具

功能：
1. tk . - 自动迁移（修复项目移动后的失忆问题）
2. tk migrate - 记忆搬家（交互式选择或显式指定旧路径）
3. tk archive - 归档清洗（将 JSONL 转换为 Markdown）

技术栈：纯 Python 标准库
"""

import argparse
import json
import os
import re
import sys
import signal
import shutil
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Iterator


# =============================================================================
# 全局配置
# =============================================================================
CLAUDE_BASE = Path.home() / ".claude" / "projects"
ARCHIVES_DIR = Path.cwd() / "claude_archives"


# =============================================================================
# 优雅退出机制
# =============================================================================
_shutdown_requested = False


def request_shutdown(signum=None, frame=None):
    global _shutdown_requested
    _shutdown_requested = True


def setup_signal_handlers():
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


def is_shutdown_requested() -> bool:
    return _shutdown_requested


# =============================================================================
# 工具函数
# =============================================================================
def clean_ansi(text: str) -> str:
    """彻底清除 ANSI 颜色代码和控制字符"""
    patterns = [
        re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'),
        re.compile(r'\x1B\[[0-9;]*m'),
        re.compile(r'\x1B\].*?\x07'),
        re.compile(r'\x1B\].*?\x1B\\'),
        re.compile(r'\x07'),
        re.compile(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]'),
    ]
    for pattern in patterns:
        text = pattern.sub('', text)
    return text


def path_to_slug(path) -> str:
    """将路径转换为 slug（/ 替换为 -），保留前导 -"""
    if isinstance(path, str):
        abs_path = Path(path).resolve()
    else:
        abs_path = path.resolve()
    slug = str(abs_path).replace('/', '-').replace('\\', '-')
    # Claude 的目录名保留前导 -（如 -home-user-project）
    return slug


def slug_to_path(slug: str) -> str:
    """将 slug 转换回路径"""
    if slug.startswith('-'):
        return '/' + slug.lstrip('-').replace('-', '/')
    return '/' + slug.replace('-', '/')


def get_current_project_slug() -> Optional[str]:
    """获取当前终端所在路径的项目 slug"""
    try:
        cwd = Path.cwd()
        return path_to_slug(cwd)
    except Exception:
        return None


def format_relative_time(mtime: float) -> str:
    """格式化相对时间"""
    delta = datetime.now().timestamp() - mtime
    if delta < 60:
        return "刚刚"
    elif delta < 3600:
        return f"{int(delta / 60)}分钟前"
    elif delta < 86400:
        return f"{int(delta / 3600)}小时前"
    else:
        return f"{int(delta / 86400)}天前"


# =============================================================================
# JSONL 解析
# =============================================================================
def parse_jsonl_stream(filepath: Path) -> Iterator[Dict]:
    """流式解析 JSONL，支持嵌套 message 格式"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)

                    # 处理嵌套的 message 格式
                    if 'message' in entry and isinstance(entry['message'], dict):
                        nested = entry['message']
                        entry['role'] = nested.get('role', entry.get('type', 'unknown'))
                        entry['content'] = nested.get('content', '')
                        entry['type'] = nested.get('type', entry.get('type', ''))

                    # 处理 content 字段：提取对话文本
                    content = entry.get('content', '')

                    # 如果 content 是列表，提取 text 内容
                    if isinstance(content, list):
                        texts = []
                        for item in content:
                            if isinstance(item, dict):
                                if item.get('type') == 'text' and 'text' in item:
                                    texts.append(item['text'])
                        entry['content'] = '\n'.join(texts) if texts else ''
                    # 如果 content 是字符串但包含 JSON 数组
                    elif isinstance(content, str) and content.strip().startswith('['):
                        try:
                            parsed = json.loads(content)
                            if isinstance(parsed, list):
                                texts = []
                                for item in parsed:
                                    if isinstance(item, dict) and item.get('type') == 'text' and 'text' in item:
                                        texts.append(item['text'])
                                entry['content'] = '\n'.join(texts) if texts else content
                        except json.JSONDecodeError:
                            pass

                    yield entry
                except json.JSONDecodeError:
                    continue
    except (IOError, OSError):
        pass


# =============================================================================
# 功能 1: 记忆搬家 (migrate)
# =============================================================================
def do_migration(old_slug: str, new_slug: str) -> int:
    """执行实际的迁移操作"""
    old_claude_dir = CLAUDE_BASE / old_slug
    new_claude_dir = CLAUDE_BASE / new_slug

    if not old_claude_dir.exists():
        print(f"\033[93m未找到旧 Claude 数据目录: {old_claude_dir}\033[0m")
        print(f"\033[90m提示: 项目可能之前未被 Claude 记录\033[0m")
        return 0

    # 检查新 slug 目录是否已存在
    if new_claude_dir.exists():
        print(f"\033[93m警告: 新目录已存在: {new_claude_dir}\033[0m")
        response = input("是否合并？(y/N): ")
        if response.lower() != 'y':
            return 0

        # 合并操作
        print(f"\033[90m正在合并目录...\033[0m")
        try:
            for item in old_claude_dir.iterdir():
                dest = new_claude_dir / item.name
                if dest.exists():
                    print(f"\033[93m跳过已存在的: {item.name}\033[0m")
                else:
                    shutil.move(str(item), str(dest))
            old_claude_dir.rmdir()
        except Exception as e:
            print(f"\033[91m合并失败: {e}\033[0m")
            return 1
    else:
        # 直接重命名
        print(f"\033[90m正在迁移...\033[0m")
        try:
            shutil.move(str(old_claude_dir), str(new_claude_dir))
        except Exception as e:
            print(f"\033[91m迁移失败: {e}\033[0m")
            return 1

    print(f"\033[92m✓ 记忆搬家完成\033[0m")
    print(f"\033[90m  旧 Claude: {old_claude_dir}\033[0m")
    print(f"\033[90m  新 Claude: {new_claude_dir}\033[0m")

    return 0


def migrate_explicit(old_path_str: str) -> int:
    """显式指定旧路径的迁移"""
    old_path = Path(old_path_str).resolve()

    # 计算新旧 slug（旧路径不需要物理存在，只需字符串）
    new_slug = get_current_project_slug()
    old_slug = path_to_slug(old_path)

    if not new_slug:
        print("\033[91m错误: 无法获取当前路径的 slug\033[0m")
        return 1

    if new_slug == old_slug:
        print(f"\033[93m当前路径与旧路径相同，无需迁移\033[0m")
        return 0

    print(f"\033[90m旧路径: {old_path}\033[0m")
    print(f"\033[90m新路径: {Path.cwd()}\033[0m")
    print(f"\033[90m旧 slug: {old_slug}\033[0m")
    print(f"\033[90m新 slug: {new_slug}\033[0m")

    return do_migration(old_slug, new_slug)


def cmd_auto_migrate(args):
    """
    自动迁移：检测当前目录是否需要迁移，自动执行
    使用方法：tk .
    """
    current_slug = get_current_project_slug()
    if not current_slug:
        print("\033[91m错误: 无法获取当前路径的 slug\033[0m")
        return 1

    current_claude_dir = CLAUDE_BASE / current_slug

    # 检查当前目录是否已有 Claude 数据
    if current_claude_dir.exists():
        print(f"\033[92m✓ 当前目录已有 Claude 数据\033[0m")
        print(f"\033[90m  {current_claude_dir}\033[0m")
        return 0

    print(f"\033[90m当前目录: {Path.cwd()}\033[0m")
    print(f"\033[90m当前 slug: {current_slug}\033[0m")
    print(f"\033[90mClaude 数据: {current_claude_dir}\033[0m")
    print(f"\033[93m未找到对应的 Claude 数据，尝试自动迁移...\033[0m")

    # 获取当前目录的最后一级名称
    current_dir_name = Path.cwd().name

    # 扫描所有 Claude 项目，寻找可能匹配的旧项目
    candidates = []
    if CLAUDE_BASE.exists():
        for old_slug_dir in CLAUDE_BASE.iterdir():
            if not old_slug_dir.is_dir():
                continue

            old_slug = old_slug_dir.name
            original_path = slug_to_path(old_slug)

            # 跳过路径仍存在的项目
            if Path(original_path).exists():
                continue

            # 计算匹配分数
            score = 0
            old_dir_name = Path(original_path).name

            # 目录名完全匹配
            if old_dir_name == current_dir_name:
                score += 100

            # 目录名包含当前目录名（部分匹配）
            elif current_dir_name in old_dir_name or old_dir_name in current_dir_name:
                score += 50

            # 检查归档文件中是否有当前路径或相关标识
            if ARCHIVES_DIR.exists():
                for md_file in ARCHIVES_DIR.glob("*.md"):
                    try:
                        with open(md_file, 'r', encoding='utf-8') as f:
                            content = f.read()
                            # 检查是否包含当前路径
                            if str(Path.cwd()) in content:
                                score += 80
                                break
                            # 检查是否包含当前 slug
                            if current_slug in content:
                                score += 60
                                break
                            # 检查是否包含目录名
                            if current_dir_name in content:
                                score += 30
                    except (IOError, OSError):
                        pass

            # 如果是唯一的项目，给予更高优先级
            if score > 0:
                candidates.append((old_slug, original_path, score))

    # 按分数排序
    candidates.sort(key=lambda x: -x[2])

    if not candidates:
        print(f"\033[93m未找到可能匹配的旧项目\033[0m")
        print()
        print("\033[90m提示:\033[0m")
        print("  1. 如果你知道旧路径，使用: tk migrate <旧路径>")
        print("  2. 查看所有项目，使用: tk migrate")
        return 1

    # 显示候选项目
    print(f"\033[90m找到 {len(candidates)} 个可能匹配的项目:\033[0m")
    for i, (old_slug, original_path, score) in enumerate(candidates, 1):
        print(f"  [{i}] {old_slug} (匹配度: {score})")
        print(f"      旧路径: {original_path}")

    # 自动选择最佳匹配
    best_match = candidates[0]
    old_slug = best_match[0]

    print()
    print(f"\033[90m自动选择: {old_slug}\033[0m")
    print(f"\033[90m将迁移: {old_slug} → {current_slug}\033[0m")

    return do_migration(old_slug, current_slug)


def cmd_migrate(args):
    """
    记忆搬家：修复项目移动后的失忆问题

    新版：交互式选择或显式指定旧路径
    """
    # 如果提供了旧路径参数，使用显式迁移
    if hasattr(args, 'old_path') and args.old_path:
        return migrate_explicit(args.old_path)

    # 否则，显示交互式界面
    print("\033[90m正在扫描 Claude 项目...\033[0m")

    current_slug = get_current_project_slug()
    if not current_slug:
        print("\033[91m错误: 无法获取当前路径的 slug\033[0m")
        return 1

    print(f"\033[90m当前目录: {Path.cwd()}\033[0m")
    print(f"\033[90m当前 slug: {current_slug}\033[0m")
    print()

    # 列出所有 Claude 项目
    projects = []
    if CLAUDE_BASE.exists():
        for slug_dir in CLAUDE_BASE.iterdir():
            if not slug_dir.is_dir():
                continue
            slug = slug_dir.name
            original_path = slug_to_path(slug)
            exists = Path(original_path).exists()
            is_current = (slug == current_slug)
            projects.append((slug, original_path, exists, is_current))

    # 按是否是当前目录排序
    projects.sort(key=lambda x: (not x[3], not x[2]))

    if not projects:
        print("\033[93m未找到任何 Claude 项目\033[0m")
        return 0

    print("\033[1mClaude 项目列表:\033[0m\n")

    for i, (slug, original_path, exists, is_current) in enumerate(projects, 1):
        status = "\033[92m✓ 当前\033[0m" if is_current else ("\033[91m✗ 不存在\033[0m" if not exists else "\033[90m○ 存在\033[0m")
        print(f"[{i}] {slug}")
        print(f"    {status}")
        print(f"    路径: {original_path}")
        print()

    # 检查是否有当前目录对应的 Claude 数据
    current_exists = any(is_current for _, _, _, is_current in projects)
    if not current_exists:
        print(f"\033[93m当前目录没有对应的 Claude 数据\033[0m")
        print("\033[90m提示:\033[0m")
        print("  如果你的项目刚移动过来，请选择要迁移的旧项目：")

        # 找出可能需要迁移的项目（路径不存在的）
        needs_migration = [(i, slug, original_path) for i, (slug, original_path, exists, _) in enumerate(projects, 1) if not exists]

        if needs_migration:
            print(f"\n  可能需要迁移的项目 (路径不存在):")
            for i, slug, path in needs_migration[:5]:  # 只显示前5个
                print(f"    [{i}] {slug}")
        else:
            print("  未发现路径不存在的项目")

        print()
        response = input("选择要迁移的项目序号 (直接回车跳过): ")

        if not response.strip():
            print("已取消")
            return 0

        try:
            idx = int(response) - 1
            if 0 <= idx < len(projects):
                old_slug = projects[idx][0]
                print(f"\n\033[90m将迁移: {old_slug} → {current_slug}\033[0m")
                response = input("确认？(y/N): ")
                if response.lower() == 'y':
                    return do_migration(old_slug, current_slug)
        except (ValueError, IndexError):
            print("\033[91m无效的序号\033[0m")
            return 1
    else:
        print(f"\033[92m✓ 当前目录已有对应的 Claude 数据，无需迁移\033[0m")

    return 0


# =============================================================================
# 功能 2: 归档清洗 (archive)
# =============================================================================
def sanitize_filename(name: str) -> str:
    """清理文件名，移除不安全字符"""
    # 移除或替换不安全的字符
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    # 移除多余的空白和标点
    name = re.sub(r'\s+', '_', name)
    # 保留中文、字母、数字、下划线、短横线、点
    name = re.sub(r'[^\w\u4e00-\u9fff\-_.]', '', name)
    # 限制长度
    if len(name) > 40:
        name = name[:40].rstrip('_')
    return name.strip() or "未命名"


def compute_file_hash(filepath: Path) -> str:
    """计算文件的 SHA256 hash"""
    sha256 = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (IOError, OSError):
        return ""


def generate_session_document(meta: Dict, entries: List[Dict], source_hash: str = "") -> Tuple[str, str]:
    """生成会话 Markdown 文档，返回 (文档内容, 标题)"""

    uuid = meta['uuid']
    project_name = meta.get('project_name', meta['project_hash'][:12])
    mtime = meta.get('source_mtime', 0)

    # 收集 subagent
    subagents = set()
    for entry in entries:
        if entry.get('type') == 'subagent' or entry.get('is_subagent'):
            subagents.add(entry.get('subagent_name', 'unknown'))

    # 使用项目名作为标题
    title = f"{project_name}会话"

    # 构建文档
    output = []

    # 标题
    output.append(f"# 📔 {title}")
    output.append("")
    output.append("---")

    # Frontmatter
    dt = datetime.fromtimestamp(mtime)
    output.append(f"date: {dt.strftime('%Y-%m-%d')}")
    output.append(f"project: {project_name}")
    output.append(f"session_id: {uuid}")
    output.append(f"last_updated: {dt.strftime('%Y-%m-%d %H:%M')}")

    # 添加项目路径
    project_hash = meta.get('project_hash', '')
    if project_hash:
        project_path = '/' + project_hash.lstrip('-').replace('-', '/')
        output.append(f"project_path: {project_path}")

    # 添加源文件 hash（用于增量更新检测）
    if source_hash:
        output.append(f"source_hash: {source_hash}")

    output.append("---")
    output.append("")

    # 对话记录
    output.append("## 对话记录")
    output.append("")

    # 子代理列表
    if subagents:
        output.append("**使用的子代理：**")
        for name in sorted(subagents):
            output.append(f"- `{name}`")
        output.append("")

    # 对话内容
    for entry in entries:
        if entry.get('is_subagent') or entry.get('type') == 'subagent':
            continue

        role = entry.get('role', '')
        if role not in ('user', 'assistant'):
            continue

        content = str(entry.get('content', '')).strip()
        content = clean_ansi(content)

        if not content:
            continue

        role_name = "User" if role == "user" else "Assistant"
        output.append(f"### {role_name}")
        output.append("")
        output.append(content)
        output.append("")

    return '\n'.join(output), title


def find_existing_archive(session_id: str) -> Optional[Tuple[Path, str]]:
    """查找已存在的归档文件，返回 (文件路径, 存储的源文件hash)"""
    if not ARCHIVES_DIR.exists():
        return None

    # 扫描归档目录，查找包含该 session_id 的文件
    for md_file in ARCHIVES_DIR.glob("*.md"):
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                stored_hash = None
                # 读取前几行，查找 session_id 和 source_hash
                for line in f:
                    if line.startswith('session_id:'):
                        existing_id = line.split(':', 1)[1].strip()
                        if existing_id == session_id:
                            # 继续读取查找 source_hash
                            for hash_line in f:
                                if hash_line.startswith('source_hash:'):
                                    stored_hash = hash_line.split(':', 1)[1].strip()
                                    break
                                if hash_line == '---':
                                    break
                            if stored_hash is not None:
                                return (md_file, stored_hash)
                    if line == '---':
                        break  # frontmatter 结束
        except (IOError, OSError):
            continue
    return None


def sync_session(meta: Dict) -> bool:
    """同步单个会话到归档目录（增量更新）"""
    source_path = Path(meta['source_path'])
    if not source_path.exists():
        return False

    uuid = meta['uuid']

    # 计算源文件 hash
    source_hash = compute_file_hash(source_path)
    if not source_hash:
        return False  # 无法计算 hash，跳过

    # 查找已存在的归档
    existing = find_existing_archive(uuid)

    # 如果归档已存在且 hash 相同，跳过
    if existing:
        existing_file, stored_hash = existing
        if stored_hash and stored_hash == source_hash:
            return False  # 内容未变更，跳过

    target_dir = ARCHIVES_DIR

    # 收集所有 entries（主会话 + subagents）
    all_entries = []
    seen_subagents = set()

    # 解析主会话 JSONL
    for entry in parse_jsonl_stream(source_path):
        all_entries.append(entry)

    # 检查 subagents 目录
    session_dir = source_path.parent / uuid
    subagents_dir = session_dir / "subagents"

    if subagents_dir.exists() and subagents_dir.is_dir():
        for subagent_file in subagents_dir.glob("*.jsonl"):
            subagent_name = subagent_file.stem
            if subagent_name in seen_subagents:
                continue
            seen_subagents.add(subagent_name)

            all_entries.append({
                'type': 'subagent',
                'is_subagent': True,
                'subagent_name': subagent_name,
                'role': 'system',
                'content': f'[Subagent: {subagent_name}]'
            })

    # 检查是否有实际对话内容
    dialog_entries = [e for e in all_entries if e.get('role') in ('user', 'assistant') and str(e.get('content', '')).strip()]
    if not dialog_entries:
        return False

    # 生成文档和标题（传入源文件 hash）
    doc, title = generate_session_document(meta, all_entries, source_hash)

    # 如果有现有归档，直接覆盖；否则生成新文件名
    if existing:
        target_file = existing[0]
    else:
        # 生成文件名：YYYY-MM-DD_标题.md
        dt = datetime.fromtimestamp(meta.get('source_mtime', time.time()))
        date_str = dt.strftime("%Y-%m-%d")
        clean_title = sanitize_filename(title)
        base_filename = f"{date_str}_{clean_title}"
        target_file = target_dir / f"{base_filename}.md"

        # 处理文件名冲突
        counter = 1
        while target_file.exists():
            target_file = target_dir / f"{base_filename}_{counter}.md"
            counter += 1

    # 写入文件
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(doc)
        return True
    except IOError:
        return False


def cmd_archive(args):
    """归档清洗：扫描 Claude 项目目录，生成 Markdown 归档"""
    if not CLAUDE_BASE.exists():
        print(f"\033[93m未找到 Claude 项目目录: {CLAUDE_BASE}\033[0m")
        return 0

    print(f"\033[90m正在扫描会话...\033[0m")

    sessions_to_sync = []
    for project_dir in CLAUDE_BASE.iterdir():
        if is_shutdown_requested():
            break
        if not project_dir.is_dir():
            continue

        for jsonl_file in project_dir.glob("*.jsonl"):
            if is_shutdown_requested():
                break

            mtime = jsonl_file.stat().st_mtime
            uuid = jsonl_file.stem

            # 获取项目名
            project_name = project_dir.name
            if project_name.startswith('-home-'):
                parts = project_name.split('-', 2)
                if len(parts) > 2:
                    project_name = parts[2]

            meta = {
                'uuid': uuid,
                'source_path': str(jsonl_file),
                'source_mtime': mtime,
                'project_hash': project_dir.name,
                'project_name': project_name,
            }
            sessions_to_sync.append(meta)

    if not sessions_to_sync:
        print(f"\033[93m未找到任何会话\033[0m")
        return 0

    print(f"\033[90m找到 {len(sessions_to_sync)} 个会话\033[0m")
    print(f"\033[90m正在生成归档到: {ARCHIVES_DIR}\033[0m")

    # 创建归档目录
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)

    synced_count = 0
    skipped_count = 0
    for i, meta in enumerate(sessions_to_sync, 1):
        if is_shutdown_requested():
            break

        uuid_short = meta['uuid'][:8]
        result = sync_session(meta)

        if result:
            synced_count += 1
            print(f"\033[90m  [{i}/{len(sessions_to_sync)}] {uuid_short}... \033[92m已更新\033[0m")
        else:
            skipped_count += 1

    print(f"\033[90m{' ' * 60}\033[0m")
    print(f"\033[92m✓ 已归档 {synced_count} 个会话\033[0m")
    if skipped_count > 0:
        print(f"\033[90m  跳过 {skipped_count} 个未变更的会话（基于 hash 检测）\033[0m")
    print(f"\033[90m  归档目录: {ARCHIVES_DIR}\033[0m")

    return 0


# =============================================================================
# 主入口
# =============================================================================
def main():
    setup_signal_handlers()

    # 检查是否是 `tk .` 命令（自动迁移）
    if len(sys.argv) >= 2 and sys.argv[1] == '.':
        try:
            return cmd_auto_migrate(None)
        except KeyboardInterrupt:
            print("\n\033[90m操作已取消\033[0m")
            return 130

    parser = argparse.ArgumentParser(
        prog="tk",
        description="TermKeeper V1.0 - Claude Code 项目管理工具"
    )

    # 短选项别名
    parser.add_argument('-m', '--migrate', nargs='*', metavar='OLD_PATH',
                        help='记忆搬家（等同于 migrate 命令）')
    parser.add_argument('-a', '--archive', action='store_true',
                        help='归档清洗（等同于 archive 命令）')

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # migrate 命令
    migrate_parser = subparsers.add_parser('migrate', help='记忆搬家（修复项目移动后的失忆问题）')
    migrate_parser.add_argument('old_path', nargs='?', help='旧的项目路径（可选，不指定则交互式选择）')

    # archive 命令
    subparsers.add_parser('archive', help='归档清洗（将 JSONL 转换为 Markdown）')

    args = parser.parse_args()

    try:
        # 处理短选项别名
        if args.migrate is not None:
            old_path = args.migrate[0] if args.migrate else None
            if old_path is None:
                # tk -m 不带参数，执行自动迁移
                return cmd_auto_migrate(None)
            else:
                # tk -m <path> 显式指定路径
                return migrate_explicit(old_path)
        if args.archive:
            return cmd_archive(None)

        # 处理子命令
        if not args.command:
            parser.print_help()
            return 0

        if args.command == 'migrate':
            return cmd_migrate(args)
        elif args.command == 'archive':
            return cmd_archive(args)
    except KeyboardInterrupt:
        print("\n\033[90m操作已取消\033[0m")
        return 130

    return 0


if __name__ == '__main__':
    sys.exit(main())
