# Text2Code 认知引擎设计说明书 v3.2-flash

## 0. 定位

v3.2-flash 是对 v3.1-flash 的减重版本。

v3.1 引入了 `Segment / Residual / Coverage`，解决了“Text 如何近乎无损写成 Code”的关键问题，但也带来一个风险：

> 如果 Segment、Residual、Coverage 都要求人工或 LLM 显式书写，系统会变成标注地狱。

v3.2 的核心修正是重新分配责任：

1. **Segment 是必要底座，但应自动生成。**
2. **Residual 是必要机制，但只记录高价值异常。**
3. **Coverage 是必要账本，但应由 Validator 自动推导。**

一句话：

> 保留近乎无损的机制，砍掉不必要的显式标注。

---

## 1. 不变的核心哲学

### 1.1 Raw Text 是最终证据源

Raw Text 仍然是 100% 最终证据源。

Code 可以作为日常认知源，但当出现冲突、不确定、覆盖不足、残差信息或用户要求原文时，必须回 Raw Text。

### 1.2 Code 是 90% 日常认知源

Canonical Code 承担大部分日常任务：

- 搜索；
- 理解；
- 管理；
- 推理；
- diff；
- AI 自查；
- 证据引用。

但 Code 不是原文替代品。

### 1.3 Graph 是有损导航源

Graph 只从 Code 派生，只负责加速定位。

Graph 不作为最终证据，不反向污染 Code，不直接生成新知识。

### 1.4 Code 的价值来自 AST 边界

选择 code 形态不是为了执行，而是为了让知识进入 AST 可规范的边界中。

自然语言语法弹性高，边界模糊；code 的 call、keyword argument、list、dict、class-like object 边界可以被 AST 稳定切分，更适合 AI 解释、管理、diff 和自查。

### 1.5 Text2Code 允许有损，但不允许静默有损

系统不承诺自然语言到 code 完全无损。

系统承诺：

- 原文无损保存；
- 结构化对象必须有 evidence；
- 无法安全结构化的重要信息进入 Residual；
- Coverage Report 必须能告诉我们哪些文本已覆盖、部分覆盖、未覆盖或被忽略。

---

## 2. v3.2 的关键减重

### 2.1 Segment 自动生成，不手写

Segment 是原文地图，必须存在。

但 Segment 不应该主要由人或 LLM 手写。它应该由 `Segmenter` 自动生成：

- 段落切分；
- 句子切分；
- 条款切分；
- 对白切分；
- 表格行切分；
- PDF/HTML 结构切分。

Segmenter 的产物可以保存为派生文件：

```text
case_001.segments.t2c.py
```

主知识文件只写语义对象和少量 residual：

```text
case_001.knowledge.t2c.py
```

### 2.2 Residual 只记录高价值异常

Residual 不是“所有未抽取信息的垃圾桶”。

只在以下情况显式记录：

- 信息重要；
- 当前 ontology 无法安全表达；
- 可能影响答案；
- 可能触发 raw fallback；
- LLM 容易把它误解为事实；
- 它涉及语气、暗示、反讽、动机、心理、复杂上下文。

低价值、无关紧要、不会影响推理的问题，不需要写 residual。

### 2.3 Coverage 不手写，由 Validator 推导

Coverage 不再是 `.t2c.py` 里的必写对象。

Validator 根据 Segment 引用情况自动生成 Coverage Report：

```text
有 semantic object，无 residual -> covered
有 semantic object，有 residual -> partial
无 semantic object，有 residual -> raw_only
显式 ignore -> ignored
无 semantic object，无 residual、未 ignored -> uncovered
```

`uncovered` 是错误或警告，取决于项目策略。

只有忽略噪声时需要显式写：

```python
IgnoreSegment(
    segment_id="seg.case_001.0012",
    reason="page number"
)
```

### 2.4 `.t2c.py` 不再混装所有东西

v3.2 建议分文件：

```text
knowledge/
  case_001.document.t2c.py   # doc/block 元信息，可自动生成
  case_001.segments.t2c.py   # segment 原文地图，自动生成
  case_001.knowledge.t2c.py  # entity/event/claim/relation/residual/ignore
```

这样 Segment 不会淹没语义知识。

---

## 3. v3.2-flash 最小架构

### 3.1 数据流

```text
Raw Text
  -> Corpus Manager
  -> Document / Block
  -> Segmenter
  -> Generated Segment Code
  -> Human/LLM Semantic Draft
  -> Generated Knowledge Code
  -> Parser
  -> Validator
  -> Coverage Report
  -> Object Store
  -> Derived Graph
  -> Evidence-backed Query
```

### 3.2 模块

只实现九个模块：

1. Corpus Manager：保存原文、分块、offset、hash。
2. Segmenter：自动生成 segment。
3. Candidate JSON Schema：定义语义对象输入格式。
4. Code Generator：确定性生成 `.t2c.py`。
5. T2C Parser：解析 `.t2c.py` AST。
6. Validator：检查语法、schema、引用、证据、claim safety，并生成 coverage report。
7. Object Store：保存通过验证的 code object。
8. Graph Builder：从已验证对象生成有损索引。
9. Query API：查询 graph/code/evidence/residual/coverage。

暂不实现：

- Agent Sandbox；
- WorldVersion；
- 通用 Rule Engine；
- 复杂 Graph 推理；
- Web UI；
- 插件系统。

---

## 4. Program / LLM 责任边界

### 4.1 总原则

Text2Code 的核心不是让 LLM 接管知识系统，而是让 LLM 只在它必要的地方做语义编译。

责任划分原则：

```text
Deterministic / Verifiable / Replayable -> Program
Semantic / Ambiguous / Language Understanding -> LLM
```

换句话说：

- 程序负责边界、格式、hash、offset、AST、schema、引用、验证、派生和重建。
- LLM 负责从自然语言 segment 中提出候选语义对象。
- LLM 的输出永远是 candidate，不是事实。
- Candidate 必须经过程序验证，才能进入 Canonical Code。

### 4.2 必须由程序完成的部分

以下步骤不应该交给 LLM：

| 阶段 | 程序职责 | 原因 |
| --- | --- | --- |
| Corpus ingest | 保存 raw text、doc id、content hash | 原文证据不能由 LLM 处理后再保存 |
| Block generation | 分块、offset、block hash | 需要稳定、可重放 |
| Segment generation | 规则分句、段落、条款、对话切分 | Segment 是证据地图，不能依赖 LLM 的不稳定边界 |
| Evidence slicing | 根据 segment_id/start/end 回放原文 | 必须字节/字符级准确 |
| Hash validation | doc/block/segment/evidence hash 校验 | 必须确定性 |
| JSON -> Code | Candidate JSON 确定性生成 `.t2c.py` | 防止 LLM 自由写代码 |
| AST parsing | 解析 `.t2c.py` | 需要严格语法边界 |
| Schema validation | 字段、类型、enum、required 检查 | 机器可判定 |
| Reference validation | id 是否存在、引用是否悬空 | 机器可判定 |
| Claim safety validation | 非 asserted claim 不能投影成 fact | 系统安全规则 |
| Coverage Report | 根据 segment 引用自动推导覆盖状态 | 避免手写 coverage 膨胀 |
| Graph Builder | 从 validated code 派生 graph | Graph 必须可重建 |
| Query API | 固定查询接口 | MVP 阶段减少 Agent 不确定性 |

程序做这些事情，是因为它们要满足：

- 可重复；
- 可测试；
- 可 diff；
- 可审计；
- 可失败并给出明确错误。

### 4.3 可以引入 LLM 的部分

LLM 只进入语义理解相关步骤。

MVP 中允许 LLM 做：

| 阶段 | LLM 职责 | 输出 |
| --- | --- | --- |
| Segment semantic compile | 从 segment text 中识别 entity/event/claim/relation | Candidate JSON |
| Residual detection | 判断哪些重要信息不能安全结构化 | Candidate residual JSON |
| Ignore suggestion | 建议哪些 segment 是页码、页眉、格式噪声 | Candidate ignore JSON |
| Compile repair | 根据 validator 错误修复 Candidate JSON | Candidate JSON |

LLM 不直接输出：

- Raw Text；
- Segment；
- Coverage；
- Graph；
- `.t2c.py`；
- 最终事实；
- 直接写入 Object Store 的对象。

### 4.4 为什么 LLM 不能直接写 `.t2c.py`

`.t2c.py` 的价值来自 AST 边界和规范稳定性。

如果让 LLM 直接写 `.t2c.py`，会引入几个问题：

- 可能生成非白名单语法；
- 可能偷偷添加自由 Python 表达式；
- 字段顺序和格式不稳定；
- ID 命名不稳定；
- 修复 diff 更困难；
- 很难保证 JSON -> Code -> Object 的 roundtrip。

所以 LLM 只写 Candidate JSON，Code Generator 再确定性生成 `.t2c.py`。

### 4.5 为什么 Segment 不交给 LLM

Segment 是证据坐标系，不是语义判断结果。

如果 Segment 由 LLM 自由决定，会导致：

- 同一文本多次切分不一致；
- offset 难以稳定；
- hash 难以重放；
- evidence 引用漂移；
- 后续 diff 和 coverage 不稳定。

因此 Segmenter 应优先使用程序规则。LLM 可以在未来辅助复杂版面或多模态边界识别，但最终 segment 必须由程序落定 offset 和 hash。

### 4.6 为什么 Coverage 不交给 LLM

Coverage 是损耗账本，必须由系统根据实际引用关系推导。

如果让 LLM 直接判断 coverage，容易出现：

- 自信地声称 covered，但其实没有 object ref；
- 忽略 residual；
- 把 coverage 变成另一层自然语言判断；
- 难以审计覆盖率。

所以 v3.2 中 Coverage 不是手写对象，而是 Validator 产物。

### 4.7 LLM 输出的信任等级

LLM 输出的所有内容都是候选。

信任链路：

```text
LLM Candidate JSON
  -> Schema validation
  -> Reference validation
  -> Evidence validation
  -> Claim safety validation
  -> Code generation
  -> AST validation
  -> Object Store
```

没有通过验证的 LLM 输出，不能进入 Canonical Code。

### 4.8 Text 最终写成什么 Code

Text2Code 的目标代码形态是：

> 受限 Python 子集中的 ontology instance constructor calls。

也就是说，文本不会被写成：

- 任意 Python 业务代码；
- 每篇文档动态生成的 class definition；
- LLM 自由生成的脚本；
- Graph triples；
- Markdown / YAML / JSON 摘要。

文本会被写成一组受 ontology 约束的对象实例声明：

```python
from t2c.ontology import Entity, Event, Claim, Relation, Residual, EvidenceRef

Entity(
    id="ent.case_001.alice",
    kind="person",
    name="Alice",
    evidence_refs=[
        EvidenceRef(
            segment_id="seg.case_001.0001",
            start=0,
            end=5,
            quote_hash="sha256:alice_span_hash"
        )
    ]
)

Claim(
    id="claim.case_001.arrival",
    subject="ent.case_001.alice",
    predicate="arrived_at",
    object="station",
    modality="asserted",
    polarity="positive",
    confidence=0.9,
    evidence_refs=[
        EvidenceRef(
            segment_id="seg.case_001.0001",
            start=10,
            end=42,
            quote_hash="sha256:event_span_hash"
        )
    ]
)
```

这里的 `Entity(...)`、`Claim(...)` 看起来像 class constructor，但系统不会直接执行它们。Parser 只读取 AST，并把这些 constructor call 转换成内部 canonical object。

因此，Code 分成两层：

1. **Ontology Code**：由开发者维护的真实 Python / Pydantic class，定义允许哪些对象、字段、类型、验证规则。
2. **Knowledge Code**：由 Text2Code 生成的 `.t2c.py`，只包含 ontology instance declarations。

这种形式最适合当前设计哲学：

- `Call` 节点给每个知识对象提供稳定边界；
- `keyword argument` 给每个字段提供稳定边界；
- nested constructor 如 `EvidenceRef(...)` 给证据对象提供稳定边界；
- AST 可以禁止控制流、赋值、函数定义和任意表达式；
- AI 可以像读代码一样管理对象，又不会获得自由编程权限；
- Code 可以稳定 roundtrip 到 canonical JSON，再派生 Graph。

简化后的语法可以理解为：

```text
file        ::= import ontology_types object_call*
object_call ::= TypeName "(" keyword_arg* ")"
value       ::= string | number | bool | None | list[value] | dict | object_call
TypeName    ::= Document | Block | Segment | Entity | Event | Claim | Relation | Residual | EvidenceRef | IgnoreSegment
```

这就是 v3.2-flash 中“Code”的准确含义：

> Code 是 AST-governed typed object declarations，不是可执行程序。

---

## 5. 核心文件类型

### 5.1 Document Code

自动或半自动生成。

包含：

- `Document(...)`
- `Block(...)`

示例：

```python
from t2c.ontology import Document, Block

Document(
    id="doc.case_001",
    title="Case 001",
    source_type="plain_text",
    content_hash="sha256:doc_hash"
)

Block(
    id="block.case_001.0001",
    doc_id="doc.case_001",
    index=1,
    start=0,
    end=512,
    text_hash="sha256:block_hash"
)
```

### 5.2 Segment Code

自动生成。

包含：

- `Segment(...)`

示例：

```python
from t2c.ontology import Segment

Segment(
    id="seg.case_001.0001",
    block_id="block.case_001.0001",
    index=1,
    start=0,
    end=42,
    text_hash="sha256:segment_hash",
    kind="sentence"
)
```

原则：

- Segment 文件可以很长；
- Segment 文件可以机器维护；
- 人类通常不直接编辑；
- Segment 必须带 offset 和 hash；
- Segment 是 Evidence 的优先锚点。

### 5.3 Knowledge Code

人类或 LLM 生成 Candidate JSON 后由 Code Generator 生成。

包含：

- `Entity(...)`
- `Event(...)`
- `Claim(...)`
- `Relation(...)`
- `Residual(...)`
- `IgnoreSegment(...)`
- `EvidenceRef(...)`

示例：

```python
from t2c.ontology import Entity, Claim, Residual, IgnoreSegment, EvidenceRef

Entity(
    id="ent.case_001.alice",
    kind="person",
    name="Alice",
    evidence_refs=[
        EvidenceRef(
            segment_id="seg.case_001.0001",
            start=0,
            end=5,
            quote_hash="sha256:alice_span_hash"
        )
    ]
)

Claim(
    id="claim.case_001.arrival",
    subject="ent.case_001.alice",
    predicate="arrived_at",
    object="station",
    modality="asserted",
    polarity="positive",
    confidence=0.9,
    evidence_refs=[
        EvidenceRef(
            segment_id="seg.case_001.0001",
            start=10,
            end=42,
            quote_hash="sha256:event_span_hash"
        )
    ]
)

Residual(
    id="res.case_001.0007",
    segment_id="seg.case_001.0007",
    category="implication",
    reason="The sentence implies possible motive, but does not explicitly assert it.",
    importance="high",
    evidence_refs=[
        EvidenceRef(
            segment_id="seg.case_001.0007",
            start=0,
            end=48,
            quote_hash="sha256:residual_span_hash"
        )
    ]
)

IgnoreSegment(
    segment_id="seg.case_001.0012",
    reason="page number"
)
```

---

## 6. 最小核心模型

v3.2-flash 的核心对象：

- Document；
- Block；
- Segment；
- EvidenceRef；
- Entity；
- Event；
- Claim；
- Relation；
- Residual；
- IgnoreSegment；
- CoverageReport。

注意：

- `CoverageReport` 不是手写 DSL object；
- 它是 Validator 的派生结果；
- 它可以被保存为 JSON、SQLite 表或 graph 属性。

### 6.1 Segment

Segment 是自动生成的原文地图。

必需字段：

- `id`
- `block_id`
- `index`
- `start`
- `end`
- `text_hash`
- `kind`

Segment 不表达语义，只表达稳定文本边界。

### 6.2 EvidenceRef

EvidenceRef 优先指向 Segment。

必需字段：

- `segment_id`
- `start`
- `end`
- `quote_hash`

`start/end` 建议使用 segment-local offset。

### 6.3 Claim

Claim 仍然是语义中心。

必需字段：

- `id`
- `subject`
- `predicate`
- `object`
- `modality`
- `polarity`
- `evidence_refs`

允许的 `modality`：

- `asserted`
- `claimed_by_source`
- `reported`
- `uncertain`
- `hypothetical`
- `conditional`
- `inferred`

原则：

- Claim 不能无证据；
- `claimed_by_source` 不能升级为事实；
- `reported` 不能升级为事实；
- `uncertain` 不能升级为事实；
- `hypothetical` 不能升级为事实；
- `negative` 不能投影为 positive fact。

### 6.4 Residual

Residual 是高价值未结构化信息。

必需字段：

- `id`
- `segment_id`
- `category`
- `reason`
- `importance`
- `evidence_refs`

允许的 `importance`：

- `medium`
- `high`

v3.2-flash 不鼓励 `low residual`。低价值残差不写，避免噪声膨胀。

### 6.5 IgnoreSegment

IgnoreSegment 用于显式忽略无知识价值的 segment。

字段：

- `segment_id`
- `reason`

允许原因：

- `page_number`
- `header_footer`
- `format_noise`
- `duplicate`
- `empty`
- `other`

### 6.6 CoverageReport

CoverageReport 由 Validator 自动生成。

字段：

- `segment_id`
- `status`
- `object_refs`
- `residual_refs`
- `ignored_reason`
- `requires_raw_fallback`
- `notes`

允许的 `status`：

- `covered`
- `partial`
- `raw_only`
- `ignored`
- `uncovered`

推导规则：

```text
有 semantic object，无 residual -> covered
有 semantic object，有 residual -> partial
无 semantic object，有 residual -> raw_only
显式 ignore -> ignored
无 semantic object，无 residual、未 ignored -> uncovered
```

Raw fallback 规则：

- `partial` -> true；
- `raw_only` -> true；
- high residual -> true；
- non-asserted claim 相关 segment -> true；
- negative / unknown polarity 相关 segment -> true。

---

## 7. `.t2c.py` 最小规范

### 7.1 Ontology Constructors

Document code 允许：

```python
from t2c.ontology import Document, Block
```

Segment code 允许：

```python
from t2c.ontology import Segment
```

Knowledge code 允许：

```python
from t2c.ontology import Entity, Event, Claim, Relation, Residual, IgnoreSegment, EvidenceRef
```

### 7.2 允许语法

只允许：

- 固定 import；
- 顶层 DSL 函数调用；
- keyword arguments；
- string / number / boolean / None；
- list；
- dict；
- 注释。

### 7.3 禁止语法

禁止：

- 任意 import；
- 变量赋值；
- 函数定义；
- 类定义；
- if / for / while；
- try / with；
- lambda；
- comprehension；
- f-string；
- attribute access；
- method call；
- exec / eval；
- IO / network / system call。

---

## 8. Text2Code 编译过程

### 8.1 编译不是摘要

禁止：

```text
Raw Text -> Summary Text -> Code
```

允许：

```text
Raw Text -> Segment -> Candidate JSON -> Code
```

原因：

- Summary 会提前丢失细节；
- 丢失发生在不可审计的自然语言层；
- 后续 code 只能规范摘要残留信息。

### 8.2 三段式编译

#### 8.2.1 原文地图阶段

由系统自动完成：

- 生成 Document；
- 生成 Block；
- 生成 Segment；
- 计算 hash；
- 记录 offset。

#### 8.2.2 语义编译阶段

由人类或 LLM 生成 Candidate JSON，再由 Code Generator 生成 Knowledge Code。

输出：

- Entity；
- Event；
- Claim；
- Relation；
- Residual；
- IgnoreSegment。

#### 8.2.3 验证与覆盖阶段

由 Validator 完成：

- AST 检查；
- Schema 检查；
- 引用检查；
- Evidence 检查；
- Claim Safety 检查；
- Coverage Report 生成。

---

## 9. Validator 最小集

### 9.1 AST Grammar Validator

检查 `.t2c.py` 只包含允许语法。

### 9.2 Schema Validator

检查每个 DSL call 的字段是否符合 schema。

### 9.3 Reference Validator

检查：

- block 指向已存在 doc；
- segment 指向已存在 block；
- evidence 指向已存在 segment；
- event participants 指向已存在 entity；
- relation source / target 存在；
- claim subject 存在，除非是 literal；
- claim source 存在，除非为空；
- residual segment 存在；
- ignore segment 存在。

### 9.4 Evidence Validator

检查：

- segment span 在 block 范围内；
- evidence span 在 segment 范围内；
- `end > start`；
- segment text hash 匹配；
- evidence quote hash 匹配；
- 每个 entity/event/claim/relation/residual 都有 evidence。

### 9.5 Claim Safety Validator

检查：

- `claimed_by_source` 不能投影成 asserted fact；
- `reported` 不能投影成 asserted fact；
- `uncertain` 不能进入默认事实边；
- `hypothetical` 不能进入默认事实边；
- `conditional` 不能无条件进入默认事实边；
- `negative` claim 不能生成 positive relation；
- `inferred` claim 必须有 derived source。

### 9.6 Coverage Report Generator

Validator 自动生成 coverage report。

推导：

```text
segment has semantic object refs and no residual -> covered
segment has semantic object refs and residual -> partial
segment has no semantic object refs and residual -> raw_only
segment ignored -> ignored
segment has no semantic object refs, no residual, not ignored -> uncovered
```

项目策略：

- `uncovered` 默认是 warning；
- 如果项目要求高覆盖，可升级为 error；
- high residual 必须标记 `requires_raw_fallback=true`；
- partial/raw_only 必须标记 `requires_raw_fallback=true`。

---

## 10. Graph Builder 最小规则

### 10.1 Graph 定位

Graph 是索引，不是真理源。

Graph 可删除、可重建、可缓存。

Graph 中每个节点和边都必须回指 code object 或 generated segment。

### 10.2 Graph Node

为以下对象建节点：

- Document；
- Block；
- Segment；
- Entity；
- Event；
- Claim；
- Residual。

不为 CoverageReport 单独建节点。CoverageReport 作为 Segment 索引属性。

### 10.3 Graph Edge

允许生成：

- `Document -> Block`
- `Block -> Segment`
- `Entity -> Segment`
- `Event -> Segment`
- `Claim -> Segment`
- `Residual -> Segment`
- `Entity -> Event`，来自 asserted positive `participates_in` relation
- `Claim -> Subject`
- `Claim -> Object`
- `Claim -> Source`
- `Segment -> Residual`

### 10.4 禁止投影

禁止：

- 将 `claimed_by_source` claim 投影成事实边；
- 将 `reported` claim 投影成事实边；
- 将 `uncertain` claim 投影成事实边；
- 将 `hypothetical` claim 投影成事实边；
- 将 `conditional` claim 投影成无条件事实边；
- 将 `negative` claim 投影成 positive relation；
- 从 Graph 新建知识对象；
- 用 Graph 覆盖 CoverageReport。

### 10.5 Graph API

第一版只提供：

```python
find_entities(name=None, kind=None)
find_events(participant=None, kind=None)
find_claims(subject=None, predicate=None, object=None, modality=None)
find_segments(status=None, has_residual=None)
find_residuals(category=None, importance=None)
get_object(object_id)
get_evidence(object_id)
get_segment_coverage(segment_id)
trace_neighbors(object_id, depth=1)
```

---

## 11. Query 最小闭环

### 11.1 查询流程

```text
User Question
  -> fixed Query API
  -> candidate object ids
  -> code object
  -> coverage report
  -> residual check
  -> evidence span
  -> answer / report
```

### 11.2 Raw fallback 触发条件

必须回 Raw Text 或至少返回原文片段的情况：

- coverage 是 `partial`；
- coverage 是 `raw_only`；
- coverage 是 `uncovered`；
- segment 存在 high residual；
- claim modality 不是 `asserted`；
- claim polarity 不是 `positive`；
- 对象存在冲突状态；
- 用户要求精确原文解释。

### 11.3 输出要求

回答至少包含：

- 结论；
- 相关 code object ID；
- coverage status；
- residual 提示；
- evidence 原文片段；
- modality；
- polarity；
- 如果存在不确定性，明确标出。

---

## 12. LLM 在 v3.2-flash 中的位置

### 12.1 Phase A：无 LLM

先做：

- Raw Text；
- 自动 Segment；
- 手写 Knowledge Code；
- Validator；
- Coverage Report；
- Query API。

目标：

- 验证 code 是否可读；
- 验证 coverage report 是否有用；
- 验证 residual 是否能承接重要未结构化信息；
- 验证 raw fallback 是否明确。

### 12.2 Phase B：LLM 只写 Candidate JSON

LLM 输入：

- Segment text；
- Segment id；
- schema；
- 已有对象 ID；
- 编译规则。

LLM 输出：

- Entity；
- Event；
- Claim；
- Relation；
- Residual；
- IgnoreSegment。

LLM 不输出：

- Segment；
- Coverage；
- Graph；
- `.t2c.py`；
- Summary。

### 12.3 Phase C：确定性 JSON -> Code

Code Generator 将 Candidate JSON 转成 Knowledge Code。

这一步不使用 LLM。

---

## 13. 最小验收实验

### 13.1 测试集

准备：

- 10 篇短文本；
- 每篇 500-2000 字；
- 覆盖人物、事件、声称、否认、时间、地点、关系、语气、暗示、心理描写；
- 每篇设计 5 个问题。

### 13.2 对比指标

只看七个指标：

1. 答案正确率。
2. 证据引用准确率。
3. unsupported claim 数量。
4. “声称/否认/不确定”误升级为事实的次数。
5. Coverage Report 可解释性。
6. High importance residual 召回率。
7. 单篇文本结构化维护成本。

### 13.3 成功标准

最低证明：

- 证据引用准确率明显高于 baseline；
- unsupported claim 明显少于 baseline；
- 模态误升级明显少于 baseline；
- Coverage Report 能稳定指出 partial/raw_only/uncovered；
- high residual 能触发 raw fallback；
- 维护成本没有高到不可接受。

---

## 14. 推荐仓库结构

```text
text2code/
  spec/
    t2c_design_v3.0.md
    t2c_design_v3.0-flash.md
    t2c_design_v3.1-flash.md
    t2c_design_v3.2-flash.md

  t2c/
    __init__.py
    dsl.py
    parser.py
    schema.py
    validator.py
    coverage.py
    corpus.py
    segmenter.py
    graph_builder.py
    graph_api.py

  examples/
    corpus/
      case_001.txt
    knowledge/
      case_001.document.t2c.py
      case_001.segments.t2c.py
      case_001.knowledge.t2c.py
    queries/
      case_001_query.py

  tests/
    test_parser.py
    test_validator.py
    test_evidence.py
    test_coverage.py
    test_graph_builder.py
```

---

## 15. 实现优先级

### P0：原文地图

- Corpus Manager；
- Document；
- Block；
- Segmenter；
- Segment；
- EvidenceRef；
- hash / offset 校验。

### P1：Code 规范与验证

- `.t2c.py` parser；
- AST grammar validator；
- schema validator；
- reference validator；
- evidence validator。

### P2：语义对象

- Entity；
- Event；
- Claim；
- Relation；
- claim safety validator。

### P3：近乎无损机制

- Residual；
- IgnoreSegment；
- Coverage Report Generator；
- raw fallback 标记；
- segment coverage report。

### P4：Graph 与查询

- Graph Builder；
- Graph API；
- evidence-backed query；
- baseline 对比实验。

### P5：接入 LLM

- Candidate JSON schema；
- Segment -> Candidate JSON prompt；
- JSON -> `.t2c.py` generator；
- compile error repair。

---

## 16. v3.2-flash 总结

v3.2-flash 保留了 v3.1 的核心洞察：

- Segment 是必要的；
- Residual 是必要的；
- Coverage 是必要的。

但它把实现方式减重为：

```text
Segment = 自动生成的原文索引
Residual = 高价值异常记录
Coverage = Validator 自动生成的报告
```

最终结构：

```text
Raw Text = 100% final evidence source
Generated Segment Code = text map
Knowledge Code = 90% daily cognition source
Coverage Report = loss ledger
Derived Graph = lossy navigation source
```

这版比 v3.1 更适合作为 MVP：它不牺牲你的设计哲学，但避免把 Text2Code 变成大规模手工标注系统。
