# T2C Pipeline 优化：DeepSeek 接入 + 缓存命中 + 架构精简

## TL;DR
> **Summary**: 将 LLM 后端从 MiniMax-M3 切换到 DeepSeek-v4-flash，通过 prompt 前缀固定化命中 DeepSeek 上下文硬盘缓存（1/50 价格），增大 batch 降低固定开销，精简无用设计。
> **Deliverables**: DeepSeek provider 预设 + prompt 结构重构 + batch 策略优化 + 3 个精简项
> **Effort**: Medium
> **Parallel**: YES - 5 waves
> **Critical Path**: Task 1 → Task 2 → Task 3（DeepSeek 接入先于 prompt 重构先于测试）

## Context

### Original Request
用户要求：1) 接入 DeepSeek-v4-flash 作为测试模型；2) LLM 缓存不止本地磁盘，还要命中 LLM 侧的上下文缓存；3) 拆细优化项，每项说清现状→改什么→怎么实现。

### Interview Summary
- MiniMax-M3 费用：$3/M input, $15/M output，无显式缓存折扣
- DeepSeek-v4-flash 费用：1元/M input（miss），0.02元/M input（hit），2元/M output
- DeepSeek 缓存命中 = 未命中的 **1/50**
- DeepSeek 支持 Anthropic API 格式，base_url = `https://api.deepseek.com/anthropic`
- DeepSeek 缓存机制：**前缀匹配**，公共前缀自动落盘，无需代码改动即可生效
- 但要最大化命中率，需要 prompt 前缀结构对齐

### 当前瓶颈分析

**成本结构（ch10 实际数据）：**
| 项 | MiniMax | DeepSeek（无缓存命中） | DeepSeek（50% 缓存命中） |
|---|---|---|---|
| Input tokens | 11,687 | 11,687 | 50% hit: 5,844×1 + 5,844×0.02 |
| Input cost | $0.035 | ¥0.012 ($0.0017) | ¥0.006 ($0.0009) |
| Output tokens | 46,451 | ~46,451 | ~46,451 |
| Output cost | $0.697 | ¥0.093 ($0.013) | ¥0.093 ($0.013) |
| **Total** | **$0.76** | **$0.015** | **$0.014** |

DeepSeek 即使 0% 缓存命中，成本也是 MiniMax 的 **1/50**。

**当前 prompt 结构问题：**
```
COMPACT_PROMPT = "你是一个文学文本结构化专家。从以下《红楼梦》第{chapter_num}回「{chapter_title}」的文本中提取...

## 输入文本
[segments...]          ← 每个 batch 不同，破坏前缀匹配

## 已知人物
[existing_entities...] ← 每个 batch 不同，进一步破坏匹配
```

5 个 batch 的 prompt 前缀在第 1 行就分叉了（因为 chapter_num/chapter_title 在开头），导致 DeepSeek 缓存 **完全无法命中**。

## Work Objectives

### Core Objective
切换到 DeepSeek-v4-flash，通过 prompt 结构重构让每个 batch 的公共前缀最大化，实现 DeepSeek 上下文缓存命中，同时精简架构中低价值设计。

### Deliverables
1. DeepSeek provider 预设（`llm_config.py` + `.env`）
2. Prompt 结构重构：固定前缀 + 可变后缀
3. Batch 策略优化：`_MAX_BATCH_CHARS` 从 1200 → 4000
4. IgnoreSegment 输出砍掉
5. Repair Loop 简化

### Definition of Done
- `python3 scripts/extract_ch10_v4.py` 使用 DeepSeek-v4-flash 跑通
- API 返回 `prompt_cache_hit_tokens > 0`
- 总成本 < ¥0.05（对比 MiniMax 的 $0.76）
- 段覆盖率 ≥ 31.6%（不低于 MiniMax 基线）

### Must Have
- DeepSeek provider 预设
- Prompt 前缀固定化（命中 API 缓存）
- Batch 增大
- 端到端测试通过

### Must NOT Have
- 不改变 compact-v1 协议本身（expand 逻辑不动）
- 不改变 CodeGen 输出格式
- 不改变本地 LLMCache 机制
- 不动 ontology.py / schema.py

---

## Verification Strategy
- Test decision: tests-after（现有 412 tests 必须全部通过）
- QA policy: 每个 task 有 agent-executed 场景
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.{ext}`

---

## Execution Strategy

### Parallel Execution Waves

**Wave 1**: Task 1（DeepSeek 接入 — 基础设施）
**Wave 2**: Task 2（Prompt 前缀固定化）+ Task 4（砍 IgnoreSegment）+ Task 5（简化 Repair）— 互相独立
**Wave 3**: Task 3（Batch 增大 — 依赖 Task 2 的 prompt 重构）
**Wave 4**: Task 6（端到端测试 — 依赖全部）

### Dependency Matrix
```
Task 1 (DeepSeek preset)
  ↓
Task 2 (Prompt refactor)  ← 依赖 Task 1 验证 API 可用
Task 4 (Kill Ignore)      ← 独立
Task 5 (Simplify Repair)  ← 独立
  ↓
Task 3 (Batch resize)     ← 依赖 Task 2 的新 prompt 结构
  ↓
Task 6 (E2E test)         ← 依赖全部
```

### Agent Dispatch Summary
- Wave 1: 1 task (quick)
- Wave 2: 3 tasks (2 quick + 1 medium)
- Wave 3: 1 task (quick)
- Wave 4: 1 task (deep)

---

## TODOs

- [ ] 1. 接入 DeepSeek-v4-flash Provider 预设

  **现状**：`llm_config.py` 的 `_PROVIDER_PRESETS` 只有 minimax/anthropic/openai 三个预设。当前使用 MiniMax-M3，走 Anthropic SDK + `https://api.minimaxi.com/anthropic` 端点。

  **要改什么**：
  - 在 `_PROVIDER_PRESETS` 中新增 `"deepseek"` 预设
  - base_url = `https://api.deepseek.com/anthropic`
  - default_model = `deepseek-v4-flash`
  - api_key_env = `DEEPSEEK_API_KEY`
  - 新增 `LLMConfig.deepseek()` classmethod
  - `.env` 切换配置

  **变更边界**：
  - 修改 `t2c/llm_config.py`：新增预设 + classmethod
  - 修改 `.env`：切换 provider/model/base_url/api_key
  - 不修改 `extractor.py`（已有 Anthropic SDK 兼容）

  **怎么实现**：

  在 `_PROVIDER_PRESETS` 中添加：
  ```python
  "deepseek": {
      "base_url": "https://api.deepseek.com/anthropic",
      "default_model": "deepseek-v4-flash",
      "api_key_env": "DEEPSEEK_API_KEY",
  },
  ```

  新增 classmethod：
  ```python
  @classmethod
  def deepseek(cls, *, api_key: str | None = None, model: str | None = None,
               base_url: str | None = None, **kwargs: Any) -> "LLMConfig":
      preset = _PROVIDER_PRESETS["deepseek"]
      return cls(
          provider="deepseek",
          model=model or preset["default_model"],
          base_url=base_url or preset["base_url"],
          api_key=api_key or os.environ.get(preset["api_key_env"], ""),
          **kwargs,
      )
  ```

  更新 `.env`：
  ```
  T2C_LLM_PROVIDER=deepseek
  T2C_LLM_API_KEY=<your-deepseek-api-key>
  T2C_LLM_MODEL=deepseek-v4-flash
  T2C_LLM_BASE_URL=https://api.deepseek.com/anthropic
  T2C_LLM_MAX_TOKENS=16000
  T2C_LLM_THINKING_BUDGET=0
  ```

  **Recommended Agent Profile**:
  - Category: `quick`
  - Skills: [] 

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: [2,3,6] | Blocked By: []

  **References**:
  - `_PROVIDER_PRESETS` 定义：`t2c/llm_config.py:33-49`
  - `minimax()` classmethod 模式：`t2c/llm_config.py:115-129`
  - `from_env()` 自动选择预设：`t2c/llm_config.py:172-273`
  - DeepSeek Anthropic API 文档：`https://api-docs.deepseek.com/zh-cn/guides/anthropic_api`

  **Acceptance Criteria**:
  - [ ] `LLMConfig.deepseek(api_key="test")` 返回正确配置
  - [ ] `LLMConfig.from_env()` 在 `T2C_LLM_PROVIDER=deepseek` 时选择 DeepSeek 预设
  - [ ] `pytest tests/test_llm_config.py` 全部通过

  **QA Scenarios**:
  ```
  Scenario: DeepSeek preset produces correct config
    Tool: Bash
    Steps: python3 -c "from t2c.llm_config import LLMConfig; c = LLMConfig.deepseek(api_key='sk-test'); assert c.provider == 'deepseek'; assert c.model == 'deepseek-v4-flash'; assert 'deepseek.com/anthropic' in c.base_url; print('OK')"
    Expected: OK
    Evidence: .sisyphus/evidence/task-1-deepseek-preset.txt

  Scenario: from_env picks deepseek when configured
    Tool: Bash
    Steps: T2C_LLM_PROVIDER=deepseek T2C_LLM_API_KEY=sk-test python3 -c "from t2c.llm_config import LLMConfig; c = LLMConfig.from_env(); assert c.provider == 'deepseek'; print('OK')"
    Expected: OK
    Evidence: .sisyphus/evidence/task-1-deepseek-env.txt
  ```

  **Commit**: YES | Message: `feat(config): add deepseek provider preset` | Files: [t2c/llm_config.py]

---

- [ ] 2. Prompt 前缀固定化 — 命中 DeepSeek 上下文缓存

  **现状**：`COMPACT_PROMPT`（`extractor.py:149-222`）将 `chapter_num`、`chapter_title` 放在 prompt **第一行**，`segments_formatted` 和 `existing_entities_section` 也直接嵌入 prompt 中部。每个 batch 的 prompt 从第 1 行就不同，DeepSeek 的前缀缓存 **完全无法命中**。

  当前 prompt 结构：
  ```
  你是一个文学文本结构化专家。从以下《红楼梦》第10回「金寡妇贪利权受辱...」的文本中提取...  ← batch 1/2/3/4/5 全不同
  ```
  5 个 batch 之间 0 个 token 的前缀重叠。

  **要改什么**：
  将 prompt 拆成 **固定前缀**（system instruction + schema + rules）和 **可变后缀**（chapter info + segments + entities）。固定前缀约 1500 tokens，所有 batch 完全相同 → DeepSeek 缓存命中这部分。

  目标 prompt 结构：
  ```
  [固定前缀 ~1500 tokens — 所有 batch 相同]
  你是一个文学文本结构化专家。从提供的文本中提取紧凑候选对象。
  
  ## 输出要求
  ### E = Entity（实体）
  ...（schema 定义）
  ### EV = Event（事件）
  ...（schema 定义）
  ### C = Claim（声明）
  ...（schema 定义）
  ### I = IgnoreSegment（忽略）
  ...（schema 定义）
  ## 严禁输出
  ...
  ## 核心原则
  ...
  
  [可变后缀 — 每个 batch 不同]
  ## 本次任务
  文档：红楼梦，第10回「金寡妇贪利权受辱　张太医论病细穷源」
  
  ## 输入文本
  [hongloumeng_seg_0001] 第十回...
  [hongloumeng_seg_0002] 话说金荣...
  
  ## 已知人物
  - hongloumeng_ent_0001: 甄士隐
  ...
  ```

  这样 Batch 1-5 共享 ~1500 tokens 的固定前缀。第 2 个 batch 开始，前缀缓存命中率 **~60-70%**（取决于 input 总长）。

  **变更边界**：
  - 修改 `COMPACT_PROMPT` 常量：拆成 `COMPACT_PROMPT_PREFIX` + `COMPACT_PROMPT_SUFFIX`
  - 修改 `_build_compact_prompt()`：拼接 prefix + suffix
  - 同步修改 `EXTRACTION_PROMPT`（verbose 路径）
  - 更新 `_prompt_version` → `compact-main-v2`（使旧缓存失效）
  - **不修改** compact_candidate.py 的解析逻辑
  - **不修改** expand 逻辑

  **怎么实现**：

  1. 将 `COMPACT_PROMPT` 拆成两段：

  ```python
  COMPACT_PROMPT_PREFIX = """\
  你是一个文学文本结构化专家。从提供的文本中提取**紧凑**候选对象。

  ## 输出要求

  **只输出 JSON 数组**。每个元素是单个候选对象，字段尽量短。只用以下四种 type：

  ### E = Entity（实体）
  ```json
  {{"t":"E","lid":"e1","n":"甄士隐","k":"person","a":["士隐"],"sid":["hongloumeng_seg_0009"],"q":["甄士隐"]}}
  ```
  - `lid` = 本批内有效 local id（其他候选可引用）
  - `n` = 实体名，`k` = kind（person/location/org/artifact/concept）
  - `a` = 其他称呼列表，可省
  - `sid` = 出现的 segment id 列表
  - `q` = 用于 EvidenceRef 定位的原文引用片段列表，可省

  **⚠️ 人物抽取是最优先任务：**
  - 必须提取文本中**每一个**有名字的人物（包括被称呼但未全名出现的角色）
  - 同一人物用不同称呼时，取最常用名作 `n`，其余作 `a`
  - "太太""奶奶""老爷""大爷"等称谓如果指向特定人物，也要提取
  - 不要遗漏对话中提到的人物
  - 人物的 `sid` 应包含所有提及该人物的 segment

  ### EV = Event（事件）
  ```json
  {{"t":"EV","n":"甄士隐做梦","k":"occurrence","p":["e1"],"sid":["hongloumeng_seg_0015"],"q":["梦"]}}
  ```
  - `p` = 参与者 entity id 列表（lid 或已知 entity id）

  ### C = Claim（声明）
  ```json
  {{"t":"C","s":"e1","p":"lives_in","o":"姑苏","m":"asserted","pol":"positive","sid":["seg1"],"q":["姑苏"]}}
  ```
  - `s` = subject (entity id or lid)
  - `p` = predicate（使用简洁的英文动词短语）
  - `o` = object (entity id, lid, or literal string)
  - `m` = modality (asserted/reported/claimed_by_source/uncertain/hypothetical/conditional/inferred)
  - `pol` = polarity (positive/negative)

  ### I = IgnoreSegment（忽略）
  ```json
  {{"t":"I","sid":"seg1","r":"chapter title"}}
  ```
  - `r` = 忽略原因

  ## 严禁输出

  - **R (Relation)** — 由程序从 Claim 自动派生
  - **EvidenceRef 字段（start/end/quote_hash）** — 由程序从 `q` 引用片段定位
  - Residual — 留到第二阶段
  - Markdown 包裹
  - 任何解释文本

  ## 核心原则

  1. 同一人物用相同 lid；跨实体引用时优先用本批的 lid
  2. **人物完整性优先于声明完整性**——宁可少一条 Claim，不可漏一个人物
  3. 不确定信息用 modality=uncertain，不要硬上 asserted
  4. 转述/对白用 reported 或 claimed_by_source
  5. `q` 给出一小段原文引用即可，程序会精确定位并算 hash
  6. `sid` 必须是输入中真实存在的 segment id
  7. 不编造，不推断，找不到的宁可不写
  """

  COMPACT_PROMPT_SUFFIX = """\

  ## 本次任务

  文档：{doc_id}，第{chapter_num}回「{chapter_title}」

  ## 输入文本

  每行格式：`[segment_id] 文本内容`

  {segments_formatted}

  {existing_entities_section}

  请直接返回紧凑 JSON 数组。
  """
  ```

  2. 修改 `_build_compact_prompt()`：
  ```python
  def _build_compact_prompt(self, doc_id, chapter_num, chapter_title, segments, existing_entities):
      segments_formatted = "\n".join(f"[{s.id}] {s.text_slice}" for s in segments)
      if existing_entities:
          lines = [f"- {eid}: {name}" for name, eid in existing_entities.items()]
          existing_section = "## 已知人物（前几回已提取，直接复用其 ID）\n\n" + "\n".join(lines)
      else:
          existing_section = ""
      return COMPACT_PROMPT_PREFIX + COMPACT_PROMPT_SUFFIX.format(
          doc_id=doc_id,
          chapter_num=chapter_num,
          chapter_title=chapter_title,
          segments_formatted=segments_formatted,
          existing_entities_section=existing_section,
      )
  ```

  3. 更新 prompt version：`_DEFAULT_PROMPT_VERSION = "compact-main-v2"`

  **Recommended Agent Profile**:
  - Category: `medium` — 涉及 prompt 内容重组，需要仔细保持语义不变
  - Skills: []

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: [3, 6] | Blocked By: [1]

  **References**:
  - `COMPACT_PROMPT` 完整定义：`t2c/extractor.py:149-222`
  - `_build_compact_prompt()` 方法：`t2c/extractor.py:808-829`
  - `_DEFAULT_PROMPT_VERSION`：`t2c/extractor.py:244`
  - DeepSeek 缓存命中规则：`https://api-docs.deepseek.com/zh-cn/guides/kv_cache`
  - DeepSeek 定价：缓存命中 ¥0.02/M，未命中 ¥1/M

  **Acceptance Criteria**:
  - [ ] `COMPACT_PROMPT_PREFIX` 以通用指令开头，不含 `{chapter_num}` / `{chapter_title}`
  - [ ] `COMPACT_PROMPT_SUFFIX` 包含所有可变字段
  - [ ] 拼接后的 prompt 与原 `COMPACT_PROMPT` 语义完全一致
  - [ ] `_prompt_version` 更新为 `compact-main-v2`
  - [ ] `pytest tests/ -x -q` 全部通过

  **QA Scenarios**:
  ```
  Scenario: Prompt prefix is identical across batches
    Tool: Bash
    Steps: |
      python3 -c "
      from t2c.extractor import COMPACT_PROMPT_PREFIX
      assert '{chapter_num}' not in COMPACT_PROMPT_PREFIX
      assert '{chapter_title}' not in COMPACT_PROMPT_PREFIX
      assert '{segments_formatted}' not in COMPACT_PROMPT_PREFIX
      assert 'E = Entity' in COMPACT_PROMPT_PREFIX
      assert '核心原则' in COMPACT_PROMPT_PREFIX
      print('OK: prefix is static')
      "
    Expected: OK: prefix is static
    Evidence: .sisyphus/evidence/task-2-prefix-static.txt

  Scenario: Full prompt renders correctly
    Tool: Bash
    Steps: |
      python3 -c "
      from t2c.extractor import COMPACT_PROMPT_PREFIX, COMPACT_PROMPT_SUFFIX
      result = COMPACT_PROMPT_PREFIX + COMPACT_PROMPT_SUFFIX.format(
          doc_id='test', chapter_num=1, chapter_title='测试',
          segments_formatted='[seg1] hello', existing_entities_section=''
      )
      assert '第1回' in result
      assert '测试' in result
      assert '[seg1] hello' in result
      assert 'E = Entity' in result
      print('OK: full prompt renders')
      "
    Expected: OK: full prompt renders
    Evidence: .sisyphus/evidence/task-2-prompt-render.txt

  Scenario: DeepSeek API call returns prompt_cache_hit_tokens
    Tool: Bash
    Steps: python3 scripts/extract_ch10_v4.py 2>&1 | grep -i "cache_hit\|prompt_cache"
    Expected: 看到 prompt_cache_hit_tokens > 0 或在 telemetry 中看到缓存命中
    Evidence: .sisyphus/evidence/task-2-cache-hit.txt
  ```

  **Commit**: YES | Message: `refactor(extractor): split prompt into prefix+suffix for API cache hit` | Files: [t2c/extractor.py]

---

- [ ] 3. 增大 `_MAX_BATCH_CHARS` 从 1200 → 4000

  **现状**：`_MAX_BATCH_CHARS = 1200`（`extractor.py:228`），5116 字符的 ch10 文本被拆成 5 个 batch。每个 batch 的 API 调用中，prompt template 固定开销约 1500 tokens，而 segment 内容只有 ~600-1500 tokens。**固定开销占比 50-70%**。

  实际 batch 分布：
  | Batch | segs | chars | API calls |
  |-------|------|-------|-----------|
  | 1 | 35 | ~1200 | 1 |
  | 2 | 15 | ~1200 | 1 |
  | 3 | 15 | ~1200 | 1 |
  | 4 | 36 | ~1200 | 1 |
  | 5 | 32 | ~1200 | 1 |
  | **合计** | 133 | 5116 | **5** |

  **要改什么**：将 `_MAX_BATCH_CHARS` 从 1200 增大到 4000，使 ch10 只需 2 个 batch，API 调用从 5 次降到 2 次。

  改后预期分布：
  | Batch | segs | chars | API calls |
  |-------|------|-------|-----------|
  | 1 | ~100 | ~4000 | 1 |
  | 2 | ~33 | ~1116 | 1 |
  | **合计** | 133 | 5116 | **2** |

  **变更边界**：
  - 修改 `extractor.py:228` 的 `_MAX_BATCH_CHARS` 常量
  - 可能需要调整 `_DEFAULT_MAX_TOKENS`（当前 8192，batch 增大后输出也增大，但 16000 已由 .env 覆盖）
  - 不修改 `_batch_segments()` 的逻辑
  - 不修改缓存 key 计算

  **怎么实现**：

  1. 修改 `_MAX_BATCH_CHARS = 4000`
  2. 清除本地缓存（batch 划分变了，旧缓存全部失效）：`rm -rf .t2c_cache/llm/v1/*.json`
  3. 运行验证

  **Recommended Agent Profile**:
  - Category: `quick`
  - Skills: []

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: [6] | Blocked By: [2]

  **References**:
  - `_MAX_BATCH_CHARS` 定义：`t2c/extractor.py:228`
  - `_batch_segments()` 方法：`t2c/extractor.py:952-974`
  - 缓存清理：`.t2c_cache/llm/v1/`

  **Acceptance Criteria**:
  - [ ] `_MAX_BATCH_CHARS == 4000`
  - [ ] ch10 extraction 的 batch 数 ≤ 2
  - [ ] 段覆盖率 ≥ 31.6%（不降质）
  - [ ] `pytest tests/ -x -q` 全部通过

  **QA Scenarios**:
  ```
  Scenario: Fewer batches with larger batch size
    Tool: Bash
    Steps: python3 scripts/extract_ch10_v4.py 2>&1 | grep "batch.*/"
    Expected: 出现 "batch 1/2" 而非 "batch 1/5"
    Evidence: .sisyphus/evidence/task-3-batch-count.txt

  Scenario: Quality maintained
    Tool: Bash
    Steps: python3 -c "import json; m=json.load(open('examples/knowledge/hongloumeng/ch10/cqm_baseline.json')); print(f'coverage={m[\"coverage_metrics\"][\"coverage_rate\"]:.1f}%, entities={m[\"extraction_counts\"][\"person_entities\"]}')"
    Expected: coverage ≥ 31.6%, person_entities ≥ 10
    Evidence: .sisyphus/evidence/task-3-quality.txt
  ```

  **Commit**: YES | Message: `perf(extractor): increase MAX_BATCH_CHARS 1200→4000` | Files: [t2c/extractor.py]

---

- [ ] 4. 砍掉 IgnoreSegment 输出类型

  **现状**：compact prompt 要求 LLM 输出 `{"t":"I","sid":"seg1","r":"chapter title"}` 格式的 IgnoreSegment。ch10 实际运行中 LLM 输出了 12 个 IgnoreSegment，占用 output tokens 但对知识图谱零贡献。未覆盖的 segment 已由 raw fallback（Step 10）的 Residual 处理。

  数据证据：
  - IgnoreSegment: 12 个 → 占 output tokens ~5%
  - Raw fallback: 35 segments → Residual 已覆盖
  - IgnoreSegment 的 `reason` 字段对下游无任何消费方

  **要改什么**：
  - 从 `COMPACT_PROMPT_PREFIX`（Task 2 重构后）中删除 `I = IgnoreSegment` 的定义
  - 从 `VALID_COMPACT_TYPES` 中移除 `COMPACT_TYPE_IGNORE = "I"`
  - 从 `compact_candidate.py` 的 `_parse_single()` 中移除 `COMPACT_TYPE_IGNORE` 分支
  - 保留 `IgnoreSegment` 类型定义（ontology.py 不动），让 raw fallback 负责所有忽略逻辑

  **变更边界**：
  - 修改 `extractor.py`：删除 prompt 中的 I 类型说明
  - 修改 `compact_candidate.py`：从 `VALID_COMPACT_TYPES` 移除 "I"，删除 `_parse_single` 中 I 分支
  - **不修改** `ontology.py` / `codegen.py`（类型定义保留，只是 LLM 不再输出）
  - **不修改** `expand_candidates()`（I 分支已有代码保留但不再触发）

  **怎么实现**：

  1. 在 prompt 中删除 `### I = IgnoreSegment` 段落和示例
  2. 在 `compact_candidate.py` 中：
     - 从 `VALID_COMPACT_TYPES` 移除 `COMPACT_TYPE_IGNORE`
     - 删除 `_parse_single()` 中 `if t == COMPACT_TYPE_IGNORE:` 分支
  3. 保留 `COMPACT_TYPE_IGNORE` 常量（向后兼容），只是不在 VALID 集合中

  **Recommended Agent Profile**:
  - Category: `quick`
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [] | Blocked By: []

  **References**:
  - IgnoreSegment prompt 段：`extractor.py:197-200`
  - `VALID_COMPACT_TYPES`：`compact_candidate.py:38-43`
  - `_parse_single` I 分支：`compact_candidate.py`（搜索 `COMPACT_TYPE_IGNORE`）
  - Raw fallback 逻辑：`pipeline.py:299-377`

  **Acceptance Criteria**:
  - [ ] `VALID_COMPACT_TYPES` 不包含 `"I"`
  - [ ] prompt 中无 IgnoreSegment 定义
  - [ ] `pytest tests/ -x -q` 全部通过
  - [ ] 提取结果中 IgnoreSegment 数 = 0

  **QA Scenarios**:
  ```
  Scenario: IgnoreSegment no longer in valid types
    Tool: Bash
    Steps: python3 -c "from t2c.compact_candidate import VALID_COMPACT_TYPES; assert 'I' not in VALID_COMPACT_TYPES; print('OK')"
    Expected: OK
    Evidence: .sisyphus/evidence/task-4-no-ignore.txt
  ```

  **Commit**: YES | Message: `refactor(extractor): remove IgnoreSegment from LLM output types` | Files: [t2c/extractor.py, t2c/compact_candidate.py]

---

- [ ] 5. 简化 Repair Loop

  **现状**：`Pipeline._repair()`（`pipeline.py:217-297`）是一个 81 行的方法，策略是"删除有错误的对象 + 清理悬空引用"。当前运行中 **0 errors**，repair 被调用 2 次（`max_repair_attempts=2`）但什么都没修。`process_text()` 中的 repair 循环即使无错误也执行空循环。

  **要改什么**：
  - 当 `val_result.valid == True` 时跳过整个 repair 循环
  - 减少 `max_repair_attempts` 默认值从 2 → 1
  - 不删除 `_repair()` 方法本身（保留能力），只是减少无效执行

  **变更边界**：
  - 修改 `pipeline.py`：在 repair 循环前加 `if val_result.valid: skip`
  - 修改 `Pipeline.__init__`：`max_repair_attempts` 默认 1
  - **不删除** `_repair()` 方法
  - **不修改** `_repair()` 内部逻辑

  **怎么实现**：

  在 `process_text()` 中：
  ```python
  # Step 6: Repair loop
  t0 = time.time()
  repair_attempts = 0
  if not val_result.valid:  # ← 新增：无错误时跳过
      while not val_result.valid and repair_attempts < self._max_repair:
          repair_attempts += 1
          ...
  ```

  在 `Pipeline.__init__` 中：
  ```python
  max_repair_attempts: int = 1,  # 从 2 改为 1
  ```

  **Recommended Agent Profile**:
  - Category: `quick`
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [] | Blocked By: []

  **References**:
  - `_repair()` 方法：`pipeline.py:217-297`
  - repair 循环：`pipeline.py:150-165`
  - `Pipeline.__init__`：`pipeline.py:49-58`

  **Acceptance Criteria**:
  - [ ] `val_result.valid == True` 时 repair 循环 0 次执行
  - [ ] `pytest tests/ -x -q` 全部通过

  **QA Scenarios**:
  ```
  Scenario: No repair when validation passes
    Tool: Bash
    Steps: python3 -c "
  import json
  m = json.load(open('examples/knowledge/hongloumeng/ch10/cqm_baseline.json'))
  print(f'repair_attempts={m[\"pipeline_metrics\"][\"repair_attempts\"]}, errors={m[\"pipeline_metrics\"][\"errors_count\"]}')
  "
    Expected: repair_attempts=0 when errors_count=0
    Evidence: .sisyphus/evidence/task-5-no-repair.txt
  ```

  **Commit**: YES | Message: `perf(pipeline): skip repair loop when validation passes, reduce default attempts to 1` | Files: [t2c/pipeline.py]

---

- [ ] 6. 端到端验证 + 缓存命中确认

  **现状**：所有修改完成后，需要一次完整的端到端运行来验证：DeepSeek 接入可用、缓存命中生效、质量不降、成本大幅降低。

  **要做什么**：
  1. 清除旧缓存：`rm -rf .t2c_cache/llm/v1/*.json`
  2. 运行 `python3 scripts/extract_ch10_v4.py`
  3. 检查日志中 `prompt_cache_hit_tokens` > 0
  4. 对比 CQM 指标
  5. 对比成本

  **验证清单**：
  - [ ] DeepSeek-v4-flash API 调用成功
  - [ ] batch 数 ≤ 2（原来 5）
  - [ ] `prompt_cache_hit_tokens > 0`
  - [ ] 段覆盖率 ≥ 31.6%
  - [ ] Entity recall ≥ 25%
  - [ ] IgnoreSegment count = 0
  - [ ] 总成本 < ¥0.05
  - [ ] `pytest tests/ -x -q` 全部通过

  **Recommended Agent Profile**:
  - Category: `deep`
  - Skills: []

  **Parallelization**: Can Parallel: NO | Wave 4 | Blocks: [] | Blocked By: [1, 2, 3, 4, 5]

  **References**:
  - 测试脚本：`scripts/extract_ch10_v4.py`
  - CQM 输出：`examples/knowledge/hongloumeng/ch10/cqm_baseline.json`
  - 日志：`examples/knowledge/hongloumeng/ch10/extraction_ch10_v4.log`

  **Acceptance Criteria**:
  - [ ] 上述验证清单全部 ✅
  - [ ] 成本对比：MiniMax $0.76 → DeepSeek < ¥0.05

  **QA Scenarios**:
  ```
  Scenario: Full extraction with DeepSeek
    Tool: Bash
    Steps: rm -rf .t2c_cache/llm/v1/*.json && python3 scripts/extract_ch10_v4.py 2>&1
    Expected: 完整运行，无 APIConnectionError，输出 CQM metrics
    Evidence: .sisyphus/evidence/task-6-e2e-output.txt

  Scenario: Cache hit on second run
    Tool: Bash
    Steps: python3 scripts/extract_ch10_v4.py 2>&1 | grep "cache hit"
    Expected: batch 1-2 本地缓存命中
    Evidence: .sisyphus/evidence/task-6-cache-hit.txt

  Scenario: Cost comparison
    Tool: Bash
    Steps: |
      python3 -c "
      import json
      m = json.load(open('examples/knowledge/hongloumeng/ch10/cqm_baseline.json'))
      t = m['llm_telemetry']
      print(f'input_tokens={t[\"total_input_tokens\"]}, output_tokens={t[\"total_output_tokens\"]}')
      # DeepSeek pricing: input miss=1元/M, input hit=0.02元/M, output=2元/M
      cost_miss = t['total_input_tokens']/1e6 * 1 + t['total_output_tokens']/1e6 * 2
      cost_50hit = t['total_input_tokens']/1e6 * 0.51 * 1 + t['total_input_tokens']/1e6 * 0.49 * 0.02 + t['total_output_tokens']/1e6 * 2
      print(f'cost_no_cache=¥{cost_miss:.4f}, cost_50%_cache=¥{cost_50hit:.4f}')
      "
    Expected: cost_50%_cache < ¥0.05
    Evidence: .sisyphus/evidence/task-6-cost.txt
  ```

  **Commit**: YES | Message: `chore: e2e validation with deepseek-v4-flash` | Files: []

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [ ] F1. Plan Compliance Audit — oracle
- [ ] F2. Code Quality Review — unspecified-high
- [ ] F3. Real Manual QA — unspecified-high (+ playwright if UI)
- [ ] F4. Scope Fidelity Check — deep

## Commit Strategy
- 每个 task 独立 commit
- 最终验证后可选 squash merge

## Success Criteria
| 指标 | 当前（MiniMax） | 目标（DeepSeek） |
|---|---|---|
| 模型 | MiniMax-M3 | deepseek-v4-flash |
| Batch 数 | 5 | ≤ 2 |
| API 缓存命中 | 0% | > 0% |
| 总成本 | $0.76 | < ¥0.05 |
| 段覆盖率 | 31.6% | ≥ 31.6% |
| Entity recall | 25-33% | ≥ 25% |
| LLM 调用次数 | 5 | ≤ 2 |
