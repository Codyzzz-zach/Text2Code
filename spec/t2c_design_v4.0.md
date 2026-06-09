# Text2Code 设计说明书 v4.0

> **Status**: 当前权威 spec（supersedes v3.0 / v3.0-flash / v3.1-flash / v3.2-flash / v3.3）
> **Date**: 2026-06-05
> **作者意图**: 收口。v3.x 把产品做成了"文本+知识库+图引擎"三合一，方向错了。v4.0 只做一件事。

---

## 0. 产品目标（v4.0 唯一收敛点）

### 0.1 一句话

> **T2C 是一台编译器。输入是 `input_txt/` 里的小说文本，输出是 `output_code/<书名>/` 里的 Python Knowledge Code 包。代码包是产品，剩下的一切都是为了产生这份代码。**

### 0.2 产品的唯一交付物

```text
input_txt/<book>.txt
  ↓
output_code/<book>/
  text.py         # Document + Block + Segment
  entities.py     # Entity
  events.py       # Event
  claims.py       # Claim
  residuals.py    # Residual + IgnoreSegment
  derived.py      # Relation (程序派生)
  coverage.py     # CoverageReport (程序派生)
  __init__.py
```

**这就是产品本身。** 编译跑完，产物落到这个目录，T2C 的工作就结束了。

### 0.3 产品的最终消费者

不是用户，不是查询 API，不是 Graph 浏览器——

> **是外部 codegraph 工具。**

Pyright / mypy / tree-sitter / SCIP / Sourcegraph / CodeQL / 任何能读 Python AST 和符号引用的工具。

它们的用户（人、agent、其他工具）会再基于这些 code 做导航、查询、分析、refactor。

### 0.4 v4.0 显式不做的事（这些才是真正的边界）

v3.x 的 spec 一边写"产品目标 = code"，一边加 ObjectStore、Graph、Query API、Coverage Report 输出——**这是产品自相矛盾**。v4.0 把这些全部从"产品功能"降级为"可选运行时"：

| 项 | v3.x 定位 | v4.0 定位 |
|---|----------|----------|
| Python Knowledge Code 文件 | 主产品 | **唯一产品** |
| `ObjectStore` | 一等公民 | 可选运行时（用户愿意跑就存在 DB） |
| `Graph` | 一等公民 | 可选派生（用户愿意跑就生成） |
| `GraphAPI` / Query API | 一等公民 | **不做**（外部 codegraph 工具替代） |
| `Coverage Report` | 一等公民 | 输出到 `coverage.py`，但**不维护运行时 coverage 状态** |
| `LLM Extractor` | 核心组件 | 核心组件（但只产出 candidate，不产出 code） |
| CLI | 没有 | **必需**（`t2c compile-library` 是标准书库入口，`t2c compile` 是单文件入口） |
| Web UI | 没做 | **不做** |
| Agent Sandbox | 没做 | **不做** |
| WorldVersion | 没做 | **不做** |

### 0.5 v4.0 砍掉 v3.x 哪些东西（具体清单）

**从 spec 中彻底删除**：

- `ObjectStore` 作为产品组件的描述（保留为可选 persistence helper）
- `GraphBuilder` / `GraphAPI` / `query()` / `find_*()` 方法
- `Query API` 章节
- `Coverage Report` 的"自动监控"语义
- `Agent Sandbox`
- `WorldVersion`
- `State` / `Rule` / `Conflict` objects
- `Status` 字段
- `Event.modality`（v3.5 决议方案 A）
- 任何"运行时状态维护"的设计

**保留但简化**：

- `Validator` 仍然存在，但**只服务于"产生 code 之前的最后一道门"**——它不再驱动 ObjectStore、Graph、Query
- `coverage.py` 仍然生成，但只是一个静态文件，没有"持续监控"语义
- `pipeline.py` 仍然存在，但**只到"代码写入磁盘"就结束**

---

## 1. 核心哲学（v4.0 收敛版）

### 1.1 一条核心哲学

> **Code is the product. Code is the API. Code is the contract.**

任何不在生成的 `.py` Knowledge Code 文件里出现的东西，都不是产品的契约。

### 1.2 真理层级（v4.0 简化为三层）

v3.x 的 5 层 Truth Hierarchy 在 v4.0 简化为 3 层，因为 v4.0 不再有"运行时 / 派生层"：

| 层级 | 名称 | 是否有损 | 用途 |
|---|---|---|---|
| L0 | Raw Text | 无损 | 唯一最终证据（保留在仓库，外部工具读） |
| L1 | Knowledge Code | 有损解释 | **产品本体** |
| L2 | (外部 codegraph 工具的索引) | 由 L1 派生 | 不归 T2C 管 |

**v3.3 的 L3 Derived Graph / L4 Answer/Report 在 v4.0 中不存在。** 那些是外部 codegraph 工具的工作。

### 1.3 三条不可妥协的原则

1. **Raw Text 必须可回放**——每个 Code object 都能回到原文具体位置
2. **Code 必须是 codegraph-manageable**——`Symbol assignment` + `cross-file reference` 是形态硬约束
3. **编译器不维护运行时状态**——编译完，磁盘上的 Knowledge Code 包就是产品的全部契约

### 1.4 LLM 的唯一职责

> **输入 segment 文本，输出 candidate JSON。**

LLM 不写 `.py` 代码，不算 hash，不生成 Symbol，不建 Graph，不写 Coverage，不维护 ObjectStore。

LLM 的输出是"原材料"，T2C 编译器把"原材料"加工成"code"。

---

## 2. 编译器契约（v4.0 唯一规格）

### 2.1 CLI 是产品的入口

```bash
$ t2c compile-library --llm --cache-mode read_write

# 单文件低层入口仍保留：
$ t2c compile input_txt/mybook.txt --output output_code/mybook --llm
```

**CLI 跑完，磁盘上有 Knowledge Code 文件包，T2C 编译器的工作就结束。**

无 LLM 的低成本路径必须显式写成 `--text-only`。它只生成可回放 text map
预检包，不计入完整 Text2Code E2E。

### 2.2 输入

- `input_txt/` 路径（默认，内含 UTF-8 `.txt` 文本）
- `--input-dir`（可选覆盖默认输入目录）
- `--output-root`（可选覆盖默认输出根目录）
- `--profile`（可选，默认 auto-detect）
- `--llm` 开关（完整语义编译必需）
- `--text-only` 开关（只生成 text map 预检包，不做语义转写）
- `--cache-mode`（`off`/`read_write`/`read_only`）

### 2.3 输出

- 目录结构如 §0.2
- 每个文件是**真实 Python**（可被 `python -c "import ..."` 加载）
- 每个对象有**真实 Python symbol**
- 每个对象有稳定 ID。默认 reference 字段保存字符串 ID，保证 Pydantic/import 安全
- 跨文件 import 和行内注释用于让外部 codegraph 工具索引对象边界、包内关联和中文检索词
- `emit_symbol_refs=True` 只能作为实验模式，不能作为默认产品路径

### 2.4 验收标准

```text
t2c compile-library --llm --cache-mode read_write
  → 退出码 0
  → output_code/<book>/text.py 存在，包含所有 Segment 的 symbol
  → output_code/<book>/entities.py 存在，import 自 .text
  → output_code/<book>/claims.py 存在，必要时 import 自 .text / .entities
  → output_code/<book>/coverage.py 存在
  → 全部 .py 文件可 py_compile
  → package 可 import
  → 全部 Symbol 可被 tree-sitter 索引（外部验证）
  → Pyright / mypy 对生成包 0 critical error（外部验证）
```

**外部 codegraph 工具的可读性是 v4.0 的最高优先级。** Pyright / mypy / tree-sitter 跑过即合格。

---

## 3. Pipeline（v4.0 简化）

### 3.1 数据流

```text
Raw Text (.txt)
  ↓
[1] Ingest
  ↓
[2] Block Generation
  ↓
[3] Segmentation
  ↓
[4] Text Code Generation      ← 纯程序
  ↓
[5] LLM Compact Candidate    ← 可选
  ↓
[6] Candidate Expansion       ← 纯程序
  ↓
[7] Validation                ← 12 道门禁
  ↓
[8] Repair Loop               ← 最多 2 次
  ↓
[9] Semantic Code Generation  ← 纯程序
  ↓
[10] Derived Code Generation  ← 纯程序
  ↓
[11] Coverage Generation      ← 纯程序
  ↓
磁盘上的 Knowledge Code 文件包
  ↓
T2C 编译器结束
  ↓
[外部] Pyright / mypy / tree-sitter / SCIP / Sourcegraph
```

**Pipeline 跑到 [11] 完就 exit 0。** 没有 [12]。

### 3.2 与 v3.x 的关键差异

| 阶段 | v3.x | v4.0 |
|------|------|------|
| LLM 输出 | candidate JSON | candidate JSON（不变） |
| Code 生成 | program（不变） | program（不变） |
| 写磁盘 | 是 | 是（不变） |
| **维护 ObjectStore** | 是 | **否** |
| **生成内部 Graph** | 是 | **否** |
| **暴露 Query API** | 是 | **否** |
| **持续监控 Coverage** | 是 | **否（每次 compile 重算）** |

---

## 4. Knowledge Code 形态（v4.0 不变）

v3.3 的受限 Python 子集、Symbol 命名规则、跨文件引用，v4.0 全部继承。理由：这套形态经过 v3.3 验证可被 Pyright / tree-sitter 索引，是 v4.0 唯一目标的实现基础。

### 4.1 文件布局（v4.0 唯一产品）

```text
input_txt/<book>.txt
  ↓
output_code/<book>/
  __init__.py         # 暴露所有顶层 symbol
  text.py             # Document + Block + Segment
  entities.py         # Entity
  events.py           # Event
  claims.py           # Claim
  residuals.py        # Residual + IgnoreSegment
  derived.py          # Relation (程序派生)
  coverage.py         # CoverageReport (程序派生)
```

### 4.2 Symbol 与 Reference（当前默认）

- Symbol 命名：见 v3.3 §3.3
- 跨文件 import：`from .text import seg_0009`
- Reference 字段默认是字符串 ID，不是 Python 对象引用
- 这样做的原因：Pydantic 模型字段是 `str`，真实对象引用会破坏 import/validation 安全
- Codegraph 适配依靠四件事：assignment symbol、cross-file import、稳定 ID、行内注释/源码上下文

### 4.3 v4.0 修复 v3.x 的小毛病

- `events.py` 独立成文件（v3.3 混入 derived.py）
- `coverage.py` 独立成文件（v3.3 混入 derived.py）
- 文件名全部小写加下划线（符合 PEP 8）

---

## 5. Genre Profile（v4.0 保留）

Genre profile 解决"非红楼梦"输入的硬编码问题。这个目标在 v4.0 仍然有效——只要 T2C 仍然是"以小说为主的编译器"，profile 就必须存在。

### 5.1 内置 Profile

| Profile | 语言 | 章节样式 | 用途 |
|---------|------|---------|------|
| `chinese_classical` | zh-Hans | 第N回 | 红楼梦/三国/水浒 |
| `modern_chinese` | zh-Hans | 第N章 | 三体/活着 |
| `english_novel` | en | Chapter N | 哈利波特/魔戒 |
| `default` | auto | auto | fallback |

### 5.2 自动探测（后续项）

```bash
$ t2c detect-profile raw.txt
→ chinese_classical
```

当前实现尚未把 `detect-profile`、`profiles`、`t2c test` 落成产品命令。v4.0
当前已实现的产品入口是 `t2c compile-library` / `t2c compile` / `t2c --version`。

### 5.3 自注册

```python
@register_profile("my_genre")
class MyGenre(GenreProfile): ...
```

---

## 6. Ontology（v4.0 收口）

### 6.1 保留的对象

```text
Document / Block / Segment / EvidenceRef
Entity / Event / Claim / Relation
Residual / IgnoreSegment / CoverageReport
```

### 6.2 砍掉的对象

```text
State / Rule / Conflict / WorldVersion
```

### 6.3 字段精简

```python
class Document(BaseModel):
    id: str
    source_path: str
    raw_text_hash: str
    total_length: int
    block_count: int
    encoding: str = "utf-8"           # v4.0 新增（profile 注入）
    language: str = "zh-Hans"         # v4.0 新增（profile 注入）
    created_at: str

# ... 其它对象见 v3.3 §5
```

**v4.0 不再增加任何新字段。** 如果将来需要扩展，要么在 v5.0 单独 spec，要么通过 `@profile.entity_kinds` 这种配置而非 ontology 字段扩展。

### 6.4 ID 命名（v4.0 收口）

```text
Document:   doc_<safe_id>
Block:      blk_<index:04d>
Segment:    seg_<index:04d>           # 全文连续，跨 block
Entity:     ent_<name_normalized_or_zh_hash>
Event:      evt_<name_normalized_or_zh_hash>
Claim:      clm_<key>_zh_<hash> | clm_<normalized>
Relation:   rel_<subject>_<pred>_<obj>
Residual:   res_<seg_sym>
IgnoreSegment: ign_<seg_sym>
```

---

## 7. Validator（v4.0 简化）

### 7.1 12 道门禁（继承 v3.3）

v3.3 的 12 道门禁全部保留：

1. grammar
2. schema
3. id
4. reference
5. evidence
6. span
7. hash
8. raw_replay
9. claim_safety
10. coverage
11. no_silent_loss
12. rebuild

### 7.2 失败处理（v4.0 明确）

- 12 道门禁中**任何一道**失败 → 整个 compile 失败，exit code != 0
- 失败不重试 LLM（v3.4 决议保留）
- 失败不部分写入（v4.0 新约束）——要么全写，要么全不写

### 7.3 不再做什么

- ❌ 不在 Validator 内做"自动修复 graph"
- ❌ 不在 Validator 内做"自动 reject 部分对象"
- ❌ 不暴露 Validator 作为"运行时 API"——它只是编译期内部组件

---

## 8. CLI（v4.0 必需）

### 8.1 唯一入口

```bash
$ t2c compile-library --llm
$ t2c compile-library --text-only
$ t2c compile <raw.txt> --output <dir> [--profile <name>] --llm
$ t2c compile <raw.txt> --output <dir> --text-only
```

### 8.2 辅助命令

```bash
$ t2c --version                    # 已实现：显示 T2C 版本
$ t2c --help                       # 已实现：显示 CLI 帮助
```

以下命令是后续迭代项，不能被 helper.md 当成当前标准流程：

```bash
$ t2c detect-profile <raw.txt>     # 后续项：自动探测
$ t2c profiles                     # 后续项：列出已注册 profile
$ t2c test --profile <name>        # 后续项：封装测试矩阵
```

### 8.3 不做的命令

- ❌ `t2c query`（外部 codegraph 工具做）
- ❌ `t2c graph`（外部 codegraph 工具做）
- ❌ `t2c serve`（T2C 不是 server）
- ❌ `t2c watch`（T2C 不维护运行时状态）

### 8.4 pyproject 注册

```toml
[project.scripts]
t2c = "t2c.cli:main"
```

---

## 9. 测试（v4.0 收口）

### 9.1 测试矩阵（继承）

v3.x 的测试矩阵 9 个 profile 全部保留：

```text
smoke / validator / textmap / graph / extractor / core / regression / e2e / full / quality
```

### 9.2 v4.0 验收指标

```text
pytest tests/                    全 pass
t2c compile-library --llm        exit 0
py_compile output_code/<book>/   0 error
import output_code/<book>/       0 error
Pyright parse output_code/       0 critical error
mypy parse output_code/          0 critical error
tree-sitter parse output_code/   0 error
```

**外部 codegraph 工具通过，是 v4.0 最高质量门禁。**

### 9.3 不作为产品验收的测试

这些测试可以作为历史兼容或内部 helper 回归测试继续存在，但不能作为产品能力宣传：

- ObjectStore CRUD 测试（内部 staging/helper）
- GraphBuilder 投影测试（历史/实验 helper）
- GraphAPI 查询测试（历史/实验 helper）
- Coverage Report 状态变更测试（不能代表运行时监控能力）

---

## 10. 不做的事（v4.0 终极边界）

v3.x 的 spec 一边写"产品目标 = 文本编译成 code"，一边加 ObjectStore / Graph / Query API——**这是产品自相矛盾**。v4.0 显式声明下面这些是产品范围之外：

| 不做 | 原因 |
|------|------|
| ObjectStore | 外部 codegraph 工具替代 |
| Derived Graph | 外部 codegraph 工具替代 |
| GraphAPI / Query API | 外部 codegraph 工具替代 |
| Agent Sandbox | 不属于编译器 |
| Web UI | 不属于编译器 |
| WorldVersion | 不属于编译器 |
| 通用 Rule Engine | 不属于编译器 |
| 复杂 Graph 推理 | 不属于编译器 |
| 多用户协作 | 不属于编译器 |
| 完整 State object | 暂用 Claim 表达 |
| 持续运行时监控 | 每次 compile 重算即可 |
| LLM 直接写 `.py` Knowledge Code | 永远禁止 |
| LLM 生成 offset/hash | 永远禁止 |
| LLM 生成 Coverage | 永远禁止 |
| Summary → Code 路径 | 永远禁止（直接编译原文） |
| 非叙事文本适配 | 范围之外 |
| 让用户"管理对象" | 用户管的是 git 仓库里的 .py 文件 |
| 任何运行时"服务" | T2C 是编译器，不是 server |

---

## 11. 仓库结构（v4.0 收口）

```text
text2code/
  pyproject.toml             # 含 [project.scripts] t2c = "t2c.cli:main"
  README.md
  helper.md                  # agent 调用 CLI 的标准操作说明
  input_txt/                 # 用户放原始 .txt 书籍
  output_code/               # 编译产物；默认只追踪 .gitkeep
  
  spec/
    t2c_design_v4.0.md       # 唯一权威 spec
  
  t2c/
    __init__.py              # __version__ = "0.4.0"
    cli.py                   # t2c compile-library / compile 入口
    
    ontology.py              # Pydantic models
    schema.py                # schema validator
    
    corpus.py                # 接受 profile
    segmenter.py             # 接受 profile
    
    parser.py                # 历史 .t2c.py 兼容解析器
    validator.py             # 12 道门禁（编译期内部）
    codegen.py               # 多文件生成（核心组件）
    
    extractor.py             # LLM candidate（核心组件）
    compact_candidate.py     # compact → verbose
    residual_stage.py        # Residual 单独阶段
    
    llm_cache.py             # LLM cache
    
    pipeline.py              # 11 phases 编排（编译期内部）
    
  tests/
    conftest.py
    test_*.py
  
  scripts/
    test_matrix.py
    quality_check.py
```

**注意 v4.0 的产品边界**：

- `t2c/object_store.py` 可作为 CLI 内部 staging/helper 存在，但不是产品能力。
- `t2c/graph_builder.py` / `t2c/graph_api.py` 可作为历史兼容或实验工具存在，但不是标准产品路径。
- `t2c/coverage.py` 是生成 `output_code/<book>/coverage.py` 的内部工具；输出文件属于产品，运行时模块不属于产品 API。
- 任何旧脚本都不能绕过 `t2c compile-library` / `t2c compile` 生成产品输出。

### 11.1 默认目录的 git 规则

`input_txt/` 和 `output_code/` 是本地工作目录。仓库默认只追踪 `.gitkeep`，
不追踪用户原文书籍和生成产物，避免把大文本或昂贵生成结果误提交。

---

## 12. 迁移路径（v4.0）

### 12.1 兼容性原则

**v4.0 兼容 v3.3 末态的代码生成结果。**

旧的单文件 `.knowledge.t2c.py` 仍可作为历史格式由 parser 兼容读取，但仓库不再保留这类旧产物。`t2c compile` / `t2c compile-library` 的输出在两种情况下完全等价：
1. 相同输入 + 相同 profile + 相同 LLM
2. 旧的单文件 .knowledge.t2c.py 仍然可读

### 12.2 实施阶段

| Phase | 内容 | 行为变化 |
|------|------|---------|
| 0（已完成） | v3.3 末态 | — |
| 1 | 抽 `GenreProfile` + 3 个内置 profile | 0 行为变化 |
| 2 | corpus/segmenter/extractor 接受 profile | 0 行为变化（默认 chinese_classical） |
| 3 | codegen 拆出 events.py / coverage.py | 0 行为变化（多文件版） |
| 4 | 加 cli.py + `t2c` 入口 | 0 行为变化（新增能力） |
| 5 | 加 genre_profiles/detector.py | 后续项 |
| 6 | 整理 spec/history/ | 后续项 |
| 7 | **v4.0 spec 收口**（本文件） | 设计层 |
| 8 | **删除** `object_store.py` / `graph_builder.py` / `graph_api.py` 从产品 | 移除运行时组件，但保留可选 helper 文件 |
| 9 | `python scripts/test_matrix.py full` 0 collection error | 验证 |
| 10 | Pyright / mypy / tree-sitter 跑通 output_code/ | 外部验证（v4.0 最高门禁） |

### 12.3 v4.0 验收

```text
□ pytest tests/ 全 pass
□ t2c compile-library --llm 退出 0，产出 output_code/<book>/ Knowledge Code 包
□ t2c compile-library --text-only 退出 0，产出可回放 text map 预检包
□ Pyright / mypy / tree-sitter 全部解析通过
□ ObjectStore / Graph / GraphAPI 不被 helper.md 描述为产品路径
□ README 明确说"产品是 Python Knowledge Code，外部工具是消费者"
□ Spec Alignment Score >= 90
```

---

## 13. v4.0 一句话

> **T2C 是一台把 `input_txt/` 里的小说编译成 `output_code/<书名>/` Python Knowledge Code 包的编译器。代码包是唯一产品，外部 codegraph 工具是唯一消费者。ObjectStore / Graph / Query / Runtime 一律不是产品。**

---

## 附录 A：v3.x → v4.0 关键决策对照

| 议题 | v3.0 | v3.3 | **v4.0** |
|------|------|------|----------|
| 唯一产品 | "三层产品（Evidence/Code/Graph）" | "Knowledge Code Repository" | **output_code/<book>/ Python 包** |
| ObjectStore | 一等公民 | 一等公民 | **删** |
| Internal Graph | 一等公民 | 一等公民 | **删** |
| Query API | 一等公民 | 一等公民 | **删（外部 codegraph 替代）** |
| 运行时状态 | 维护 | 维护 | **不维护（每次 compile 重算）** |
| CLI | 没有 | 没有 | **`t2c` 强制** |
| Genre 范围 | 任意 | 红楼梦 | **3 profile + auto-detect** |
| Knowledge Code 形态 | top-level call | symbol assignment | symbol assignment + 字符串 ID 默认安全引用 |
| 哲学偏移 | Code/Graph 并列 | CodeGraph-first | **"Code is the product"** |
| Truth Hierarchy | 5 层 | 5 层 | **3 层（去掉 L3/L4）** |

## 附录 B：v4.0 验收清单（Action Items）

**产品本体**：

- [ ] `input_txt/` / `output_code/` 默认目录
- [ ] `t2c/cli.py` + `t2c compile-library` / `t2c compile` / `t2c --version`
- [ ] `pyproject.toml` 注册 `t2c` script
- [ ] `output_code/<book>/` 多文件布局
- [ ] events.py / coverage.py 独立成文件

**产品外部（不归 T2C 管）**：

- [ ] Pyright 解析 output_code/ → 0 critical error
- [ ] mypy 解析 output_code/ → 0 critical error
- [ ] tree-sitter 解析 output_code/ → 0 error

**产品内部清理**：

- [ ] `t2c/object_store.py` 只作为内部 staging/helper
- [ ] `t2c/graph_builder.py` / `t2c/graph_api.py` 不进入 helper 标准路径
- [ ] README 明确"产品 = Python Knowledge Code，外部工具 = 消费者"

**文档**：

- [ ] `spec/t2c_design_v4.0.md` review 通过（本文件）
- [ ] 旧 README 改为指向 v4.0 spec

**测试**：

- [ ] `pytest tests/` 全 pass
- [ ] `t2c compile-library --text-only` 跑通
- [ ] `t2c compile-library --llm --cache-mode read_write` 跑通真实 DeepSeek E2E

## 附录 C：参考资料

- v3.0 spec: `spec/history/t2c_design_v3.0.md`
- v3.1-flash: `spec/history/t2c_design_v3.1-flash.md`
- v3.2-flash: `spec/history/t2c_design_v3.2-flash.md`
- v3.3: `spec/history/t2c_design_v3.3.md`
- v3.3 末态实现: `t2c/` 目录
- 测试基线: 363 tests passed, 4 skipped
