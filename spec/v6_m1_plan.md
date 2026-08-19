# T2C v6.0 M1 实施计划：形态完整

> **Status**: 已确认（三个决策点已拍板）
> **Date**: 2026-08-19
> **母文档**: spec/t2c_design_v6.0.md（边界与能力矩阵）
> **M1 目标**: 点亮矩阵 C4 C5 C6 C7 C9 C10，ARR 0% → 100%

---

## 0. 决策记录（2026-08-19 拍板）

| # | 决策 | 结论 |
|---|------|------|
| ① | Residual / IgnoreSegment 是否补 `segment_symbol` 字段 | **补**。让 ARR 覆盖这两类的 segment_id FK，消除"有对应符号面者"的 hedge |
| ② | Claim 符号 hash 公式 | **统一为 `sha256(key + id)[:6]`**（与 compact_candidate 旧实现对齐；修复 codegen 版同 (s,p,o) 撞 hash 靠 suffix 的尴尬） |
| ③ | symbol 分配的位置 | **compile 入口单点分配**（见 §1 的证伪过程） |

## 1. 关键发现：P3-2"前置到 extract"被代码证伪

代码库存在两套已分叉的 symbol 命名实现：

| 分支 | `compact_candidate.assign_symbols`（v3.3，仅测试用） | `codegen._compute_symbol_names`（现产） |
|------|------|------|
| Segment | 无分支 → `obj_*` | `seg_{id后缀}` |
| Residual / IgnoreSegment | 无分支 → `obj_*` | `res_{seg_sym}` / `ign_{seg_sym}` |
| Claim hash | `sha256(key+id)` | `sha256(key)`（不含 id） |
| 混合名 Entity | 纯 ASCII 才 normalize | 提取 ASCII 片段 |
| 唯一性作用域 | 全批次共享 | 按文件分区 |

"启用 assign_symbols"等于一次未申报的符号面 breaking change。

**且前置到 extract 没有必要**：M1 需要的 `symbol='...'` 是生成代码里的自声明字面量，pipeline（extract/validate/store）各阶段均不消费 symbol。单点分配放在 `compile_to_knowledge_code` 入口即可：

- 输入是 CLI 已按 id 排序的最终对象列表 → 确定性天然成立
- 不用穿批次携带 `existing_symbols` 状态
- 不用担心 repair 删对象后的符号漂移
- 不用改 schema 透传（`validate_and_construct` 不搬 `obj["symbol"]`）
- ObjectStore 是 `model_dump_json`，新字段默认 None，向后兼容

**连带决定：唯一性作用域升为全包全局**——C7 要求 `__init__.py` 全量 re-export，只有全局唯一才能保证无冲突。

## 2. 落地设计（D1–D5）

### D1. ontology.py（约 +40 行，v6.0 唯一特批字段变更）

- `Segment / Entity / Event / Claim / Relation / Residual / IgnoreSegment` 各加 `symbol: str | None = None`（自声明）
- `Residual / IgnoreSegment` 各加 `segment_symbol`（决策①）
- **Pyright 兼容（C8 硬约束）**：`*_symbol` 字段类型必须容忍被引对象，否则 bare Name 触发类型错误。采用精确 union：
  - `EvidenceRef.segment_symbol: str | Segment | None`（需把 EvidenceRef 定义移到 Segment 之后，无循环——Segment 不引用 EvidenceRef）
  - `Claim.subject_symbol / object_symbol: str | Entity | None`
  - `Event.participant_symbols: list[str | Entity]`
  - `Relation.subject_symbol / object_symbol: str | Entity | None`，`claim_symbol: str | Claim | None`（Relation 定义在 Claim 之后，无 forward ref）
  - `Residual / IgnoreSegment.segment_symbol: str | Segment | None`
- 每个模型挂定向 `field_validator(mode="before")`：BaseModel 值解包为其 `.symbol`，str/None 透传；list 字段逐元素。**禁止 wildcard validator**——会把 `evidence_refs` 里的 EvidenceRef 实例误解包成 None

### D2. t2c/symbols.py（新模块，约 100 行）

```python
compute_symbol_table(doc, blocks, segments, entities, events, claims,
                     relations, residuals, ignores) -> SymbolTable
```

- 固定类型序：Document → Block → Segment → Entity → Event → Claim → Relation → Residual → IgnoreSegment；类内按 id 排序；全局 used set
- 命名规则（以现 codegen 版为准，修正后）：
  - Segment: `seg_{id中_seg_后缀}`；Block: `blk_{index:04d}`（修复现产的 `bloc_` 拼写）；Document: `doc_{sanitized}`
  - Entity/Event: `{ent|evt}_{ascii_norm}` 或 `{ent|evt}_zh_{sha256(name+id)[:6]}`
  - Claim: `claim_{norm}`（≤30）或 `claim_zh_{sha256(key+id)[:6]}`（决策②）
  - Relation: `_rel_clm_` 在 id 中 → `rel_clm_{NNNN}`；否则 `rel_{i:04d}`
  - Residual/IgnoreSegment: `res_{seg_sym}` / `ign_{seg_sym}`，seg 不在表 → `res_{i:04d}` fallback
- 跨类型同 id → CodegenError（防御）
- `SymbolTable` 携带 `id_to_symbol` + `symbol_to_module`（供 import 生成反查）

### D3. codegen.py 重构（净减行）

- `generate_multi_file_compilation` 开头一次 `compute_symbol_table`，全文件生成共享
- 赋值 LHS 读表；有 `symbol` 字段的模型 kwargs 增加 `symbol='...'` 自声明字面量（FIELD_ORDER 中 id 之后）
- `_SYMBOL_DERIVATION` 去 `!r` → **bare Name**；同时记录本文件用到的外部符号（驱动活 import）：
  - 严格字段（subject_symbol / segment_symbol / claim_symbol / participant_symbols）：FK 不在表 → CodegenError（编译期 dangling gate，C10 的另一半）
  - 宽松字段（object_symbol）：FK 为 None 跳过；看似 entity id 但不在表 → CodegenError；字面量 object → 跳过
- import 生成 = 本文件实际发射的 bare Name 按 symbol→module 分组，零死 import（C4）
- `__init__.py` 全量显式 re-export + `__all__`，按 DAG 序（text → entities → events → claims → residuals → derived → coverage）（C7）
- 删除：`emit_symbol_refs` 双模式、`_compute_symbol_names`（迁入 symbols.py）、claims 分区重算 entity 符号的冗余（codegen.py:1020）
- 版本头 `v6.0`

### D4. validator.py 简化

- 删除 `_validate_symbol_references` + `_build_symbol_type_map` + `_get_symbol_ref_expected_types`（生成方向验证由 import 系统 + Pyright 接管）
- pipeline 期 FK dangling 检查**保留**（LLM 输出质量门；codegen gate 是第二道）
- 验收盯 C10 负例 + Pyright 0 错，不盯删除行数

### D5. scripts/verify_codegraph.py（新，约 150 行）

核心发现：**ARR 验收不依赖外部工具链**，stdlib `ast` 足够：

- C1: py_compile 全文件
- C2: AST 定义数 == 对象数、符号零冲突
- C4: 每个 import 的 symbol 都被使用（ast.Name 出现 ≥1）
- ARR: 每个 `*_symbol` kwarg 的值是 ast.Name（或 list[Name]），且 Name.id ∈ 全包符号表；字符串字面量计入未达标
- C7: `from <pkg> import <symbol>` 抽样 import 测试
- C10: `--break-symbol <sym>` 负例：临时移除定义后 import 必须 ImportError
- C11/C12 数据层：evidence 非空率、hash 回放抽样
- SCIP / Pyright 作为独立复验（`--scip` / `--pyright` 可选接入，M2）

## 3. import DAG（已验证无环）

```text
text ← entities ← claims ← derived
text ← entities ← events
text ← residuals
全部 ← __init__
```

同模块内无 `_symbol` 引用（Claim.derived_from 无符号通道，维持字符串，不计入 ARR）。

## 4. 风险与测试迁移面

| 风险/影响面 | 处理 |
|------------|------|
| `test_phase3_compact` / `test_phase4_5_integration` / `test_phase6_v4_compile` 引用 `assign_symbols` / `expand_and_assign_symbols` | 迁移到 symbols 模块或删除旧测试类 |
| `test_codegen_v3_3` 引用 `_compute_symbol_names` | 迁移到 `compute_symbol_table` |
| `test_codegen_codegraph_compat` 依赖 `emit_symbol_refs` 双模式 | 重写为 v6 单模式 |
| `test_validator_symbols_v3_3` | 删除（职责被 import 系统接管）， gate 行为由 codegraph 契约测试覆盖 |
| claim 符号名 churn（hash 公式变更） | 一次性；rebuild gate 的首个真实测试对象 |
| parser.py 回读 bare Name | 已兼容（v3.3 `__symbol__` marker 机制） |
| scip-python 对 7767 行 text.py 的性能 | M2 实测，不达标则 text.py 按 block 分页 |

## 5. 完成定义

- `pytest` 全绿（含迁移后）
- `t2c compile-library --text-only` 与（缓存允许时）`--llm --cache-mode read_only` 产物通过 `verify_codegraph.py`
- ARR = 100%，C10 负例必现，import 全活
