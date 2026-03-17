# TermKeeper (tk)

Claude Code 项目管理工具 —— 解决移动项目目录后的失忆问题。

## 问题背景

当你把一个项目目录移动到新位置时，Claude Code 会认为这是一个新项目，导致"失忆"——所有之前的对话历史都找不到了。

这是因为 Claude 用路径作为项目标识：
- 旧路径：`/home/user/old/project` → slug: `-home-user-old-project`
- 新路径：`/home/user/new/project` → slug: `-home-user-new-project`

TermKeeper 解决这个问题。

## 特性

- **`tk .`** - 自动迁移：在新目录一键恢复记忆
- **智能匹配** - 自动检测可能的旧项目
- **会话归档** - 将 JSONL 转换为可读的 Markdown 格式
- **增量更新** - 基于 SHA256 hash，只处理变化的文件
- **零依赖** - 仅使用 Python 标准库

## 安装

```bash
# 克隆仓库
git clone <repository-url>
cd termkeeper

# 赋予执行权限
chmod +x tk.py

# 可选：创建符号链接到 PATH
sudo ln -s $(pwd)/tk.py /usr/local/bin/tk
```

## 使用方法

### `tk .` - 自动迁移

移动项目后，在新目录中直接运行：

```bash
cd /new/project/path
tk .
```

自动检测并迁移旧项目的记忆：

```
当前目录: /home/rubick/termkeeper
当前 slug: -home-rubick-termkeeper
未找到对应的 Claude 数据，尝试自动迁移...

找到 1 个可能匹配的项目:
  [1] -home-old-termkeeper (匹配度: 100)
      旧路径: /home/old/termkeeper

自动选择: -home-old-termkeeper
将迁移: -home-old-termkeeper → -home-rubick-termkeeper

✓ 记忆搬家完成
  旧 Claude: ~/.claude/projects/-home-old-termkeeper
  新 Claude: ~/.claude/projects/-home-rubick-termkeeper
```

### `tk migrate` - 交互式迁移

列出所有 Claude 项目，交互式选择：

```bash
tk migrate
```

输出示例：

```
正在扫描 Claude 项目...

Claude 项目列表:

[1] -home-rubick-termkeeper
    ✓ 当前
    路径: /home/rubick/termkeeper

[2] -home-old-project
    ✗ 不存在
    路径: /home/old/project

选择要迁移的项目序号: 2
```

### `tk migrate <old_path>` - 显式迁移

直接指定旧路径：

```bash
tk migrate /home/old/project
```

### `tk archive` - 归档会话

将 Claude 的 JSONL 会话文件转换为 Markdown：

```bash
tk archive
```

输出示例：

```
正在扫描会话...
找到 25 个会话
正在生成归档到: ./claude_archives
  [1/25] a1f0c813... 已更新
  [2/25] b2e1f924... 已更新
  [3/25] c3d2a835...

✓ 已归档 3 个会话
  跳过 22 个未变更的会话（基于 hash 检测）
  归档目录: ./claude_archives
```

## 归档格式

生成的 Markdown 文件包含完整的对话记录：

```markdown
# 📔 rubick会话

---
date: 2026-03-18
project: rubick
session_id: a1f0c813-6f49-40e4-bfbd-b24cb090cce7
last_updated: 2026-03-18 01:40
project_path: /home/rubick/termkeeper
source_hash: a3d5f9e2b1c4...  ← SHA256 hash，用于增量更新检测
---

## 对话记录

**使用的子代理：**
- `agent-a082a1e`

### User
请帮我优化这段代码...

### Assistant
我来帮你分析...
```

**文件命名：** `YYYY-MM-DD_项目名会话.md`

**存储位置：** `./claude_archives/`

## 工作原理

### Slug 转换

Claude Code 将路径转换为 slug 作为项目 ID：

```
/home/rubick/termkeeper  →  -home-rubick-termkeeper
```

规则：将 `/` 替换为 `-`，保留前导 `-`。

### 迁移原理

移动项目目录本质是重命名 Claude 的项目目录：

```bash
~/.claude/projects/-home-old-termkeeper/
  → ~/.claude/projects/-home-rubick-termkeeper/
```

### 自动匹配算法

`tk .` 使用多维度评分自动找到旧项目：

| 匹配条件 | 分数 |
|----------|------|
| 目录名完全匹配 | +100 |
| 目录名部分匹配 | +50 |
| 归档包含当前路径 | +80 |
| 归档包含当前 slug | +60 |
| 归档包含目录名 | +30 |

### 增量归档

基于 SHA256 hash 检测文件变更：

1. 计算源 JSONL 文件的 SHA256
2. 读取现有归档的 `source_hash`
3. hash 相同 → 跳过
4. hash 不同 → 更新归档

## 目录结构

```
termkeeper/
├── tk.py                    # 主程序
├── README.md                # 本文档
├── claude_archives/         # 归档目录（自动生成）
│   └── *.md                 # Markdown 会话文件

# Claude 数据目录
~/.claude/projects/
├── -home-rubick-termkeeper/  # 项目 slug
│   └── *.jsonl              # 会话文件
```

## 故障处理

| 问题 | 解决方案 |
|------|----------|
| 未找到匹配的旧项目 | 使用 `tk migrate <旧路径>` 显式指定 |
| 归档文件已存在 | 自动覆盖，基于 hash 检测变更 |
| 项目目录已存在 | 询问是否合并 |

## 技术栈

- **Python 3.8+**: 仅使用标准库
- **依赖**: `pathlib`, `json`, `re`, `shutil`, `hashlib`, `signal`
- **无第三方依赖**: 极简、可移植

## 开发

```bash
# 克隆仓库
git clone <repository-url>
cd termkeeper

# 运行
./tk.py .
./tk.py migrate
./tk.py archive

# 提交变更
git add .
git commit -m "描述你的变更"
```
