# Text2Code 认知引擎设计说明书 v3.0-flash

## 0. 定位

v3.0-flash 是 v3.0 的最小可行内核版本。

它不是缩水版哲学，而是砍掉暂时不必要的系统复杂度，只保留最能证明 Text2Code 合理性的部分。

核心目标：

1. 原文尽量无损保存，所有结构化知识必须可回到 Evidence。
2. Code 是规范化知识表达，必须可验证、可 diff、可重建。
3. Graph 是从 Code 派生的有损索引，只用于搜索和定位，不作为证据。

一句话：

> 先做一个小而硬的知识编译内核，不先做完整认知操作系统。

---

## 1. 不变的设计哲学

v3.0-flash 绝不偏离以下原则。

### 1.1 Evidence 是证据源

系统不能只保存 AI 的结构化结果。原始文本、分块、offset、hash 必须保存。

任何关键结论都必须能追溯到：

- 原始 document；
- block；
- span；
- 原文切片；
- hash 校验。

### 1.2 Code 是规范化解释

`.t2c.py` 表达的是系统对文本的结构化解释。

它不是原文替代品，也不是自由 Python 程序。它必须是受限 DSL，可以被 AST 和 schema 验证。

选择 code 形态的核心原因不是为了执行，而是为了获得比自然语言更清晰的信息边界。自然语言的语法弹性太高，同一句话可以隐藏转述、否定、条件、隐喻和上下文省略；而 code 的类、函数调用、参数、列表、字典等结构可以被 AST 明确切分。对 AI 来说，这种边界清晰的对象形态更容易解释、编辑、diff、定位错误和做增量管理。

因此，Text2Code 中的 code 首先是 **AST-governed knowledge container**，其次才可能是可执行接口。

### 1.3 Graph 是有损索引

Graph 不能成为事实源。Graph 只能回答：

> 哪些 code object 和 evidence span 可能相关？

最终判断必须回到 `.t2c.py` 和 Evidence。

### 1.4 Claim 优先于 Fact

自然语言里的很多信息不是事实，而是断言、声称、否认、推测、条件和转述。

系统第一版就必须建模 Claim，避免把“某人声称 X”错误提升为“X 为真”。

### 1.5 Validator 优先于 Agent

第一阶段不追求聪明 Agent，而追求可靠写入。

只有通过 validator 的 code object 才能进入知识层。

---

## 2. 明确砍掉的东西

v3.0-flash 暂时不做以下内容。

### 2.1 不做 Agent Sandbox

第一版不让 AI 写 Python 查询脚本。

原因：

- 查询脚本沙箱会引入安全复杂度；
- 早期问题可以用固定 API 覆盖；
- 当前最需要验证的是知识写入质量，不是 Agent 编程能力。

保留替代：

- 固定查询 API；
- 人类或测试脚本调用 API；
- 后续再接 Planner / Sandbox。

### 2.2 不做 WorldVersion

第一版不做多世界、多假设分支。

原因：

- 会复杂化每个查询；
- 会复杂化 Graph 投影；
- 会复杂化 UI 和审核流程。

保留替代：

- `status = validated | conflicted | rejected`；
- conflicted 对象进入冲突列表；
- 暂不进行多版本推理。

### 2.3 不做通用 Rule Engine

第一版不做可配置规则语言或插件规则系统。

原因：

- 通用规则引擎会过早抽象；
- 大部分价值可以由少量硬编码 validator 证明；
- 规则 DSL 本身会变成另一个项目。

保留替代：

- 5 个以内硬编码 validator；
- 规则代码写在系统内部；
- `.t2c.py` 不写自定义规则逻辑。

### 2.4 不做复杂 Ontology

第一版不做完整领域本体。

暂不建模：

- State；
- Rule object；
- WorldVersion；
- 高级 Conflict object；
- 复杂时间规范化；
- 复杂实体消歧系统。

保留最小对象：

- Document；
- Block；
- EvidenceRef；
- Entity；
- Event；
- Claim；
- Relation。

### 2.5 不做复杂 Graph 推理

Graph 第一版只做索引，不做结论推理。

Graph 可以：

- 找节点；
- 找边；
- 找 claim；
- 找 evidence ref；
- 路径搜索。

Graph 不可以：

- 自动判定事实真假；
- 自动升级 claim；
- 生成新知识；
- 覆盖 code object。

---

## 3. v3.0-flash 架构

### 3.1 最小数据流

```text
Raw Text
  -> Document / Block
  -> Candidate JSON
  -> .t2c.py
  -> Validator
  -> Object Store
  -> Derived Graph
  -> Evidence-backed Query
```

### 3.2 最小模块

只实现七个模块：

1. Corpus Manager：保存原文、分块、offset、hash。
2. Candidate JSON Schema：定义结构化输入格式。
3. Code Generator：确定性生成 `.t2c.py`。
4. T2C Parser：解析 `.t2c.py` AST。
5. Validator：检查语法、schema、引用、证据、基本逻辑。
6. Graph Builder：从已验证对象生成有损索引。
7. Query API：查询 graph，并回到 code/evidence。

暂不实现：

- LLM compiler 服务；
- Agent planner；
- Python sandbox；
- Web UI；
- 多版本图谱；
- 插件系统。

---

## 4. 最小核心模型

### 4.1 Document

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

### 4.2 Block

表示原文分块。

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

### 4.3 EvidenceRef

表示结构化对象对应的原文证据。

必需字段：

- `block_id`
- `start`
- `end`
- `quote_hash`

可选字段：

- `role`
- `confidence`

示例：

```python
evidence(
    block_id="block.case_001.0001",
    start=12,
    end=38,
    quote_hash="sha256:..."
)
```

### 4.4 Entity

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
            block_id="block.case_001.0001",
            start=0,
            end=5,
            quote_hash="sha256:..."
        )
    ]
)
```

### 4.5 Event

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
            block_id="block.case_001.0001",
            start=12,
            end=38,
            quote_hash="sha256:..."
        )
    ]
)
```

### 4.6 Claim

Claim 是 flash 版最重要的对象。

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
            block_id="block.case_001.0001",
            start=42,
            end=68,
            quote_hash="sha256:..."
        )
    ]
)
```

这个对象只表示“张三声称/指控李四”，不能被 Graph Builder 投影成“李四确实做了某事”。

### 4.7 Relation

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
            block_id="block.case_001.0001",
            start=12,
            end=38,
            quote_hash="sha256:..."
        )
    ]
)
```

---

## 5. `.t2c.py` 最小规范

### 5.1 文件定位

`.t2c.py` 是受限 Python DSL。

它只用于声明知识对象，不直接执行。

### 5.2 允许语法

只允许：

- 固定 import；
- 顶层 DSL 函数调用；
- keyword arguments；
- string / number / boolean / None；
- list；
- dict；
- 注释。

固定 import：

```python
from t2c.dsl import doc, block, entity, event, claim, relation, evidence
```

### 5.3 禁止语法

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

### 5.4 最小完整示例

```python
from t2c.dsl import doc, block, entity, event, claim, relation, evidence

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

entity(
    id="ent.case_001.alice",
    kind="person",
    name="Alice",
    evidence_refs=[
        evidence(
            block_id="block.case_001.0001",
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
            block_id="block.case_001.0001",
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
            block_id="block.case_001.0001",
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
            block_id="block.case_001.0001",
            start=10,
            end=42,
            quote_hash="sha256:event_span_hash"
        )
    ]
)
```

---

## 6. Validator 最小集

第一版 validator 只做必要检查。

### 6.1 AST Grammar Validator

检查 `.t2c.py` 只包含允许语法。

失败示例：

- 出现 `for`；
- 出现变量赋值；
- 调用了非白名单函数；
- 出现任意 import。

### 6.2 Schema Validator

检查每个 DSL call 的字段是否符合 schema。

检查：

- 必需字段；
- 类型；
- enum；
- confidence 范围；
- evidence_refs 非空。

### 6.3 Reference Validator

检查对象引用是否存在。

检查：

- block 指向已存在 doc；
- evidence 指向已存在 block；
- event participants 指向已存在 entity；
- relation source / target 存在；
- claim subject 存在，除非是 literal；
- claim source 存在，除非为空。

### 6.4 Evidence Validator

检查 evidence 是否真实对应原文。

检查：

- span 在 block 范围内；
- `end > start`；
- span 切片 hash 等于 `quote_hash`；
- 每个 entity/event/claim/relation 都有 evidence。

### 6.5 Claim Safety Validator

检查断言模态不能被误升级。

规则：

- `claimed_by_source` 不能被投影成 asserted fact；
- `reported` 不能被投影成 asserted fact；
- `uncertain` 不能进入默认事实边；
- `hypothetical` 不能进入默认事实边；
- `negative` claim 不能生成 positive relation。

这是 flash 版最关键的语义安全检查。

---

## 7. Graph Builder 最小规则

### 7.1 Graph 定位

Graph 是索引，不是真理源。

Graph 可删除、可重建、可缓存。

Graph 中每个节点和边都必须回指 code object。

### 7.2 Graph Node

为以下对象建节点：

- Document；
- Block；
- Entity；
- Event；
- Claim。

暂不为 Relation 单独建节点。Relation 默认投影为边。

### 7.3 Graph Edge

允许生成：

- `Document -> Block`
- `Entity -> Evidence Block`
- `Event -> Evidence Block`
- `Claim -> Evidence Block`
- `Entity -> Event`，来自 asserted positive `participates_in` relation
- `Claim -> Subject`
- `Claim -> Object`
- `Claim -> Source`

### 7.4 禁止投影

禁止：

- 将 `claimed_by_source` claim 投影成事实边；
- 将 `reported` claim 投影成事实边；
- 将 `uncertain` claim 投影成事实边；
- 将 `hypothetical` claim 投影成事实边；
- 将 `negative` claim 投影成 positive relation；
- 从 Graph 新建知识对象。

### 7.5 Graph API

第一版只提供：

```python
find_entities(name=None, kind=None)
find_events(participant=None, kind=None)
find_claims(subject=None, predicate=None, object=None, modality=None)
get_object(object_id)
get_evidence(object_id)
trace_neighbors(object_id, depth=1)
```

所有 API 返回对象 ID、code object 和 evidence refs，不直接返回最终结论。

---

## 8. Query 最小闭环

### 8.1 查询流程

```text
User Question
  -> fixed Query API
  -> candidate object ids
  -> code object
  -> evidence span
  -> answer / report
```

### 8.2 输出要求

回答至少包含：

- 结论；
- 相关 code object ID；
- evidence 原文片段；
- modality；
- polarity；
- 如果存在不确定性，明确标出。

### 8.3 第一版不要求

暂不要求：

- Agent 自动写查询脚本；
- 多轮推理链；
- 自动生成复杂报告；
- UI 展示；
- 权限系统。

---

## 9. LLM 在 flash 版中的位置

flash 版可以先不接 LLM。

推荐顺序：

### 9.1 Phase A：手写 `.t2c.py`

先人工把几段短文本写成 `.t2c.py`。

目的：

- 验证 DSL 是否可读；
- 验证 validator 是否有用；
- 验证 graph 是否能重建；
- 验证 evidence 是否能回放。

### 9.2 Phase B：LLM 只写 Candidate JSON

LLM 可以参与 Text -> Candidate JSON。

但不允许：

- 直接写 `.t2c.py`；
- 直接写 Graph；
- 修改已验证知识；
- 根据 Graph 生成新知识。

### 9.3 Phase C：确定性 JSON -> Code

Code Generator 把 Candidate JSON 转成 `.t2c.py`。

这一步不使用 LLM。

---

## 10. 最小验收实验

v3.0-flash 是否有价值，不靠想象，要靠对比实验。

### 10.1 测试集

准备：

- 10 篇短文本；
- 每篇 500-2000 字；
- 覆盖人物、事件、声称、否认、时间、地点、关系；
- 每篇设计 5 个问题。

总计：

- 10 篇文本；
- 50 个问题。

### 10.2 Baseline

Baseline 使用：

- 直接 long-context QA；
- 或普通 RAG + citation。

### 10.3 T2C-flash

T2C-flash 使用：

- Evidence；
- `.t2c.py`；
- Validator；
- Derived Graph；
- Query API。

### 10.4 对比指标

只看五个指标：

1. 答案正确率。
2. 证据引用准确率。
3. unsupported claim 数量。
4. “声称/否认/不确定”误升级为事实的次数。
5. 单篇文本结构化维护成本。

### 10.5 成功标准

T2C-flash 合理性的最低证明：

- 证据引用准确率明显高于 baseline；
- unsupported claim 明显少于 baseline；
- 模态误升级明显少于 baseline；
- 维护成本没有高到不可接受。

如果做不到这些，就不应该继续扩展到完整 v3.0。

---

## 11. 推荐仓库结构

```text
text2code/
  spec/
    t2c_design_v3.0.md
    t2c_design_v3.0-flash.md

  t2c/
    __init__.py
    dsl.py
    parser.py
    schema.py
    validator.py
    corpus.py
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
    test_graph_builder.py
```

---

## 12. 实现优先级

### P0：必须先做

- `Document`
- `Block`
- `EvidenceRef`
- `.t2c.py` parser
- AST grammar validator
- schema validator
- evidence span validator

### P1：证明价值

- `Entity`
- `Event`
- `Claim`
- `Relation`
- claim safety validator
- graph builder
- basic query API

### P2：接入 LLM

- Candidate JSON schema；
- JSON -> `.t2c.py` generator；
- LLM compile prompt；
- compile error repair。

### P3：再考虑扩展

- Conflict object；
- State；
- Rule；
- Agent Sandbox；
- WorldVersion；
- UI；
- plugin。

---

## 13. flash 版总结

v3.0-flash 保留 Text2Code 的核心锋利度：

- 原文无损保存；
- 结构化解释必须带证据；
- Claim 不能被偷换成 Fact；
- Code 必须可验证；
- Graph 只能做有损索引；
- 结论必须能回到 Evidence。

它砍掉的是暂时不必要的庞大系统：

- 不先做 Agent；
- 不先做多世界；
- 不先做规则引擎；
- 不先做复杂 ontology；
- 不先做复杂图推理。

如果 flash 版不能在证据准确率、unsupported claim、模态误升级上明显优于普通 text/RAG 方案，完整 v3.0 就不应该继续膨胀。

如果 flash 版能证明这些核心优势，再扩展完整 v3.0 才有意义。
