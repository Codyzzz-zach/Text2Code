# T2C v5.0 优化方案：结构先行，LLM 精化

> **Status**: Final（经代码审计 + codegraph 依赖链验证）
> **Date**: 2026-06-11
> **核心原则**: 程序做程序的事，LLM 做 LLM 的事
> **产品定位**: 垂直领域——扔一本小说进去，系统把小说写成 code

---

## 0. 产品边界与核心问题

### 0.1 核心场景

**输入**：一本小说的 .txt 文件（格式未必标准，含噪音）
**输出**：可被 codegraph 工具链消费的 Python Knowledge Code

### 0.2 场景约束

| 约束 | 对架构的影响 |
|------|------------|
| 输入是小说 | Entity 以 person/location 为主，ontology 可收窄 |
| 格式不标准 | Segmenter 要鲁棒，不假设格式 |
| 人物出现多次 | Entity 提取率"差不多达标"即可，不必逐段追求 100% |
| 垂直领域 | 可针对小说语言特征做专门优化 |

### 0.3 核心问题：架构分工不对

不是"LLM 不够好"，是"程序做了 LLM 的事，LLM 做了程序的事"：

1. **结构信息浪费**：Segmenter 做了结构分析，extractor 一行代码就扔了
2. **程序做了 LLM 的事**：Validator 278 行模拟 Python import 免费的验证
3. **LLM 做了程序的事**：LLM 判断文本类型、分配 modality、识别标题
4. **输出不是真正的 code**：字符串 ID 让 codegraph 工具链无法消费

### 0.4 实测数据（红楼梦 Ch1-3，759 segments）

- **38.7% 的 segment 不以标点结尾** — 切分质量差
- `"那僧道："` 被切成独立 3 字残片段 — 说话人和对话拆散
- `segment_type` 在 t2c/ 中**只被定义和赋值，从未被读取** — 结构信息白算了
- `_symbol` 字段在 forward pipeline 中**从未被填充** — codegraph 索引断裂

### 0.5 Codegraph 依赖链验证结果

| 验证项 | 结论 |
|-------|------|
| `segment_type` 被谁消费？ | **无人消费**。只有 ontology 定义、segmenter 赋值、codegen FIELD_ORDER 列出，无读取 |
| `_build_compact_prompt` 如何消费 segment？ | 唯一一处：`f"[{s.id}] {s.text_slice}"` — segment_type 被丢弃 |
| P1-1 合并说话人+对话后 quote 定位是否安全？ | ✅ `locate_quote_with_ambiguity` 用 `str.find()`，合并后 text_slice 变长但仍能找到 quote，offset 自修正 |
| `_format_object_v33` 的调用链 | 只被 `_generate_type_file_v33`、`_format_value_v33`、`generate_text_code_v33` 调用 — P4-1 改动隔离性好 |
| `segment_block` 的调用者 | pipeline、cli、scripts — 修改切分逻辑后自动传播，无需改调用者 |
| Entity 对象有没有 `.symbol` 属性？ | ❌ 没有。只有 id/name/kind/aliases/evidence_refs/source_segment_ids — field_validator 方案不可行 |

---

## 1. 架构设计

```
原文
  │
  ▼
┌──────────────────────────────────────┐
│  Phase 1: 程序化结构分析              │  ← 程序全权负责
│  · 段落/场景边界识别（heading → scene）│
│  · 对话 span 识别（「」/""）           │
│  · 说话人提取（X道：模式 → 合并segment）│
│  · 回目/章节检测（第X回）              │
│  · 噪音过滤（OCR 错误、页码、封面）    │
│  · 产出: Segment(segment_type + 文本)  │
│  · ⚠️ segment_type 必须向下传递        │
└──────────┬───────────────────────────┘
           │ 结构化标注的文本
           ▼
┌──────────────────────────────────────┐
│  Phase 2: LLM 语义提取               │  ← LLM 只做语义理解
│  · 输入: [seg_id|type spk=X] 文本     │
│  · Entity: 程序给候选，LLM 确认/补充   │
│  · Claim: 程序给结构，LLM 填语义       │
│  · Event: 程序给边界，LLM 判断因果     │
│  · 产出: Entity/Claim/Event 候选       │
└──────────┬───────────────────────────┘
           │ 候选对象
           ▼
┌──────────────────────────────────────┐
│  Phase 3: 程序化后处理                 │  ← 程序全权负责
│  · modality 默认值（segment_type→值）  │
│  · source_segment_ids 补全            │
│  · Relation 派生 + 去重 + 稳定 ID      │
│  · EvidenceRef 定位 + hash            │
│  · IgnoreSegment 预筛                 │
│  · 产出: 验证后的 Pydantic 模型        │
└──────────┬───────────────────────────┘
           │ Pydantic 模型
           ▼
┌──────────────────────────────────────┐
│  Phase 4: CodeGraph-native 生成        │  ← 程序全权负责
│  · Symbol name 分配                    │
│  · _symbol 字段填充（FK→symbol 推导）  │
│  · 删除死 import（v5.0）               │
│  · 产出: 可被 codegraph 消费的 .py     │
│  · v5.1: AST symbol ref + 真 import   │
└──────────────────────────────────────┘
```

---

## 2. 改动清单

### Phase 1: Segmenter 升级 + 结构传递

#### P1-1: 修复对话切分 — 合并说话人与对话 [P0]

**问题**：`"那僧道："` 和 `「对话内容」` 被切成两个 segment，说话人成孤立残片段

**改法**：`_segment_paragraph` 中，当 sentence 段以说话人模式结尾（`X道：`/`X说：`/`X笑道：`等）且紧跟 dialogue 段时，合并为一个 `dialogue` segment

```
# 当前（2 个 segment）
[sentence] "那僧道："
[dialogue] "「大师，弟子蠢物...」"

# 改为（1 个 segment）
[dialogue] "那僧道：「大师，弟子蠢物...」"
```

**说话人模式正则**：`r'[道说笑哭骂叹答问喊叫吼唱念][着了过]?[：:]$'`

**审计确认**：
- ✅ offset 自修正：`seg.start_offset + quote_local_offset = 正确绝对偏移`
- ✅ quote 定位安全：`locate_quote_with_ambiguity` 用 `str.find()`，合并后仍可找到
- ✅ 不影响 extractor/compact_candidate/coverage/validator — 它们都消费 segment，不关心内部切分
- ⚠️ 需更新 segmenter 测试（test_dialogue_basic, test_dialogue_multiple, test_segment_offsets）

**改动**：segmenter.py ~30 行

**收益**：
- 消除大量 3-5 字残片段（实测：`"石道："` `"子兴道："` `"雨村道："` 等约 30 个）
- segment 完整率预计从 61.3% → ≥ 90%
- 说话人和对话不再拆散，LLM 看到完整的对话上下文

#### P1-2: segment_type + speaker 传入 prompt [P0]

**当前**（`_build_compact_prompt` 唯一消费 segments 的地方）：

```python
segments_formatted = "\n".join(f"[{s.id}] {s.text_slice}" for s in segments)
```

**改为**：

```python
segments_formatted = "\n".join(
    f"[{s.id}|{s.segment_type}] {s.text_slice}" for s in segments
)
```

对话 segment 如已含说话人（P1-1 合并后），格式为：

```
[seg_0055|dialogue] 那僧道：「大师，弟子蠢物...」
[seg_0056|sentence] 说着便走了。
[seg_0057|heading] 第二回 贾夫人仙逝扬州城
```

**审计确认**：codegraph trace 验证 `_build_compact_prompt` 只在这一行消费 segment，改动完全隔离

**改动**：extractor.py 1 行

**收益**：LLM 不需要重新判断文本类型

#### P1-3: block 边界标记 [P1]

不同 block_index 的 segments 之间插入空行。

**改动**：extractor.py `_build_compact_prompt` ~5 行

#### P1-4: 噪音预筛 [P1]

**问题**：`"红楼梦》"` `"曹雪芹 　高鄂  著"` `"至?"` 是封面/OCR 噪音

**改法**：在 extractor 中预筛，不送入 LLM：
- 书名/作者行：首个 paragraph block，非正文内容
- OCR 错误：含 `?` 的短段
- 超短段：<3 字且无标点结尾

**改动**：extractor.py ~15 行

---

### Phase 2: LLM 语义提取优化

#### P2-1: modality 从 segment_type 程序化默认 [P0]

LLM 不再输出 modality，程序推导：

```python
def _default_modality(segment_types: list[str]) -> str:
    """dialogue/heading/list_item/table_row → reported; sentence → asserted"""
    non_asserted = {"dialogue", "heading", "list_item", "table_row"}
    if any(t in non_asserted for t in segment_types):
        return "reported"
    return "asserted"
```

**改动**：compact_candidate.py ~15 行 + prompt 减少规则

**收益**：每个 Claim 省约 1 output token，modality 准确率提升

#### P2-2: source_segment_ids 程序化补全 [P1]

LLM 常遗漏 Entity 在后续 segment 中的出现。后处理扫描补全：

```python
def _backfill_source_segments(entity, all_segments):
    existing = set(entity.source_segment_ids)
    for seg in all_segments:
        if seg.id not in existing and entity.name in seg.text_slice:
            entity.source_segment_ids.append(seg.id)
```

**改动**：extractor.py ~15 行

#### P2-3: IgnoreSegment 程序化预筛 [P1]

heading、超短段、书名/作者行 → 程序标记为 IgnoreSegment，不进 LLM。

**改动**：extractor.py ~15 行

---

### Phase 3: 程序化后处理

#### P3-1: Relation 去重 + 稳定 ID [P0]

```python
# 1. 去重：相同 (subject, predicate, object) 只一条 Relation
seen = set()
for claim in eligible_claims:
    key = (claim.subject, claim.predicate, claim.object)
    if key in seen:
        continue
    seen.add(key)
    ...

# 2. 稳定 ID：从 claim_id 派生
rel_id = f"{claim.id}_rel"
```

**改动**：compact_candidate.py ~10 行

#### P3-2: Symbol name 前置分配 [P2]

当前 symbol name 在 codegen 才分配，导致两套命名空间。改为在 Phase 3 分配。

**改动**：compact_candidate.py（启用 `assign_symbols`）+ codegen.py — 需进一步评估对 codegen 的影响

---

### Phase 4: CodeGraph-native 输出

#### P4-1: _symbol 字段填充（字符串方案）[P1]

**当前**：SKIP_FIELDS 跳过所有 _symbol 字段，它们在 forward pipeline 中为 None

**改为**：codegen 从 `all_symbols` 推导 symbol 名，填充为字符串字面量

```python
# 改动后生成的代码
claim_zh_29bb13 = Claim(
    id='红楼梦1_3_clm_0001',
    subject='红楼梦1_3_ent_0004',
    subject_symbol='ent_zh_a06e8f',         # ← 新增：字符串
    predicate='is_child_of',
    object='红楼梦1_3_ent_0001',
    object_symbol='ent_zh_394e40',           # ← 新增：字符串
    ...
)
```

**实现**：在 `_format_object_v33` 的字段迭代中，对 _symbol 字段做 FK→symbol 推导：

```python
_SYMBOL_DERIVATION = {
    "subject_symbol": ("subject", False),
    "object_symbol": ("object", False),
    "segment_symbol": ("segment_id", False),
    "claim_symbol": ("claim_id", False),
    "participant_symbols": ("participants", True),
}

# 字段迭代中
if field_name in _SYMBOL_DERIVATION:
    fk_field, is_list = _SYMBOL_DERIVATION[field_name]
    if is_list:
        fk_values = getattr(obj, fk_field, []) or []
        syms = [all_symbols[v] for v in fk_values if v in all_symbols]
        if syms:
            kwargs.append(f"{field_name}={syms!r}")
    else:
        fk_value = getattr(obj, fk_field, None)
        if fk_value and fk_value in all_symbols:
            kwargs.append(f"{field_name}={all_symbols[fk_value]!r}")
    continue
```

**审计修正**：原方案 `subject_symbol=ent_zh_394e40`（bare Name）+ field_validator **不可行**：
1. Entity 无 `.symbol` 属性
2. `Claim.subject: str` 不接受 Entity 对象
3. field_validator 无法提取 symbol 名

正确方案：字符串字面量 `subject_symbol='ent_zh_394e40'`，Pydantic 安全。

**find-references 路径**：
- v5.0：FTS5 索引字符串值 → 找到 symbol 定义
- v5.1：给 Entity 加 `symbol: str` 字段 → bare Name + field_validator → AST find-references

**改动**：codegen.py ~30 行（删除 SKIP_FIELDS，加 _SYMBOL_DERIVATION + 推导逻辑）

#### P4-2: 消除死 import + Segment symbol 修正 [P0]

**死 import 根因**：codegen 生成 `from .text import seg_0145` 但代码用字符串 ID — import 未使用

**改法**：
1. 删除死 import（v5.0 _symbol 是字符串，仍然不用 import 的 symbol）
2. Segment symbol 用 ID 后缀：`hongloumeng_seg_0015` → `seg_0015`（非枚举序号 `seg_0002`）

**改动**：codegen.py ~13 行

#### P4-3: Validator 简化 → 降级到 v5.1

原评估：symbol ref 在 import 时自动验证 → ~60% 检查不再必要

**审计修正**：v5.0 _symbol 是字符串字面量，import 机制无法验证字符串值存在性。Validator dangling ref 检查仍需要。

**改动**：暂不删除 validator 代码

---

## 3. 优先级排序

| 优先级 | 改动 | 理由 | 改动量 | 审计结论 |
|--------|------|------|--------|---------|
| **P0** | P1-1 修复对话切分 | 地基问题 | ~30 行 | ✅ 可行，offset 自修正，需更新测试 |
| **P0** | P1-2 segment_type 传入 prompt | 1 行核心改动 | 1 行 | ✅ 可行，codegraph 确认隔离 |
| **P0** | P2-1 modality 程序化默认 | 消除 LLM 做程序事 | ~15 行 | ✅ 可行 |
| **P0** | P3-1 Relation 去重 + 稳定 ID | 确定性改进 | ~10 行 | ✅ 可行 |
| **P0** | P4-2 死 import 删除 + symbol 修正 | lint 干净 | ~13 行 | ✅ 可行 |
| P1 | P1-3 block 边界标记 | 结构传递 | ~5 行 | ✅ 可行 |
| P1 | P1-4 噪音预筛 | 减少浪费 | ~15 行 | ✅ 可行 |
| P1 | P2-2 Entity 补全 | SCR 提升 | ~15 行 | ✅ 可行 |
| P1 | P2-3 IgnoreSegment 预筛 | 减少浪费 | ~15 行 | ✅ 可行 |
| P1 | P4-1 _symbol 字段填充 | codegraph FTS5 索引 | ~30 行 | ⚠️ 字符串方案，非 AST Name 节点 |
| P2 | P3-2 Symbol name 前置分配 | 架构简化 | ~20 行 | ⚠️ 需评估对 codegen 的影响 |
| v5.1 | 真正的 AST symbol ref | find-references 核心 | Entity 加 symbol 字段 + field_validator | 前置：P4-1 |
| v5.1 | Validator 简化 (~-170 行) | import 机制替代手写 | 删除 dangling ref 检查 | 前置：AST symbol ref |

---

## 4. 实施路径

### Phase A: 地基修复（2-3 天）

**目标**：Segmenter 切分质量 + 结构信息传递

**改动**：P1-1, P1-2, P1-3, P1-4

**验证**：
- segment 完整率 61.3% → ≥ 90%
- 说话人 + 对话不再拆散
- E2E 红楼梦 Ch1-3，对比 ER/EP/SCR
- segmenter 测试全通过

### Phase B: 分工校正（2-3 天）

**目标**：程序做程序的事，LLM 做 LLM 的事

**改动**：P2-1, P2-2, P2-3, P3-1

**验证**：
- modality 准确率 ≥ 95%
- SCR 提升（source_segment_ids 补全）
- Relation 去重后无重复

### Phase C: CodeGraph-native（3-5 天）

**目标**：_symbol 字段填充，消除死代码，FTS5 可索引

**改动**：P4-1, P4-2

**验证**：
- `import output_code/红楼梦1-3/` 无错误
- Pyright parse 0 critical error
- _symbol 字段有值
- 死 import 消除

### Phase D: 全书验证（1-2 天）

**验证**：
- CQM 全指标对比
- 433+ 测试全通过

---

## 5. LLM-only 清单

| 任务 | 原因 |
|------|------|
| Entity 语义识别 | 程序给候选（speaker + NER），LLM 确认 + 补充新名字 |
| Claim 语义提取 | subject-predicate-object 需要理解句子含义 |
| Event 因果判断 | 程序给边界（heading/block），LLM 判断因果关系 |
| Coreference resolution | "他"指代需要上下文理解 |
| 隐含 Claim 推断 | "贾政哼了一声"→ disapproval |
| Residual 分类 | 文学判断（程序只能预筛噪音） |

---

## 6. 不做的事

| 方案 | 原因 |
|------|------|
| 追求 100% Entity 提取率 | 小说人物出现多次，偶尔遗漏不重要 |
| FK 字段改为 Entity 类型 | 循环引用 + 序列化复杂 |
| field_validator 方案 | Entity 无 .symbol 属性，Pydantic 不接受类型不匹配 |
| 通用文本处理 | 收敛场景，只做小说→代码 |
| 自建 Graph 数据库 | 外部 codegraph 工具替代 |
| Ontology 增加非 _symbol 字段 | 不改变模型结构 |

---

## 7. v5.1 路线图（本次不做，但设计上预留）

| 改动 | 前置条件 | 收益 |
|------|---------|------|
| Entity 加 `symbol: str` 字段 | P4-1 完成 | Entity 对象可提供 symbol 名 |
| `_symbol` 字段改为 bare Name | Entity.symbol 可用 | AST find-references 生效 |
| field_validator Entity→str | Entity.symbol 可用 | Pydantic 安全 + AST 引用 |
| 死 import 变为真 import | bare Name 使用 import 的 symbol | import graph 可分析 |
| Validator 简化 -170 行 | import 机制验证引用 | 代码简化 |
