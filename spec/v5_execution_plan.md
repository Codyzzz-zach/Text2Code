# T2C v5.0 执行计划

> **生成时间**: 2026-06-12
> **基线**: 429 tests passed, 4 skipped
> **未提交改动**: segmenter.py (+51), extractor.py (+355), validator.py (+84), compact_candidate.py (+1)

## 现状盘点

### 已实现（未提交）

| 改动 | 文件 | 状态 | 缺失 |
|------|------|------|------|
| P1-1 `_merge_speaker_dialogue` | segmenter.py:183-220 | ✅ 代码在 | ❌ 零测试覆盖 |
| P1-1 `_SPEAKER_ATTR_RE` | segmenter.py:15-19 | ✅ 代码在 | ❌ 零测试覆盖 |
| P1-1 调用点 | segmenter.py:74 | ✅ 代码在 | — |
| Pass0 entity scan | extractor.py:1099-1211 | ✅ 代码在 | ❌ 零测试覆盖 |
| Attention hints | extractor.py:913-972 | ✅ 代码在 | ❌ 零测试覆盖 |
| D3 self-ref + P1 uniqueness | validator.py | ✅ 代码在 | — |

### 未实现

| 改动 | 文件 | 优先级 |
|------|------|--------|
| P1-2 segment_type 传入 prompt | extractor.py:924, 1122, 1298 | P0 |
| P2-1 modality 程序化默认 | compact_candidate.py:577 | P0 |
| P3-1 Relation 去重 + 稳定 ID | compact_candidate.py:600-680 | P0 |
| P4-2 死 import 删除 | codegen.py:604-649 | P0 |
| P4-2 Segment symbol 从 ID 派生 | codegen.py:280-409 | P0 |
| P1-3 block 边界标记 | extractor.py:923 | P1 |
| P1-4 噪音预筛 | extractor.py | P1 |
| P4-1 _symbol 字段填充 | codegen.py:687-690 | P1 |

---

## Task 1: P1-1 补全测试 + 验证已有实现

**目标**：已有 `_merge_speaker_dialogue` 代码零测试，先补测试确保正确性

### 改动文件
- `tests/test_segmenter.py` — 新增 `TestSpeakerDialogueMerge` 类

### 测试用例

```python
class TestSpeakerDialogueMerge:
    """P1-1: speaker attribution + dialogue merge."""

    def test_speaker_merged_with_dialogue(self):
        """他说：「你好。」→ 1 个 dialogue segment"""
        text = '他说：「你好。」'
        block = Block(id="b", doc_id="d", index=0, block_type="paragraph",
                      start_offset=0, end_offset=len(text), text_slice=text, hash="h")
        segs = Segmenter().segment_block("d", block, text)
        assert len(segs) == 1
        assert segs[0].segment_type == "dialogue"
        assert '他说' in segs[0].text_slice
        assert '你好' in segs[0].text_slice

    def test_no_attribution_unchanged(self):
        """「你好。」再见。→ dialogue + sentence，不合并"""
        text = '「你好。」再见。'
        block = Block(id="b", doc_id="d", index=0, block_type="paragraph",
                      start_offset=0, end_offset=len(text), text_slice=text, hash="h")
        segs = Segmenter().segment_block("d", block, text)
        types = [s.segment_type for s in segs]
        assert "dialogue" in types
        assert "sentence" in types

    def test_colon_not_attribution(self):
        """注意：这是重点。→ 不合并（'注意：' 不匹配说话人模式）"""
        text = '注意：这是重点。'
        block = Block(id="b", doc_id="d", index=0, block_type="paragraph",
                      start_offset=0, end_offset=len(text), text_slice=text, hash="h")
        segs = Segmenter().segment_block("d", block, text)
        # 不应有 dialogue 类型
        assert all(s.segment_type != "dialogue" for s in segs)

    def test_multiple_pairs(self):
        """他说：「你好。」她答：「我很好。」→ 2 个合并后的 dialogue"""
        text = '他说：「你好。」她答：「我很好。」'
        block = Block(id="b", doc_id="d", index=0, block_type="paragraph",
                      start_offset=0, end_offset=len(text), text_slice=text, hash="h")
        segs = Segmenter().segment_block("d", block, text)
        dialogue_segs = [s for s in segs if s.segment_type == "dialogue"]
        assert len(dialogue_segs) == 2

    def test_merged_offset_integrity(self):
        """合并后 text_slice 与 offset 一致"""
        text = '那僧道：「大师，弟子蠢物，不能礼佛。」'
        block = Block(id="b", doc_id="d", index=0, block_type="paragraph",
                      start_offset=0, end_offset=len(text), text_slice=text, hash="h")
        segs = Segmenter().segment_block("d", block, text)
        for s in segs:
            assert text[s.start_offset:s.end_offset] == s.text_slice

    def test_merged_hash_correct(self):
        """合并后 hash 正确"""
        text = '宝玉笑道：「林妹妹，你放心。」'
        block = Block(id="b", doc_id="d", index=0, block_type="paragraph",
                      start_offset=0, end_offset=len(text), text_slice=text, hash="h")
        segs = Segmenter().segment_block("d", block, text)
        for s in segs:
            expected = f"sha256:{hashlib.sha256(s.text_slice.encode('utf-8')).hexdigest()}"
            assert s.hash == expected

    def test_speaker_with_modifier(self):
        """笑着说道：→ 合并（'着'修饰语）"""
        text = '她笑着说道：「我很好。」'
        block = Block(id="b", doc_id="d", index=0, block_type="paragraph",
                      start_offset=0, end_offset=len(text), text_slice=text, hash="h")
        segs = Segmenter().segment_block("d", block, text)
        dialogue_segs = [s for s in segs if s.segment_type == "dialogue"]
        assert len(dialogue_segs) == 1
        assert '笑着说道' in dialogue_segs[0].text_slice

    def test_gap_between_speaker_and_dialogue(self):
        """说话人和对话之间有间隔 → 不合并"""
        text = '他说：这是真的。「你好。」'
        block = Block(id="b", doc_id="d", index=0, block_type="paragraph",
                      start_offset=0, end_offset=len(text), text_slice=text, hash="h")
        segs = Segmenter().segment_block("d", block, text)
        # "他说：这是真的。" 是 sentence，和后面的 dialogue 不相邻
```

### 验证
```bash
pytest tests/test_segmenter.py -v
```

### 预期
- 8 个新测试全通过
- 已有 19 个 segmenter 测试不受影响

---

## Task 2: P1-2 segment_type 传入 prompt

**目标**：让 LLM 看到 segment_type，不再需要猜文本类型

### 改动文件
- `t2c/extractor.py` — 4 处改动

### 具体改动

#### 2a. COMPACT_PROMPT_PREFIX 格式说明（line 55）
```python
# 当前
每行格式：[segment_id] 文本内容

# 改为
每行格式：[segment_id|segment_type] 文本内容
```

#### 2b. _build_compact_prompt（line 923-924）
```python
# 当前
segments_formatted = "\n".join(
    f"[{s.id}] {s.text_slice}" for s in segments
)

# 改为
segments_formatted = "\n".join(
    f"[{s.id}|{s.segment_type}] {s.text_slice}" for s in segments
)
```

#### 2c. Pass0 entity scan（line 1122）
```python
# 当前
segments_text = "\n".join(f"[{s.id}] {s.text_slice}" for s in chunk)

# 改为
segments_text = "\n".join(f"[{s.id}|{s.segment_type}] {s.text_slice}" for s in chunk)
```

#### 2d. _build_prompt verbose（line 1298-1299）
```python
# 当前
segments_formatted = "\n".join(
    f"[{s.id}] {s.text_slice}" for s in segments
)

# 改为
segments_formatted = "\n".join(
    f"[{s.id}|{s.segment_type}] {s.text_slice}" for s in segments
)
```

### 验证
```bash
pytest tests/test_extractor.py -v
```

### 风险
- LLM 输出格式不变（segment_type 只在输入 prompt，不在输出 JSON）
- 如果 prompt 中有硬编码的 `[seg_0001]` 示例，需同步更新

---

## Task 3: P2-1 modality 程序化默认 + P3-1 Relation 去重/稳定ID

### P2-1: modality 从 segment_type 推导

**改动文件**：`t2c/compact_candidate.py`

#### 3a. expand_candidates Claim 构建（line 577）

```python
# 当前
"modality": c.fields.get("modality", "asserted"),

# 改为
```

在 Claim data 构建前加推导逻辑：

```python
# P2-1: modality 从 segment_type 程序化推导
modality_raw = c.fields.get("modality", None)
if modality_raw is None:
    seg_types = set()
    for sid in c.fields.get("source_segment_ids", []):
        seg = segments_by_id.get(sid)
        if seg:
            seg_types.add(seg.segment_type)
    non_asserted = {"dialogue", "heading", "list_item", "table_row"}
    modality_raw = "reported" if seg_types & non_asserted else "asserted"
```

然后在 data dict 中用 `"modality": modality_raw`。

#### 3b. _parse_single modality 默认（line ~250）

找到 `m = item.get("m", "asserted")` 改为 `m = item.get("m", None)`。
调整后续逻辑：`None` 时不报 warning，透传到 expand_candidates。

### P3-1: Relation 去重 + 稳定 ID

**改动文件**：`t2c/compact_candidate.py`

#### 3c. derive_relations 去重（line 600-680）

在 `for obj in objects` 循环前加：

```python
rel_dedup: dict[tuple, dict] = {}
```

在创建 Relation 前：

```python
dup_key = (subj, data.get("predicate", "related_to"), obj_val)
if dup_key in rel_dedup:
    # 合并 evidence_refs
    existing = rel_dedup[dup_key]
    existing_refs = existing["data"].setdefault("evidence_refs", [])
    new_refs = data.get("evidence_refs", [])
    for ref in new_refs:
        if ref not in existing_refs:
            existing_refs.append(ref)
    continue
```

创建后记录：

```python
rel_dedup[dup_key] = rel_obj  # 在 append 前
```

#### 3d. 稳定 ID 从 claim_id 派生

```python
# 当前
rid = f"{doc_id}_rel_{rel_counter:04d}" if doc_id else f"rel_{rel_counter:04d}"
rel_counter += 1

# 改为
cid = data.get("id", "")
if doc_id and "_clm_" in cid:
    rid = cid.replace("_clm_", "_rel_clm_", 1)
else:
    rid = f"{doc_id}_rel_{rel_counter:04d}" if doc_id else f"rel_{rel_counter:04d}"
    rel_counter += 1
```

### 验证
```bash
pytest tests/ -v -k "compact or relation"
```

---

## Task 4: P4-2 死 import 删除 + Segment symbol 修正

### 死 import 删除

**改动文件**：`t2c/codegen.py`

#### 4a. _generate_type_file_v33（line 604-649）

当 `emit_symbol_refs=False` 时，跳过 import 生成：

```python
# 在 for obj in objects 循环前（line 608）
if self._emit_symbol_refs:
    for obj in objects:
        # ... 现有 import 生成逻辑 (lines 608-644) ...
```

缩进现有循环体一级。当 `emit_symbol_refs=False` 时，`mod_syms` 保持空，不生成任何 `from .text import` / `from .entities import` 行。

### Segment symbol 从 ID 派生

#### 4b. _compute_symbol_names Segment 分支（line ~301-308）

找到 Segment 的 symbol 计算逻辑，改为从 ID 派生：

```python
if type_name == "Segment":
    obj_id_val = getattr(obj, "id", None) or str(i)
    if "_seg_" in obj_id_val:
        base = "seg_" + obj_id_val.rsplit("_seg_", 1)[-1]
    else:
        base = f"seg_{i:04d}"
    name = base
    suffix = 0
    while name in used:
        suffix += 1
        name = f"{base}_{suffix}"
    symbols[obj_id_val] = name
```

### 验证
```bash
pytest tests/test_codegen.py -v
```

手动检查：生成红楼梦 Ch1-3 的 output_code，确认：
- claims.py / events.py 无 `from .entities import` 行（当 emit_symbol_refs=False）
- text.py 中 Segment symbol 名为 `seg_0001` 格式（非枚举序号）

---

## Task 5: P1 附加 + P4-1 _symbol 填充

### P1-3: block 边界标记

**改动文件**：`t2c/extractor.py`

在 `_build_compact_prompt` 中，不同 `block_index` 的 segments 之间插入空行：

```python
# 在 segments_formatted 构建中
parts = []
prev_block = None
for s in segments:
    if prev_block is not None and s.block_index != prev_block:
        parts.append("")  # 空行分隔
    parts.append(f"[{s.id}|{s.segment_type}] {s.text_slice}")
    prev_block = s.block_index
segments_formatted = "\n".join(parts)
```

### P1-4: 噪音预筛

**改动文件**：`t2c/extractor.py`

在 `_build_compact_prompt` 中过滤噪音 segment：

```python
def _is_noise_segment(seg: Segment, is_first_block: bool) -> bool:
    """预筛噪音 segment，不送入 LLM。"""
    text = seg.text_slice.strip()
    # 超短段：<3 字且无标点结尾
    if len(text) < 3 and not text[-1:] in '。！？.!?':
        return True
    # OCR 错误：含 ? 的短段
    if '?' in text and len(text) < 10:
        return True
    # 书名/作者行：首个 block 中的 heading
    if is_first_block and seg.segment_type == "heading":
        return True
    return False
```

### P4-1: _symbol 字段填充

**改动文件**：`t2c/codegen.py`

在 `_format_object_v33` 中删除 SKIP_FIELDS，改为 _SYMBOL_DERIVATION 推导：

```python
# 删除
SKIP_FIELDS = {
    "subject_symbol", "object_symbol", "segment_symbol",
    "participant_symbols", "claim_symbol",
}

# 替换为
_SYMBOL_DERIVATION = {
    "subject_symbol": ("subject", False),
    "object_symbol": ("object", False),
    "segment_symbol": ("segment_id", False),
    "claim_symbol": ("claim_id", False),
    "participant_symbols": ("participants", True),
}
```

字段迭代中：

```python
for field_name in fields:
    # _symbol 字段：FK→symbol 推导
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

    value = getattr(obj, field_name, None)
    if value is None:
        continue
    # ... 现有逻辑 ...
```

### 验证
```bash
pytest tests/ -v
```

---

## 执行顺序与依赖

```
Task 1 (P1-1 测试)     ← 先做，验证已有代码
  │
  ▼
Task 2 (P1-2 prompt)   ← 依赖 segment_type 正确（P1-1 保证）
  │
  ▼
Task 3 (P2-1+P3-1)     ← 独立，compact_candidate
  │
  ▼
Task 4 (P4-2 codegen)  ← 独立，codegen
  │
  ▼
Task 5 (P1-3+P1-4+P4-1) ← P1 附加 + _symbol 填充
  │
  ▼
E2E 验证               ← 全量回归 + CQM 对比
```

## 全局验证

每个 Task 完成后：
1. `pytest tests/ -v` — 429+ tests 全通过
2. `python3 -m t2c compile-library` — 红楼梦 Ch1-3 E2E
3. 检查 `output_code/` 生成代码质量

全部 Task 完成后：
4. CQM 指标对比基线（ER 27.7%, EP 76.5%, SCR 24.55%）
5. `py_compile` 检查生成代码可导入
6. segment 完整率 ≥ 90%（基线 61.3%）

## 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| P1-1 合并破坏 offset | 低 | 高 | Task 1 8 个测试覆盖 |
| P1-2 prompt 格式变化导致 LLM 输出变 | 中 | 中 | segment_type 只在输入，不影响输出 schema |
| P2-1 modality 推导错误 | 低 | 低 | dialogue→reported 是正确映射 |
| P3-1 去重误删 Relation | 低 | 中 | (subj, pred, obj) 三元组去重，保留 evidence_refs 合并 |
| P4-2 死 import 删除后 Pyright 报错 | 低 | 低 | emit_symbol_refs=False 时本就不该有 import |
| P4-1 _symbol 字段 Pydantic 验证失败 | 低 | 中 | 字符串字面量，Pydantic str 类型天然安全 |
