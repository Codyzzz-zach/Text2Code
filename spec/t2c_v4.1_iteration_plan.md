# T2C v4.1 迭代优化方案：基于红楼梦第十回全流程测试

> **Status**: 修订版（基于 ch10 基线实测数据）
> **Date**: 2026-06-08
> **目的**: 通过第十回全流程测试，发现并量化现有 pipeline 的优化点，建立持续改进的量化指标体系，同时设定边界防止偏离 spec 设计哲学

---

## 0. 方案核心思路

**一次测试 → 两层产出**：

1. **产出 A**：第十回的 `.t2c.py` 编译产物（产品本身）
2. **产出 B**：一套量化指标 + 优化迭代清单（让项目可持续改进）

关键约束：**所有优化必须在 v4.0 spec 的哲学边界内**。spec 说"T2C 是编译器"，优化方向是"编译质量"，不是"加功能"。

---

## 1. 基线实测数据（ch10，当前代码原样运行）

### 1.1 CQM 基线指标

| 指标 | 基线值 | 说明 |
|------|--------|------|
| **ER 实体召回率** | **8.3%** | 12 个已知人物仅抽到 1 个正确（秦钟） |
| **EP 实体精确率** | **12.5%** | 8 person entity 中仅 1 个命中 ground truth |
| **RR 引用正确率** | **0%** | events.py/claims.py 导入就崩溃 |
| **SCR 段覆盖率** | **9.0%** | 133 段仅 12 段 covered |
| **ECR Evidence 覆盖率** | **100%** | 所有语义对象都有 EvidenceRef |
| **RD Residual 区分度** | **0.0** | 111 个 residual 全是 `structural + medium` |
| **PC Predicate 一致率** | **低** | 8 个 unique predicate 全是自由词 |
| **IR 代码可导入率** | **50%** | 6 个语义文件中 3 个导入失败 |
| **SRR 符号引用率** | **100%** | 引用都用符号（但传 Entity 对象给 str 字段→崩溃） |

### 1.2 基线暴露的问题清单（按严重度）

| # | 问题 | 严重度 | 影响 | 根因 |
|---|------|--------|------|------|
| B1 | **符号引用传 Entity 对象给 str 字段** | 🔴 P0 阻断 | events/claims/residuals 无法导入 | `_format_value_v33` 的 `use_symbol` 逻辑把 Entity ID 替换为符号名，但运行时符号名解析为 Entity Pydantic 对象，而 Claim.subject 类型是 `str` |
| B2 | **residuals.py 缺 `from .text import`** | 🔴 P0 阻断 | residuals.py 无法导入 | `_generate_type_file_v33` 只扫描 evidence_refs 构建 segment import，但 Residual 的 `segment_id` 不在 evidence_refs 中 |
| B3 | **residuals.py 缺 IgnoreSegment import** | 🟠 P1 | 有 IgnoreSegment 时 NameError | `_generate_type_file_v33` 的 type_names 只有 `["Residual", "EvidenceRef"]`，不含 `"IgnoreSegment"` |
| B4 | **3/5 LLM batch 连接失败** | 🟡 P2 | 覆盖率低 | API 稳定性问题，非代码问题 |
| B5 | **实体召回率 8.3%** | 🟡 P2 | 编译质量极低 | LLM prompt 未充分指导人物抽取 |
| B6 | **Predicate 无受控词表** | 🟡 P3 | CodeGraph 索引质量低 | 无受控词表配置 |
| B7 | **Residual 零区分度** | 🟡 P3 | 诊断价值为零 | pipeline 中 `_generate_raw_fallbacks` 模板化 |

### 1.3 B1 问题深度分析

**现象**：生成的代码是 `subject=ent_zh_3c0877`，但运行时 `ent_zh_3c0877` 解析为 Entity Pydantic 对象，而 `Claim.subject: str` 字段期望字符串 → Pydantic ValidationError。

**根因**：v4.1 的 CodeGraph 适配改动中，`emit_symbol_refs=True` 使得 `_format_value_v33` 把 Entity ID 替换为符号名。这在语法上正确（Python 会解析符号名），但在 Pydantic 语义上不正确（Entity 对象不是 str）。

**设计冲突**：
- CodeGraph 需要 `subject=ent_zh_3c0877`（ast.Name → 构建 references 边）
- Pydantic 需要 `subject='hongloumeng_ent_0001'`（str 类型验证）

**解决方案**：两种兼容方式：

**方案 A（推荐）：双模式输出 — 字符串字面量 + 类型注解注释**
```python
# claims.py
claim_zh_394d20 = Claim(
    subject='hongloumeng_ent_0001',  # type: ent_zh_3c0877
    object='心细思虑过度',
    ...
)
```
- CodeGraph 通过 `# type: ent_zh_3c0877` 注释做 FTS5 索引（CodeGraph 支持 comment 解析）
- Pydantic 正确接收 str 类型
- 保留跨文件 import（供 CodeGraph 的 import 边使用）

**方案 B：改 ontology 字段类型**
```python
class Claim(BaseModel):
    subject: str | Entity  # Union type
```
- 破坏 Pydantic schema 一致性
- spec §6.3 明确禁止增加字段
- ❌ 不合规

**结论**：采用方案 A。

---

## 2. 量化指标体系（CQM）

### 2.1 指标定义

| 指标 | 缩写 | 定义 | 计算方式 | 目标 |
|------|------|------|----------|------|
| 实体召回率 | ER | 命名人物被正确抽取的比例 | `正确 person entity 数 / 章节实际人物数` | ≥ 70% |
| 实体精确率 | EP | 抽取的 person entity 中正确的比例 | `正确 person entity 数 / 总 person entity 数` | ≥ 75% |
| 引用正确率 | RR | Claim/Event 引用字段可正确解析的比例 | `可导入文件数 / 总语义文件数` | 100% |
| 段覆盖率 | SCR | 至少被一个语义对象覆盖的段比例 | `(covered + partial) / total_segments` | ≥ 35% |
| Evidence 覆盖率 | ECR | 有 EvidenceRef 的语义对象比例 | `有 evidence 的对象数 / 总语义对象数` | ≥ 60% |
| Residual 区分度 | RD | Residual category/importance 分布的熵 | `H(categories) + H(importance)` | > 1.0 |
| Predicate 一致率 | PC | 使用受控词表 predicate 的比例 | `受控词表内 predicate 数 / 总 predicate 数` | ≥ 85% |
| 代码可导入率 | IR | 生成的 .t2c.py 文件可被 `python import` 的比例 | `可导入文件数 / 8` | 100% |
| 符号索引率 | SIR | 引用字段有 `# type:` 注释供 CodeGraph FTS5 索引的比例 | `有注释的引用字段数 / 总引用字段数` | 100% |

---

## 3. 优化迭代清单

### 3.1 迭代 I-1：修复符号引用导致导入崩溃（方案 A）

| 项 | 值 |
|---|---|
| 问题 | B1: `subject=ent_zh_3c0877` 传 Entity 对象给 str 字段 |
| 影响 | RR=0%, IR=50% |
| 改动 | `_format_value_v33`：当 `use_symbol=True` 且字段是 str 类型时，输出 `subject='hongloumeng_ent_0001'  # type: ent_zh_3c0877` |
| Spec 合规 | ✅ 字符串字面量满足 Pydantic 验证，`# type:` 注释供 CodeGraph FTS5 索引，不改变 ontology |
| 优先级 | P0 |
| 预期指标变化 | IR: 50% → 100%, RR: 0% → 100% |

### 3.2 迭代 I-2：修复 residuals.py import 缺失

| 项 | 值 |
|---|---|
| 问题 | B2+B3: residuals.py 缺 `from .text import seg_*` 和 `IgnoreSegment` import |
| 影响 | IR（residuals.py 无法导入） |
| 改动 | `_generate_type_file_v33`：1) 扫描 Residual.segment_id 构建 segment import；2) 有 IgnoreSegment 时 type_names 加入 `"IgnoreSegment"` |
| Spec 合规 | ✅ 修复 bug |
| 优先级 | P0 |
| 预期指标变化 | IR: 加入 residuals.py 可导入 |

### 3.3 迭代 I-3：改进 Entity 抽取 prompt

| 项 | 值 |
|---|---|
| 问题 | B5: ER=8.3%, EP=12.5% |
| 影响 | ER↓ EP↓ |
| 改动 | `extractor.py` 中 LLM prompt 优化：显式要求抽取所有命名人物、提供 person 子类型示例 |
| Spec 合规 | ✅ spec §1.4 LLM 职责 = 输出 candidate JSON |
| 优先级 | P1 |
| 预期指标变化 | ER: 8% → ≥50%, EP: 12% → ≥60% |

### 3.4 迭代 I-4：Predicate 受控词表

| 项 | 值 |
|---|---|
| 问题 | B6: Predicate 无受控词表 |
| 影响 | PC↓ |
| 改动 | 定义 `PREDICATE_VOCABULARY`；extractor prompt 要求使用；validator 加 warning gate |
| Spec 合规 | ⚠️ 受控词表是配置不是字段→合规。warning gate 不影响 12-gate 结构 |
| 优先级 | P2 |

### 3.5 迭代 I-5：Residual 分类细化

| 项 | 值 |
|---|---|
| 问题 | B7: RD=0 |
| 影响 | RD↓ |
| 改动 | 改进 `_generate_raw_fallbacks`：按段内容分配 category 和 importance |
| Spec 合规 | ✅ pipeline 内部逻辑 |
| 优先级 | P2 |

### 3.6 迭代 I-6：LLM 批处理重试策略

| 项 | 值 |
|---|---|
| 问题 | B4: 3/5 batch 失败 |
| 影响 | SCR↓ |
| 改动 | extractor 加重试逻辑：连接失败时指数退避重试 3 次 |
| Spec 合规 | ✅ extractor 内部策略 |
| 优先级 | P2 |

---

## 4. 测试流程

### 4.1 Phase A：基线 ✅ 已完成

- 已跑 ch10 全流程，采集 CQM 指标
- 基线数据见 §1

### 4.2 Phase B：逐项迭代

按优先级执行 I-1 → I-2 → I-3 → I-4 → I-5 → I-6：
1. 实现改动
2. 运行 `pytest` 确保全部测试通过
3. 重跑 ch10 全流程
4. 采集 CQM 指标
5. 对比基线，记录 delta
6. 检查 spec 合规性

### 4.3 Phase C：回归验证

1. 运行 `python3 -c "from examples.knowledge.hongloumeng.ch10 import *"` 验证可导入
2. 运行 `pytest` 全部通过
3. Spec Alignment Score ≥ 0.9

---

## 5. 指标边界与 Spec 对齐检查

### 5.1 Spec Alignment 检查清单

```text
□ LLM 只输出 candidate JSON（不写 .t2c.py、不算 hash、不生成 symbol）
□ 没有引入新的运行时状态（ObjectStore/Graph/Query API）
□ Ontology 模型没有新增非 _symbol 字段
□ Pipeline 仍然停在"代码写入磁盘"（没有第 12 步）
□ 12-gate 结构未被改变
□ .t2c.py 输出仍然是 8 文件包结构
□ 所有 reference 字段传入 Pydantic 兼容类型（str，非 Entity 对象）
```

---

## 6. 成功标准

### 6.1 量化目标

| 指标 | ch10 基线 | 目标 |
|------|-----------|------|
| ER 实体召回率 | 8.3% | ≥ 50% |
| EP 实体精确率 | 12.5% | ≥ 60% |
| RR 引用正确率 | 0% | 100% |
| SCR 段覆盖率 | 9.0% | ≥ 30% |
| ECR Evidence 覆盖率 | 100% | ≥ 60% |
| RD Residual 区分度 | 0 | > 0.5 |
| IR 代码可导入率 | 50% | 100% |
| SIR 符号索引率 | N/A | 100% |

### 6.2 不退化的硬约束

- 433+ 测试全部通过
- Spec Alignment Score ≥ 0.9
