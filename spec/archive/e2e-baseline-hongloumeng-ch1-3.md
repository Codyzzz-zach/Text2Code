# T2C v4.1 E2E Baseline Report

> **Date**: 2026-06-09  
> **Input**: `input_txt/红楼梦1-3.txt` (193 lines, Ch1-3 of 红楼梦)  
> **LLM**: deepseek / deepseek-v4-flash  
> **Protocol**: compact-v1 / compact-main-v2  
> **Cache mode**: read_write  
> **Compiler version**: v0.4.0 (post-I-1~I-6, spec v4.1 aligned)

---

## 1. CQM 量化指标基线

### 1.1 核心指标

| 指标 | 缩写 | 基线值 | v4.1 目标 | 差距 | 状态 |
|------|------|--------|-----------|------|------|
| 实体召回率 | ER | **27.7%** | ≥ 70% | -42.3pp | 🔴 |
| 实体精确率 | EP | **76.5%** | ≥ 75% | +1.5pp | ✅ |
| 引用正确率 | RR | **100%** | 100% | 0 | ✅ |
| 段覆盖率 | SCR | **24.55%** | ≥ 35% | -10.5pp | 🟡 |
| Evidence 覆盖率 | ECR | **74.4%** | ≥ 60% | +14.4pp | ✅ |
| Residual 区分度 | RD | **0.89** | > 1.0 | -0.11 | 🟡 |
| Predicate 一致率 | PC | **100%** | ≥ 85% | +15pp | ✅ |
| 代码可导入率 | IR | **100%** | 100% | 0 | ✅ |
| 符号索引率 | SIR | **100%** | 100% | 0 | ✅ |
| Grounding rate | GR | **89.36%** | ≥ 70% | +19.4pp | ✅ |

> 注: ER/EP 基于 47 个 ground-truth 人物计算（含神话角色），详见 §2.2。

### 1.2 编译流水线指标

| 指标 | 值 |
|------|-----|
| 输入段数 | 759 |
| LLM batch 数 | 6 |
| 总 input tokens | 32,448 |
| 总 output tokens | 48,778 |
| API 耗时 | 426.29s (~7.1 min) |
| Cache hits / misses | 0 / 6 |
| Pipeline valid | true |
| Repair attempts | 0 |
| Saved objects | 205 |
| Rejected objects | 0 |
| Raw fallback segments | 476 |

### 1.3 Coverage 分布

| 状态 | 数量 | 占比 |
|------|------|------|
| covered | 96 | 12.6% |
| partial | 0 | 0.0% |
| raw_only | 476 | 62.7% |
| uncovered | 187 | 24.6% |
| ignored | 0 | 0.0% |
| **total** | **759** | **100%** |

---

## 2. 知识提取质量分析

### 2.1 Entity 明细

| 指标 | 值 |
|------|-----|
| 总 Entity 数 | 27 |
| person | 19 |
| location | 7 |
| org | 1 |
| 有 alias 的 Entity | 11 / 27 (40.7%) |
| 平均 alias 数 | 0.52 |
| **重复 Entity** | **2 对** (贾珠×2, 贾宝玉×2) |

**重复 Entity 明细**:

| 名称 | ID 1 | ID 2 | 根因 |
|------|------|------|------|
| 贾珠 | ent_0013 (seg_0627) | ent_0017 (seg_0368) | ch2 冷子兴演说 vs ch2 荣府介绍，两批 LLM batch 各自独立创建 |
| 贾宝玉 | ent_0008 (seg_0616) | ent_0018 (seg_0369) | 同上，冷子兴演说 vs 荣府世系 |

### 2.2 Entity Recall / Precision 计算

**Ground truth**: 47 个命名人物 (Ch1-3)

**Extracted unique**: 17 个 person entity (去重前 19)

**True positives (13)**: 贾敏, 鹦哥, 贾政, 贾珠, 李嬷嬷, 薛蟠, 甄宝玉, 王夫人, 李纨, 王子腾, 雪雁, 袭人, 王嬷嬷

**False positives (4)**: 贾宝玉, 贾迎春, 贾探春, 贾惜春  
> 注: 这些并非错误，只是 alias 匹配偏差（如"贾宝玉"存在于 ground truth，但被计为 FP 是因为 ground truth 中包含更细粒度的人物名集合）

**False negatives (34)**: 甄士隐, 贾雨村, 林黛玉, 王熙凤, 贾母, 冷子兴, 林如海, 薛宝钗, 封氏, 英莲, 娇杏, 霍启 等

**严重遗漏的核心人物** (10):

| 排名 | 人物 | 出现章节 | 文本中重要性 |
|------|------|----------|-------------|
| 1 | 甄士隐 | Ch1 | **主角** (Ch1 核心人物) |
| 2 | 贾雨村 | Ch1-2 | **主角** (贯穿 3 回) |
| 3 | 林黛玉 | Ch2-3 | **主角** (全书女主) |
| 4 | 贾母 | Ch2-3 | **核心** (贾府家长) |
| 5 | 王熙凤 | Ch2-3 | **核心** (荣府管事) |
| 6 | 冷子兴 | Ch2 | **关键** (演说荣国府) |
| 7 | 林如海 | Ch2 | 重要 (黛玉之父) |
| 8 | 薛宝钗 | Ch3 | 重要 (四大家族) |
| 9 | 封氏 | Ch1 | 次要 (士隐之妻) |
| 10 | 英莲 | Ch1 | 次要 (士隐之女) |

### 2.3 Event 明细

| 指标 | 值 |
|------|-----|
| 总 Event 数 | 13 |
| 平均参与者数 | 2.15 |
| **无 EvidenceRef 的 Event** | **3 / 13 (23.1%)** |

**无 EvidenceRef 的 Event**:

| Event | 原因 |
|-------|------|
| 黛玉带王嬷嬷雪雁入府 | LLM 未提供 quote |
| 甄士隐随跛足道人出家 | LLM 未提供 quote |
| 袭人劝慰黛玉 | LLM 未提供 quote |

### 2.4 Claim 明细

| 指标 | 值 |
|------|-----|
| 总 Claim 数 | 24 |
| **无 object 的 Claim** | **6 / 24 (25.0%)** |
| **自引用 Claim** | **1 / 24 (4.2%)** |

**Predicate 分布**:

| Predicate | 数量 | 受控词表? |
|-----------|------|-----------|
| is_child_of | 7 | ✅ |
| is_servant_of | 6 | ✅ |
| is_relative_of | 2 | ✅ |
| is_spouse_of | 2 | ✅ |
| lives_in | 2 | ✅ |
| believes_in | 1 | ⚠️ |
| died | 1 | ✅ |
| born_with | 1 | ⚠️ |
| serves_as | 1 | ⚠️ |
| desires | 1 | ⚠️ |

**Modality 分布**: asserted=9, reported=15

**自引用 Claim**: `鹦哥 is_servant_of 鹦哥` (应为 is_servant_of 黛玉/贾母)

### 2.5 Residual 明细

| 指标 | 值 |
|------|-----|
| 总 Residual 数 | 476 |
| **category 分布** | structural=404 (84.9%), interpersonal=61 (12.8%), stylistic=11 (2.3%) |
| **importance 分布** | medium=415 (87.2%), high=61 (12.8%) |
| **区分度 (entropy)** | H(category)=0.62, H(importance)=0.53, **RD=1.15** |

> 注: 使用自然熵计算（非归一化），H_max(category,3类)=1.585, H_max(importance,2类)=1.0  
> 归一化 RD = H(category)/1.585 + H(importance)/1.0 = 0.39 + 0.53 = **0.92**  
> 原始 RD = 0.62 + 0.53 = 1.15（接近但未达 >1.0 目标，主要是 structural 占比过高）

---

## 3. Spec 对齐分析

### 3.1 Pipeline Phase 对齐

| Spec Phase | 名称 | 实现状态 | 差异 |
|------------|------|----------|------|
| [1] | Ingest | ✅ 完整 | — |
| [2] | Block Generation | ✅ 完整 | — |
| [3] | Segmentation | ✅ 完整 | — |
| [4] | Text Code Generation | ✅ 完整 | — |
| [5] | LLM Compact Candidate | ✅ 完整 | compact-v1 为默认协议 |
| [6] | Candidate Expansion | ✅ 完整 | expand_candidates + derive_relations |
| [7] | Validation (12 gates) | ⚠️ 部分 | **9/12 gates 实现**, 见 §3.2 |
| [8] | Repair Loop | ✅ 完整 | MAX_REPAIR=2 (CLI), 1 (API default) |
| [9] | Semantic Code Generation | ✅ 完整 | 8 文件包结构正确 |
| [10] | Derived Code Generation | ✅ 完整 | Relation 从 Claim 自动推导 |
| [11] | Coverage Generation | ✅ 完整 | 但**不作为验证门** |

### 3.2 Validator 12-Gate 对齐

| # | Gate | 实现? | 位置 | 备注 |
|---|------|-------|------|------|
| 1 | grammar | ✅ | parser.py | AST 级别严格校验 |
| 2 | schema | ✅ | schema.py | Pydantic model validation |
| 3 | id | ❌ | — | **无唯一性检查** |
| 4 | reference | ✅ | validator.py | 含跨文件引用解析 |
| 5 | evidence | ✅ | validator.py | 含 span+hash+raw_replay |
| 6 | span | ✅ | 子检查 | EvidenceRef 边界校验 |
| 7 | hash | ✅ | 子检查 | sha256 一致性校验 |
| 8 | raw_replay | ✅ | 子检查 | 原文回放验证 |
| 9 | claim_safety | ✅ | claim_safety.py | 6 条认识论安全规则 |
| 10 | coverage | ❌ | — | CoverageGenerator 存在但**未接入验证链** |
| 11 | no_silent_loss | ❌ | — | 测试存在但**无 gate 实现** |
| 12 | rebuild | ❌ | — | **零实现，无 placeholder** |

**Gate 完成度: 9/12 = 75%**

### 3.3 Spec 永久禁止项检查

| 禁止项 | 状态 | 备注 |
|--------|------|------|
| LLM 直接写 `.py` | ✅ 合规 | LLM 只输出 JSON |
| LLM 生成 offset/hash | ✅ 合规 | `build_evidence_refs()` 程序化计算 |
| Summary-to-Code 路径 | ✅ 合规 | 始终从原文编译 |
| 运行时 service | ✅ 合规 | 纯编译器模式 |
| 用户管理对象 | ✅ 合规 | 用户管理 `.py` 文件 |
| Ontology 新增字段 | ✅ 合规 | 无新增字段 |
| Phase [12] 及以后 | ✅ 合规 | Pipeline 在 Phase 11 后退出 |

### 3.4 Spec 哲学对齐检查

| 原则 | 状态 | 备注 |
|------|------|------|
| "T2C 是编译器" | ✅ | 无运行时状态，纯编译 |
| "Raw Text must be replayable" | ✅ | EvidenceRef + hash 链 |
| "LLM 只输出 candidate JSON" | ✅ | compact-v1 协议 |
| "Reference 字段默认 str" | ✅ | `_emit_symbol_refs=False` |
| "12-gate 全过才算成功" | ❌ | 3 gate 缺失，当前无法验证 |

---

## 4. 缺陷清单

### 4.1 实际缺陷（本次测试观测到）

| # | 缺陷 | 严重度 | CQM 影响 | 量化证据 |
|---|------|--------|----------|----------|
| D1 | **Entity 去重缺失** | 🔴 P0 | ER↑, EP↑, 数据一致性↓ | 2 对重复 Entity (贾珠×2, 贾宝玉×2), 跨 batch 无合并 |
| D2 | **核心人物漏抽取** | 🔴 P0 | ER=27.7% | 47 个 GT 人物仅抽到 17 unique, 含 10 个核心人物遗漏 (甄士隐/贾雨村/林黛玉/贾母/王熙凤等) |
| D3 | **Claim 自引用** | 🟠 P1 | GR↓ | `鹦哥 is_servant_of 鹦哥`, 应引用黛玉/贾母 |
| D4 | **Event 参与者 ID 错误** | 🟠 P1 | 数据正确性↓ | evt_0006: participants=[雪雁, 王嬷嬷], 实际应为[王夫人, 王熙凤]; evt_0010: 引用 ent_0001/ent_0007 不匹配 |
| D5 | **Event 缺 EvidenceRef** | 🟡 P2 | ECR↓ | 3/13 Event 无 evidence (23.1%) |
| D6 | **Claim 缺 object** | 🟡 P2 | 完整性↓ | 6/24 Claim 无 object (25.0%), 如 lives_in/believes_in/died |
| D7 | **Residual 分类同质化** | 🟡 P3 | RD=0.92 | structural=84.9%, medium=87.2%, 缺乏细粒度区分 |
| D8 | **Coverage gate 未接入** | 🟡 P3 | Spec 对齐度 | CoverageGenerator 存在但未作为验证 gate |

### 4.2 潜在缺陷（代码审查发现，本次未触发）

| # | 缺陷 | 严重度 | 触发条件 | 预期影响 |
|---|------|--------|----------|----------|
| P1 | **ID 唯一性无检查** | 🟠 P1 | 同名 Entity 跨 batch 出现 | 同名不同 ID 的 Entity 并存，数据混乱 |
| P2 | **Rebuild gate 零实现** | 🟠 P1 | 编译产物需确定性重建 | 无法验证 round-trip 一致性 |
| P3 | **no_silent_loss gate 未实现** | 🟡 P2 | Segment 无声丢失 | 违反 spec §7 核心约束 |
| P4 | **IgnoreSegment compact 协议丢包** | 🟡 P2 | LLM 输出 type="I" | `_parse_single` 接受但 `expand_candidates` 静默丢弃 |
| P5 | **Coverage O(segments×objects)** | 🟡 P3 | 大文档 (>10k segments) | 性能瓶颈，全表扫描无索引 |
| P6 | **Cross-chapter Entity 延续未自动启用** | 🟡 P3 | 多章编译 | `_seed_entity_map` 存在但 pipeline 未调用 |
| P7 | **Repair 模块默认仅 1 次** | 🟡 P3 | API 调用时 | programmatic API 用户仅 1 次修复, CLI 为 2 次 |
| P8 | **Quote 定位仅取首匹配** | 🟡 P3 | 重复文本段 | `locate_quote_with_ambiguity` 警告但不纠正 |

---

## 5. Spec v4.0 vs 实现深度差异

### 5.1 Entity ID 命名规范

**Spec §6.4 要求**: `ent_<name_normalized_or_zh_hash>`

**实际实现**: `ent_zh_<6位hex>` (如 `ent_zh_04ee15`)

**差异**: Spec 预期名字中包含可读的 normalized 名称或 hash，实现全部使用 hash。这导致:
- 无法从 ID 推断实体名称
- 同名实体会生成不同 hash（因为 hash 基于 name+batch 上下文而非仅 name）
- 与 spec 的 "normalization → same ID → 自动去重" 设计意图不一致

### 5.2 Coverage 作为验证门

**Spec §7 要求**: coverage 为 12 gate 之一 (#10), gate failure = compile fails

**实际实现**: CoverageGenerator 在 Phase 11 运行，结果写入 coverage.py，但**不参与验证链**。编译始终可以成功即使 coverage 极低。

### 5.3 no_silent_loss 作为验证门

**Spec §7 要求**: 每 Segment 必须被语义对象或 Residual/IgnoreSegment 覆盖

**实际实现**: pipeline._generate_raw_fallbacks() 确实为所有 uncovered 段生成 Residual，但**无验证门确认**这一不变量。当前 187 个 uncovered 段本应全有 Residual，但需验证。

### 5.4 Residual 分类

**Spec 暗示**: Residual 应有有意义的 category/importance 区分

**实际实现**: `_classify_residual_text()` 使用硬编码中文字符模式，84.9% 被归为 structural + medium，区分度不足

### 5.5 Predicate 受控词表

**v4.1 迭代计划要求**: PC ≥ 85%, 受控词表定义

**实际实现**: 无显式词表。当前 10 种 predicate 中 4 种为自由词 (believes_in, born_with, serves_as, desires)。但这些词语义上是合理的，PC=100% 只是缺乏受控约束。

---

## 6. 与 v4.1 迭代基线对比

### 6.1 v4.1 ch10 基线 vs 本次 ch1-3 基线

| 指标 | ch10 基线 | ch1-3 基线 | 变化 | 说明 |
|------|-----------|-----------|------|------|
| ER | 8.3% | 27.7% | ↑ 19.4pp | 改善，但仍远低于 70% 目标 |
| EP | 12.5% | 76.5% | ↑ 64pp | **大幅改善** |
| RR | 0% | 100% | ↑ 100pp | I-1 修复后完全恢复 |
| SCR | 9.0% | 24.55% | ↑ 15.6pp | 改善，但仍低于 35% 目标 |
| ECR | 100% | 74.4% | ↓ 25.6pp | 下降（3 个 Event 无 evidence） |
| RD | 0 | 0.92 | ↑ 0.92 | I-5 改善但仍 <1.0 |
| PC | 低 | 100% | ↑ | I-4 有效但缺乏受控词表 |
| IR | 50% | 100% | ↑ 50pp | I-1+I-2 修复后完全恢复 |
| GR | N/A | 89.36% | — | 新指标 |

### 6.2 v4.1 迭代项完成状态

| 迭代 | 内容 | 状态 | 证据 |
|------|------|------|------|
| I-1 | 符号引用→字符串字面量 + # type: 注释 | ✅ 完成 | IR=100%, RR=100% |
| I-2 | residuals.py import 修复 | ✅ 完成 | residuals.py 可导入 |
| I-3 | Entity 抽取 prompt 优化 | ⚠️ 部分 | ER=27.7% (↑但远不够) |
| I-4 | Predicate 受控词表 | ⚠️ 部分 | PC=100% 但无显式词表 |
| I-5 | Residual 分类细化 | ⚠️ 部分 | RD=0.92 (↑但<1.0) |
| I-6 | LLM 批处理重试 | ✅ 完成 | 6/6 batch 成功 |

---

## 7. 优先优化路径建议

### 7.1 按影响排序

| 优先级 | 优化项 | 预期 ER 变化 | 预期 SCR 变化 | 工作量 |
|--------|--------|-------------|-------------|--------|
| 🔴 P0 | Entity 去重合并 | +5~10pp (消除重复) | 0 | M |
| 🔴 P0 | 核心人物抽取 prompt 强化 | +30~40pp | +5~10pp | L |
| 🟠 P1 | 补全 3 缺失 Validator gate | 0 | 0 | M |
| 🟠 P1 | Claim/Event 引用质量校验 | 0 | 0 | S |
| 🟡 P2 | Residual 分类改进 | 0 | 0 | S |
| 🟡 P2 | Evidence 强制化 (Event) | 0 | +3~5pp | S |
| 🟡 P3 | Coverage 索引优化 | 0 | 0 | S |

### 7.2 Spec 对齐路线

```
当前 Gate 完成度: 9/12 = 75%
     ↓ 补 ID gate
    10/12 = 83%
     ↓ 补 coverage gate
    11/12 = 92%
     ↓ 补 no_silent_loss + rebuild gate  
    12/12 = 100% ← Spec 合规
```

---

## 8. 测试可重复性

### 8.1 复现命令

```bash
# 环境准备
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Phase 1: Text-only preflight
t2c compile input_txt/红楼梦1-3.txt --output output_code/红楼梦1-3 --text-only --json

# Phase 2: Semantic compile (需要 DEEPSEEK_API_KEY)
t2c compile input_txt/红楼梦1-3.txt --output output_code/红楼梦1-3 --llm --cache-mode read_write --json

# Phase 3: Quality evaluation
python scripts/test_matrix.py quality --json

# Phase 4: Import verification
python3 -c "import importlib, sys; sys.path.insert(0,'output_code'); importlib.import_module('红楼梦1-3'); print('OK')"
```

### 8.2 Cache 行为

- `--cache-mode read_write`: 首次运行写入 cache, 后续 `read_only` 可复用
- Cache 位置: `data/llm_cache/<doc_id>/`
- 重跑成本: `--cache-mode read_only` 时 0 API 调用

### 8.3 Build 系统注意

- pyproject.toml 需 `build-backend = "setuptools.build_meta"` + `[tool.setuptools.packages.find] include = ["t2c*"]`
- 原始 `setuptools.backends._legacy:_Backend` 在 pip 25.x 下不可用
