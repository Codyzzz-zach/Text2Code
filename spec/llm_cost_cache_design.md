# Text2Code LLM 成本与 Cache 命中设计

## 0. 目标

当前真实流程的主要成本来自 LLM 输出：

```text
Input tokens: 26,322
Output tokens: 223,974
耗时: 74 min
```

这说明瓶颈不是 AST、Validator、Graph，也不是本地 pipeline，而是：

1. prompt 被 batch 重复发送；
2. LLM 输出 canonical JSON 过长；
3. 同时抽取 Entity/Event/Claim/Relation/Residual/IgnoreSegment；
4. Relation 和 EvidenceRef 过早交给 LLM；
5. 缺少稳定 replay/cache；
6. max_tokens 上限过高，允许模型持续扩写。

本设计目标：

> 保持 Text2Code 设计哲学不变，但把 LLM 从“昂贵的全量结构化生成器”降级为“可缓存的紧凑语义候选生成器”。

不改变：

- Raw Text 是最终证据源；
- Knowledge Code 是日常认知源；
- `.t2c.py` 是 AST-governed typed object declarations；
- LLM 只输出 Candidate JSON；
- Validator 是入库门禁；
- Graph 只做派生索引。

改变：

- LLM 输出 compact candidate；
- Relation 由程序派生；
- EvidenceRef 的 start/end/hash 由程序定位；
- Residual 改为二阶段抽取；
- 所有 LLM batch 必须可 cache/replay。

---

## 1. Cache 设计

### 1.1 Cache 的目的

Cache 不是为了掩盖不稳定，而是为了让迭代可控：

```text
真实 LLM 调用 -> 保存 candidate response
后续开发 -> replay cached candidate
版本验收 -> 选择性 refresh
```

日常开发不应该重复跑全章 LLM。

### 1.2 Cache 命中粒度

Cache 粒度应该是 batch，不是整章。

原因：

- 一个章节可能有 9 个 batch；
- 修改其中一个 batch 的 prompt 或 segment，不应该废掉整章；
- 单 batch failure 可以隔离；
- 可做局部 refresh。

推荐 cache 文件：

```text
.t2c_cache/
  llm/
    v1/
      {cache_key}.json
```

`cache_key` 必须由确定性输入生成。

### 1.3 Cache Key

cache key 由以下字段 sha256 得出：

```json
{
  "cache_schema": "t2c-llm-cache-v1",
  "extractor_protocol": "compact-v1",
  "model": "MiniMax-M3",
  "prompt_version": "compact-main-v1",
  "doc_id": "hongloumeng",
  "chapter_num": 1,
  "chapter_title": "...",
  "batch_index": 4,
  "segment_ids": ["hongloumeng_seg_0001"],
  "segment_hashes": ["sha256:..."],
  "segment_text_hash": "sha256:...",
  "known_entity_map_hash": "sha256:...",
  "options": {
    "max_tokens": 8192,
    "thinking_budget": 1024,
    "temperature": 0
  }
}
```

必须进入 cache key：

- model；
- prompt_version；
- extractor_protocol；
- segment ids；
- segment hashes；
- known entity map hash；
- extraction options。

不应该进入 cache key：

- wall clock；
- api elapsed；
- token usage；
- request id；
- file path；
- batch retry count。

### 1.4 Cache Entry

cache value 保存完整可审计信息：

```json
{
  "cache_schema": "t2c-llm-cache-v1",
  "cache_key": "...",
  "created_at": "2026-06-05T...",
  "request": {
    "model": "...",
    "prompt_version": "...",
    "extractor_protocol": "compact-v1",
    "segments": [
      {"id": "...", "hash": "...", "text": "..."}
    ],
    "known_entities": {}
  },
  "response": {
    "raw_text": "...",
    "parsed_candidates": [],
    "stop_reason": "end_turn",
    "input_tokens": 0,
    "output_tokens": 0,
    "elapsed_sec": 0.0
  },
  "quality": {
    "parse_ok": true,
    "truncated": false,
    "recovered_partial": false
  }
}
```

### 1.5 Cache 模式

Extractor 支持四种模式：

```text
off           不读不写 cache
read_write    命中则读，未命中则调 LLM 并写入
read_only     只读 cache，未命中失败
refresh       忽略已有 cache，强制调 LLM 并覆盖
```

日常推荐：

```text
dev: read_only 或 read_write
ci: read_only
release: refresh 或 read_write
```

### 1.6 Cache Miss 策略

`read_only` 模式下 cache miss 必须明确失败：

```text
Cache miss for batch hongloumeng ch1 batch 4.
Run with cache_mode=read_write or refresh to populate cache.
```

不要自动调用 LLM。

---

## 2. Compact Candidate 协议

### 2.1 为什么压缩 Candidate

Candidate JSON 不是最终 code。

最终 code 仍由程序生成：

```text
Compact Candidate
  -> Program expand
  -> Ontology objects
  -> CodeGenerator
  -> .t2c.py
```

因此 Candidate 可以短，只要信息不丢失。

### 2.2 Compact 输出类型

LLM 第一阶段只输出：

```text
E = Entity candidate
EV = Event candidate
C = Claim candidate
I = IgnoreSegment candidate
```

暂时不让 LLM 输出：

```text
R = Relation
ER = EvidenceRef
```

Relation 由程序从 Claim 派生。

EvidenceRef 由程序根据 quote 定位并计算 hash。

Residual 放到第二阶段。

### 2.3 Compact Candidate 示例

```json
[
  {"t":"E","lid":"e1","n":"甄士隐","k":"person","a":["士隐"],"sid":["hongloumeng_seg_0009"],"q":["甄士隐"]},
  {"t":"C","s":"e1","p":"lives_in","o":"姑苏","m":"asserted","pol":"positive","sid":["hongloumeng_seg_0010"],"q":["姑苏"]},
  {"t":"EV","n":"甄士隐做梦","k":"occurrence","p":["e1"],"sid":["hongloumeng_seg_0015"],"q":["梦"]},
  {"t":"I","sid":"hongloumeng_seg_0001","r":"chapter title"}
]
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| t | candidate type |
| lid | local id，只在当前 batch 内有效 |
| n | name |
| k | kind |
| a | aliases |
| sid | segment ids |
| q | quote text，用于程序定位 evidence |
| s | subject local/global entity id |
| p | predicate 或 participants |
| o | object，可以是 entity id 或 literal |
| m | modality |
| pol | polarity |
| r | reason |

### 2.4 Program Expand

程序负责把 compact candidate 扩成 ontology objects：

```text
local id -> canonical entity id
quote -> EvidenceRef(start/end/hash)
Claim(asserted, positive, entity object) -> Relation
Ignore candidate -> IgnoreSegment
```

扩展失败时：

- 不编造；
- 记录 expansion error；
- 对相关 segment 标记 raw fallback 或 Residual 二阶段候选。

---

## 3. Relation 程序派生

### 3.1 派生规则

程序生成 Relation 的条件：

```text
Claim.modality == "asserted"
Claim.polarity == "positive"
Claim.subject 是 Entity.id
Claim.object 是 Entity.id
Claim 有 evidence_refs 或 source_segment_ids
```

否则不生成 Relation。

这样可以减少：

- LLM 输出 token；
- dangling relation；
- unsafe fact projection；
- Claim/Relation 不一致。

### 3.2 Graph 继续保持安全

GraphBuilder 仍然检查：

```text
claim.modality == asserted
claim.polarity == positive
claim.subject == relation.subject
claim.object == relation.object
has evidence
```

Relation 程序派生后，Graph safety 不是替代 validator，而是二次防线。

---

## 4. EvidenceRef 程序生成

### 4.1 LLM 不输出 offset/hash

LLM 最多输出 quote：

```json
{"sid":["seg1"],"q":["甄士隐"]}
```

程序负责：

1. 在 `Segment.text_slice` 中查找 quote；
2. 生成 `start/end`；
3. 计算 `quote_hash`；
4. 若 quote 多次出现，优先选择最短且唯一匹配；
5. 若找不到 quote，则退化为 `source_segment_ids`，并记录 warning。

### 4.2 不强求所有对象都有 EvidenceRef

短期策略：

- Entity/Claim/Event 尽量有 EvidenceRef；
- 找不到精确 quote 时保留 source_segment_ids；
- Validator 不因缺 EvidenceRef 失败；
- Coverage 对缺 EvidenceRef 但有 source_segment_ids 的对象仍可视为 covered；
- 质量报告统计 `evidence_ref_rate`。

---

## 5. Residual 二阶段抽取

### 5.1 不和主抽取混跑

主抽取阶段只处理：

```text
Entity / Event / Claim / IgnoreSegment
```

Residual 阶段只处理：

```text
uncovered segments
partial segments
validator failed segments
low evidence confidence segments
```

这样可以显著降低主抽取输出。

### 5.2 Residual Prompt 更短

Residual 阶段只问：

```text
这些 segment 是否包含高价值但无法安全结构化的信息？
如果有，输出 Residual candidate；如果没有，输出 []。
```

不要重复 Entity/Claim schema。

---

## 6. Token Budget

推荐默认：

```text
max_tokens = 8192
thinking_budget = 1024
batch_chars = 1200
temperature = 0
max_candidates_per_batch = 40
```

release 可提高：

```text
max_tokens = 12000
batch_chars = 1500
max_candidates_per_batch = 80
```

不建议默认 `max_tokens=32768`。

它避免截断，但会鼓励过长输出，且触发 streaming/超时复杂度。

---

## 7. 测试与验收

新增测试：

1. cache key 相同输入稳定一致；
2. segment hash 变化导致 cache miss；
3. prompt_version 变化导致 cache miss；
4. read_only cache miss 失败；
5. read_write cache miss 会写 cache；
6. compact candidate 可 expand 成 ontology objects；
7. quote 可生成 EvidenceRef；
8. Claim 可派生 Relation；
9. non-asserted/negative Claim 不派生 Relation；
10. residual stage 只处理指定 segment。

新增指标：

```text
cache_hit_count
cache_miss_count
cache_hit_rate
llm_calls
input_tokens
output_tokens
cost_estimate
candidate_count
expanded_object_count
evidence_ref_rate
derived_relation_count
residual_stage_segment_count
```

目标：

```text
dev cache_hit_rate >= 95%
release output_tokens <= 当前基线的 30%
full chapter elapsed <= 当前基线的 30%
quality reference_issue_count = 0
quality grounding_rate >= 85%
```

---

## 8. 推荐实现顺序

1. 新增 `LLMCache` 模块。
2. Extractor 加入 `cache_mode/cache_dir/prompt_version/extractor_protocol`。
3. 保存 raw response + parsed candidate 到 cache。
4. 新增 compact candidate parser/expander。
5. 将 Relation 改为程序派生。
6. 将 EvidenceRef 改为 quote 定位生成。
7. 将 Residual 改为第二阶段。
8. 降低默认 token budget。
9. `test_matrix.py` 增加 `cache` 和 `quality` profile。
10. 真实 LLM 全章只在 release profile 运行。

---

## 9. 取舍结论

应该保留的重：

- AST code；
- Validator；
- Evidence hash；
- Coverage；
- Graph safety。

应该砍掉的重：

- LLM 输出 canonical JSON；
- LLM 输出 Relation；
- LLM 输出 EvidenceRef offset/hash；
- 主抽取阶段同时输出 Residual；
- 日常开发重复跑真实全章 LLM；
- 默认 32768 max_tokens。

这套取舍不削弱设计哲学。

相反，它让设计更符合 Text2Code 的核心原则：

> LLM 负责语义候选，程序负责边界、证据、派生、验证和 code。
