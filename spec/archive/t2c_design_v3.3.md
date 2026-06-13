# Text2Code 设计说明书 v3.3

## 0. 版本定位

v3.3 是一次产品核心逻辑重定义。

此前 v3.2/v3.4 系列的实现重点逐渐偏向：

```text
Raw Text
  -> LLM semantic extraction
  -> Candidate objects
  -> Validator
  -> Internal graph
```

这个方向能做知识抽取，但没有充分实现最初目标：

> 把 text 转为 code，使 text 成为可以被开源社区 codegraph/code intelligence 工具管理的代码资产。

v3.3 重新定义产品：

> Text2Code 是一个 Text-to-Code Compiler。它把原始文本编译成 codegraph-manageable Knowledge Code，使文本信息进入代码生态的 AST、symbol、reference、diff、index、query、review、refactor 工具链。

v3.3 不把“内部 graph”作为核心产品。

v3.3 的核心产品输出是：

```text
Knowledge Code Repository
```

而不是：

```text
LLM 生成的语义 JSON
内部自建 Graph
普通 RAG 索引
```

---

## 1. 不变的核心哲学

### 1.1 Raw Text 是最终证据源

Raw Text 仍然是 100% 最终证据源。

任何 Code、Graph、Summary、Claim 都不能取代 Raw Text。

### 1.2 Code 是 90% 日常认知源

Code 承担日常查询、索引、AI 读取、人工 review、diff 和结构化管理。

但 Code 不是自然语言原文的替代品。

Code 必须能稳定回到 Raw Text。

### 1.3 CodeGraph 是管理层，不是证据层

v3.3 里，Graph 的核心位置发生变化。

Graph 不再优先指内部自建 graph。

Graph 优先指开源代码生态中的 codegraph/code intelligence 能力，例如：

- AST；
- symbol definitions；
- references；
- imports；
- module graph；
- call/reference graph；
- SCIP/Kythe/CodeQL/tree-sitter 等工具可消费的结构。

Text2Code 的核心目标是让文本信息进入这些工具可管理的代码形态。

### 1.4 只接受结构化导致的损失

Text2Code 不承诺自然语言到语义对象完全无损。

但 v3.3 明确区分两种损失：

#### 可接受损失

高度结构化时必然产生的语义损失，例如：

- 把复杂语气压缩为 modality；
- 把模糊关系压缩为 Claim；
- 把多义表达归入 Residual；
- 把上下文暗示标记为需要 raw fallback。

#### 不可接受损失

架构造成的损失，例如：

- 原文片段没有稳定 code symbol；
- reference 只是字符串，codegraph 无法识别；
- LLM 没输出对象，segment 就消失；
- repair 删除对象但不留下损耗记录；
- cache/replay 覆盖了错误输出；
- internal graph 替代了可被开源 codegraph 工具读取的 code。

v3.3 的目标是：

> 损失只能发生在语义压缩层，不能发生在 Text-to-Code 基础映射层。

---

## 2. 当前实现审核

### 2.1 当前实现已完成的部分

当前代码已经有价值：

- parser 能限制 `.t2c.py` 的 AST 语法；
- codegen 能稳定生成 ontology constructor calls；
- validator 已经开始检查 reference 和 evidence；
- graph_builder 已经区分 `fact` 和 `claim_index`；
- extractor 已支持 cache、compact candidate、partial recovery；
- test matrix 已能快速跑全量测试。

当前测试结果：

```text
full: 298 passed, 4 skipped
```

工程基础可以保留。

### 2.2 当前实现的核心偏移

#### 偏移 1：Knowledge Code 不是 codegraph-native

当前 `.t2c.py` 的核心形态接近：

```python
Entity(...)
Claim(...)
Segment(...)
```

这种 top-level constructor call 能被自定义 parser 识别，但对通用 codegraph 工具不够友好。

原因：

- 没有稳定的 Python symbol definition；
- codegraph 很难把每个 Entity/Segment/Claim 当成可导航对象；
- string id 不是真实 code reference；
- `subject="hongloumeng_ent_0001"` 对 codegraph 来说只是字符串，不是符号引用；
- `source_segment_ids=["hongloumeng_seg_0001"]` 也只是字符串，不是到 segment symbol 的引用。

这会导致：

```text
Text2Code 自己能读
开源 codegraph 工具不能充分管理
```

这不符合产品目标。

#### 偏移 2：内部 graph 抢占了产品核心

当前实现越来越像：

```text
文本 -> LLM 语义抽取 -> 内部 graph/query API
```

但目标应该是：

```text
文本 -> codegraph-manageable code -> 外部 codegraph 工具管理
```

内部 graph 可以保留为派生产物，但不能成为产品主轴。

#### 偏移 3：LLM 承担了过多结构化工作

当前 LLM 仍承担：

- entity selection；
- event selection；
- claim generation；
- residual 判断；
- ignore 判断；
- quote selection；
- 跨 batch entity coherence；
- 某些 reference 决策。

这导致：

- 成本高；
- 速度慢；
- 质量不稳定；
- grounding 低；
- cross-chapter entity 冲突；
- 修复流程依赖删除对象。

v3.3 需要把“可以程序化的结构化”从 LLM 手里拿回来。

#### 偏移 4：质量测试暴露真实产物不可用

当前 `quality_check.py` 结果显示：

```text
第 1 回 grounding 命中率: 11%
第 2 回 reference issues: 42
第 3 回 reference issues: 5
跨章实体冲突: 10
总质量问题: 126
```

这说明：

```text
pytest pass != 产品达标
```

v3.3 必须把质量门禁纳入产品定义。

---

## 3. CodeGraph vs TextGraph

### 3.1 CodeGraph 管理 Knowledge Code

CodeGraph 路径：

```text
Raw Text
  -> Knowledge Code
  -> AST / symbols / references / code index
  -> codegraph tools
```

优势：

- 可以复用开源代码生态工具；
- AST 边界稳定；
- symbol definition / reference 可被索引；
- diff、review、branch、commit、CI 都天然可用；
- AI 更擅长读写标准化 code；
- code format 可以被 parser、linter、validator 机械检查；
- 知识对象可以作为代码符号被查找、跳转、引用；
- 代码仓库本身就是可演化知识库。

劣势：

- 必须把文本设计成代码符号；
- code 结构设计不当会让 codegraph 工具看不懂；
- 不能只靠 string id；
- 代码文件会变大；
- 自然语言 nuance 仍需要 raw fallback；
- 需要维护 grammar/schema/codegen 规范。

结论：

> CodeGraph 路径适合你的目标，因为你要的是可演化、可验证、可被代码生态管理的长期知识库。

### 3.2 直接从 Text 生成 TextGraph

TextGraph 路径：

```text
Raw Text
  -> embedding / extraction / graph triples
  -> custom graph database
```

优势：

- 初期实现快；
- 不需要生成代码；
- graph schema 可以灵活定制；
- 适合快速 RAG；
- 对短期问答成本较低。

劣势：

- graph 是有损抽取；
- graph 容易被误当证据源；
- LLM 抽取错误会直接污染 graph；
- 缺少通用 code review / refactor / symbol navigation 工具；
- diff 很难解释；
- reference 多半是字符串或数据库边；
- AI 修改 graph 的可审计性弱；
- 很容易变成定制 RAG，而不是 Text-to-Code 产品。

结论：

> TextGraph 适合快速问答，不适合作为你的核心产品主线。

### 3.3 v3.3 判断

v3.3 选择：

```text
CodeGraph-first
TextGraph-derived
```

也就是说：

- 先生成 codegraph-manageable code；
- 再从 code 派生 graph；
- graph 只能加速搜索和理解；
- graph 不作为证据源；
- graph 不反向污染 code。

---

## 4. v3.3 的 Code 形态

### 4.1 关键变化

v3.2 的 Knowledge Code：

```python
Entity(id="hongloumeng_ent_0001", ...)
Claim(subject="hongloumeng_ent_0001", ...)
```

v3.3 的 Knowledge Code：

```python
ent_zhen_shiyin = Entity(
    id="hongloumeng_ent_0001",
    name="甄士隐",
    evidence=[seg_0009],
)

claim_zhen_lives_in_gusu = Claim(
    subject=ent_zhen_shiyin,
    predicate="lives_in",
    object=loc_gusu,
    modality="asserted",
    evidence=[seg_0010],
)
```

核心区别：

| v3.2 | v3.3 |
| --- | --- |
| top-level constructor call | symbol assignment |
| string ids | symbol references |
| internal parser 友好 | external codegraph 友好 |
| graph 自己建 | codegraph 工具可索引 |
| LLM 输出接近 canonical object | 程序生成 codegraph-native code |

### 4.2 v3.3 受限 Python 子集

v3.3 仍然使用受限 Python。

但语法从“只允许 constructor call”升级为：

```text
file          ::= import* assignment*
assignment    ::= symbol "=" constructor_call
constructor   ::= TypeName "(" keyword_arg* ")"
value         ::= literal
                | list[value]
                | dict[literal, value]
                | constructor_call
                | symbol_ref
symbol_ref    ::= previously_defined_symbol
```

允许：

- import ontology types；
- assignment；
- constructor call；
- keyword args；
- list/dict；
- nested EvidenceSpan；
- symbol references。

禁止：

- function definition；
- class definition；
- control flow；
- arbitrary expression；
- function call other than ontology constructors；
- attribute access；
- mutation；
- comprehension；
- lambda；
- exec/eval/import side effects。

### 4.3 为什么必须用 symbol references

如果使用字符串：

```python
Claim(subject="hongloumeng_ent_0001")
```

codegraph 工具只能看到一个 string。

如果使用 symbol：

```python
Claim(subject=ent_zhen_shiyin)
```

codegraph 工具可以看到：

- `ent_zhen_shiyin` 的定义；
- `ent_zhen_shiyin` 的引用；
- 引用分布；
- rename/refactor 可能性；
- module import relation；
- cross-file reference。

这正是 Text2Code 选择 code 而不是 JSON/text graph 的关键。

### 4.4 Text-as-Code 层必须近乎无损

v3.3 把 code 分成两层：

```text
Text Code Layer
Semantic Code Layer
```

#### Text Code Layer

程序自动生成，尽量无损。

示例：

```python
doc_hongloumeng_ch01 = Document(
    id="hongloumeng_ch01",
    raw_hash="sha256:...",
    title="第一回 甄士隐梦幻识通灵 贾雨村风尘怀闺秀",
)

seg_0009 = Segment(
    id="hongloumeng_seg_0009",
    doc=doc_hongloumeng_ch01,
    start=128,
    end=156,
    text="甄士隐住在姑苏城中。",
    text_hash="sha256:...",
)
```

要求：

- 每个 segment 都是一个 code symbol；
- segment symbol 保存原文切片；
- segment 有 start/end/hash；
- segment 能回放到 raw text；
- segment symbol 可被 codegraph 索引。

这一层不允许 LLM 写。

#### Semantic Code Layer

AI 候选 + 程序生成。

示例：

```python
ent_zhen_shiyin = Entity(
    id="hongloumeng_ent_0001",
    name="甄士隐",
    kind="person",
    aliases=["士隐"],
    evidence=[
        EvidenceSpan(segment=seg_0009, quote="甄士隐"),
    ],
)
```

要求：

- AI 可以提出 entity/claim/event 候选；
- 程序生成 canonical symbol；
- evidence 使用 segment symbol；
- quote offset/hash 由程序生成；
- relation 由程序派生；
- validator 检查所有 symbol ref。

---

## 5. 文件布局

v3.3 推荐生成一个标准代码包：

```text
knowledge_repo/
  pyproject.toml
  knowledge/
    __init__.py
    hongloumeng/
      __init__.py
      ch01/
        __init__.py
        text.py        # Document / Block / Segment symbols, program generated
        entities.py    # Entity symbols
        claims.py      # Claim symbols
        events.py      # Event symbols
        residuals.py   # Residual / IgnoreSegment symbols
        derived.py     # program-derived Relation symbols
```

### 5.1 text.py

只由程序生成。

包含：

- Document；
- Block；
- Segment；
- exact text slice；
- offset；
- hash。

### 5.2 entities.py / claims.py / events.py

AI 输出 candidate。

程序负责：

- symbol naming；
- id assignment；
- evidence span；
- codegen；
- validation。

### 5.3 derived.py

只由程序生成。

包含：

- Relation；
- coverage report；
- any derived index hints。

AI 不写 derived.py。

---

## 6. AI 与程序的职责边界

### 6.1 程序必须负责

| 工作 | 原因 |
| --- | --- |
| raw text 保存 | 证据源不能被 AI 改写 |
| block/segment 切分 | offset/hash 必须可重放 |
| Text Code Layer 生成 | 近乎无损，必须确定性 |
| symbol naming | codegraph 稳定性 |
| id assignment | 引用一致性 |
| quote offset/hash | 程序更可靠 |
| Relation 派生 | 可机械判定 |
| Coverage | 损耗账本，不能靠 AI |
| Parser/Validator | 可信边界 |
| Graph/index 派生 | 必须可重建 |

### 6.2 AI 可以负责

AI 只负责语义判断：

| 工作 | 输出 |
| --- | --- |
| Entity candidate | name/kind/alias/segment/quote |
| Event candidate | name/kind/participants/segment/quote |
| Claim candidate | subject/predicate/object/modality/polarity/segment/quote |
| Residual candidate | category/importance/reason/segment |
| Ignore suggestion | segment/reason |

AI 不直接写：

- `.py` Knowledge Code；
- Segment；
- offset/hash；
- Relation；
- Coverage；
- Graph；
- final fact。

### 6.3 让 AI 写得快且质量高

v3.3 不要求 AI 输出完整 code。

AI 输出 compact candidate：

```json
[
  {"t":"E","lid":"e1","n":"甄士隐","k":"person","sid":["seg_0009"],"q":["甄士隐"]},
  {"t":"C","s":"e1","p":"lives_in","o":"姑苏","m":"asserted","pol":"positive","sid":["seg_0010"],"q":["姑苏"]}
]
```

程序再做：

```text
compact candidate
  -> symbol resolution
  -> evidence span
  -> ontology object
  -> codegraph-native code
  -> validator
```

这样 AI 快，因为：

- 输出短；
- 不写 hash；
- 不写 relation；
- 不写 code；
- 不维护全局 ID；
- 不处理 coverage。

质量高，因为：

- 程序负责稳定结构；
- validator 负责失败；
- codegraph 负责引用可见；
- raw text 负责最终证据。

---

## 7. Pipeline v3.3

```text
Raw Text
  -> Corpus Manager
  -> Program Segmenter
  -> Text Code Generator
  -> Text Code Parser/Validator
  -> AI Compact Semantic Candidate
  -> Program Candidate Expander
  -> Semantic Code Generator
  -> AST + Symbol Validator
  -> CodeGraph Index
  -> Derived Graph / Query API
```

### 7.1 Text Code 先行

v3.3 必须先生成 Text Code Layer。

如果 Text Code Layer 没有成功，不能进入 AI 抽取。

原因：

- AI 必须引用 segment symbols；
- evidence 必须基于 segment symbols；
- codegraph 必须先能看到原文结构。

### 7.2 Semantic Code 后置

AI 不直接面对 raw 文本全文。

AI 面对的是：

```text
segment symbol + segment text + local context
```

例如：

```text
[seg_0009] 甄士隐住在姑苏城中。
```

AI 输出 candidate 后，程序把 `seg_0009` 转成 code symbol ref。

### 7.3 Graph 后置

Graph 从 code 派生。

v3.3 不允许：

```text
AI -> graph
graph -> code
```

只允许：

```text
code -> graph
```

---

## 8. Validator v3.3

Validator 不只验证 schema。

必须验证：

1. AST grammar；
2. symbol assignment；
3. symbol reference 存在；
4. reference type 正确；
5. segment text hash；
6. segment raw replay；
7. evidence quote 能定位；
8. evidence quote_hash 正确；
9. claim safety；
10. derived relation 是否可解释；
11. coverage 是否完整报告；
12. no silent loss。

### 8.1 no silent loss

每个 segment 必须处于一种状态：

```text
covered
partial
raw_only
ignored
uncovered
```

`uncovered` 不是一定错误，但必须显式出现在 Coverage Report。

不允许：

```text
segment 没有语义对象
没有 residual
没有 ignore
coverage 不记录
```

---

## 9. 质量门禁

v3.3 的质量门禁不是只跑 pytest。

必须同时输出：

```text
full pytest status
text_code_validation_status
symbol_reference_status
quality grounding rate
reference issue count
cross-chapter entity conflict count
coverage status counts
evidence_ref_rate
cache_hit_rate
llm token usage
```

最低验收线：

```text
pytest full: pass
Text Code Layer validation: pass
symbol references: 0 error
reference issues: 0
evidence hash errors: 0
grounding rate >= 85%
coverage report generated
silent loss count = 0
```

---

## 10. 实现迁移路线

### Phase 1：CodeGraph-native Code Form

目标：

> 让每个 knowledge object 成为 code symbol。

任务：

- 修改 codegen：top-level call -> assignment；
- 修改 parser：支持 assignment；
- 修改 parser：支持 symbol ref；
- 修改 validator：验证 symbol ref 类型；
- 生成 `text.py`，每个 Segment 都是 symbol；
- 生成 `entities.py/claims.py/events.py/derived.py`。

### Phase 2：Text Code Layer 近乎无损

目标：

> 原文 segment 全部进入 code symbol。

任务：

- 每个 segment 保存 exact text；
- offset/hash 校验；
- raw replay；
- codegraph 可索引 segment symbol；
- coverage 基于 segment symbol。

### Phase 3：AI Compact Candidate

目标：

> AI 只输出语义候选，不写 code。

任务：

- AI 输出 compact candidate；
- 程序做 symbol resolution；
- quote -> evidence；
- relation derivation；
- candidate failure -> residual/coverage。

### Phase 4：CodeGraph Integration

目标：

> 验证开源 codegraph 工具能管理 Knowledge Code。

任务：

- tree-sitter parse pass；
- Python AST parse pass；
- optional SCIP/Pyright/Sourcegraph index；
- symbol definition count；
- symbol reference count；
- find references for segment/entity/claim symbol。

### Phase 5：Quality Gate

目标：

> 质量指标进入验收门禁。

任务：

- quality_check 输出 JSON；
- test_matrix 增加 quality profile；
- grounding/reference/coverage/evidence 指标门槛；
- 每次版本评审输出量化结果。

---

## 11. v3.3 的一句话

v3.3 的核心不是：

> 用 LLM 把文本抽成 graph。

而是：

> 用程序把文本编译成 codegraph-manageable code，再让 AI 在这个 code 边界内补充语义。

这才是 Text2Code。

