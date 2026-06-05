# Text2Code (T2C)

**将自然语言文本转化为可执行的知识代码。**

Text2Code 是一个认知引擎，它将原始文本（小说、新闻、法律条文等）通过多阶段流水线处理，提取实体、事件、声明和关系，最终编译为结构化的 `.t2c.py` 知识代码文件——这些文件是可导入、可查询、可验证的 Python 模块。

## 架构概览

```
raw.txt → Segment → Extract(LLM) → Validate → Compact → CodeGen → .t2c.py
```

| 阶段 | 模块 | 说明 |
|------|------|------|
| Ingest | `corpus.py` | 文本摄入、分块 |
| Segment | `segmenter.py` | 语义分段 |
| Extract | `extractor.py` | LLM 驱动的实体/事件/声明提取 |
| Validate | `validator.py` + `schema.py` | 结构校验与修复 |
| Compact | `compact_candidate.py` | 去重与压缩 |
| CodeGen | `codegen.py` | 生成知识代码 |
| Compile | `compile_target.py` | 多文件编译输出 |

核心支撑：`ontology.py`（类型系统）、`llm_config.py`（LLM 配置）、`llm_cache.py`（缓存）、`object_store.py`（对象存储）、`graph_builder.py` / `graph_api.py`（知识图谱）

## 快速开始

### 安装

```bash
git clone https://github.com/Codyzzz-zach/Text2Code.git
cd Text2Code
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 配置 LLM

复制环境变量模板并填入你的 API Key：

```bash
cp .env.example .env
# 编辑 .env，设置 T2C_LLM_API_KEY
```

支持多种 LLM 提供商（MiniMax、Anthropic、OpenAI 兼容端点），详见 `.env.example`。

### 运行示例

```bash
# 无需 LLM 的端到端 demo（使用硬编码实体）
python examples/run_case_001.py

# 使用 LLM 提取红楼梦第一章
python scripts/extract_ch01_v4.py
```

## 项目结构

```
Text2Code/
├── t2c/                    # 核心引擎
│   ├── pipeline.py         # 流水线编排
│   ├── extractor.py        # LLM 提取器
│   ├── codegen.py          # 知识代码生成
│   ├── compile_target.py   # 多文件编译
│   ├── llm_config.py       # LLM 配置（多提供商）
│   ├── llm_cache.py        # LLM 响应缓存
│   ├── validator.py        # 结构校验与修复
│   ├── ontology.py         # 类型系统
│   └── ...
├── tests/                  # 测试套件
├── scripts/                # 提取脚本与工具
├── examples/               # 示例语料与运行脚本
│   ├── corpus/             # 原始文本样本
│   └── knowledge/          # 输出目录（.t2c.py 由脚本生成）
├── data/                   # 大型数据文件
│   ├── rawtxt/             # 原始长文本
│   └── generated/          # LLM 生成的大文件
├── spec/                   # 设计文档
│   ├── t2c_design_v4.0.md  # 当前版本设计
│   └── archive/            # 历史版本
├── .env.example            # 环境变量模板
└── pyproject.toml
```

## 测试

```bash
pytest                          # 运行全部测试
pytest tests/test_parser.py     # 运行单个模块测试
```

## 设计文档

- [v4.0 设计文档](spec/t2c_design_v4.0.md) — 当前版本
- [v3.3 设计文档](spec/t2c_design_v3.3.md) — 上一版本
- [历史版本](spec/archive/) — v3.0 ~ v3.2

## License

MIT License — 详见 [LICENSE](LICENSE)。
