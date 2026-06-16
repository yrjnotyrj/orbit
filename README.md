# orbit

`orbit` 是一个面向代码仓库的轻量本地 coding agent。它直接跑在终端里，先看当前工作区，再用一组受约束的工具去读文件、改文件、跑命令。

它更像一个能在仓库里持续工作的命令行助手，不是纯聊天窗口。你可以拿它做代码排查、测试修复、仓库分析，或者让它在当前项目里执行一次性的工程任务。

## 适合做什么

- 在本地仓库里排查测试失败
- 读取当前代码结构并给出修改建议
- 基于现有文件做小步迭代，而不是脱离仓库空想
- 生成多个队友代理协作完成复杂任务
- 后台执行耗时命令，不阻塞主循环

## 核心功能

| 功能 | 说明 |
|------|------|
| **TodoWrite** | 轻量内存任务清单，支持 pending / in_progress / completed 状态 |
| **文件任务** | 持久化任务管理（.tasks/），支持依赖关系、状态流转、任务认领 |
| **后台执行** | `background_run` 在后台线程执行命令，完成后自动注入通知 |
| **技能加载** | 从 `skills/` 目录递归加载 SKILL.md 文件，支持动态注入系统提示 |
| **子代理** | `task` 工具派生子代理执行独立探索或编辑任务 |
| **队友代理** | 持久化队友线程，支持 work → idle → auto-claim 生命周期 |
| **对话压缩** | 每轮 microcompact + 超过阈值自动 auto-compact，生成摘要并保存完整记录 |
| **消息总线** | 基于 JSONL 文件的队友通信系统 |
| **关闭协议** | 支持 shutdown_request / shutdown_response 安全关闭队友 |
| **计划审批** | 支持 plan_approval_response 审批队友提出的计划 |

## 安装

需要 Python 3.9+。

```bash
# 克隆仓库
git clone <repo-url>
cd orbit

# 安装（开发模式）
pip install -e .

# 或者直接安装
pip install .
```

## 配置

在项目根目录或用户目录创建 `.env` 文件：

```env
ANTHROPIC_API_KEY=your-api-key
MODEL_ID=deepseek-v4-pro
# 可选：自定义 API 地址（代理等）
# ANTHROPIC_BASE_URL=https://your-proxy.com
```

## 使用

```bash
# 启动交互式 CLI
orbit

# 或作为模块运行
python -m orbit
```

### REPL 命令

| 命令 | 说明 |
|------|------|
| `/tasks` | 列出所有文件任务 |
| `/team` | 列出所有队友及其状态 |
| `/inbox` | 读取 lead 的收件箱 |
| `/compact` | 手动压缩对话历史 |
| `q` / `exit` | 退出 |

## 目录结构

```
orbit/
├── orbit/                  # 包目录
│   ├── __init__.py         # 公共 API 导出
│   ├── __main__.py         # python -m orbit 入口
│   ├── cli.py              # 主入口，初始化所有组件
│   ├── core.py             # agent_loop 主循环
│   ├── todo.py             # TodoManager 内存任务清单
│   ├── task_mgr.py         # TaskManager 文件持久化任务
│   ├── background.py       # BackgroundManager 后台命令执行
│   ├── skills.py           # SkillLoader 技能加载
│   ├── compress.py         # Compressor 对话压缩
│   ├── subagent.py         # run_subagent 子代理
│   ├── bus.py              # MessageBus 消息总线
│   ├── manager.py          # TeammateManager 队友生命周期
│   └── tools.py            # 工具定义与处理器
├── pyproject.toml
└── README.md
```

运行时产生的目录：

```
.team/                      # 队友配置与通信
├── config.json             # 团队配置
└── inbox/                  # 收件箱（JSONL 文件）
    ├── lead.jsonl
    ├── alice.jsonl
    └── ...

.tasks/                     # 持久化任务文件
├── task_1.json
└── task_2.json

.transcripts/               # 压缩时保存的完整对话记录
└── transcript_<timestamp>.jsonl
```

## API 概览

```python
from orbit import (
    TodoManager,          # 内存任务清单
    TaskManager,          # 文件持久化任务
    BackgroundManager,    # 后台命令执行
    SkillLoader,          # 技能加载
    Compressor,           # 对话压缩
    MessageBus,           # 消息总线
    TeammateManager,      # 队友管理
    agent_loop,           # 主循环
    run_subagent,         # 子代理
    build_system_prompt,  # 系统提示构建
)
```

## 许可证

MIT
