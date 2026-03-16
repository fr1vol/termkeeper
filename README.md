# TermKeeper (tk)

Claude Code 日志管理工具 —— GLM 智能摘要，纯 Markdown 归档。

## 特性

- **GLM 智能摘要**: 使用智谱 AI 自动分析对话核心意图
- **纯 Markdown 格式**: 干净的文档格式，易于阅读和搜索
- **按序号恢复**: 快速定位和恢复历史会话
- **智能压缩**: 基于 Anthropic 最佳实践的结构化摘要，节省 Token
- **智能缓存**: 基于文件修改时间的增量更新
- **零依赖**: 仅使用 Python 标准库

## 安装

```bash
# 克隆仓库
git clone <repository-url>
cd termkeeper

# 复制配置文件模板
cp config.json.example config.json

# 编辑配置文件，填入你的 API Key
nano config.json  # 或使用你喜欢的编辑器

# 赋予执行权限
chmod +x tk.py

# 可选：创建符号链接到 PATH
sudo ln -s $(pwd)/tk.py /usr/local/bin/tk
```

## 配置

编辑 `config.json` 文件：

```json
{
  "glm": {
    "api_key": "your-api-key-here",
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
```

**配置说明：**

| 配置项 | 说明 |
|--------|------|
| `glm.api_key` | 智谱 AI 的 API 密钥（必填） |
| `glm.base_url` | GLM API 端点地址 |
| `glm.model` | 使用的 GLM 模型 |
| `ollama.base_url` | 本地 Ollama 服务地址（备选） |
| `ollama.model` | Ollama 使用的模型 |
| `display.list_threshold_hours` | 列表显示的时间阈值（小时） |

**获取 GLM API Key：**
1. 访问 [智谱开放平台](https://open.bigmodel.cn/)
2. 注册/登录账号
3. 在个人中心 → API Keys 创建新密钥
4. 使用 **Coding 套餐** 端点获得更优惠的价格

**注意：** `config.json` 包含敏感信息，已加入 `.gitignore`，不会被提交到 Git 仓库。

## 使用方法

### `tk list` (或 `tk` / `tk l`)

列出所有会话（按时间排序，最新的在前）：

```
$ tk list
GLM API: https://open.bigmodel.cn/api/coding/paas/v4
GLM 模型: glm-4-flash
✓ LLM 服务可用

所有会话 (25):

[  1] 03-17 02:12 (刚刚)    优化小说爬虫仓库代码与监控
[  2] 03-17 02:06 (1分钟前) TermKeeper 项目状态检查与后续优化
[  3] 03-17 02:06 (2分钟前) 重启并修复小说爬虫程序
...
```

**输出字段：**
- `[1]` - 序号（可用于恢复）
- `03-17 02:12` - 最后更新时间
- `(刚刚)` - 相对时间
- `优化小说爬虫...` - 会话标题

### `tk sync`

手动同步所有会话（从 Claude 会话文件重新生成摘要）：

```bash
$ tk sync
正在同步会话...
✓ 已更新 1 个会话

总计: 23 个会话
```

**用途：**
- 强制重新读取所有 Claude 会话文件
- 更新会话摘要（当 LLM 提示词改进后）
- 检查新增或修改的会话

### `tk recover` (或 `tk r`)

恢复会话，使用 LLM 压缩生成恢复提示词：

```bash
# 恢复最新会话
$ tk recover

[novel-scraper] 优化小说爬虫仓库代码与监控
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
复制以下内容到 Claude 即可恢复上下文：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

已完成的工作：优化 Docker 配置，禁用 GSSAPI 认证
当前进度：Docker 配置已完成，正在完善文档
关键发现：单容器单小说架构更稳定
下一步行动：完善文档和监控功能

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
会话 ID: 4d4e2ac8-02a8-48a2-b573-dcda7983df11

# 恢复指定序号的会话
$ tk recover 5

# 自动启动新的 Claude 会话并恢复上下文（无需手动复制粘贴）
$ tk r 5 -l
# 或
$ tk recover 5 --launch
```

**恢复结构（基于 Anthropic 最佳实践）：**

- 已完成的工作 - 完成的关键任务和结果
- 当前进度 - 整体进度状态
- 关键发现 - 重要信息和学到的经验
- 下一步行动 - 接下来要做什么

目标长度：200-300 字

## 文件格式

会话文件使用 **纯 Markdown** 格式：

```markdown
# [novel-scraper] 优化小说爬虫仓库代码与监控

**项目描述：** 核心内容：优化小说爬虫项目，要求单个Docker爬一本小说...

---
content_hash: e097edcfe626
date: 2026-03-17
session_id: 4d4e2ac8-02a8-48a2-b573-dcda7983df11
last_updated: 2026-03-17 02:12
---

## 对话记录

**使用的子代理：**
- `agent-a3de129`

### User
优化当前仓库代码和使用方法...

### Assistant
我来帮你优化这个小说爬虫项目...
```

**目录结构：**

```
~/.termkeeper/sessions/
├── 2026-03-17_优化小说爬虫仓库代码与监控.md
├── 2026-03-17_TermKeeper项目状态检查与后续优化.md
├── 2026-03-15_小说爬虫容器重启与进度更新.md
└── ...
```

**文件命名：** `YYYY-MM-DD_标题.md`

## 工作原理

### LLM 服务优先级

1. **GLM API** (智谱 AI) - 优先使用
   - 端点: `https://open.bigmodel.cn/api/coding/paas/v4`
   - 模型: `glm-4-flash`
   - Coding 套餐享受更优惠价格

2. **Ollama** (本地) - 备选
   - 端点: `http://localhost:11434`
   - 当 GLM 不可用时自动回退

### 内容提取

- **自动过滤**: 只保留 `type='text'` 的对话内容
- **移除噪音**: 过滤 thinking、tool_use 等内部数据
- **忠实记录**: 保留完整的用户与助手对话

### 缓存机制

基于 `content_hash` 的增量缓存：
- 内容未变时直接使用缓存的摘要
- 仅当内容变化时调用 GLM 重新生成

### 项目名处理

自动清理 Claude Code 生成的项目名前缀：
- `-home-rubick-project-name` → `project-name`
- `-home-rubick` → `default`

### 恢复压缩

使用 GLM 智能压缩对话，生成恢复提示词（基于 Anthropic 最佳实践）：
- **已完成的工作** - 完成的关键任务和结果
- **当前进度** - 整体进度状态
- **关键发现** - 重要信息和学到的经验
- **下一步行动** - 接下来要做什么

压缩后的提示词可直接复制到新的 Claude 对话中恢复上下文，大幅节省 Token。

## 快捷命令

```bash
tk              # 默认显示列表
tk list         # 显示所有会话
tk l            # 同上
tk sync         # 手动同步所有会话
tk recover      # 恢复最新会话
tk r            # 同上
tk r 5          # 恢复第 5 个会话
tk r 5 -l       # 自动启动 Claude 并恢复第 5 个会话（无需复制粘贴）
```

## 故障处理

| 问题 | 解决方案 |
|------|----------|
| GLM API 不可用 | 自动尝试 Ollama |
| API Key 无效 | 检查密钥格式，确保使用 Coding 端点 |
| JSONL 损坏 | 自动跳过损坏的行 |
| 对话内容为空 | 可能是工具调用类会话，无文本内容 |

## 技术栈

- **Python 3.8+**: 仅使用标准库
- **依赖**: `pathlib`, `json`, `re`, `urllib.request`, `signal`
- **无第三方依赖**: 极简、可移植

## 项目结构

```
termkeeper/
├── tk.py                    # 主程序
├── config.json.example      # 配置文件模板
├── config.json              # 实际配置文件（不提交到 Git）
├── README.md                # 项目文档
└── .gitignore               # Git 忽略文件规则
```

**数据存储位置：**
- 会话归档: `~/.termkeeper/sessions/*.md`
- Claude 源文件: `~/.claude/projects/*/session.jsonl`

## 开发

```bash
# 克隆仓库
git clone <repository-url>
cd termkeeper

# 创建配置文件
cp config.json.example config.json
# 编辑 config.json 填入你的 API Key

# 运行测试
python3 tk.py list

# 提交变更
git add .
git commit -m "描述你的变更"
```

## GLM API 参考

- [智谱 AI 开放平台](https://open.bigmodel.cn/)
- [快速开始文档](https://docs.bigmodel.cn/cn/guide/start/quick-start)
- [Coding 套餐说明](https://open.bigmodel.cn/pricing)
