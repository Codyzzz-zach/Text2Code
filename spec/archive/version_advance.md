# Text2Code 后续优化推进说明 version_advance

## 0. 文档定位

本文不是新的设计哲学，也不是替代 `t2c_design_v3.2-flash.md`。

本文只做一件事：

> 指导现有实现如何继续优化，使代码实现更忠实地承载 v3.2-flash 的设计哲学。

当前实现已经完成了核心骨架：

- Raw Text / Block / Segment 的基础链路；
- 受限 Python AST `.t2c.py` 解析；
- ontology constructor calls 形式的 Knowledge Code；
- schema validation；
- claim safety 的基础规则；
- coverage report 的基础推导；
- object store；
- derived graph；
- query API；
- 基础测试覆盖。

但当前实现距离“Code 作为 90% 日常最高信息源”还有三个关键差距：

1. Code 内部引用关系还没有被充分验证。
2. EvidenceRef 还没有被 span/hash 级验证。
3. Graph 投影还没有足够明确地区分“事实索引”和“候选/不确定索引”。

因此，后续优化的主线应该是：

```text
先补可验证性
  -> 再补近乎无损
  -> 再收紧 graph 投影
  -> 最后才扩展抽取能力和体验层
```

不要先做 UI、复杂 graph 推理、agent、插件或世界版本管理。

---

## 1. 最高优先级：把 Validator 做成系统可信边界

### 1.1 为什么先做 Validator

Text2Code 的核心不是“把 text 变成看起来像 code 的文本”，而是：

> 把自然语言信息放入可被程序证明边界、引用和证据的 code object 中。

Parser 目前已经能证明 `.t2c.py` 的语法边界：

- 只能 import ontology；
- 顶层只能是 constructor call；
- constructor 只能是白名单 ontology type；
- 只能使用 keyword args；
- value 只能是 literal/list/dict/nested constructor；
- 禁止赋值、函数、类、控制流、表达式执行。

这解决的是“code 形态可信”。

但还没有完全解决“code 内容可信”。

后续必须把 Validator 升级成进入 Object Store 之前的强制门禁。

### 1.2 Reference Validation 必须补全

当前 `_validate_references` 只检查 `Block/Segment.doc_id`，而且主要以 warning 形式出现。后续需要扩展为完整 ID 引用验证。

必须检查：

| 对象 | 字段 | 必须引用 |
| --- | --- | --- |
| Block | doc_id | Document.id |
| Segment | doc_id | Document.id |
| Entity | source_segment_ids | Segment.id |
| Entity | evidence_refs[].segment_id | Segment.id |
| Event | participants[] | Entity.id |
| Event | source_segment_ids | Segment.id |
| Event | evidence_refs[].segment_id | Segment.id |
| Claim | subject | Entity.id |
| Claim | object | Entity.id 或允许的 literal object 策略 |
| Claim | source | Entity.id 或 Claim.id，取决于 ontology 策略 |
| Claim | derived_from[] | Claim.id |
| Claim | source_segment_ids | Segment.id |
| Claim | evidence_refs[].segment_id | Segment.id |
| Relation | subject | Entity.id |
| Relation | object | Entity.id |
| Relation | claim_id | Claim.id |
| Relation | evidence_refs[].segment_id | Segment.id |
| Residual | segment_id | Segment.id |
| Residual | evidence_refs[].segment_id | Segment.id |
| IgnoreSegment | segment_id | Segment.id |
| IgnoreSegment | evidence_refs[].segment_id | Segment.id |

默认策略：

- 当前文件内存在 Document/Segment/Entity/Claim 时，悬空引用应为 error。
- 如果项目未来支持跨文件引用，需要显式传入 `external_index` 或 `ObjectStore` 作为解析上下文。
- 不允许静默接受未知 ID。

验收标准：

- 新增 dangling reference 测试；
- 每种核心对象至少有一个悬空引用失败用例；
- `validate_objects()` 和 `validate_string()` 行为一致；
- 通过验证的对象才能进入 Object Store。

### 1.3 EvidenceRef 必须做 span/hash 验证

`EvidenceRef` 是 Knowledge Code 与 Raw Text 之间最重要的桥。

后续 Validator 必须验证：

1. `EvidenceRef.segment_id` 存在；
2. `start >= 0`；
3. `end > start`；
4. `end <= len(segment.text_slice)`；
5. `segment.text_slice[start:end]` 的 hash 等于 `quote_hash`；
6. 如果存在 raw text，则 segment 本身也必须能回放到 raw text；
7. `source_segment_ids` 与 `evidence_refs[].segment_id` 的关系不能互相矛盾。

推荐 hash 策略：

```text
quote_hash = sha256(segment.text_slice[start:end])
segment.hash = sha256(segment.text_slice)
block.hash = sha256(block.text_slice)
document.raw_text_hash = sha256(raw_text)
```

注意：

- `EvidenceRef.start/end` 应该是相对于 segment 的 offset，而不是相对于 document 的 offset。
- `Segment.start_offset/end_offset` 才是相对于 document/raw text 的 offset。
- 如果未来需要字节级 offset，应另加字段，不要混淆字符 offset。

验收标准：

- 篡改 `quote_hash` 必须失败；
- 篡改 `start/end` 必须失败；
- `EvidenceRef` 指向不存在 segment 必须失败；
- `EvidenceRef` 超出 segment 边界必须失败；
- segment hash 正确但 evidence hash 错误时必须失败。

### 1.4 Validator 输出要能服务 AI 自查

错误信息不能只是 “invalid reference”。

推荐错误格式：

```text
Reference error in Claim (claim.xxx): subject 'ent.missing' not found in Entity ids
Evidence error in Entity (ent.xxx): evidence_refs[0] quote_hash mismatch for segment seg.xxx[3:8]
Claim safety error (claim.xxx): reported claim cannot produce Relation rel.xxx
```

目标是让 LLM 可以根据错误信息修复 Candidate JSON，而不是重新猜。

---

## 2. 第二优先级：补强 Text -> Code 的近乎无损机制

### 2.1 Residual 是必要机制，但不能泛滥

v3.2-flash 的原则是：

> Residual 只记录高价值异常，不记录所有未抽取文本。

当前 LLM extractor prompt 只要求 `Entity/Event/Claim/Relation`，这会让系统容易漏掉：

- 反讽；
- 暗示；
- 心理活动；
- 模糊因果；
- 复杂上下文；
- 重要但 ontology 暂时表达不了的信息；
- 可能被误投影成事实的信息。

后续需要让 LLM Candidate JSON 可以输出：

- `Residual`
- `IgnoreSegment`

但 Coverage 仍然必须由程序推导，不能由 LLM 输出。

### 2.2 LLM 只输出 Candidate JSON

保持当前大方向：

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

不要让 LLM 直接写 `.t2c.py`。

原因：

- `.t2c.py` 的价值来自 AST 边界；
- LLM 自由写 code 会破坏稳定格式；
- JSON -> Code 由程序生成，才能保证字段顺序、import、format、roundtrip 稳定；
- Candidate 失败后更容易做局部修复。

### 2.3 Extractor prompt 必须加入损耗声明

后续 prompt 不应该只问“抽取哪些对象”，还要问：

1. 哪些信息可以安全结构化为 Entity/Event/Claim/Relation；
2. 哪些重要信息不能安全结构化，应进入 Residual；
3. 哪些 segment 是页码、目录、格式噪声，可以建议 IgnoreSegment；
4. 所有对象必须引用已有 segment；
5. 所有语义对象尽量生成 EvidenceRef；
6. 不确定、转述、否定、条件信息不得生成 Relation fact edge。

推荐加入 prompt 约束：

```text
If information is important but cannot be safely represented as Entity/Event/Claim/Relation,
emit Residual instead of forcing it into a fact-like object.
```

中文版本：

```text
如果某段信息重要，但无法被安全表达为 Entity/Event/Claim/Relation，
请输出 Residual，不要强行结构化成事实。
```

### 2.4 Candidate 修复流程

当 Validator 失败时，不要直接丢弃整批结果。

推荐流程：

```text
Candidate JSON
  -> Validator errors
  -> LLM repair with errors + original candidate + relevant segment text
  -> Re-validate
  -> Max retry 2
  -> still fail: keep raw fallback + emit Residual if necessary
```

验收标准：

- 引用错误可被修复；
- evidence span/hash 错误可被程序重算或要求 LLM 重新定位；
- unsafe relation 可被移除；
- 无法修复时 segment 进入 raw fallback，不静默 covered。

---

## 3. 第三优先级：收紧 Graph 的哲学边界

### 3.1 Graph 只从 validated code 派生

Graph Builder 不能处理未验证对象。

推荐策略：

- Pipeline 层保证只有通过 Validator 的对象进入 Object Store；
- GraphBuilder 构建前可选执行 defensive validation；
- ObjectStore 可以记录 object 的 validation status；
- Graph 节点/边应保留 evidence_refs 或 source_segment_ids，方便回到 code/raw。

### 3.2 Relation edge 必须只来自安全 Claim

后续 graph 投影规则：

```text
Relation edge 可以进入 graph fact-like edge 的条件：
  claim_id 存在；
  claim.modality == "asserted"；
  claim.polarity == "positive"；
  claim subject/object 与 relation subject/object 一致；
  claim 有 evidence_refs 或 source_segment_ids；
  claim safety validator 通过。
```

否则：

- 不生成 fact-like relation edge；
- 或生成 `type="claim_index"` 的弱索引边；
- edge 上必须标记 modality/polarity；
- query API 不得默认把它当事实返回。

### 3.3 Event 不应无条件升级成事实

当前 Event 没有 modality/polarity 字段。

后续有两个选择：

方案 A：Event 保持轻量，只作为语义对象和导航节点，不直接当事实。

方案 B：给 Event 增加：

```python
modality: Literal["asserted", "reported", "claimed_by_source", "uncertain", "hypothetical", "conditional", "inferred"]
polarity: Literal["positive", "negative"]
```

推荐短期选择方案 A：

- 不急着扩 ontology；
- Event graph edge 只作为 participates_in navigation；
- 用户要事实判断时必须回到 Claim/Relation/Evidence。

中期如果事件推理成为核心需求，再引入 Event modality。

### 3.4 Query API 必须区分 evidence ref 与 raw quote

当前 `get_evidence()` 返回 evidence refs，这是对的，但不足以支持最终证据链。

后续应增加：

```text
get_evidence_refs(object_id)
get_raw_quotes(object_id)
get_answer_context(object_id)
```

其中：

- `get_evidence_refs` 返回结构化引用；
- `get_raw_quotes` 根据 segment/start/end 回放原文；
- `get_answer_context` 返回 code object + raw quote + coverage status + residual。

Graph API 不应直接把 graph edge 当最终答案证据。

---

## 4. 第四优先级：修复测试与依赖边界

### 4.1 当前测试状态

当前评审结果：

```text
总测试意图：191
核心可运行测试：177 passed
被 extractor 依赖阻断：14
完整 pytest：失败于 collection 阶段
失败原因：ModuleNotFoundError: No module named 'anthropic'
```

这说明核心非 LLM 路径较稳，但完整测试套件还不能作为 CI 信号。

### 4.2 extractor 依赖处理

推荐短期修复：

- `anthropic` 改为 lazy import；
- mocked tests 不应要求真实安装 anthropic；
- 如果用户真的调用 LLMExtractor，再提示缺依赖；
- 或在测试环境明确安装 project dependencies。

推荐错误信息：

```text
LLMExtractor requires the optional anthropic dependency. Install project dependencies or configure an extractor backend.
```

### 4.3 测试优先级

新增测试顺序：

1. Validator dangling reference tests；
2. EvidenceRef span/hash tests；
3. Claim/Relation projection safety tests；
4. Residual/IgnoreSegment extractor prompt parse tests；
5. GraphBuilder only projects safe relations；
6. Query API raw quote replay tests；
7. Full pipeline tests：raw text -> segment -> candidate -> code -> validate -> store -> graph -> quote。

不要先写 UI 测试。

---

## 5. 推荐版本路线

### 5.1 v3.3：Validation Hardening

目标：

> 让 `.t2c.py` 不仅语法正确，而且内部引用和证据边界可验证。

必须完成：

- 完整 reference validation；
- EvidenceRef span/hash validation；
- validate_objects 与 validate_string 行为统一；
- dangling reference 测试；
- evidence tamper 测试；
- ObjectStore 或 Pipeline 禁止保存 invalid objects。

不做：

- UI；
- agent；
- 复杂 graph 推理；
- 新 ontology 大扩展。

通过标准：

```text
pytest 全量可运行
Validator 新增错误场景覆盖
核心测试通过率 100%
extractor 测试不被依赖收集阻断
```

### 5.2 v3.4：Near-Lossless Candidate Flow

目标：

> 让 Text -> Code 的损耗被显式记录，而不是静默发生。

必须完成：

- LLM Candidate JSON 支持 Residual；
- LLM Candidate JSON 支持 IgnoreSegment；
- prompt 明确禁止强行事实化；
- Candidate repair loop；
- Coverage Report 把 residual/raw fallback 正确暴露；
- pipeline 对不可修复 segment 生成 raw fallback 状态。

通过标准：

```text
重要但不可结构化信息不会消失
uncertain/reported/negative 不会被错误投影为 Relation
Coverage 能准确显示 covered/partial/raw_only/ignored/uncovered
```

### 5.3 v3.5：Graph Safety and Evidence Query

目标：

> Graph 继续做有损导航，但不越权成为证据源或事实源。

必须完成：

- GraphBuilder 只从 validated objects 构建；
- Relation fact edge 只来自 asserted positive claim；
- 其他 claim 只作为 claim index；
- Event 只作为导航节点，或显式增加 modality；
- Query API 支持 raw quote 回放；
- answer context 包含 code object、evidence refs、raw quote、coverage、residual。

通过标准：

```text
Graph 查询结果能回到 code 和 raw
Graph 不默认返回 reported/uncertain/negative 为事实
用户答案可以展示证据链
```

### 5.4 v3.6：Pipeline Robustness

目标：

> 把流程从模块可用推进到端到端稳定。

必须完成：

- raw text -> document code -> segment code -> candidate JSON -> knowledge code -> validate -> store -> graph 全流程命令；
- 可重复运行；
- 输出稳定 diff；
- 失败时可定位到具体 object/field/evidence；
- 支持小规模真实文本回归集。

不做：

- 大规模性能优化；
- 多用户协作；
- agent 自主修改知识库。

---

## 6. 量化评审指标

后续每个版本都应该给出一组固定指标。

### 6.1 测试指标

```text
total_tests
passed_tests
failed_tests
blocked_tests
core_tests_pass_rate
full_suite_status
```

当前基线：

```text
total_tests = 191
passed_core_tests = 177
blocked_extractor_tests = 14
core_tests_pass_rate = 100%
full_suite_status = failed_on_collection
```

### 6.2 Spec Alignment Score

建议每次评审按以下维度打分：

| 维度 | 权重 | 说明 |
| --- | ---: | --- |
| AST Code Form | 15 | `.t2c.py` 是否保持受限 Python constructor calls |
| Raw Evidence Integrity | 20 | raw/block/segment/evidence hash 是否可回放 |
| Reference Integrity | 20 | 所有 ID 引用是否可验证 |
| Near-Lossless Coverage | 15 | residual/ignore/coverage 是否能揭示损耗 |
| LLM Boundary | 10 | LLM 是否只输出 candidate，不直接写 code/graph/fact |
| Graph Safety | 10 | graph 是否只做有损索引，不升级不确定事实 |
| Test Reliability | 10 | 测试是否完整可运行且覆盖关键失败模式 |

当前粗评：

```text
AST Code Form: 95
Raw Evidence Integrity: 70
Reference Integrity: 55
Near-Lossless Coverage: 72
LLM Boundary: 82
Graph Safety: 68
Test Reliability: 78
Overall: about 78/100
```

v3.3 的目标不是功能变多，而是把分数推进到：

```text
Raw Evidence Integrity >= 85
Reference Integrity >= 85
Test Reliability >= 90
Overall >= 85
```

### 6.3 Coverage 指标

每次真实文本评测应输出：

```text
total_segments
covered_segments
partial_segments
raw_only_segments
ignored_segments
uncovered_segments
requires_raw_fallback_count
high_residual_count
unsafe_relation_count
dangling_reference_count
evidence_hash_error_count
```

核心目标：

- 不追求 `covered_segments = 100%`；
- 追求 `uncovered_segments` 可解释；
- 追求 `requires_raw_fallback` 准确；
- 追求 `unsafe_relation_count = 0`；
- 追求 `dangling_reference_count = 0`；
- 追求 `evidence_hash_error_count = 0`。

---

## 7. 不要做的事

为了避免系统变臃肿，短期明确不做：

- 不做 Web UI；
- 不做复杂 Agent Sandbox；
- 不做 WorldVersion；
- 不做通用 Rule Engine；
- 不做复杂 graph reasoning；
- 不做 graph 到 code 的反向写入；
- 不让 LLM 直接写 `.t2c.py`；
- 不让 LLM 生成 Segment offset/hash；
- 不让 LLM 生成 Coverage Report；
- 不把 Graph 当最终证据源；
- 不追求所有自然语言都结构化；
- 不把 Residual 变成所有未抽取内容的垃圾桶。

这些能力不是永远不能做，而是当前阶段做了会稀释核心目标。

当前阶段的核心目标只有一个：

> 让 Knowledge Code 成为可验证、可回放、可审计的 90% 日常认知源。

---

## 8. 后续实现顺序建议

推荐具体执行顺序：

1. 修复 extractor 依赖导致的测试收集失败。
2. 为 Validator 增加完整 ID index。
3. 实现完整 dangling reference validation。
4. 实现 EvidenceRef span/hash validation。
5. 补齐 Validator 测试。
6. Pipeline/ObjectStore 层禁止 invalid objects 入库。
7. Extractor prompt 加入 Residual/IgnoreSegment。
8. GraphBuilder 收紧 Relation 投影规则。
9. Query API 增加 raw quote replay。
10. 增加端到端量化报告脚本。

每一步都应该伴随测试，不要把多个哲学层面的改动混在一个大改里。

---

## 9. 最终判断

当前实现没有偏离 Text2Code 的主方向。

它已经正确选择了：

- 受限 Python 子集；
- ontology instance constructor calls；
- AST 管理信息边界；
- raw text 作为最终证据；
- graph 作为派生索引；
- LLM candidate 而非 final fact。

但当前实现还偏弱在：

- 引用完整性；
- evidence 精确验证；
- residual 候选生成；
- graph 事实投影安全；
- 完整测试可运行性。

所以后续不是重做，而是加固。

最重要的下一版应该是 v3.3：

> Validation Hardening。

只要 v3.3 把引用和证据验证补严，这套系统就会从“有设计感的原型”进入“可信知识代码系统”的门槛。
