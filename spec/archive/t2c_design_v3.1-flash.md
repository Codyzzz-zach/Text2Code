# Text2Code 认知引擎设计说明书 v3.1-flash

## 0. 定位

v3.1-flash 是 v3.0-flash 的一次关键升级。

v3.0-flash 已经明确了三层哲学：

- Evidence 是证据源；
- Code 是规范化解释；
- Graph 是有损索引。

v3.1-flash 进一步解决最重的问题：

> Text 如何近乎无损地被写成 Code？

这里的“近乎无损”不是承诺自然语言可以被完全结构化。自然语言到 code 必然有损。v3.1 的目标是：

1. Raw Text 仍然是 100% 最终证据源。
2. Canonical Code 成为约 90% 日常认知源，承担大部分搜索、理解、管理和推理。
3. Graph 只作为有损导航源。
4. 信息损耗不能静默发生，必须被记录、定位、解释和回放。

一句话：

> Text2Code 不是摘要，而是带损耗账本的知识编译。

---

## 1. 核心哲学

### 1.1 Raw Text 是最终法庭

Raw Text 永远是最高证据源。

当出现以下情况时，系统必须回到 Raw Text：

- Code object 互相冲突；
- Code 覆盖不足；
- 关键 segment 只有 partial / raw_only coverage；
- 存在 high importance residual；
- Claim modality 是 uncertain / hypothetical / claimed_by_source / reported；
- 用户要求精确原文判断；
- 问题依赖语气、反讽、隐喻、心理描写、动机推断等细腻语义。

### 1.2 Code 是 90% 日常认知源

Code 不是原文替代品，但它应该承担大多数日常认知工作：

- 结构化搜索；
- 实体、事件、断言管理；
- 关系定位；
- 证据引用；
- 模态保留；
- 冲突暴露；
- 增量 diff；
- AI 自查。

设计目标不是让 Code 变成 100% 无损真理源，而是让 Code 成为高覆盖、高可验、高可维护的认知工作层。

### 1.3 Graph 只是导航源

Graph 是从 Code 派生的有损索引。

Graph 可以帮助定位：

- 相关 entity；
- 相关 event；
- 相关 claim；
- 相关 evidence；
- 相关 residual；
- 可能的路径。

Graph 不可以替代 Code 或 Raw Text 给出最终证据。

### 1.4 Code 的价值来自 AST 边界

选择 code 形态不是为了执行，而是为了获得比自然语言更稳定的信息边界。

自然语言有很高语法弹性，同一句话可以混合事实、转述、否定、条件、隐喻、暗示和省略。Code 的函数调用、参数、列表、字典、类式对象边界可以被 AST 明确切分。AI 面对 code object 时，不需要先猜测文本边界，而是可以直接解释字段、层级、引用和证据。

因此 `.t2c.py` 的第一身份是：

> AST-governed knowledge container。

### 1.5 不允许静默损耗

Text2Code 可以有损，但必须知道哪里有损。

任何原文 segment 都必须进入以下状态之一：

- `covered`：主要语义已被 Code 表达；
- `partial`：部分语义已表达，但仍有 residual；
- `raw_only`：暂时无法安全结构化，只能回原文；
- `ignored`：明确判定为无知识价值或噪声。

如果一段文本没有 coverage 状态，就说明编译过程不可审计。

---

## 2. v3.1-flash 相比 v3.0-flash 的变化

### 2.1 新增 Segment

Segment 是原文地图层。

它比 Block 更细，通常对应：

- 句子；
- 条款；
- 段内子句；
- 对白；
- 表格行；
- 标题；
- 脚注。

Segment 的目的不是表达语义，而是让 Code 拥有稳定的原文切片索引。

### 2.2 新增 Residual

Residual 是残差信息对象。

它表示：

> 这里有重要信息，但当前 ontology 不能安全表达，或者暂时不值得强行结构化。

Residual 防止系统只保存“抽取成功的信息”，从而静默丢掉语气、暗示、情绪、修辞和复杂上下文。

### 2.3 新增 Coverage

Coverage 是损耗账本。

它记录每个 Segment 的语义是否已被 code object 覆盖。

Coverage 让系统能回答：

- 哪些原文已经结构化？
- 哪些原文只部分结构化？
- 哪些原文必须回 Raw？
- 哪些信息被明确忽略？

### 2.4 Text2Code 过程升级为三层编译

v3.1-flash 的编译顺序：

```text
Raw Text
  -> Document / Block
  -> Segment 原文地图
  -> Entity / Event / Claim / Relation 语义对象
  -> Residual 残差信息
  -> Coverage 损耗账本
  -> Validator
  -> Derived Graph
```

---

## 3. 明确砍掉的东西

v3.1-flash 仍然保持轻量，不做完整系统。

暂不做：

- Agent Sandbox；
- WorldVersion；
- 通用 Rule Engine；
- 复杂领域 ontology；
- 复杂 Graph 推理；
- Web UI；
- 插件系统；
- 自动多世界假设推理。

保留原因：

- 当前最重要的是验证 Text2Code 写入质量；
- Segment / Residual / Coverage 已经足够证明“近乎无损”机制；
- 过早引入 Agent 和复杂图推理会掩盖核心问题。

---

## 4. v3.1-flash 最小架构

### 4.1 数据流

```text
Raw Text
  -> Corpus Manager
  -> Document / Block
  -> Segmenter
  -> Segment Objects
  -> Candidate JSON
  -> Code Generator
  -> .t2c.py
  -> Parser
  -> Validator
  -> Object Store
  -> Graph Builder
  -> Query API
  -> Evidence-backed Answer
```

### 4.2 模块

只实现九个模块：

1. Corpus Manager：保存原文、分块、offset、hash。
2. Segmenter：确定性或半确定性生成 segment。
3. Candidate JSON Schema：定义结构化输入格式。
4. Code Generator：确定性生成 `.t2c.py`。
5. T2C Parser：解析 `.t2c.py` AST。
6. Validator：检查语法、schema、引用、证据、coverage 和 claim safety。
7. Object Store：保存通过验证的 code object。
8. Graph Builder：从已验证对象生成有损索引。
9. Query API：查询 graph/code/evidence/residual。

暂不实现：

- LLM compiler 服务；
- Agent planner；
- Python sandbox；
- Web UI。

---

## 5. 最小核心模型

v3.1-flash 的最小对象：

- Document；
- Block；
- Segment；
- EvidenceRef；
- Entity；
- Event；
- Claim；
- Relation；
- Residual；
- Coverage。

其中最关键的是：

- `Segment`：原文地图；
- `Claim`：语义中心；
- `Residual`：残差信息；
- `Coverage`：损耗账本。

### 5.1 Document

表示原始文档。

必需字段：

- `id`
- `title`
- `source_type`
- `content_hash`

示例：

```python
doc(
    id="doc.case_001",
    title="Case 001",
    source_type="plain_text",
    content_hash="sha256:..."
)
```

### 5.2 Block

表示原文分块。

Block 通常对应较大文本单元，例如章节、页、自然段或 token window。

必需字段：

- `id`
- `doc_id`
- `index`
- `start`
- `end`
- `text_hash`

示例：

```python
block(
    id="block.case_001.0001",
    doc_id="doc.case_001",
    index=1,
    start=0,
    end=120,
    text_hash="sha256:..."
)
```

### 5.3 Segment

Segment 是 Code 对 Raw Text 的最小地图单元。

Segment 本身不等于结构化知识，它只表达：

> 原文在这里有一个可定位的信息单元。

必需字段：

- `id`
- `block_id`
- `index`
- `start`
- `end`
- `text_hash`
- `kind`

可选字段：

- `speaker`
- `order`
- `parent_segment`

允许的 `kind`：

- `sentence`
- `clause`
- `paragraph`
- `dialogue`
- `heading`
- `list_item`
- `table_row`
- `footnote`
- `other`

示例：

```python
segment(
    id="seg.case_001.0001",
    block_id="block.case_001.0001",
    index=1,
    start=0,
    end=42,
    text_hash="sha256:...",
    kind="sentence"
)
```

Segment 的生成应尽量确定性，可以用规则分句、标点、段落结构或 PDF/HTML 结构。LLM 可以辅助识别复杂边界，但最终必须通过 offset 和 hash 校验。

### 5.4 EvidenceRef

表示结构化对象对应的原文证据。

v3.1 中 EvidenceRef 优先指向 Segment，也可以退回 Block。

必需字段：

- `segment_id`
- `start`
- `end`
- `quote_hash`

可选字段：

- `block_id`
- `role`
- `confidence`

`start` 和 `end` 可以采用 segment-local offset。实现必须统一约定，不允许同一项目里混用不标注的 offset 坐标系。

示例：

```python
evidence(
    segment_id="seg.case_001.0001",
    start=12,
    end=38,
    quote_hash="sha256:..."
)
```

### 5.5 Entity

表示文本中的对象。

必需字段：

- `id`
- `kind`
- `name`
- `evidence_refs`

示例：

```python
entity(
    id="ent.case_001.alice",
    kind="person",
    name="Alice",
    evidence_refs=[
        evidence(
            segment_id="seg.case_001.0001",
            start=0,
            end=5,
            quote_hash="sha256:..."
        )
    ]
)
```

### 5.6 Event

表示文本中的事件。

必需字段：

- `id`
- `kind`
- `title`
- `participants`
- `evidence_refs`

可选字段：

- `time_text`
- `location_text`

示例：

```python
event(
    id="evt.case_001.arrival",
    kind="arrival",
    title="Alice arrived at the station",
    participants=["ent.case_001.alice"],
    time_text="10:00",
    location_text="station",
    evidence_refs=[
        evidence(
            segment_id="seg.case_001.0001",
            start=12,
            end=38,
            quote_hash="sha256:..."
        )
    ]
)
```

### 5.7 Claim

Claim 是语义中心。

必需字段：

- `id`
- `subject`
- `predicate`
- `object`
- `modality`
- `polarity`
- `evidence_refs`

可选字段：

- `source`
- `confidence`
- `status`

允许的 `modality`：

- `asserted`
- `claimed_by_source`
- `reported`
- `uncertain`
- `hypothetical`
- `conditional`
- `inferred`

允许的 `polarity`：

- `positive`
- `negative`
- `unknown`

示例：

```python
claim(
    id="claim.case_001.zhang_accuses_li",
    subject="ent.case_001.zhang",
    predicate="accuses",
    object="ent.case_001.li",
    modality="claimed_by_source",
    polarity="positive",
    source="ent.case_001.zhang",
    confidence=0.78,
    evidence_refs=[
        evidence(
            segment_id="seg.case_001.0003",
            start=0,
            end=26,
            quote_hash="sha256:..."
        )
    ]
)
```

这个对象只表示“张三声称/指控李四”，不能被 Graph Builder 投影成“李四确实做了某事”。

### 5.8 Relation

表示对象间关系。

必需字段：

- `id`
- `source`
- `target`
- `predicate`
- `evidence_refs`

可选字段：

- `modality`
- `polarity`
- `derived`

示例：

```python
relation(
    id="rel.case_001.alice_arrival",
    source="ent.case_001.alice",
    target="evt.case_001.arrival",
    predicate="participates_in",
    modality="asserted",
    polarity="positive",
    evidence_refs=[
        evidence(
            segment_id="seg.case_001.0001",
            start=12,
            end=38,
            quote_hash="sha256:..."
        )
    ]
)
```

### 5.9 Residual

Residual 表示无法安全结构化、但不能丢掉的信息。

它是 v3.1 解决“近乎无损”的关键对象之一。

适合进入 Residual 的信息：

- 语气；
- 情绪；
- 暗示；
- 反讽；
- 隐喻；
- 复杂心理描写；
- 模糊动机；
- 复杂上下文依赖；
- 当前 ontology 无法表达的信息；
- 暂时无法确认但可能重要的信息。

必需字段：

- `id`
- `segment_id`
- `category`
- `reason`
- `importance`
- `evidence_refs`

允许的 `category`：

- `tone`
- `emotion`
- `implication`
- `metaphor`
- `ambiguity`
- `context_dependency`
- `ontology_gap`
- `unsafe_inference`
- `other`

允许的 `importance`：

- `low`
- `medium`
- `high`

示例：

```python
residual(
    id="res.case_001.0001",
    segment_id="seg.case_001.0007",
    category="implication",
    reason="The sentence implies possible motive, but does not explicitly assert it.",
    importance="high",
    evidence_refs=[
        evidence(
            segment_id="seg.case_001.0007",
            start=0,
            end=48,
            quote_hash="sha256:..."
        )
    ]
)
```

Residual 的原则：

- 不把不确定含义硬编译成 Claim；
- 不让重要未结构化信息消失；
- 为 raw fallback 提供明确触发点；
- 让 ontology gap 可见。

### 5.10 Coverage

Coverage 表示一个 Segment 的语义覆盖状态。

它是 v3.1 的损耗账本。

必需字段：

- `id`
- `segment_id`
- `status`
- `object_refs`
- `residual_refs`

可选字段：

- `ignored_reason`
- `notes`

允许的 `status`：

- `covered`
- `partial`
- `raw_only`
- `ignored`

示例：

```python
coverage(
    id="cov.case_001.0007",
    segment_id="seg.case_001.0007",
    status="partial",
    object_refs=["claim.case_001.0007_a"],
    residual_refs=["res.case_001.0001"],
    notes="Core assertion captured, implied motive left as residual."
)
```

状态解释：

- `covered`：主要语义已经由 entity / event / claim / relation 表达。
- `partial`：部分语义已表达，仍有 residual。
- `raw_only`：当前不安全结构化，必须回 Raw Text。
- `ignored`：明确无知识价值或属于格式噪声。

Coverage 的原则：

- 每个 Segment 必须有且只有一个 Coverage；
- `covered` 必须至少有一个 object ref；
- `partial` 必须至少有一个 object ref 或 residual ref；
- `raw_only` 必须至少有一个 residual ref 或 notes；
- `ignored` 必须有 ignored_reason。

---

## 6. `.t2c.py` 最小规范

### 6.1 文件定位

`.t2c.py` 是受限 Python DSL。

它只用于声明知识对象，不直接执行。

### 6.2 固定 Import

```python
from t2c.dsl import (
    doc,
    block,
    segment,
    entity,
    event,
    claim,
    relation,
    residual,
    coverage,
    evidence,
)
```

### 6.3 允许语法

只允许：

- 固定 import；
- 顶层 DSL 函数调用；
- keyword arguments；
- string / number / boolean / None；
- list；
- dict；
- 注释。

### 6.4 禁止语法

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

### 6.5 最小完整示例

```python
from t2c.dsl import doc, block, segment, entity, event, claim, relation, residual, coverage, evidence

doc(
    id="doc.case_001",
    title="Case 001",
    source_type="plain_text",
    content_hash="sha256:doc_hash"
)

block(
    id="block.case_001.0001",
    doc_id="doc.case_001",
    index=1,
    start=0,
    end=64,
    text_hash="sha256:block_hash"
)

segment(
    id="seg.case_001.0001",
    block_id="block.case_001.0001",
    index=1,
    start=0,
    end=42,
    text_hash="sha256:segment_hash",
    kind="sentence"
)

entity(
    id="ent.case_001.alice",
    kind="person",
    name="Alice",
    evidence_refs=[
        evidence(
            segment_id="seg.case_001.0001",
            start=0,
            end=5,
            quote_hash="sha256:alice_span_hash"
        )
    ]
)

event(
    id="evt.case_001.arrival",
    kind="arrival",
    title="Alice arrived at the station",
    participants=["ent.case_001.alice"],
    time_text="10:00",
    location_text="station",
    evidence_refs=[
        evidence(
            segment_id="seg.case_001.0001",
            start=10,
            end=42,
            quote_hash="sha256:event_span_hash"
        )
    ]
)

claim(
    id="claim.case_001.arrival",
    subject="ent.case_001.alice",
    predicate="arrived_at",
    object="station",
    modality="asserted",
    polarity="positive",
    confidence=0.9,
    evidence_refs=[
        evidence(
            segment_id="seg.case_001.0001",
            start=10,
            end=42,
            quote_hash="sha256:event_span_hash"
        )
    ]
)

relation(
    id="rel.case_001.alice_arrival",
    source="ent.case_001.alice",
    target="evt.case_001.arrival",
    predicate="participates_in",
    modality="asserted",
    polarity="positive",
    evidence_refs=[
        evidence(
            segment_id="seg.case_001.0001",
            start=10,
            end=42,
            quote_hash="sha256:event_span_hash"
        )
    ]
)

coverage(
    id="cov.case_001.0001",
    segment_id="seg.case_001.0001",
    status="covered",
    object_refs=[
        "ent.case_001.alice",
        "evt.case_001.arrival",
        "claim.case_001.arrival",
        "rel.case_001.alice_arrival"
    ],
    residual_refs=[]
)
```

---

## 7. Text2Code 编译过程

### 7.1 编译不是摘要

Text2Code 不允许把长文本先总结成短文本，再从短文本抽取 code。

禁止路径：

```text
Raw Text -> Summary Text -> Code
```

允许路径：

```text
Raw Text -> Segment -> Candidate JSON -> Code
```

原因：

- Summary 会提前丢失细节；
- 丢失发生在不可审计的自然语言层；
- 后续 code 再规范也只能规范摘要残留的信息。

### 7.2 三层输出

Text2Code 对每个 Block 生成三类结果。

#### 7.2.1 原文地图

输出：

- Segment；
- EvidenceRef 坐标。

目标：

- 把原文切成稳定可引用单位；
- 为结构化对象建立定位基础；
- 不在这一步做复杂语义判断。

#### 7.2.2 语义对象

输出：

- Entity；
- Event；
- Claim；
- Relation。

目标：

- 承载约 90% 日常认知；
- 保留主体、谓词、客体、模态、极性、证据；
- 避免把 claim 误升为 fact。

#### 7.2.3 残差与覆盖

输出：

- Residual；
- Coverage。

目标：

- 标记未结构化但重要的信息；
- 记录每个 Segment 的覆盖状态；
- 让损耗可检查、可回放。

### 7.3 编译策略

每个 Segment 都必须经过四步判断：

1. 它包含哪些明确可结构化对象？
2. 它包含哪些不能安全结构化但重要的信息？
3. 它的主要语义是否已经被 object refs 覆盖？
4. 它是否需要 raw fallback？

输出规则：

- 明确事实或断言 -> Claim。
- 可识别对象 -> Entity。
- 可定位发生过程 -> Event。
- 明确对象关系 -> Relation。
- 暗示、语气、反讽、复杂心理 -> Residual。
- 完全无法安全结构化 -> Coverage `raw_only`。
- 无知识价值噪声 -> Coverage `ignored`。

---

## 8. Validator 最小集

v3.1-flash 的 validator 不只检查对象合法，还要检查信息损耗是否被记录。

### 8.1 AST Grammar Validator

检查 `.t2c.py` 只包含允许语法。

失败示例：

- 出现 `for`；
- 出现变量赋值；
- 调用了非白名单函数；
- 出现任意 import。

### 8.2 Schema Validator

检查每个 DSL call 的字段是否符合 schema。

检查：

- 必需字段；
- 类型；
- enum；
- confidence 范围；
- evidence_refs 非空；
- coverage status 合法；
- residual category / importance 合法。

### 8.3 Reference Validator

检查对象引用是否存在。

检查：

- block 指向已存在 doc；
- segment 指向已存在 block；
- evidence 指向已存在 segment；
- event participants 指向已存在 entity；
- relation source / target 存在；
- claim subject 存在，除非是 literal；
- claim source 存在，除非为空；
- residual segment 存在；
- coverage segment 存在；
- coverage object_refs / residual_refs 存在。

### 8.4 Evidence Validator

检查 evidence 是否真实对应原文。

检查：

- segment span 在 block 范围内；
- evidence span 在 segment 范围内；
- `end > start`；
- segment text hash 匹配；
- evidence quote hash 匹配；
- 每个 entity/event/claim/relation/residual 都有 evidence。

### 8.5 Claim Safety Validator

检查断言模态不能被误升级。

规则：

- `claimed_by_source` 不能被投影成 asserted fact；
- `reported` 不能被投影成 asserted fact；
- `uncertain` 不能进入默认事实边；
- `hypothetical` 不能进入默认事实边；
- `conditional` 不能无条件进入默认事实边；
- `negative` claim 不能生成 positive relation；
- `inferred` claim 必须有明确 derived source，flash 版默认不鼓励使用。

### 8.6 Coverage Validator

检查每个 Segment 的损耗账本是否完整。

规则：

- 每个 Segment 必须有且只有一个 Coverage。
- `covered` 必须至少有一个 object ref。
- `partial` 必须至少有一个 object ref 或 residual ref。
- `raw_only` 必须至少有一个 residual ref 或 notes。
- `ignored` 必须有 ignored_reason。
- High importance residual 所在 Segment 不能是 `covered`。
- High importance residual 必须触发 raw fallback 标记。

Coverage Validator 是 v3.1-flash 的关键。它保证 Text2Code 允许有损，但不允许不知道哪里有损。

---

## 9. Graph Builder 最小规则

### 9.1 Graph 定位

Graph 是索引，不是真理源。

Graph 可删除、可重建、可缓存。

Graph 中每个节点和边都必须回指 code object。

### 9.2 Graph Node

为以下对象建节点：

- Document；
- Block；
- Segment；
- Entity；
- Event；
- Claim；
- Residual。

暂不为 Relation 和 Coverage 单独建节点。Relation 默认投影为边；Coverage 作为 Segment 的索引属性。

### 9.3 Graph Edge

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

### 9.4 禁止投影

禁止：

- 将 `claimed_by_source` claim 投影成事实边；
- 将 `reported` claim 投影成事实边；
- 将 `uncertain` claim 投影成事实边；
- 将 `hypothetical` claim 投影成事实边；
- 将 `conditional` claim 投影成无条件事实边；
- 将 `negative` claim 投影成 positive relation；
- 从 Graph 新建知识对象；
- 用 Graph 覆盖 Coverage 状态。

### 9.5 Graph API

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

所有 API 返回对象 ID、code object、coverage 和 evidence refs，不直接返回最终结论。

---

## 10. Query 最小闭环

### 10.1 查询流程

```text
User Question
  -> fixed Query API
  -> candidate object ids
  -> code object
  -> coverage check
  -> residual check
  -> evidence span
  -> answer / report
```

### 10.2 Raw fallback 触发条件

查询过程中，只要出现以下条件，必须回 Raw Text 或至少返回原文片段：

- 相关 Segment coverage 是 `partial`；
- 相关 Segment coverage 是 `raw_only`；
- 相关 Segment 存在 high importance residual；
- 相关 Claim modality 不是 `asserted`；
- 相关 Claim polarity 不是 `positive`；
- 相关对象存在冲突状态；
- 用户要求精确原文解释。

### 10.3 输出要求

回答至少包含：

- 结论；
- 相关 code object ID；
- coverage 状态；
- residual 提示；
- evidence 原文片段；
- modality；
- polarity；
- 如果存在不确定性，明确标出。

### 10.4 第一版不要求

暂不要求：

- Agent 自动写查询脚本；
- 多轮推理链；
- 自动生成复杂报告；
- UI 展示；
- 权限系统。

---

## 11. LLM 在 v3.1-flash 中的位置

v3.1-flash 可以先不接 LLM。

推荐顺序：

### 11.1 Phase A：手写 `.t2c.py`

先人工把几段短文本写成 `.t2c.py`。

目的：

- 验证 Segment 是否足够表达原文地图；
- 验证 Residual 是否能承接无法结构化的信息；
- 验证 Coverage 是否能暴露损耗；
- 验证 validator 是否能拦住静默损耗；
- 验证 graph 是否能重建；
- 验证 evidence 是否能回放。

### 11.2 Phase B：规则 Segmenter

先用规则生成 Segment：

- 段落；
- 句子；
- 条款；
- 对白。

Segmenter 可以粗糙，但必须产生 offset 和 hash。

### 11.3 Phase C：LLM 只写 Candidate JSON

LLM 可以参与：

```text
Segment -> Candidate JSON
```

LLM 必须输出：

- semantic objects；
- residuals；
- coverage。

LLM 不允许：

- 直接写 `.t2c.py`；
- 直接写 Graph；
- 修改已验证知识；
- 根据 Graph 生成新知识；
- 先总结原文再编译。

### 11.4 Phase D：确定性 JSON -> Code

Code Generator 把 Candidate JSON 转成 `.t2c.py`。

这一步不使用 LLM。

---

## 12. 最小验收实验

v3.1-flash 是否有价值，不靠想象，要靠对比实验。

### 12.1 测试集

准备：

- 10 篇短文本；
- 每篇 500-2000 字；
- 覆盖人物、事件、声称、否认、时间、地点、关系、语气、暗示、心理描写；
- 每篇设计 5 个问题。

总计：

- 10 篇文本；
- 50 个问题。

### 12.2 Baseline

Baseline 使用：

- 直接 long-context QA；
- 或普通 RAG + citation。

### 12.3 T2C-flash

T2C-flash 使用：

- Evidence；
- Segment；
- `.t2c.py`；
- Claim；
- Residual；
- Coverage；
- Validator；
- Derived Graph；
- Query API。

### 12.4 对比指标

只看七个指标：

1. 答案正确率。
2. 证据引用准确率。
3. unsupported claim 数量。
4. “声称/否认/不确定”误升级为事实的次数。
5. Coverage 完整率。
6. High importance residual 召回率。
7. 单篇文本结构化维护成本。

### 12.5 成功标准

T2C v3.1-flash 合理性的最低证明：

- 证据引用准确率明显高于 baseline；
- unsupported claim 明显少于 baseline；
- 模态误升级明显少于 baseline；
- 每个 Segment 都有 coverage；
- high importance residual 能稳定触发 raw fallback；
- 维护成本没有高到不可接受。

如果做不到这些，就不应该继续扩展到完整系统。

---

## 13. 推荐仓库结构

```text
text2code/
  spec/
    t2c_design_v3.0.md
    t2c_design_v3.0-flash.md
    t2c_design_v3.1-flash.md

  t2c/
    __init__.py
    dsl.py
    parser.py
    schema.py
    validator.py
    corpus.py
    segmenter.py
    graph_builder.py
    graph_api.py

  examples/
    corpus/
      case_001.txt
    knowledge/
      case_001.t2c.py
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

## 14. 实现优先级

### P0：必须先做

- `Document`
- `Block`
- `Segment`
- `EvidenceRef`
- `.t2c.py` parser
- AST grammar validator
- schema validator
- evidence span validator

### P1：近乎无损机制

- `Residual`
- `Coverage`
- coverage validator
- raw fallback 标记
- segment coverage report

### P2：证明语义价值

- `Entity`
- `Event`
- `Claim`
- `Relation`
- claim safety validator
- graph builder
- basic query API

### P3：接入 LLM

- Candidate JSON schema；
- JSON -> `.t2c.py` generator；
- Segment -> Candidate JSON prompt；
- compile error repair；
- coverage / residual 生成约束。

### P4：再考虑扩展

- Conflict object；
- State；
- Rule；
- Agent Sandbox；
- WorldVersion；
- UI；
- plugin。

---

## 15. v3.1-flash 总结

v3.1-flash 的核心升级是把“近乎无损”变成可验证机制。

它不再只要求：

- 原文无损保存；
- 结构化解释带证据；
- Claim 不能偷换成 Fact；
- Graph 只能做有损索引。

它进一步要求：

- 原文必须被 Segment 映射；
- 每个 Segment 必须有 Coverage；
- 无法安全结构化的信息必须进入 Residual；
- High importance residual 必须触发 Raw fallback；
- Text2Code 允许有损，但不允许静默有损。

最终关系：

```text
Raw Text = 100% final evidence source
Canonical Code = 90% daily cognition source
Derived Graph = lossy navigation source
Residual + Coverage = loss ledger
```

如果 v3.1-flash 能证明：Code 可以承载大部分日常认知，而 Raw Text 只在冲突、不确定和高残差场景下回退，那么 Text2Code 的存在合理性就真正站住了。
