# Text2Code 测试标准化与量化评估策略

## 0. 目标

这份策略解决一个现实问题：

> 每次返工都跑完整测试太慢，会打断迭代节奏；但不跑测试又无法判断是否达标。

因此后续测试不采用“一律全量”的方式，而采用分层门禁：

```text
改动中：跑 smoke / 相关专项
提交前：跑 core
阶段回归：跑 regression
版本验收：跑 full + quality report
设计评审：输出量化指标
```

核心原则：

- 快速测试给迭代手感；
- 专项测试对应当前改动风险；
- 全量测试只在阶段验收时跑；
- 每次评审都要有可比较的数字；
- 测试失败要能指向具体哲学偏移，而不是只说 fail。

---

## 1. 测试分层

### 1.1 P0 Smoke

用途：

> 普通改动后的最快反馈。

覆盖：

- ontology；
- parser；
- codegen；
- claim safety。

命令：

```bash
./.venv/bin/python3 scripts/test_matrix.py smoke
```

适用场景：

- 改了 ontology 字段；
- 改了 parser/codegen；
- 改了 claim safety；
- 小范围重构后想马上知道有没有炸。

目标耗时：

```text
<= 3s
```

达标线：

```text
100% pass
0 collection error
```

### 1.2 P1 专项测试

用途：

> 改哪层，跑哪层。

专项 profile：

```bash
./.venv/bin/python3 scripts/test_matrix.py validator
./.venv/bin/python3 scripts/test_matrix.py textmap
./.venv/bin/python3 scripts/test_matrix.py graph
./.venv/bin/python3 scripts/test_matrix.py extractor
```

对应关系：

| 改动内容 | 必跑 profile |
| --- | --- |
| Validator / schema / reference / evidence | validator |
| Corpus / Segmenter / raw offset / hash | textmap |
| ObjectStore / Coverage / GraphBuilder / GraphAPI | graph |
| LLM prompt / response parse / candidate repair | extractor |

达标线：

```text
100% pass
0 collection error
```

### 1.3 P2 Core

用途：

> 非 LLM、非 e2e 的确定性核心回归。

命令：

```bash
./.venv/bin/python3 scripts/test_matrix.py core
```

覆盖：

- claim safety；
- codegen；
- corpus；
- coverage；
- graph；
- object store；
- ontology；
- parser；
- segmenter；
- validator。

当前基线：

```text
158 passed
约 1s 内
```

达标线：

```text
100% pass
duration 不应显著劣化
```

### 1.4 P3 Regression

用途：

> 非 extractor 的完整回归，包含真实文本 e2e。

命令：

```bash
./.venv/bin/python3 scripts/test_matrix.py regression
```

当前基线：

```text
177 passed
约 10s
```

适用场景：

- 一个任务完成后；
- v3.3/v3.4/v3.5 阶段评审；
- 改动影响多个模块；
- 需要复现之前“非 extractor 全绿”的基线。

达标线：

```text
100% pass
duration 不应显著劣化
```

### 1.5 P4 E2E

用途：

> 检查真实文本路径是否仍然能端到端工作。

命令：

```bash
./.venv/bin/python3 scripts/test_matrix.py e2e
```

适用场景：

- 改了 pipeline；
- 改了 segment offset/hash；
- 改了 coverage 规则；
- 改了 object store；
- 做版本验收。

达标线：

```text
100% pass
无明显耗时回退
```

### 1.6 P5 Full

用途：

> 最终验收，不用于每次小迭代。

命令：

```bash
./.venv/bin/python3 scripts/test_matrix.py full
```

当前风险：

`extractor` 由于 `anthropic` 顶层 import，可能导致 full 在 collection 阶段失败。

v3.3 必须修复这个问题，使 full 可以稳定收集和运行。

达标线：

```text
0 collection error
100% pass
```

---

## 2. 日常迭代协议

### 2.1 改动中

每完成一个小改动，跑：

```bash
./.venv/bin/python3 scripts/test_matrix.py smoke
```

如果改的是某个专项，再补跑对应 profile。

例：

```bash
./.venv/bin/python3 scripts/test_matrix.py validator
```

### 2.2 一个任务完成前

跑：

```bash
./.venv/bin/python3 scripts/test_matrix.py core
```

如果本次涉及 LLM extractor，再跑：

```bash
./.venv/bin/python3 scripts/test_matrix.py extractor
```

如果本次涉及 pipeline 或真实文本，补跑：

```bash
./.venv/bin/python3 scripts/test_matrix.py e2e
```

### 2.3 一个版本验收前

跑：

```bash
./.venv/bin/python3 scripts/test_matrix.py full --save reports/full.json
./.venv/bin/python3 scripts/quality_check.py
```

`quality_check.py` 用于真实知识文件质量评估，不替代 pytest。

---

## 3. 量化评估指标

每次评审至少输出以下指标：

```text
profile
status
duration_seconds
passed
failed
errors
skipped
collection_error_count
blocked_reason
```

版本评审额外输出：

```text
core_pass_rate
full_pass_rate
full_collection_status
duration_regression
quality_issue_count
reference_issue_count
grounding_issue_count
coverage_rate
unsafe_relation_count
evidence_hash_error_count
```

### 3.1 当前测试基线

当前已知基线：

```text
total_tests = 191
core_tests = 177
core_status = pass
core_duration = about 10s
blocked_extractor_tests = 14
full_status = fail_on_collection
full_blocker = missing anthropic
```

这个基线非常重要：后续评估不能只说“比之前好”，必须和这些数字对比。

### 3.2 达标等级

建议用四档：

| 等级 | 含义 | 标准 |
| --- | --- | --- |
| Red | 不能继续叠功能 | smoke fail 或 collection error |
| Yellow | 可局部迭代，不可验收 | smoke pass，但专项/core fail |
| Green | 可提交当前任务 | core pass，相关专项 pass |
| Release Green | 可版本验收 | full pass，quality 指标达标 |

### 3.3 v3.3 目标线

v3.3 是 Validation Hardening，因此目标线应该是：

```text
smoke = pass
validator = pass
core = pass
full = pass
reference_issue_count = 0
evidence_hash_error_count = 0
unsafe_relation_count = 0
```

不要用 coverage 100% 作为 v3.3 目标。

v3.3 的核心是“可验证”，不是“抽取很多”。

### 3.4 v3.4 目标线

v3.4 是 Near-Lossless Candidate Flow，因此目标线应该是：

```text
core = pass
extractor = pass
e2e = pass
high_value_residual_supported = true
ignore_segment_supported = true
uncovered_segments_explained = true
```

### 3.5 v3.5 目标线

v3.5 是 Graph Safety and Evidence Query，因此目标线应该是：

```text
graph = pass
e2e = pass
unsafe_relation_count = 0
raw_quote_replay_success_rate = 100%
reported_uncertain_negative_not_default_fact = true
```

---

## 4. 测试矩阵脚本

新增脚本：

```bash
scripts/test_matrix.py
```

支持 profile：

```text
smoke
validator
textmap
graph
core
regression
e2e
extractor
full
```

普通输出：

```bash
./.venv/bin/python3 scripts/test_matrix.py smoke
```

JSON 输出：

```bash
./.venv/bin/python3 scripts/test_matrix.py core --json
```

保存报告：

```bash
./.venv/bin/python3 scripts/test_matrix.py core --save reports/core.json
```

追加 pytest 参数：

```bash
./.venv/bin/python3 scripts/test_matrix.py validator -- -k reference
```

---

## 5. 测试和设计哲学的对应关系

| 设计哲学 | 主要测试 |
| --- | --- |
| Code 是 AST-governed typed declarations | parser, codegen |
| Raw Text 是最终证据源 | corpus, segmenter, validator |
| Code 是 90% 日常认知源 | validator, object_store, graph |
| Graph 是有损导航源 | graph, claim_safety |
| 不允许静默有损 | coverage, validator, e2e |
| LLM 只输出 candidate | extractor |

如果某次改动没有对应测试，说明测试设计需要补，不说明改动可以不测。

---

## 6. 后续需要补的测试

v3.3 必补：

- dangling `EvidenceRef.segment_id`；
- dangling `Claim.subject`；
- dangling `Claim.object`；
- dangling `Relation.claim_id`；
- dangling `Relation.subject/object`；
- dangling `Event.participants`；
- dangling `Residual.segment_id`；
- `EvidenceRef.quote_hash` mismatch；
- `EvidenceRef.start/end` out of range；
- invalid objects cannot enter ObjectStore/Pipeline。

v3.4 必补：

- extractor can parse Residual candidate；
- extractor can parse IgnoreSegment candidate；
- important unstructured info becomes Residual；
- repair loop removes invalid reference；
- repair loop removes unsafe relation。

v3.5 必补：

- reported claim does not create fact relation edge；
- uncertain claim does not create fact relation edge；
- negative claim does not create positive relation edge；
- Query API can replay raw quote from EvidenceRef；
- graph result includes route back to code/raw。

---

## 7. 返工方式

每次返工建议遵守：

```text
1. 先写或确认失败测试
2. 跑对应专项 profile
3. 修改实现
4. 跑 smoke
5. 跑对应专项 profile
6. 跑 core
7. 记录指标
```

如果某个问题只在 full/e2e 出现，不要每次都跑 full/e2e。

先定位它属于哪一层，然后把它缩小成一个专项测试。

这套策略的目的不是少测试，而是：

> 把慢测试变成验收工具，把快测试变成迭代工具。
