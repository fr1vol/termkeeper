#!/usr/bin/env python3
"""
TermKeeper (tk) - Claude Code 日志管理工具
统一目录管理，LLM 智能摘要（GLM 优先，Ollama 备选）

架构：
- ~/.termkeeper/sessions/  所有会话统一存放（纯 Markdown 格式）
- 每次运行自动同步所有会话
- tk list 只显示最近 24h 的
"""

import hashlib
import json
import re
import sys
import time
import signal
import argparse
import shutil
from itertools import islice
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Iterator
import urllib.request
import urllib.error


# =============================================================================
# 全局配置
# =============================================================================
CLAUDE_BASE = Path.home() / ".claude" / "projects"
TERMKEEPER_BASE = Path.home() / ".termkeeper"
SESSIONS_DIR = TERMKEEPER_BASE / "sessions"

# 配置文件路径
CONFIG_FILE = Path(__file__).parent / "config.json"
CONFIG_EXAMPLE_FILE = Path(__file__).parent / "config.json.example"


# =============================================================================
# 配置加载
# =============================================================================
def load_config() -> dict:
    """加载配置文件"""
    config = {
        "glm": {
            "api_key": "",
            "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
            "model": "glm-4-flash",
            "timeout": 30
        },
        "ollama": {
            "base_url": "http://localhost:11434",
            "model": "qwen3.5:2b",
            "timeout": 30
        },
        "display": {
            "list_threshold_hours": 24,
            "max_summary_length": 30
        }
    }

    # 尝试加载配置文件
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                # 递归合并配置
                def merge_dict(base, update):
                    for key, value in update.items():
                        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                            merge_dict(base[key], value)
                        else:
                            base[key] = value
                merge_dict(config, user_config)
        except (json.JSONDecodeError, IOError):
            pass

    return config


# 加载配置
_config = load_config()

# GLM API 配置（智谱 AI）
GLM_API_KEY = _config["glm"]["api_key"]
GLM_BASE_URL = _config["glm"]["base_url"]
GLM_MODEL = _config["glm"]["model"]
GLM_TIMEOUT = _config["glm"]["timeout"]

# Ollama 配置（备选）
OLLAMA_BASE_URL = _config["ollama"]["base_url"]
OLLAMA_MODEL = _config["ollama"]["model"]
OLLAMA_TIMEOUT = _config["ollama"]["timeout"]

# 显示配置
LIST_THRESHOLD_HOURS = _config["display"]["list_threshold_hours"]
MAX_SUMMARY_LENGTH = _config["display"]["max_summary_length"]


# =============================================================================
# 优雅退出机制
# =============================================================================
_shutdown_requested = False


def request_shutdown(signum=None, frame=None):
    global _shutdown_requested
    _shutdown_requested = True


def is_shutdown_requested() -> bool:
    return _shutdown_requested


def setup_signal_handlers():
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


# =============================================================================
# 工具函数
# =============================================================================
def clean_ansi(text: str) -> str:
    """清除 ANSI 颜色代码"""
    patterns = [
        re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'),
        re.compile(r'\x1B\[[0-9;]*m'),
        re.compile(r'\x07'),
        re.compile(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]'),
    ]
    for pattern in patterns:
        text = pattern.sub('', text)
    return text


def truncate_text(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + '…'


def format_relative_time(mtime: float) -> str:
    delta = time.time() - mtime
    if delta < 60:
        return "刚刚"
    elif delta < 3600:
        return f"{int(delta / 60)}分钟前"
    elif delta < 86400:
        return f"{int(delta / 3600)}小时前"
    else:
        return f"{int(delta / 86400)}天前"


def extract_uuid_from_path(filepath: Path) -> str:
    """从路径提取 UUID"""
    return filepath.stem


def get_file_mtime(filepath: Path) -> float:
    """安全获取文件修改时间"""
    try:
        return filepath.stat().st_mtime
    except OSError:
        return 0.0


# =============================================================================
# LLM 客户端
# =============================================================================
class LLMClient:
    """GLM + Ollama 统一客户端"""

    def __init__(self):
        self.glm_api_key = GLM_API_KEY
        self.glm_base_url = GLM_BASE_URL.rstrip('/')
        self.glm_model = GLM_MODEL
        self.glm_timeout = GLM_TIMEOUT

        self.ollama_base_url = OLLAMA_BASE_URL.rstrip('/')
        self.ollama_model = OLLAMA_MODEL
        self.ollama_timeout = OLLAMA_TIMEOUT
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        # 优先检查 GLM
        if self._check_glm():
            self._available = True
            return True
        # 备选：Ollama
        if self._check_ollama():
            self._available = True
            return True
        self._available = False
        return False

    def _check_glm(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{self.glm_base_url}/chat/completions",
                method="POST"
            )
            req.add_header("Authorization", f"Bearer {self.glm_api_key}")
            req.add_header("Content-Type", "application/json")
            test_data = json.dumps({
                "model": self.glm_model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1
            }).encode("utf-8")
            with urllib.request.urlopen(req, data=test_data, timeout=10) as response:
                return 200 <= response.status < 300
        except Exception:
            return False

    def _check_ollama(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{self.ollama_base_url}/api/tags",
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except Exception:
            return False

    def _call_glm(self, messages: list, timeout: Optional[int] = None) -> Optional[str]:
        try:
            data = json.dumps({
                "model": self.glm_model,
                "messages": messages,
                "stream": False
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.glm_base_url}/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.glm_api_key}"
                }
            )

            to = timeout or self.glm_timeout
            with urllib.request.urlopen(req, timeout=to) as response:
                result = json.loads(response.read().decode("utf-8"))
                if "choices" in result and len(result["choices"]) > 0:
                    return result["choices"][0]["message"]["content"].strip()
                return None
        except Exception:
            return None

    def _call_ollama(self, prompt: str, timeout: Optional[int] = None) -> Optional[str]:
        try:
            data = json.dumps({
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.ollama_base_url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"}
            )

            to = timeout or self.ollama_timeout
            with urllib.request.urlopen(req, timeout=to) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result.get("response", "").strip()
        except Exception:
            return None

    def generate(self, prompt: str, timeout: Optional[int] = None) -> Optional[str]:
        # 优先使用 GLM API
        result = self._call_glm([{"role": "user", "content": prompt}], timeout)
        if result:
            return result
        # 备选：Ollama
        return self._call_ollama(prompt, timeout)

    def generate_intent(self, content: str) -> str:
        """生成意图（用于标题）"""
        if not content or not content.strip():
            return "(空)"
        clean_content = clean_ansi(content)
        prompt = f"""用 15-20 个中文字符总结这段对话的核心工作内容，作为标题使用。

{clean_content[:1500]}"""
        result = self.generate(prompt)
        if result:
            return clean_ansi(result)[:30]
        return truncate_text(clean_content, 30)

    def generate_summary(self, content: str) -> str:
        """生成详细摘要"""
        if not content or not content.strip():
            return "(空)"
        clean_content = clean_ansi(content)
        prompt = f"""用 50-100 字总结这段对话的核心内容、解决的问题和最终结果。

{clean_content[:2500]}"""
        result = self.generate(prompt)
        if result:
            return clean_ansi(result)[:200]
        return truncate_text(clean_content, 200)

    def generate_recovery_capsule(self, entries: List[Dict]) -> str:
        """生成恢复胶囊"""
        # 取最后几轮对话
        tail_entries = entries[-6:] if len(entries) >= 6 else entries
        context = '\n\n'.join([
            f"{e.get('role', '')}: {str(e.get('content', ''))[:300]}"
            for e in tail_entries
            if e.get('role') in ('user', 'assistant')
        ])

        prompt = f"""基于以下对话末尾，生成恢复胶囊：

用户现在的进度停留在什么阶段，还有什么待办事项。
直接输出内容，不要 XML 标签，100 字以内。

{context[:2000]}"""

        result = self.generate(prompt, timeout=45)
        if result:
            return clean_ansi(result)
        return "会话进行中，待办事项未知。"

    def generate_context_compaction(self, dialog_content: str) -> str:
        """使用 Anthropic 风格的上下文压缩方法生成恢复提示词

        基于 Anthropic Automatic Context Compaction 最佳实践：
        1. 已完成的工作 - 完成的关键任务和结果
        2. 当前进度 - 整体进度状态
        3. 关键发现 - 重要信息和学到的经验
        4. 下一步行动 - 接下来要做什么

        这种方法在客户服务工作流中实现了 58.6% 的 Token 节省。
        """
        if not dialog_content or not dialog_content.strip():
            return "无法提取上下文"

        clean_content = clean_ansi(dialog_content)

        # 使用结构化的提示词，基于 Anthropic 的最佳实践
        prompt = f"""你是一个上下文压缩专家。请将以下对话压缩成一段结构化的"恢复提示词"（200-300字）。

严格按照以下 4 部分结构输出（不要使用标题或格式符号）：

已完成的工作：
[列出完成的关键任务、实现的功能、解决的问题。使用简洁的短语，每项一行]

当前进度：
[描述整体进度状态，包括：已完成多少、正在做什么、还剩多少]

关键发现：
[列出重要的技术发现、学到的经验、需要注意的坑。每项一行]

下一步行动：
[列出接下来要做的具体事项。使用动词开头，每项一行]

直接输出压缩后的内容，不要添加任何前言、总结或格式符号。

对话内容：
{clean_content[:4000]}
"""

        result = self.generate(prompt, timeout=60)
        if result:
            result = clean_ansi(result).strip()
            # 确保结果不会太短或太长
            if len(result) < 100:
                # 结果太短，返回原始内容的截断版本
                return clean_content[:300] + "..." if len(clean_content) > 300 else clean_content
            elif len(result) > 600:
                # 结果太长，进行截断
                return result[:600] + "..."
            return result

        # LLM 失败时的备选方案：提取关键对话片段
        lines = clean_content.split('\n')
        key_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('###') and len(line) > 10:
                key_lines.append(line)
                if len(key_lines) >= 5:
                    break

        if key_lines:
            return '\n'.join(key_lines[:5])
        return clean_content[:300] + "..." if len(clean_content) > 300 else clean_content


llm = LLMClient()


# =============================================================================
# JSONL 解析
# =============================================================================
def parse_jsonl_stream(filepath: Path) -> Iterator[Dict]:
    """流式解析 JSONL"""
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
                                # 只保留 type='text' 的内容
                                if item.get('type') == 'text' and 'text' in item:
                                    texts.append(item['text'])
                        entry['content'] = '\n'.join(texts) if texts else ''
                    # 如果 content 是字符串但包含 JSON 数组
                    elif isinstance(content, str) and content.strip().startswith('['):
                        # 尝试解析 JSON 字符串
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


def extract_files_changed(entries: List[Dict]) -> List[Dict[str, str]]:
    """提取变更的文件"""
    files = []
    for entry in entries:
        if entry.get('type') == 'tool_use':
            tool_name = entry.get('name', '')
            content = str(entry.get('content', ''))
            if 'read' in tool_name or 'edit' in tool_name or 'write' in tool_name:
                paths = re.findall(r'["\']([/\w\.\-]+)["\']', content)
                for p in paths:
                    if '/' in p and not p.startswith('/'):
                        action = 'modify' if 'edit' in tool_name else 'check'
                        files.append({'path': p, 'action': action})
                        if len(files) >= 10:
                            break
    return files


def compute_content_hash(content: str) -> str:
    """计算内容哈希，用于缓存 GLM 结果"""
    return hashlib.md5(content.encode('utf-8')).hexdigest()[:12]


def clean_json_arrays(text: str) -> str:
    """移除文本中的 JSON 数组内容（如思考过程），保留对话文本"""
    result = []
    lines = text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # 跳过空行
        if not line:
            result.append('')
            i += 1
            continue

        # 检测 JSON 数组开始
        if line.startswith('['):
            # 尝试收集完整的 JSON（可能跨多行）
            json_text = line
            j = i + 1
            bracket_count = line.count('[') - line.count(']')
            while j < len(lines) and bracket_count > 0:
                json_text += '\n' + lines[j]
                bracket_count += lines[j].count('[') - lines[j].count(']')
                j += 1

            # 尝试解析 JSON
            try:
                parsed = json.loads(json_text)
                if isinstance(parsed, list):
                    # 提取文本内容
                    texts = []
                    for item in parsed:
                        if isinstance(item, str):
                            texts.append(item)
                        elif isinstance(item, dict):
                            # 提取 text 字段
                            if 'text' in item:
                                texts.append(item['text'])
                            # 提取 content 字段
                            elif 'content' in item:
                                content = item['content']
                                if isinstance(content, str):
                                    texts.append(content)
                            # 提取 thinking 字段（标记为思考）
                            elif 'thinking' in item:
                                thinking = item['thinking']
                                if isinstance(thinking, str) and len(thinking) > 0:
                                    texts.append(f"[思考] {thinking[:100]}...")
                    if texts:
                        result.extend(texts)
                    i = j
                    continue
            except (json.JSONDecodeError, ValueError):
                pass

        # 非 JSON 或解析失败，保留原行
        result.append(lines[i])
        i += 1

    # 清理残留的 JSON 片段
    cleaned = '\n'.join(result)
    # 移除明显的 JSON 残留
    cleaned = re.sub(r'\[\'"\w+\'"(?:,\s*)?', '', cleaned)
    cleaned = re.sub(r'\]\s*', '', cleaned)
    cleaned = re.sub(r",\s*\]", ']', cleaned)

    return cleaned.strip()


def sanitize_filename(name: str) -> str:
    """清理文件名，移除不安全字符和 JSON 残留"""
    # 先清理 JSON 数组
    name = clean_json_arrays(name)
    # 移除或替换不安全的字符
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    # 移除多余的空白和标点
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'[^\w\u4e00-\u9fff\-_.]', '', name)
    # 限制长度
    if len(name) > 50:
        name = name[:50].rstrip('_')
    return name.strip() or "未命名"


def extract_cached_data(filepath: Path) -> Optional[Dict]:
    """从已有 MD 文件中提取缓存的 GLM 结果"""
    if not filepath.exists():
        return None

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            # 提取 content_hash
            hash_match = re.search(r'content_hash:\s*(\w+)', content)
            if not hash_match:
                return None

            # 从标题提取 intent (格式: # [project] intent)
            intent = None
            title_match = re.search(r'^#\s+\[[^\]]+\]\s*(.+)$', content, re.MULTILINE)
            if title_match:
                intent = title_match.group(1).strip()

            # 提取项目描述
            summary = None
            desc_match = re.search(r'\*\*项目描述：\*\*\s*(.+?)(?:\n|$)', content)
            if desc_match:
                summary = desc_match.group(1).strip()

            return {
                'content_hash': hash_match.group(1),
                'intent': intent,
                'summary': summary,
            }
    except (IOError, OSError):
        pass

    return None


def generate_session_filename(meta: Dict, intent: str) -> str:
    """生成文件名: YYYY-MM-DD_标题.md"""
    dt = datetime.fromtimestamp(meta.get('source_mtime', time.time()))
    date_str = dt.strftime("%Y-%m-%d")

    clean_intent = sanitize_filename(intent)

    base_name = f"{date_str}_{clean_intent}"
    return base_name[:100] + ".md"  # 限制总长度


# =============================================================================
# 会话文档生成
# =============================================================================
def generate_session_document(meta: Dict, entries: List[Dict], cached_data: Optional[Dict] = None) -> Tuple[str, str]:
    """生成会话文档，返回 (文档内容, 建议文件名)"""

    # 提取对话内容
    dialog_entries = [e for e in entries if e.get('role') in ('user', 'assistant')]
    content_sample = '\n'.join([
        str(e.get('content', ''))
        for e in dialog_entries[:50]
    ])

    # 计算内容哈希
    content_hash = compute_content_hash(content_sample)

    # 检查缓存
    intent = summary = None
    use_cache = False

    if cached_data and cached_data.get('content_hash') == content_hash:
        # 内容未变，使用缓存
        use_cache = True
        intent = cached_data.get('intent')
        summary = cached_data.get('summary')

    if not use_cache:
        # 需要调用 GLM
        clean_sample = clean_json_arrays(content_sample)
        intent = llm.generate_intent(clean_sample)
        summary = llm.generate_summary(clean_sample)

    # 清理 GLM 返回的内容
    if intent:
        intent = clean_json_arrays(clean_ansi(intent))
    if summary:
        summary = clean_json_arrays(clean_ansi(summary))

    # 获取时间信息
    mtime = meta.get('source_mtime', time.time())
    dt = datetime.fromtimestamp(mtime)
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%Y-%m-%d %H:%M")

    # 构建文档
    output = []

    # 标题: 项目概括（简短，意图明显）
    project_name = meta.get('project_name', meta['project_hash'][:12])
    title = f"# [{project_name}] {intent}" if intent else f"# [{project_name}]"
    output.append(title)
    output.append("")

    # 项目描述：本次对话概括，50字以内
    if summary:
        output.append(f"**项目描述：** {summary[:50]}")
        output.append("")

    # Frontmatter
    output.append("---")
    output.append(f"content_hash: {content_hash}")
    output.append(f"date: {date_str}")
    output.append(f"session_id: {meta['uuid']}")
    output.append(f"last_updated: {time_str}")
    output.append("---")
    output.append("")

    # 对话记录
    output.append("## 对话记录")
    output.append("")

    # 收集 subagent 名称
    subagents = set()
    for entry in entries:
        if entry.get('type') == 'subagent':
            subagents.add(entry.get('subagent_name', 'unknown'))

    # 输出 subagent 列表
    if subagents:
        output.append("**使用的子代理：**")
        for name in sorted(subagents):
            output.append(f"- `{name}`")
        output.append("")

    # 输出对话（只保留有内容的）
    for entry in entries:
        if entry.get('is_subagent') or entry.get('type') == 'subagent':
            continue

        role = entry.get('role', '')
        if role not in ('user', 'assistant'):
            continue

        content = str(entry.get('content', '')).strip()
        # 清理对话内容
        content = clean_json_arrays(clean_ansi(content))

        # 跳过空内容
        if not content:
            continue

        # Markdown 格式输出
        role_name = "User" if role == "user" else "Assistant"
        output.append(f"### {role_name}")
        output.append("")
        output.append(content)
        output.append("")

    # 生成语义化文件名
    filename = generate_session_filename(meta, intent)

    return '\n'.join(output), filename


# =============================================================================
# 同步
# =============================================================================
def sync_session(meta: Dict) -> bool:
    """同步单个会话（合并主会话和 subagent）"""
    source_path = Path(meta['source_path'])
    if not source_path.exists():
        return False

    uuid = meta['uuid']

    # 先尝试查找已有的语义化文件（通过 session_id 匹配）
    existing_file = None
    cached_data = None

    if SESSIONS_DIR.exists():
        for md_file in SESSIONS_DIR.glob("*.md"):
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    for line in islice(f, 30):
                        if f"session_id: {uuid}" in line:
                            existing_file = md_file
                            break
            except (IOError, OSError):
                pass
            if existing_file:
                break

    # 检查是否需要更新
    need_update = False
    if not existing_file:
        need_update = True
    else:
        # 比较 mtime
        target_mtime = get_file_mtime(existing_file)
        if meta['source_mtime'] > target_mtime:
            need_update = True
            # 提取缓存数据
            cached_data = extract_cached_data(existing_file)

    if not need_update:
        return False

    # 收集所有 entries（主会话 + subagents）
    all_entries = []
    seen_subagents = set()

    # 解析主会话 JSONL
    for entry in parse_jsonl_stream(source_path):
        all_entries.append(entry)

    # 检查是否有 subagents 目录
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
                'timestamp': '',
                'role': 'system',
                'content': f'[Subagent: {subagent_name}]'
            })

    # 检查是否有实际对话内容（排除空的）
    dialog_entries = [e for e in all_entries if e.get('role') in ('user', 'assistant') and str(e.get('content', '')).strip()]
    if not dialog_entries:
        # 没有实际对话内容，跳过归档
        return False

    # 按时间排序
    all_entries.sort(key=lambda e: e.get('timestamp', ''), reverse=False)

    # 生成文档（传入缓存数据，减少 GLM 调用）
    doc, filename = generate_session_document(meta, all_entries, cached_data)

    # 确定最终文件名（处理冲突）
    target_file = SESSIONS_DIR / filename
    if target_file != existing_file and target_file.exists():
        # 文件名冲突，追加 UUID 后缀
        name_without_ext = filename.rsplit('.', 1)[0]
        target_file = SESSIONS_DIR / f"{name_without_ext}_{uuid[:8]}.md"

    # 写入文件
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(doc)

        # 如果旧文件存在且路径不同，删除旧文件
        if existing_file and existing_file != target_file and existing_file.exists():
            existing_file.unlink()

        return True
    except IOError:
        return False


def sync_all_sessions() -> int:
    """同步所有会话"""
    if not CLAUDE_BASE.exists():
        return 0

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    synced_count = 0

    # 扫描所有会话
    sessions_to_sync = []
    for project_dir in CLAUDE_BASE.iterdir():
        if is_shutdown_requested():
            break
        if not project_dir.is_dir():
            continue

        # 只扫描主目录的 .jsonl 文件（跳过 subagents 目录）
        for jsonl_file in project_dir.glob("*.jsonl"):
            if is_shutdown_requested():
                break

            mtime = get_file_mtime(jsonl_file)
            uuid = extract_uuid_from_path(jsonl_file)

            # 获取项目名
            project_name = project_dir.name
            # 移除 -home-rubick- 前缀或 -home-rubick
            if project_name == '-home-rubick':
                project_name = 'default'
            elif project_name.startswith('-home-rubick-'):
                project_name = project_name[13:] or 'default'
            project_name_file = project_dir / ".tk_project_name"
            if project_name_file.exists():
                try:
                    project_name = project_name_file.read_text(encoding='utf-8').strip()
                except IOError:
                    pass

            meta = {
                'uuid': uuid,
                'source_path': str(jsonl_file),
                'source_mtime': mtime,
                'project_hash': project_dir.name,
                'project_name': project_name,
            }
            sessions_to_sync.append(meta)

    # 同步
    for meta in sessions_to_sync:
        if is_shutdown_requested():
            break
        if sync_session(meta):
            synced_count += 1

    return synced_count


def generate_resume_prompt(content: str) -> str:
    """生成恢复提示词（压缩上下文）

    使用 Anthropic Automatic Context Compaction 最佳实践：
    1. 已完成的工作 - 完成的关键任务和结果
    2. 当前进度 - 整体进度状态
    3. 关键发现 - 重要的信息和学到的经验
    4. 下一步行动 - 接下来要做什么

    这种方法在客户服务工作流中实现了 58.6% 的 Token 节省。
    """
    # 提取对话部分
    dialog_match = re.search(r'## 对话记录\s*(.*?)(?=\n---\n|$)', content, re.DOTALL)
    if not dialog_match:
        return "无法提取对话内容"

    dialog = dialog_match.group(1)
    clean_dialog = clean_ansi(dialog)

    # 使用 LLMClient 的上下文压缩方法
    return llm.generate_context_compaction(clean_dialog)


# =============================================================================
# 命令实现
# =============================================================================
def get_all_sessions_sorted():
    """获取所有会话，按时间排序（最新的在前）"""
    all_sessions = [(f, get_file_mtime(f)) for f in SESSIONS_DIR.glob("*.md")]
    all_sessions.sort(key=lambda x: x[1], reverse=True)
    return all_sessions


def cmd_list(args):
    """列出所有会话（按时间排序）"""
    print("\033[90m同步中...\033[0m", end="", flush=True)

    synced = sync_all_sessions()

    if synced > 0:
        print(f" \033[90m(更新 {synced} 个会话)\033[0m")
    else:
        print(f" \033[90m(已是最新)\033[0m")

    all_sessions = get_all_sessions_sorted()

    if not all_sessions:
        print(f"\n没有找到任何会话")
        return

    print(f"\n\033[1m所有会话 ({len(all_sessions)}):\033[0m\n")

    for idx, (filepath, mtime) in enumerate(all_sessions, 1):
        if is_shutdown_requested():
            break

        time_str = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
        relative = format_relative_time(mtime)

        # 从文件读取标题
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
            # 提取 ] 后面的内容作为标题
            if ']' in first_line:
                title = first_line.split(']', 1)[1].strip() if ']' in first_line else first_line
            else:
                title = first_line
        except IOError:
            title = filepath.stem

        title = re.sub(r'^会话归档:\s*', '', title)
        title = truncate_text(title, 60)

        print(f"[{idx:3d}] \033[36m{time_str}\033[0m (\033[90m{relative}\033[0m) {title}")


def cmd_sync(args):
    """手动同步所有会话"""
    print("\033[90m正在同步会话...\033[0m", end="", flush=True)

    synced = sync_all_sessions()
    print()

    all_sessions = get_all_sessions_sorted()

    if synced > 0:
        print(f"\033[92m✓ 已更新 {synced} 个会话\033[0m")
    else:
        print(f"\033[90m所有会话已是最新\033[0m")

    print(f"\n总计: {len(all_sessions)} 个会话")


def cmd_recover(args):
    """恢复指定序号的会话，或最新的会话"""
    print("\033[90m正在生成恢复提示词...\033[0m", end="", flush=True)
    sync_all_sessions()
    print()

    all_sessions = get_all_sessions_sorted()
    if not all_sessions:
        print("\n未找到任何会话")
        return

    # 获取序号参数
    index = None
    if hasattr(args, 'index') and args.index is not None:
        try:
            index = int(args.index) - 1  # 转换为 0-based
            if index < 0 or index >= len(all_sessions):
                print(f"\n\033[91m错误: 序号必须在 1-{len(all_sessions)} 之间\033[0m")
                return
        except ValueError:
            print(f"\n\033[91m错误: 无效的序号 '{args.index}'\033[0m")
            return

    # 检查是否启动模式
    launch_mode = getattr(args, 'launch', False)

    # 默认使用最新会话
    target_file, _ = all_sessions[index] if index is not None else all_sessions[0]

    # 读取会话信息
    try:
        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 提取标题
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else target_file.stem

        # 提取会话 ID
        id_match = re.search(r'session_id:\s*(\S+)', content)
        session_id = id_match.group(1) if id_match else target_file.stem

    except IOError:
        title = target_file.stem
        session_id = target_file.stem
        content = ""

    # 生成压缩的恢复提示词
    resume_prompt = generate_resume_prompt(content) if content else ""

    # 启动模式：直接启动 Claude 会话
    if launch_mode:
        import subprocess
        import tempfile
        import os

        # 构建恢复提示
        recovery_message = f"""# 会话恢复

{title}

{resume_prompt}

---

请基于以上上下文继续工作。"""

        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            temp_script = f.name
            f.write(f'''#!/bin/bash
echo "{recovery_message.replace('"', '\\"').replace('\n', '\\n')}" | claude
''')
        os.chmod(temp_script, 0o755)

        print(f"\033[1m{title}\033[0m")
        print(f"\033[90m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
        print(f"\033[90m正在启动新的 Claude 会话...\033[0m")
        print(f"\033[90m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
        print(f"\033[90m提示: 按 Ctrl+C 退出当前进程，新 Claude 会话将在后台继续运行\033[0m")
        print()

        try:
            # 使用 os.execvp 替换当前进程
            # 这样 claude 会接管当前终端
            os.execvp('claude', ['claude', '-c', recovery_message])
        except OSError as e:
            # 如果 execvp 失败，尝试使用 subprocess
            try:
                subprocess.Popen(
                    ['claude', '-c', recovery_message],
                    start_new_session=True
                )
                print(f"\033[92m✓ Claude 会话已在后台启动\033[0m")
            except Exception as e2:
                print(f"\033[91m启动 Claude 失败: {e2}\033[0m")
                print(f"\n\033[90m提示: 你可以手动复制以下内容到 Claude:\033[0m")
                print(f"\033[93m{recovery_message}\033[0m")
        finally:
            try:
                os.unlink(temp_script)
            except:
                pass
        return

    # 标准模式：显示恢复信息
    print(f"\n\033[1m{title}\033[0m")
    print()
    print(f"\033[90m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print(f"\033[90m复制以下内容到 Claude 即可恢复上下文：\033[0m")
    print(f"\033[90m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print()
    print(f"\033[93m{resume_prompt}\033[0m")
    print()
    print(f"\033[90m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print()
    print(f"\033[90m会话 ID: {session_id}\033[0m")
    print(f"\033[90m文件: {target_file}\033[0m")
    print()
    print(f"\033[90m提示: 使用 'tk r {index + 1 if index is not None else 1} -l' 可自动启动 Claude 会话\033[0m")


# =============================================================================
# 初始化
# =============================================================================
def initialize():
    """初始化 TermKeeper"""
    TERMKEEPER_BASE.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"GLM API: {GLM_BASE_URL}")
    print(f"GLM 模型: {GLM_MODEL}")
    print(f"Ollama (备选): {OLLAMA_BASE_URL}")

    if llm.is_available():
        print("✓ LLM 服务可用")
    else:
        print("⚠ LLM 服务均不可用，将使用简化模式")


# =============================================================================
# 主入口
# =============================================================================
def main():
    setup_signal_handlers()

    parser = argparse.ArgumentParser(
        prog="tk",
        description="TermKeeper - Claude Code 日志管理工具"
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # list 命令
    subparsers.add_parser('list', aliases=['l', 's'], help='列出所有会话（按时间排序）')

    # sync 命令
    subparsers.add_parser('sync', help='手动同步所有会话')

    # recover 命令
    recover_parser = subparsers.add_parser('recover', aliases=['r'], help='恢复会话')
    recover_parser.add_argument('index', nargs='?', help='会话序号（不指定则恢复最新）')
    recover_parser.add_argument('-l', '--launch', action='store_true',
                            help='自动启动新的 Claude 会话并恢复上下文')

    args = parser.parse_args()

    if not TERMKEEPER_BASE.exists():
        initialize()

    if not args.command:
        args.command = 'list'

    try:
        if args.command in ['list', 'l', 's']:
            cmd_list(args)
        elif args.command == 'sync':
            cmd_sync(args)
        elif args.command in ['recover', 'r']:
            cmd_recover(args)
    except KeyboardInterrupt:
        print("\n\033[90m操作已取消\033[0m")
        sys.exit(130)


if __name__ == '__main__':
    main()
