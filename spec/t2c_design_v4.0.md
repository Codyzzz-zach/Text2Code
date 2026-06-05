# Text2Code 设计说明书 v4.0

> **Status**: 当前权威 spec（supersedes v3.0 / v3.0-flash / v3.1-flash / v3.2-flash / v3.3）
> **Date**: 2026-06-05
> **作者意图**: 收口。v3.x 把产品做成了"文本+知识库+图引擎"三合一，方向错了。v4.0 只做一件事。

---

## 0. 产品目标（v4.0 唯一收敛点）

### 0.1 一句话

> **T2C 是一台编译器。输入是小说文本，输出是 `.t2c.py` 代码包。代码包是产品，剩下的一切都是为了产生这份代码。**

### 0.2 产品的唯一交付物

```text
examples/knowledge/<book>/<chapter>/
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
| `.t2c.py` 文件 | 主产品 | **唯一产品** |
| `ObjectStore` | 一等公民 | 可选运行时（用户愿意跑就存在 DB） |
| `Graph` | 一等公民 | 可选派生（用户愿意跑就生成） |
| `GraphAPI` / Query API | 一等公民 | **不做**（外部 codegraph 工具替代） |
| `Coverage Report` | 一等公民 | 输出到 `coverage.py`，但**不维护运行时 coverage 状态** |
| `LLM Extractor` | 核心组件 | 核心组件（但只产出 candidate，不产出 code） |
| CLI | 没有 | **必需**（`t2c compile` 是唯一入口） |
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

任何不在 `.t2c.py` 文件里出现的东西，都不是产品的契约。

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
3. **编译器不维护运行时状态**——编译完，磁盘上的 `.t2c.py` 就是产品的全部契约

### 1.4 LLM 的唯一职责

> **输入 segment 文本，输出 candidate JSON。**

LLM 不写 `.t2c.py`，不算 hash，不生成 Symbol，不建 Graph，不写 Coverage，不维护 ObjectStore。

LLM 的输出是"原材料"，T2C 编译器把"原材料"加工成"code"。

---

## 2. 编译器契约（v4.0 唯一规格）

### 2.1 CLI 是产品的入口

```bash
$ t2c compile raw.txt --output examples/knowledge/mybook/ch01/ \
                     --profile chinese_classical \
                     --llm  # 不传则跳过 LLM，只生成 text.py + 空 coverage
```

**CLI 跑完，磁盘上有 `.t2c.py` 文件包，T2C 编译器的工作就结束。**

### 2.2 输入

- `raw.txt` 路径（UTF-8 文本）
- `--profile`（可选，默认 auto-detect）
- `--output` 目录
- `--llm` 开关（不传则只生成 text.py）
- `--cache-mode`（`off`/`read_write`/`read_only`）

### 2.3 输出

- 目录结构如 §0.2
- 每个文件是**真实 Python**（可被 `python -c "import ..."` 加载）
- 每个对象有**真实 Python symbol**
- 每个 reference 是**真实 Python import**（不是字符串）

### 2.4 验收标准

```text
t2c compile raw.txt --output dir/ --llm
  → 退出码 0
  → dir/text.py 存在，包含所有 Segment 的 symbol
  → dir/entities.py 存在，import 自 .text
  → dir/claims.py 存在，import 自 .text, .entities
  → dir/coverage.py 存在
  → 全部 .t2c.py 文件可被 Pyright 解析（外部验证）
  → 全部 Symbol 可被 tree-sitter 索引（外部验证）
  → 全部 reference 可被 mypy 解析（外部验证）
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
磁盘上的 .t2c.py 文件包
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
examples/knowledge/<book>/<chapter>/
  __init__.py         # 暴露所有顶层 symbol
  text.py             # Document + Block + Segment
  entities.py         # Entity
  events.py           # Event
  claims.py           # Claim
  residuals.py        # Residual + IgnoreSegment
  derived.py          # Relation (程序派生)
  coverage.py         # CoverageReport (程序派生)
```

### 4.2 Symbol 与 Reference（不变）

- Symbol 命名：见 v3.3 §3.3
- 跨文件 import：`from .text import seg_0009`
- Reference 是真实 Python 引用，不是字符串

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

### 5.2 自动探测

```bash
$ t2c detect-profile raw.txt
→ chinese_classical
```

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
$ t2c compile <raw.txt> --output <dir> [--profile <name>] [--llm]
```

### 8.2 辅助命令

```bash
$ t2c detect-profile <raw.txt>     # 自动探测
$ t2c profiles                     # 列出已注册 profile
$ t2c test --profile <name>        # 跑测试矩阵
$ t2c --version                    # 显示 T2C 版本
$ t2c --help
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
t2c compile <raw.txt>            exit 0
Pyright parse examples/knowledge 0 error
mypy parse examples/knowledge    0 error
tree-sitter parse examples/knowledge  0 error
```

**外部 codegraph 工具通过，是 v4.0 最高质量门禁。**

### 9.3 v4.0 删掉的测试

- ❌ ObjectStore CRUD 测试（v4.0 不维护运行时 store）
- ❌ GraphBuilder 投影测试（v4.0 不维护内部 graph）
- ❌ GraphAPI 查询测试（v4.0 不暴露 Query API）
- ❌ Coverage Report 状态变更测试（v4.0 不监控运行时 coverage）

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
| LLM 直接写 `.t2c.py` | 永远禁止 |
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
  
  spec/
    t2c_design_v4.0.md       # 唯一权威 spec
    history/                 # 历史 spec 快照
  
  t2c/
    __init__.py              # __version__ = "4.0.0"
    cli.py                   # t2c CLI 入口（v4.0 强制）
    
    ontology.py              # Pydantic models
    schema.py                # schema validator
    
    corpus.py                # 接受 profile
    segmenter.py             # 接受 profile
    
    parser.py                # 解析 .t2c.py
    validator.py             # 12 道门禁（编译期内部）
    codegen.py               # 多文件生成（核心组件）
    
    extractor.py             # LLM candidate（核心组件）
    compact_candidate.py     # compact → verbose
    residual_stage.py        # Residual 单独阶段
    
    llm_cache.py             # LLM cache
    
    pipeline.py              # 11 phases 编排（编译期内部）
    
    genre_profiles/          # v4.0 保留
      __init__.py
      base.py
      chinese_classical.py
      modern_chinese.py
      english_novel.py
      default.py
      detector.py
      registry.py
  
  examples/
    corpus/                  # 原文
    knowledge/               # 编译产物（产品本体）
    queries/                 # 历史 demo（保留为参考）
  
  tests/
    conftest.py
    test_*.py
  
  scripts/
    test_matrix.py
    quality_check.py
```

**注意 v4.0 删掉的目录/文件**：

- ❌ `t2c/object_store.py`（v4.0 移除产品）
- ❌ `t2c/graph_builder.py`（v4.0 移除产品）
- ❌ `t2c/graph_api.py`（v4.0 移除产品）
- ❌ `t2c/coverage.py`（v4.0 移除产品；coverage 信息写进 coverage.py 文件，由 validator 静态检查）
- ❌ `t2c/residual_stage.py`（可保留或合并进 pipeline，依实现决定）

> **等等——我在这里需要重新澄清**：coverage.py 是产品输出的一部分（用户 git 仓库里能看到），但 `t2c/coverage.py` 模块（生成 coverage.py 的工具）必须保留。这两者不冲突。

---

## 12. 迁移路径（v4.0）

### 12.1 兼容性原则

**v4.0 兼容 v3.3 末态的代码生成结果。**

旧的 `examples/knowledge/hongloumeng_ch01.knowledge.t2c.py` 仍然可被 v4.0 parser 解析。`t2c compile` 的输出在两种情况下完全等价：
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
| 5 | 加 genre_profiles/detector.py | 0 行为变化 |
| 6 | 整理 spec/history/ | 文档层 |
| 7 | **v4.0 spec 收口**（本文件） | 设计层 |
| 8 | **删除** `object_store.py` / `graph_builder.py` / `graph_api.py` 从产品 | 移除运行时组件，但保留可选 helper 文件 |
| 9 | `t2c test full` 0 collection error | 验证 |
| 10 | Pyright / mypy / tree-sitter 跑通 examples/knowledge/ | 外部验证（v4.0 最高门禁） |

### 12.3 v4.0 验收

```text
□ 363+ existing tests pass
□ t2c compile raw.txt 退出 0，产出 .t2c.py 文件包
□ t2c detect-profile 三个样本各返回正确 profile
□ Pyright / mypy / tree-sitter 全部解析通过
□ ObjectStore / Graph / GraphAPI 不在产品路径
□ README 明确说"产品是 .t2c.py，外部工具是消费者"
□ Spec Alignment Score >= 90
```

---

## 13. v4.0 一句话

> **T2C 是一台把小说编译成 .t2c.py 代码包的编译器。代码包是唯一产品，外部 codegraph 工具是唯一消费者。ObjectStore / Graph / Query / Runtime 一律不做。**

---

## 附录 A：v3.x → v4.0 关键决策对照

| 议题 | v3.0 | v3.3 | **v4.0** |
|------|------|------|----------|
| 唯一产品 | "三层产品（Evidence/Code/Graph）" | "Knowledge Code Repository" | **.t2c.py 文件包** |
| ObjectStore | 一等公民 | 一等公民 | **删** |
| Internal Graph | 一等公民 | 一等公民 | **删** |
| Query API | 一等公民 | 一等公民 | **删（外部 codegraph 替代）** |
| 运行时状态 | 维护 | 维护 | **不维护（每次 compile 重算）** |
| CLI | 没有 | 没有 | **`t2c` 强制** |
| Genre 范围 | 任意 | 红楼梦 | **3 profile + auto-detect** |
| `.t2c.py` 形态 | top-level call | symbol assignment | symbol assignment（不变） |
| 哲学偏移 | Code/Graph 并列 | CodeGraph-first | **"Code is the product"** |
| Truth Hierarchy | 5 层 | 5 层 | **3 层（去掉 L3/L4）** |

## 附录 B：v4.0 验收清单（Action Items）

**产品本体**：

- [ ] `t2c/genre_profiles/` 目录 + 3 内置 profile + detector
- [ ] `t2c/cli.py` + `t2c compile` / `t2c detect-profile` / `t2c profiles` / `t2c test` 子命令
- [ ] `pyproject.toml` 注册 `t2c` script
- [ ] `examples/knowledge/<book>/<chapter>/` 多文件布局
- [ ] events.py / coverage.py 独立成文件

**产品外部（不归 T2C 管）**：

- [ ] Pyright 解析 examples/knowledge/ → 0 error
- [ ] mypy 解析 examples/knowledge/ → 0 error
- [ ] tree-sitter 解析 examples/knowledge/ → 0 error

**产品内部清理**：

- [ ] `t2c/object_store.py` 标记为 deprecated（v4.0 不再是产品）
- [ ] `t2c/graph_builder.py` 标记为 deprecated
- [ ] `t2c/graph_api.py` 标记为 deprecated
- [ ] README 明确"产品 = .t2c.py，外部工具 = 消费者"

**文档**：

- [ ] `spec/t2c_design_v4.0.md` review 通过（本文件）
- [ ] v3.x spec 移入 `spec/history/`
- [ ] 旧 README 改为指向 v4.0 spec

**测试**：

- [ ] `pytest tests/` 363+ tests pass
- [ ] `t2c compile rawtxt/红楼梦.txt` 跑通
- [ ] `t2c test full` 0 collection error

## 附录 C：参考资料

- v3.0 spec: `spec/history/t2c_design_v3.0.md`
- v3.1-flash: `spec/history/t2c_design_v3.1-flash.md`
- v3.2-flash: `spec/history/t2c_design_v3.2-flash.md`
- v3.3: `spec/history/t2c_design_v3.3.md`
- v3.3 末态实现: `t2c/` 目录
- 测试基线: 363 tests passed, 4 skipped
