# Text2Code 认知引擎设计说明书 v3.0

## 0. 版本定位

v3.0 是对 `t2c_design2.1.pdf` 的一次原则性重构。

v2.1 的核心表达是“代码即知识”和“统一 Code-Graph”。这个方向仍然成立，但需要修正一个关键点：**Graph 不应该成为证据来源，也不应该成为唯一真理源**。Graph 是有损派生索引，用来加速 AI 搜索、定位、遍历和理解；真正可审计、可验证、可回放的基础，应由原文证据层与规范化代码层共同承担。

v3.0 的核心目标是建立一个可以把自然语言文本转换为规范代码、再从规范代码派生图索引的认知基础设施。它要同时满足三件事：

1. 原始 text 信息尽量无损保存，并且所有结构化解释都能回到原文证据。
2. CodeGraph 是有损提取结果，只服务于搜索、导航、推理加速，不作为最终证据。
3. Code 必须符合明确规范，可以被 AST、Schema、引用完整性、证据完整性和业务逻辑验证器自动检查。

一句话概括：

> Evidence 是证据源，Canonical Code 是规范化知识源，CodeGraph 是派生搜索视图。

---

## 1. 产品愿景

### 1.1 愿景

构建一个以 **Text-as-Evidence、Code-as-Knowledge、Graph-as-Index** 为核心的认知引擎，将复杂长文本世界编译为：

- 可回溯的证据集合；
- 可验证的规范化代码；
- 可重建的有损代码图谱；
- 可执行的沙箱推理环境。

系统最终服务于超级长文本理解、多跳推理、知识审计、复杂规则检查、AI 自查与人机协同判断。

### 1.2 设计哲学

#### 1.2.1 原文优先

自然语言文本不是一次性消耗品，而是系统最高等级的证据源。任何结构化知识、代码对象、图节点、推理结论都必须能回到原始 text 的具体位置。

#### 1.2.2 代码承载知识，不承载证据

Code 是对 text 的规范化解释和管理形态。它比普通 JSON 更适合被 AI 阅读、被程序验证、被版本管理、被差异审查，但它仍然是对原文的解释，不是原文自身。

#### 1.2.3 Graph 是索引，不是真相

CodeGraph 可以压缩、抽取、聚合、重排知识，因此天然有损。它可以帮助 AI 快速找到相关节点和路径，但不能替代 Evidence 与 Canonical Code 参与最终举证。

#### 1.2.4 有损解释必须显式标注

从 text 到 JSON、Code、Graph 的过程都会产生语义选择。系统必须保留这些选择的边界，例如置信度、模态、极性、信息来源、证据 span 和冲突状态。

#### 1.2.5 规范优先于智能

LLM 可以参与结构化，但不能自由写入最终知识层。所有写入都必须通过明确规范和验证器。

#### 1.2.6 可重建优先于缓存便利

Graph、embedding、摘要 hint、搜索索引都应能从 Evidence + Canonical Code 重新生成。任何不可重建的派生物都不能被视作核心知识资产。

---

## 2. 核心概念

### 2.1 Evidence Layer

Evidence Layer 是原文证据层，负责无损或近无损保存输入文本及其元信息。

它保存：

- 原始文档；
- 文档版本；
- 分块结果；
- 字符级 offset；
- 文本 hash；
- 来源元数据；
- span 定位；
- span 内容校验；
- 多模态证据扩展位。

Evidence Layer 回答的问题是：

> 这个结构化判断到底来自哪一段原文？

### 2.2 Canonical Code Layer

Canonical Code Layer 是规范化知识代码层，负责用受限代码表达对原文的结构化解释。

它保存：

- entity；
- event；
- state；
- rule；
- claim；
- relation；
- qualifier；
- evidence reference；
- conflict；
- world version。

Canonical Code 回答的问题是：

> 系统如何以可验证、可 diff、可查询的方式管理对原文的解释？

### 2.3 Derived CodeGraph Layer

Derived CodeGraph Layer 是有损图索引层，负责从 Canonical Code 派生节点、边、索引字段和搜索辅助信息。

它保存：

- 节点索引；
- 关系索引；
- 时间索引；
- 空间索引；
- 实体倒排索引；
- claim 依赖关系；
- embedding；
- 检索 hint；
- graph traversal cache。

Graph 回答的问题是：

> 我应该去哪几个 code object 和 evidence span 里寻找答案？

### 2.4 Agent Sandbox

Agent Sandbox 是受控执行环境，负责让 AI 或人类开发者用规范 API 查询 Evidence、Code 和 Graph。

它支持：

- 图遍历；
- 节点过滤；
- 关系查询；
- claim 聚合；
- evidence 解压；
- 冲突包生成；
- 结果可追溯输出。

---

## 3. 三层真相关系

### 3.1 Truth Hierarchy

系统内部需要明确不同层的可信等级：

| 层级 | 名称 | 是否有损 | 是否可作为证据 | 是否可重建 | 用途 |
| --- | --- | --- | --- | --- | --- |
| L0 | Raw Text | 无损 | 是 | 原始输入 | 证据源 |
| L1 | Evidence Span | 近无损 | 是 | 从 Raw Text 切分 | 精确引用 |
| L2 | Canonical Code | 有损解释 | 条件性 | 从 JSON/人工编写生成 | 规范化知识管理 |
| L3 | Derived CodeGraph | 有损派生 | 否 | 从 Canonical Code 重建 | 搜索与推理加速 |
| L4 | Answer / Report | 有损表达 | 否 | 从查询过程重放 | 用户输出 |

### 3.2 证据规则

任何最终回答中的关键结论必须至少关联：

- 一个 Canonical Code object；
- 一个或多个 Evidence Span；
- 对应 Raw Text 的 hash 校验；
- 推理路径或查询脚本记录。

Graph 查询结果不能单独作为证据，只能作为定位入口。

### 3.3 派生规则

所有 L3 Graph 数据必须从 L2 Canonical Code 派生。

禁止：

- 直接从 LLM 输出写入 Graph；
- 直接从 embedding 结果写入 Graph；
- 手工修改 Graph 后反向污染 Code；
- 将 Graph 摘要作为新的 Text2Code 输入。

允许：

- Graph 记录派生时间；
- Graph 记录构建器版本；
- Graph 记录索引统计；
- Graph 记录指向 Canonical Code object 的稳定 ID。

---

## 4. 总体架构

### 4.1 模块视图

系统由八个核心模块组成：

1. Corpus Manager：管理原始文本、文档版本、分块和 span。
2. Knowledge Compiler：将 text block 编译为符合 schema 的 JSON candidate。
3. Code Generator：将 JSON candidate 确定性转换为 `.t2c.py` 规范代码。
4. Code Validator：对 `.t2c.py` 做语法、语义、引用、证据和逻辑验证。
5. Knowledge Store：保存通过验证的 Canonical Code object。
6. Graph Builder：从 Canonical Code 派生 CodeGraph。
7. Agent Sandbox：执行受限查询脚本和推理脚本。
8. Audit UI / Review API：展示 diff、冲突、证据链和人工仲裁入口。

### 4.2 数据流

```text
Raw Text
  -> Corpus Manager
  -> Evidence Blocks / Spans
  -> Knowledge Compiler
  -> Candidate JSON
  -> Code Generator
  -> Canonical .t2c.py
  -> Code Validator
  -> Knowledge Store
  -> Graph Builder
  -> Derived CodeGraph
  -> Agent Sandbox
  -> Evidence-backed Answer
```

### 4.3 写入路径

知识写入必须经过完整链路：

```text
Text -> Evidence Span -> Candidate JSON -> Canonical Code -> Validation -> Store -> Graph Rebuild
```

任何绕开 Evidence Span 或 Validation 的写入都应被拒绝。

### 4.4 查询路径

用户查询可以使用 Graph 加速，但必须回到 Code 和 Evidence：

```text
User Question
  -> Planner
  -> Graph Search
  -> Code Object Fetch
  -> Evidence Span Fetch
  -> Sandbox Reasoning
  -> Answer with Evidence
```

---

## 5. Text-as-Code 的代码规范

### 5.1 文件格式

Canonical Code 使用 `.t2c.py` 作为文件扩展名。

`.t2c.py` 是 Python 子集，但它不是通用 Python 程序。它是声明式知识 DSL。

示例：

```python
from t2c.dsl import doc, block, entity, event, claim, relation, evidence

doc(
    id="doc.case_001",
    title="Case 001",
    source_type="plain_text",
    version="1",
    content_hash="sha256:..."
)

block(
    id="block.case_001.0001",
    doc_id="doc.case_001",
    index=1,
    start=0,
    end=128,
    text_hash="sha256:..."
)

entity(
    id="ent.alice",
    kind="person",
    canonical_name="Alice",
    aliases=["A"],
    evidence_refs=[
        evidence(block_id="block.case_001.0001", start=0, end=5)
    ]
)

event(
    id="evt.arrival_001",
    kind="arrival",
    title="Alice arrived at the station",
    participants=["ent.alice"],
    time={"text": "10:00", "normalized": "10:00"},
    location=None,
    evidence_refs=[
        evidence(block_id="block.case_001.0001", start=12, end=45)
    ]
)

claim(
    id="claim.arrival_001",
    subject="ent.alice",
    predicate="arrived_at",
    object="station",
    modality="asserted",
    polarity="positive",
    confidence=0.86,
    evidence_refs=[
        evidence(block_id="block.case_001.0001", start=12, end=45)
    ]
)

relation(
    id="rel.alice_participates_arrival",
    source="ent.alice",
    target="evt.arrival_001",
    predicate="participates_in",
    evidence_refs=[
        evidence(block_id="block.case_001.0001", start=12, end=45)
    ]
)
```

### 5.2 允许语法

`.t2c.py` 只允许：

- 固定 import：`from t2c.dsl import ...`；
- 顶层函数调用；
- 字符串、数字、布尔值、None；
- list；
- dict；
- keyword arguments；
- trailing comma；
- 注释。

### 5.3 禁止语法

`.t2c.py` 禁止：

- 任意 import；
- `exec` / `eval`；
- 变量赋值；
- 函数定义；
- 类定义；
- lambda；
- if / for / while / try；
- with；
- yield；
- await；
- 文件、网络、系统调用；
- 动态字符串拼接；
- f-string；
- comprehension；
- attribute access；
- method call；
- arithmetic expression；
- 任何非白名单函数调用。

### 5.4 设计原因

使用 Python 子集而不是纯 JSON 的原因：

- Code 形态能提供比自然语言更清晰的信息边界；
- AI 更擅长阅读和维护代码形态；
- diff 更清晰；
- 可以借助 AST 做严格验证；
- 可以自然承载 domain object；
- 未来可以和真实 Python API 对齐；
- 便于人类 reviewer 进行代码审查。

这里选择 code 的核心目的不是执行，而是边界管理。自然语言的语法自由度太高，同一句话可能同时包含事实、转述、否定、条件、修辞和省略；而 code 的 class、call、keyword argument、list、dict 等结构可以被 AST 稳定切分。AI 在解释和维护这类对象时，不需要先猜测文本边界，而是可以直接面对清晰的字段、层级和引用关系。

因此，`.t2c.py` 的第一身份是 **AST-governed knowledge container**，不是普通 Python 程序。

但为了安全和可验证，最终系统不直接执行 `.t2c.py`，而是解析 AST 后转换为内部对象。

---

## 6. 核心数据模型

### 6.1 Document

Document 表示一个原始输入文档。

字段：

- `id`：稳定唯一 ID。
- `title`：文档标题。
- `source_type`：plain_text、pdf、html、markdown、transcript、image、table、code。
- `version`：文档版本。
- `content_hash`：原始内容 hash。
- `metadata`：来源、作者、时间、许可等扩展信息。

### 6.2 Block

Block 表示文档切分后的文本块。

字段：

- `id`；
- `doc_id`；
- `index`；
- `start`；
- `end`；
- `text_hash`；
- `metadata`。

Block 不一定是语义段落，可以是页、章节、自然段、句群或 token window。

### 6.3 EvidenceRef

EvidenceRef 是所有结构化知识的逃生舱。

字段：

- `block_id`；
- `start`；
- `end`；
- `quote_hash`；
- `quote_preview`；
- `role`：support、contradict、context、source_attribution；
- `confidence`。

规则：

- 每个 claim 必须至少有一个 support EvidenceRef。
- 每个 relation 必须至少有一个 support EvidenceRef，除非它是系统派生关系。
- EvidenceRef 的 `start` 和 `end` 必须落在对应 block 范围内。
- `quote_hash` 必须与原文切片匹配。

### 6.4 Entity

Entity 表示文本世界中的对象。

字段：

- `id`；
- `kind`：person、organization、location、object、concept、law、rule、document、unknown；
- `canonical_name`；
- `aliases`；
- `properties`；
- `evidence_refs`。

原则：

- Entity 不等于 Claim。
- Entity 的存在本身也需要证据。
- Entity 属性如果来自文本断言，应优先建模为 Claim，而不是直接塞进 properties。

### 6.5 Event

Event 表示发生或被描述为发生的事件。

字段：

- `id`；
- `kind`；
- `title`；
- `participants`；
- `time`；
- `location`；
- `state_before`；
- `state_after`；
- `evidence_refs`。

原则：

- Event 可以是不确定事件。
- Event 的真实性由关联 Claim 的 modality 和 polarity 表达。
- Event 本身可以作为 claim object。

### 6.6 State

State 表示某对象在某个时间或条件下的状态。

字段：

- `id`；
- `holder`；
- `attribute`；
- `value`；
- `time_scope`；
- `condition_scope`；
- `evidence_refs`。

适用场景：

- 人物位置；
- 合同状态；
- 权限状态；
- 角色关系；
- 情绪状态；
- 法律条文生效状态。

### 6.7 Claim

Claim 是 v3.0 的中心模型。

自然语言文本中的大量内容不是“事实”，而是“断言”。系统必须避免把断言直接升级成事实。

字段：

- `id`；
- `subject`；
- `predicate`；
- `object`；
- `modality`；
- `polarity`；
- `source`；
- `time_scope`；
- `condition_scope`；
- `confidence`；
- `evidence_refs`；
- `derived_from`；
- `status`。

`modality` 可选值：

- `asserted`：文本直接断言。
- `reported`：转述。
- `claimed_by_source`：某个来源声称。
- `inferred`：系统推断。
- `hypothetical`：假设。
- `conditional`：条件成立时成立。
- `uncertain`：不确定。
- `negated`：否定。
- `questioned`：被质疑。

`polarity` 可选值：

- `positive`；
- `negative`；
- `mixed`；
- `unknown`。

`status` 可选值：

- `candidate`；
- `validated`；
- `conflicted`；
- `rejected`；
- `superseded`。

示例：

```python
claim(
    id="claim.zhang_accuses_li",
    subject="ent.zhang",
    predicate="accuses",
    object={
        "subject": "ent.li",
        "predicate": "stole",
        "object": "obj.wallet"
    },
    modality="claimed_by_source",
    polarity="positive",
    source="ent.zhang",
    confidence=0.78,
    evidence_refs=[
        evidence(block_id="block.0001", start=50, end=82)
    ]
)
```

这表达的是“张三声称李四偷了钱包”，而不是“李四偷了钱包”。

### 6.8 Relation

Relation 表示两个对象之间的结构化关系。

字段：

- `id`；
- `source`；
- `target`；
- `predicate`；
- `qualifiers`；
- `evidence_refs`；
- `derived`。

常见 predicate：

- `participates_in`；
- `located_at`；
- `causes`；
- `depends_on`；
- `contradicts`；
- `supports`；
- `mentions`；
- `quotes`；
- `same_as`；
- `part_of`。

原则：

- 文本直接表达的关系需要 evidence。
- 系统推导的关系必须标记 `derived=True`，并记录 `derived_from`。

### 6.9 Rule

Rule 表示可执行或可检查的领域规则。

字段：

- `id`；
- `kind`；
- `description`；
- `scope`；
- `logic_ref`；
- `severity`；
- `evidence_refs`。

重要原则：

- `.t2c.py` 中不直接写任意规则代码。
- 规则逻辑由系统预注册的 validator 实现。
- `.t2c.py` 只能引用规则 ID 或 rule kind。

### 6.10 Conflict

Conflict 表示验证器发现的冲突。

字段：

- `id`；
- `kind`；
- `objects`；
- `rule_id`；
- `severity`；
- `message`；
- `evidence_refs`；
- `resolution_status`。

Conflict 可以进入审核队列，但不应自动吞掉原始候选知识。

### 6.11 WorldVersion

WorldVersion 支持多版本、多假设、多解释并存。

字段：

- `id`；
- `parent_id`；
- `name`；
- `included_objects`；
- `excluded_objects`；
- `assumptions`；
- `created_by`；
- `created_at`。

适用场景：

- 小说多解释；
- 案件假设推理；
- 法律条文不同解释；
- 历史材料互相冲突。

---

## 7. Knowledge Compiler

### 7.1 职责边界

Knowledge Compiler 的唯一职责是：

> 将 Evidence Block 编译为符合 Schema 的 Candidate JSON。

LLM 不允许：

- 直接写 `.t2c.py`；
- 直接写 Graph；
- 修改已有 Canonical Code；
- 根据 Graph 摘要生成新知识；
- 将已有 Code 转述成自然语言后再次生成 Code。

### 7.2 输入

Compiler 输入：

- 原始 block text；
- block id；
- block offset；
- schema；
- ontology；
- 已有对象 ID 列表；
- 可选上下文窗口；
- 可选术语表。

### 7.3 输出

Compiler 输出严格 JSON：

```json
{
  "entities": [],
  "events": [],
  "states": [],
  "claims": [],
  "relations": [],
  "rules": []
}
```

每个对象必须包含：

- `id` 或临时 ID；
- 类型字段；
- 内容字段；
- evidence refs；
- confidence；
- modality；
- polarity。

### 7.4 自修复机制

当 Candidate JSON 验证失败时，系统可以将结构化错误返回给同一个编译会话。

错误反馈只能包含：

- schema path；
- expected type；
- actual value；
- missing field；
- invalid reference；
- invalid evidence span；
- validator rule id；
- 简短机器可读说明。

禁止把失败 JSON 改写成自然语言摘要再重新生成。

---

## 8. Code Generator

### 8.1 职责

Code Generator 将 Candidate JSON 确定性转换为 `.t2c.py`。

LLM 不参与该步骤。

### 8.2 确定性要求

同一份 Candidate JSON 在同一 generator 版本下必须生成字节级稳定的 code，或至少 AST 级稳定的 code。

要求：

- 固定字段顺序；
- 固定缩进；
- 固定字符串转义规则；
- 固定 list 排序策略；
- 固定 object 排序策略；
- 固定 ID normalization；
- 固定空值表达方式。

### 8.3 Roundtrip

系统必须支持：

```text
Candidate JSON -> .t2c.py -> Parsed Object -> Canonical JSON
```

并检查 Canonical JSON 是否与输入等价。

---

## 9. Code Validator

### 9.1 验证总览

Code Validator 是认知防火墙的核心。

它至少包含十道检查：

1. Syntax Gate：Python AST 可解析。
2. Grammar Gate：只使用 `.t2c.py` 白名单语法。
3. Import Gate：只允许固定 DSL import。
4. Schema Gate：每个调用符合 Pydantic / JSON Schema。
5. ID Gate：ID 唯一、稳定、格式正确。
6. Reference Gate：引用对象存在。
7. Evidence Gate：所有必要对象带 evidence。
8. Span Gate：span 范围、hash、quote 校验。
9. Logic Gate：领域规则和跨对象一致性。
10. Rebuild Gate：Graph 可从 Code 成功重建。

### 9.2 Syntax Gate

检查：

- 文件可以被 `ast.parse()` 解析；
- 无非法编码；
- 无截断语法；
- 无 parse warning。

### 9.3 Grammar Gate

检查 AST 只包含：

- `Module`；
- `ImportFrom`；
- `Expr`；
- `Call`；
- `keyword`；
- `Constant`；
- `List`；
- `Dict`。

### 9.4 Import Gate

唯一允许：

```python
from t2c.dsl import doc, block, entity, event, state, claim, relation, rule, evidence
```

### 9.5 Schema Gate

每个 DSL 调用转换为内部 dict 后，用 schema 检查。

Schema 检查内容：

- required fields；
- type；
- enum；
- number range；
- string pattern；
- nested object；
- default values。

### 9.6 ID Gate

ID 规范：

```text
<type>.<namespace>.<slug>
```

示例：

- `doc.case_001`
- `block.case_001.0001`
- `ent.case_001.alice`
- `evt.case_001.arrival_001`
- `claim.case_001.arrival_001`
- `rel.case_001.alice_arrival`

检查：

- 全局唯一；
- 类型前缀匹配；
- 无空格；
- 无动态生成；
- 无不可见字符；
- slug 稳定。

### 9.7 Reference Gate

检查：

- `doc_id` 指向存在文档；
- `block_id` 指向存在 block；
- relation source / target 存在；
- event participants 存在；
- claim subject 存在或是合法 literal；
- rule scope 存在；
- derived_from 存在。

### 9.8 Evidence Gate

检查：

- Entity 至少有一个 evidence，除非是系统内部概念。
- Event 至少有一个 evidence。
- Claim 至少有一个 support evidence。
- Relation 至少有一个 evidence，除非 `derived=True`。
- Rule 如果来自文本，必须有 evidence。

### 9.9 Span Gate

检查：

- `start >= block.start` 或使用 block-local offset 时 `start >= 0`；
- `end > start`；
- `end <= block.end` 或 `end <= len(block_text)`；
- `quote_hash` 匹配；
- `quote_preview` 与原文切片一致；
- span 不跨越错误 block。

### 9.10 Logic Gate

第一批通用逻辑检查：

- 同一 ID 不能表示不同对象。
- `same_as` 不能连接不同 kind 的实体，除非有明确规则允许。
- 时间线冲突需要进入 Conflict。
- 互斥状态不能在同一 time_scope 同时为真。
- negative claim 不能被 graph builder 当成 positive relation。
- `claimed_by_source` 不能自动升级为 `asserted`。
- `hypothetical` 不能自动进入默认世界版本。
- `inferred` 必须有 `derived_from`。

### 9.11 Rebuild Gate

检查：

- 所有 validated code object 可以构建 graph；
- graph node 均能回指 code object；
- graph edge 均能回指 relation / claim / derived rule；
- graph 中不存在孤儿节点；
- graph 构建结果 hash 可记录。

---

## 10. CodeGraph 设计

### 10.1 定位

CodeGraph 是从 Canonical Code 派生出的有损索引。

它不是：

- 事实数据库；
- 证据仓库；
- 原文替代品；
- LLM 新知识写入目标。

它是：

- 搜索加速器；
- 多跳遍历结构；
- AI 理解辅助；
- 查询规划辅助；
- 可重建缓存。

### 10.2 图节点

Graph Node 可以来自：

- Entity；
- Event；
- State；
- Claim；
- Rule；
- Document；
- Block；
- Conflict；
- WorldVersion。

每个 graph node 必须包含：

- `graph_id`；
- `object_id`；
- `object_type`；
- `label`；
- `index_fields`；
- `code_ref`；
- `evidence_refs`；
- `derived_at`；
- `builder_version`。

### 10.3 图边

Graph Edge 可以来自：

- Relation；
- Claim subject-object projection；
- Event participant projection；
- Evidence support projection；
- Derived rule projection。

每条 edge 必须包含：

- `edge_id`；
- `source`；
- `target`；
- `predicate`；
- `source_object_id`；
- `derived`；
- `confidence`；
- `polarity`；
- `modality`；
- `evidence_refs`。

### 10.4 有损投影规则

Graph Builder 必须显式处理有损信息。

示例：

如果存在：

```text
Claim: Zhang claims Li stole wallet
modality = claimed_by_source
```

Graph 可以生成：

```text
Zhang --accuses--> Li
ClaimNode --mentions--> Li
ClaimNode --object_event--> StealEvent
```

但不能生成：

```text
Li --stole--> Wallet
```

除非存在独立的 asserted positive claim 支持。

### 10.5 Graph API

基础 API：

```python
graph.get_node(object_id)
graph.get_neighbors(object_id, predicate=None)
graph.find_nodes(kind=None, text=None, filters=None)
graph.find_claims(subject=None, predicate=None, object=None)
graph.find_events(participant=None, time_range=None, location=None)
graph.trace_path(source, target, max_depth=3)
graph.get_evidence_refs(object_id)
graph.fetch_code_object(object_id)
graph.fetch_evidence(ref)
```

原则：

- Graph API 返回的是候选路径和对象引用。
- 最终回答必须调用 evidence API 获取原文。

---

## 11. Agent 推理闭环

### 11.1 Planner 职责

Planner 接收用户问题，将问题转为查询计划。

Planner 可以：

- 搜索 graph；
- 拉取 code object；
- 拉取 evidence；
- 写查询脚本；
- 聚合结果；
- 标注不确定性。

Planner 不可以：

- 根据 graph 摘要生成新知识；
- 把 code 翻译成 text 后再生成 code；
- 绕过 validator 写入知识；
- 把无 evidence 的 graph path 当作结论。

### 11.2 查询脚本

Agent 生成的 Python 查询脚本也应运行在受限沙箱中。

允许：

- 调用只读 API；
- 遍历对象；
- 过滤；
- 聚合；
- 生成报告结构。

禁止：

- 文件写入；
- 网络访问；
- 任意 import；
- 修改 Knowledge Store；
- 直接执行系统命令。

### 11.3 回答生成

最终回答必须包含：

- 结论；
- 关键依据；
- evidence span 引用；
- 不确定性；
- 冲突提示；
- 查询路径摘要。

对于高风险领域，回答必须支持展开：

- 原文；
- code object；
- graph path；
- validator 状态；
- conflict 包。

---

## 12. 冲突与仲裁

### 12.1 冲突来源

冲突可能来自：

- 原文本身互相矛盾；
- LLM 编译错误；
- 实体消歧错误；
- 时间解析错误；
- 模态丢失；
- 规则检查失败；
- 多版本世界观差异。

### 12.2 冲突包

Conflict Package 包含：

- 冲突对象列表；
- 冲突规则；
- 严重程度；
- 相关 evidence；
- code diff；
- graph impact；
- 建议操作。

### 12.3 仲裁动作

人类或高级 Agent 可以：

- 接受新对象；
- 拒绝新对象；
- 修改对象；
- 合并对象；
- 标记同义；
- 降级为 uncertain；
- 移入独立 WorldVersion；
- 创建人工注释。

### 12.4 审核原则

仲裁不能覆盖原始 evidence。

任何人工修改都必须记录：

- 修改者；
- 修改时间；
- 修改原因；
- before / after；
- 影响对象；
- 影响 graph rebuild hash。

---

## 13. 版本管理

### 13.1 Text Version

原文版本变化会产生新的 document version。

如果原文 hash 变化，所有相关 span 必须重新校验。

### 13.2 Code Version

Canonical Code 应进入版本控制。

每次变更可以审查：

- 新增对象；
- 删除对象；
- 修改 evidence；
- 修改 modality；
- 修改 confidence；
- 修改 relation；
- 修改 rule 引用。

### 13.3 Graph Version

Graph 是派生结果，可以不手工版本化，但必须记录：

- source code commit；
- graph builder version；
- ontology version；
- build timestamp；
- graph hash。

### 13.4 Ontology Version

Ontology 变化可能导致旧 code 需要 migration。

系统应支持：

- schema migration；
- deprecated field；
- compatibility validator；
- migration report。

---

## 14. 可验证性指标

### 14.1 编译指标

- JSON schema 一次通过率；
- JSON 自修复通过率；
- Code generation roundtrip 通过率；
- AST grammar 通过率；
- evidence 覆盖率；
- span hash 通过率。

### 14.2 知识质量指标

- claim modality 保真率；
- entity resolution 准确率；
- relation precision；
- event time normalization 准确率；
- conflict detection recall；
- unsupported claim 数量。

### 14.3 推理指标

- graph 检索召回率；
- graph path precision；
- evidence-backed answer 比例；
- 多跳任务成功率；
- 高风险回答人工复核触发率。

### 14.4 可维护性指标

- `.t2c.py` diff 可读性；
- validator 错误可操作性；
- ontology migration 成功率；
- graph rebuild 时间；
- sandbox 查询脚本平均长度。

---

## 15. 安全边界

### 15.1 LLM 安全边界

LLM 被限制在三个位置：

1. Text -> Candidate JSON。
2. User Question -> Query Plan。
3. Evidence-backed Answer 表达。

LLM 不直接：

- 写最终 code；
- 写 graph；
- 绕过 evidence；
- 绕过 validator；
- 执行系统操作。

### 15.2 Code 安全边界

`.t2c.py` 不直接执行。

系统只解析 AST，并将白名单 DSL call 转换为内部对象。

### 15.3 Sandbox 安全边界

查询脚本沙箱：

- 只读；
- 限时；
- 限内存；
- 限 import；
- 限 API；
- 记录执行日志。

---

## 16. MVP 路线

### 16.1 Phase 0：规格定稿

目标：完成最小可实现规范。

交付：

- `t2c_design_v3.0.md`；
- `.t2c.py` grammar；
- 核心 schema；
- validator checklist；
- graph projection rules。

验收：

- 人类可以根据规范手写合法 `.t2c.py`；
- 可以明确判断一段 `.t2c.py` 是否非法。

### 16.2 Phase 1：无 LLM 纯代码闭环

目标：验证 Evidence -> Code -> Graph -> Query 的核心链路。

交付：

- Corpus Manager；
- `.t2c.py` parser；
- Code Validator；
- 内存 Knowledge Store；
- Graph Builder；
- 基础 Graph API；
- 示例文本和手写知识文件。

验收：

- 手写 `.t2c.py` 能通过 validator；
- graph 能从 code 重建；
- 查询能从 graph 回到 evidence；
- 任意结论能展示原文 span。

### 16.3 Phase 2：接入 LLM 编译器

目标：让 LLM 在严格约束下参与 Text -> Candidate JSON。

交付：

- schema-constrained compiler；
- JSON repair loop；
- JSON -> Code generator；
- 编译错误报告；
- 人工审核入口。

验收：

- 简单文本一次编译通过率 >= 80%；
- 修复后通过率 >= 90%；
- unsupported claim 自动拦截；
- modality 丢失可被测试集发现。

### 16.4 Phase 3：领域本体与逻辑验证

目标：让系统具备领域内自查能力。

交付：

- 时间线 validator；
- 状态互斥 validator；
- source attribution validator；
- entity resolution assistant；
- conflict package UI。

验收：

- 能发现同一角色同一时间互斥位置；
- 能区分“事实”和“某人声称”；
- 能将冲突打包给人工审核。

### 16.5 Phase 4：Agent Sandbox 推理

目标：支持复杂问题的 evidence-backed 多跳推理。

交付：

- Planner；
- 查询脚本生成；
- 只读 sandbox；
- answer citation；
- trace replay。

验收：

- 用户复杂问题能被拆成 graph/code/evidence 查询；
- 最终答案带证据；
- 查询过程可重放。

---

## 17. 推荐仓库结构

```text
text2code/
  spec/
    t2c_design_v3.0.md
    t2c_grammar.md
    t2c_schema.md
    graph_projection_rules.md

  t2c/
    __init__.py
    corpus.py
    dsl.py
    parser.py
    schema.py
    validator.py
    graph_builder.py
    graph_api.py
    sandbox.py
    compiler.py

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
    test_graph_builder.py
    test_evidence_roundtrip.py
```

---

## 18. 与 v2.1 的关键差异

### 18.1 真理源修正

v2.1 倾向于将 Unified Code-Graph 称作唯一事实源。

v3.0 修正为：

> Evidence 是证据源，Canonical Code 是规范化知识源，CodeGraph 是派生索引。

### 18.2 Claim 中心化

v2.1 以 Entity / Event / Relation 为主。

v3.0 将 Claim 放到中心，防止把“声称、否认、推测、假设、条件”误编译成事实。

### 18.3 受限代码 DSL

v2.1 使用 Python Class 实例代码作为 Code IR。

v3.0 明确 `.t2c.py` 是 Python 子集 DSL，只解析不执行，便于安全验证和 AI 自查。

### 18.4 Graph 有损声明

v2.1 强调 Code-Graph 推理。

v3.0 强调 Graph 是有损视图，所有结论必须回到 code object 和 evidence span。

### 18.5 可重建原则

v3.0 要求 Graph、索引和摘要 hint 都可从 Canonical Code 重建，避免派生层污染知识源。

---

## 19. 风险与待研究问题

### 19.1 Text 到 Code 的“不可能完全无损”

自然语言到结构化 code 不可能语义完全无损。

系统的应对方式不是承诺无损结构化，而是：

- 原文无损保存；
- 每个结构化判断带 evidence；
- 模态与不确定性显式建模；
- 高风险结论回到原文复核。

### 19.2 Evidence 粒度

span 太短会丢上下文，span 太长会降低精确性。

需要实验：

- claim-level span；
- sentence-level span；
- paragraph-level context span；
- source attribution span。

### 19.3 Ontology 过强与过弱

本体太弱，Graph 价值不足；本体太强，编译成本和迁移成本升高。

MVP 应采用小核心本体 + 可扩展 domain plugin。

### 19.4 LLM 编译稳定性

LLM 仍可能：

- 漏提 claim；
- 错配 evidence；
- 丢失 modality；
- 过度推断；
- 实体消歧错误。

因此必须使用测试集、validator 和人工审核闭环。

### 19.5 Code 可读性

`.t2c.py` 既要机器稳定，又要人类可读。字段排序、换行策略、注释策略需要规范化。

---

## 20. v3.0 总结

Text2Code v3.0 的核心不是“让 AI 把文本变成代码”这么简单，而是建立一套知识工程秩序：

- 原文必须被保留；
- 解释必须被规范；
- 代码必须可验证；
- 图谱必须承认自己有损；
- 推理必须能回证据；
- 冲突必须能被看见；
- 系统状态必须可重建。

最终目标是让 AI 面对长文本时，不再只依赖 prompt、摘要和 embedding，而是拥有一套接近软件工程的知识管理基础设施：

```text
Text is evidence.
Code is structured interpretation.
Graph is accelerated navigation.
Validation is the firewall.
Evidence-backed reasoning is the product.
```
