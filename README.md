# Card Wash — AI 角色卡版权清洗工具

读取 SillyTavern 角色卡（PNG / JSON），自动检测版权风险，通过 LLM 智能改写去除版权内容，导出干净的角色卡。

## 功能

- **上传解析** — 支持 PNG（含 tEXt 嵌入数据）和 JSON 格式角色卡
- **版权风险扫描** — 内置 150+ 条版权关键词规则，覆盖动漫、游戏、影视等 IP，逐字段评分 0-5
- **LLM 智能改写** — 支持 OpenAI / Claude / 任何 OpenAI 兼容 API（Ollama 等），三档改写强度
- **逐字段对比** — 原文 vs 改写对比视图，支持手动编辑、逐条采纳/拒绝
- **导出** — 导出为 PNG（保留原图）或 JSON

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动
python -m uvicorn main:app --reload --port 8000
```

然后打开浏览器访问 **http://localhost:8000**

## 使用流程

### 单张处理
1. **上传** — 拖拽或选择角色卡文件（.png / .json）
2. **分析** — 查看每个字段的版权风险评分和匹配的关键词
3. **改写** — 配置 LLM（API Key、模型、改写强度），选择要改写的字段，点击改写
4. **导出** — 逐条审核改写结果，确认后导出 PNG 或 JSON

### 批量处理（Web UI）
1. 点击「批量处理」模式
2. 拖放或选择多个角色卡文件
3. 配置 LLM 参数，点击「一键批量改写」
4. 查看每个文件的处理结果（风险评分变化）
5. 导出全部为 ZIP（JSON 或 PNG 格式）

### 批量处理（命令行）
```bash
# 使用 OpenAI 中度改写整个目录
python3 batch.py ./cards/ -o ./washed/ \
    --provider openai --api-key sk-xxx --model gpt-4o-mini

# 使用 Ollama 本地模型
python3 batch.py ./cards/ -o ./washed/ \
    --provider openai_compatible --api-key none \
    --base-url http://localhost:11434/v1 --model llama3

# 仅改写指定字段，重度改写
python3 batch.py ./cards/ -o ./washed/ \
    --provider anthropic --api-key sk-ant-xxx \
    --model claude-sonnet-4-20250514 --strength heavy \
    --fields name,description,scenario,first_mes

# 查看所有参数
python3 batch.py --help
```

CLI 批量处理特性：
- 自动跳过无风险的卡和已处理的文件
- 带颜色的进度显示
- 处理完成后生成 `_batch_report.json` 汇总报告
- 可配置文件间延迟（`--delay`）防止 API 限流

## 改写强度

| 强度 | 说明 |
|------|------|
| **轻度** | 仅替换显式的角色名和直接引用，最小改动 |
| **中度** | 替换名称、地点和世界观引用，保留性格和风格 |
| **重度** | 完全转化为原创角色，仅保留核心性格原型 |

## 支持的 LLM

| 提供商 | 配置 |
|--------|------|
| OpenAI | 填入 API Key，选择模型（gpt-4o-mini 等） |
| Anthropic | 填入 API Key，选择模型（claude-sonnet-4-20250514 等） |
| OpenAI 兼容 | 填入 Base URL（如 `http://localhost:11434/v1`），API Key 可填任意值 |

## 项目结构

```
card-wash/
├── main.py           # FastAPI 服务入口（含单张 + 批量 API）
├── batch.py          # CLI 批量处理脚本
├── card_io.py        # PNG/JSON 角色卡读写（tEXt chunk 解析）
├── models.py         # Pydantic 数据模型（v1/v2 兼容）
├── analyzer.py       # 版权风险检测引擎（150+ 规则）
├── rewriter.py       # LLM 改写引擎
├── requirements.txt  # Python 依赖
└── static/           # 前端（单张 + 批量模式）
    ├── index.html
    ├── style.css
    └── app.js
```

## 技术栈

- **后端**: Python + FastAPI
- **角色卡解析**: 手动 PNG tEXt chunk 解析（无外部依赖），支持 v1/v2 spec
- **LLM**: OpenAI SDK + Anthropic SDK
- **前端**: 原生 HTML/CSS/JS，暗色工业风 UI
