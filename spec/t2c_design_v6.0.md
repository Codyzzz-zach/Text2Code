# Text2Code 设计说明书 v6.0：边界再收敛与 CodeGraph 能力矩阵

> **Status**: 当前权威 spec（supersedes v5.0 优化方案；历史文档见 spec/archive/）
> **实现状态**: M1+M2+M3 已完成（commits 5bd2759 / c68a320）——能力矩阵在 golden fixture 上全绿
> **Date**: 2026-08-19
> **一句话**: T2C 只做一件事——把文本编译成 Python Knowledge Code 包，且该包被 codegraph 工具链 100% 利用。
> **验收公式**: 对 golden fixture（红楼梦 1-3 回），能力矩阵 C1–C12 全绿，由验证脚本在每次 compile 强制复验。

---

## 0. 产品边界（v6.0 唯一收敛点）

```text
input_txt/<book>.txt ──► [T2C 编译器] ──► output_code/<book>/*.py
                                              │
                                              ▼
                                  tree-sitter / SCIP / Pyright / Sourcegraph
                                  （唯一的消费者，点名，不抽象）
```

**做**：text → code 这一个环节，做到 codegraph 可利用度 100%。

**不做**（v6.0 显式排除，含本轮新砍）：

| 不做 | 说明 |
|------|------|
| agent loop / demo 应用 | 应用层，不归编译器 |
| 用户故事驱动的产品扩张 | 消费者是 codegraph 工具，验收是机械的能力矩阵 |
| 查询 API / 图数据库 / Web UI / 评测工厂 | v4.0 已砍，维持 |
| 跨书编译、法律/医疗等域扩张 | 维持 v5 垂直小说边界 |
| ER 等质量数字本身不作为验收门槛 | 属编译器质量追踪（CQM），不进 codegraph 矩阵 |

---

## 1. 思路现状：当前代码库是什么样的

### 1.1 流水线实际形态（与 spec 图的差异已核实）

```text
raw text
 → corpus.ingest + create_blocks            # Document/Block，sha256
 → segmenter.segment_block                  # v5.0: 说话人+对话合并（_merge_speaker_dialogue）
 → extractor.extract_chapter                # compact-v1 协议；Pass0 实体扫描 → attention hints；
                                           #   prompt 带 [seg_id|segment_type]、block 空行分隔、噪音预筛
 → compact_candidate.expand_candidates      # EvidenceRef 程序定位+hash；modality 由 segment_type 推导
 → derive_relations                         # (subj,pred,obj) 去重；稳定 ID 从 claim_id 派生
 → validator.validate_objects               # schema + id 唯一性 + reference + symbol ref + evidence
                                           #   + claim_safety（6 规则）+ coverage（opt-in，仅 warning）
 → pipeline._repair                         # 注意：修复=删除出错对象，非 LLM 修复
 → object_store（SQLite，内部 staging）
 → codegen v3.3 多文件生成                   # symbol 分配；_symbol 字段=字符串；死 import 已删
 → cli 事务化写盘 + py_compile/import 验证
```

### 1.2 产物现状（output_code_v5_final/红楼梦1_3，实测）

| 维度 | 数值/状态 |
|------|----------|
| 规模 | 609 segments / 89 entities / 46 claims / 25 events / 489 residuals / **4 relations** |
| 文件 | 8 文件包，text.py 7767 行，全量 py_compile 通过 |
| 跨文件 import | **0 条**（P4-2 删死 import 后，文件间无任何 AST 边） |
| `_symbol` 字段 | 已填充，但是**字符串字面量**（FTS5 可搜，AST 不可导航） |
| `__init__.py` | 仅 3 行注释，无符号面 |
| evidence_refs 空率 | entity 44% / claim 20% / event 24% |
| 引用完整性 | ❌ 存在悬空引用：`hongloumeng_seg_*` 与 `红楼梦1_3_seg_*` 两个命名空间混用于同一文件 |
| 头骨指标 ARR | **0%**（全部引用关系以字符串存在，无一为 AST Name 节点） |

### 1.3 工程现状

- 测试：437 passed / 4 skipped；**无 CI**；CQM 质量评估靠手动 `scripts/test_matrix.py quality`
- validator：12-gate 名义下实际 9~10 道；rebuild gate 零实现；no_silent_loss 非门禁
- 质量基线（v4.1 ch1-3 归档报告，v5 后未重测）：ER 27.7% / EP 76.5% / SCR 24.55% / ECR 74.4% / RD 0.92 / IR 100%

---

## 2. 推进本次目标的限制

### 2.1 哲学约束（自我承诺，不可违反）

1. LLM 只输出 candidate JSON——不写 `.py`、不算 offset/hash、不生 symbol、不产 coverage
2. 编译器无运行时状态——compile 完即结束，磁盘上的包是全部契约
3. 只从原文编译，无 summary→code 路径
4. 不做应用层（见 §0 不做清单）

### 2.2 技术约束（设计空间的真实形状）

| 约束 | 推论 |
|------|------|
| Pydantic：FK 字段类型为 `str` | 真 AST 引用只能落在 `*_symbol` 字段，配 `mode="before"` field_validator 提取 `.symbol`；FK 字符串面不动 |
| import DAG 必须无环 | `text ← entities ← claims ← derived`；`text ← entities ← events`；`text ← residuals`。新增引用边前必须验证不破坏无环性 |
| ontology 冻结（v4.0 起） | v6.0 唯一特批：各语义模型加 `symbol: str` 字段。除此之外零字段变更 |
| 确定性 | symbol 由 `hash(name+id)` 派生；ID 由 doc_id+计数器派生；LLM 有确定性缓存 → rebuild gate（字节一致重编译）可行 |
| 产物依赖 `t2c.ontology` | 验收环境必须安装 text2code 包本身；v6.0 接受此耦合（ontology 是跨书共享的 schema 层） |
| LLM 成本 | 验收复跑依赖 `--cache-mode read_only` 零成本路径 |

### 2.3 生态约束（codegraph 工具的现实，已核实）

| 工具 | 现实 | 对设计的影响 |
|------|------|------------|
| SCIP / scip-python | 索引符号定义与 Name 引用；**字符串字面量不是 occurrence** | bare Name 是硬前置，字符串 `_symbol` 永远无法产生引用边 |
| tree-sitter | 只给语法树 | 仅用于 C1 层验收 |
| Pyright | 需要 import 可解析 + t2c.ontology 可见 | 验收环境依赖；hover/类型检查随之免费 |
| CodeQL | 默认排除生成代码 | **不作为验收工具** |
| Sourcegraph | 消费 SCIP 索引 | 演示层，非验收层 |
| 单文件 700+ Segment 定义 | scip-python 对大文件性能未实测 | M2 的第一项实测任务 |

### 2.4 环境与数据约束

- 无 CI：验收必须先落成脚本（exit code + JSON），再谈接入
- golden fixture 仅红楼梦 1-3 回；人物 ground truth 47 人（归档基线）
- 当前产物自身过不了 C10/C11（悬空引用 + evidence 空缺）——验收先行会立即红

---

## 3. 目标定义：CodeGraph 能力矩阵

**"代码可以被 codegraph 100% 利用"的精确定义 = 以下 C1–C12 全绿。**

### L0 可解析层

| # | 能力 | 验证 | 阈值 |
|---|------|------|------|
| C1 | 每文件语法可解析 | tree-sitter + py_compile | 8/8 文件 |
| C2 | 每对象是可索引的顶层符号定义，符号零冲突 | AST/SCIP definitions | 100% 对象 |
| C3 | 中文名全文检索可命中定义行（行内注释） | FTS5/grep 抽样 | Top-20 人物 100% |

### L1 可导航层

| # | 能力 | 验证 | 阈值 |
|---|------|------|------|
| C4 | 跨文件 import 存在且全为活引用 | SCIP imports | 死 import = 0 |
| C5 | find-references：从定义找到全部引用点 | SCIP occurrences | 可解析率 100%，unresolved = 0 |
| C6 | go-to-definition：从引用点跳回定义 | SCIP | 成功率 100% |
| C7 | 包级符号面：`from <book> import <symbol>` 可解析 | import 抽样 + `__init__.py` re-export + `__all__` | 抽样 100% |

### L2 语义工具层

| # | 能力 | 验证 | 阈值 |
|---|------|------|------|
| C8 | 类型检查零错误（构造调用对得上 ontology 签名） | Pyright | 0 error |
| C9 | 重命名重构安全：改 symbol 全部引用同步 | 抽样 rename 后 import + refs 一致 | 抽样 100% |
| C10 | **import 即验证**：删任一定义 → ImportError | 负例测试 | 必现 |

### L3 证据可遍历层（T2C 独有）

| # | 能力 | 验证 | 阈值 |
|---|------|------|------|
| C11 | Claim/Event → evidence_refs → text.py Segment 定义 → text_slice 全程可跳 | SCIP 链路 + 数据 gate | evidence 非空率 100%；segment_symbol 解析率 100% |
| C12 | hash 链可程序化回放（quote→segment→block→document） | 抽样校验 | 抽样 50 条一致率 100% |

### 3.1 头骨指标：ARR（AST Reference Rate）

```text
ARR = 以 AST Name 节点存在的引用关系数 / 全部引用关系数
全部引用关系 = Claim.subject/object + Event.participants + Relation.subject/object/claim_id
             + EvidenceRef.segment_id + Residual/IgnoreSegment.segment_id（其有对应符号面者）

v5.0 现状：ARR = 0%    v6.0 目标：ARR = 100%
```

ARR 是本里程碑的单一数字定义：字符串形态的引用不计入分子。

### 3.2 反空洞化条款（防止"100%"退化为"能 parse"）

1. **语义查询精确匹配**：从 SCIP 索引查询"ent_甄士隐 的全部引用"，返回集合必须**恰好**等于该实体参与的全部 Claim/Event 位置（precision = recall = 1.0）。字符串 grep 过不了此关（会混入注释与字符串字面量中的同名串）。
2. **C10 负例必现**：删除任一 Entity 定义后 import 包必须抛 ImportError；恢复后通过。此条同时是"validator 删 170 行"的验收。

### 3.3 质量追踪（不挡验收，持续报告）

ER / EP / SCR / ECR / RD / PC / GR 维持 CQM 口径，每次 compile 输出，不设门槛。
其中 entity resolution（去重）例外：**重复实体会产生 `_1` 后缀符号直接污染引用图**，故程序化去重属于本次边界内工作（M3）。

---

## 4. 验收设计

### 4.1 验收组织

- **单一入口**：`scripts/verify_codegraph.py <package_dir> --json`——输出逐条 C 结果 + ARR + exit code
- **golden fixture**：红楼梦 1-3 回（`--cache-mode read_only`，零 LLM 成本复放）
- **pytest 集成**：`tests/test_codegraph_contract.py` 调验收脚本，红灯 = 测试失败
- **CI 接入**（GitHub Actions）：随 M2 落地（仓库当前无 CI，本次新建）
- **rebuild gate**：`read_only` 重编译字节一致（diff = 0），一并纳入验收脚本

### 4.2 量化验收表（汇总）

| 指标 | 现状 | 目标 | 工具 |
|------|------|------|------|
| **ARR** | **0%** | **100%** | AST 校验（工具无关） |
| 可编译文件率 | 8/8 | 8/8 | py_compile |
| 符号定义覆盖 | 100% | 100% | AST/SCIP |
| 死 import 数 | 0（无 import） | 0（有 import） | SCIP imports |
| 引用可解析率 | n/a（无引用边） | 100%，unresolved=0 | SCIP |
| 包级 import 抽样 | 0%（无符号面） | 100% | import test |
| Pyright error | 未测 | 0 | pyright |
| C10 负例 | 不触发（字符串不检查） | ImportError 必现 | import test |
| evidence 非空率（Claim/Event） | 80% / 76% | 100% | 数据 gate |
| hash 回放一致率 | 未测 | 100%（抽样 50） | 校验脚本 |
| rebuild diff | 未测 | 0 字节差异 | 重编译对比 |
| 语义查询 P/R | n/a | 1.0 / 1.0 | SCIP 查询 |

### 4.3 里程碑与矩阵的对应

| 里程碑 | 内容 | 点亮的矩阵项 |
|--------|------|------------|
| **M1 形态完整**（= 原 v5.1，已定稿） | `symbol` 字段 + field_validator；symbol 前置分配（原 P3-2）；bare Name `_symbol`；真实活 import；validator −170 行；`__init__.py` 全量 re-export + `__all__` | C4 C5 C6 C7 C9 C10，ARR 0→100% |
| **M2 验证 harness** | `verify_codegraph.py` + pytest gate + CI；scip-python 大文件性能实测；rebuild gate 落地 | C1–C12 自动化强制 |
| **M3 内容 gate** | Claim/Event evidence 非空升级为编译 gate；零悬空引用 gate（杀灭 `hongloumeng_seg` 混名）；程序化 entity resolution | C11 C12 实际可用 |

### 4.4 完成定义（Definition of Done）

> 红楼梦 1-3 回 golden fixture 上 C1–C12 全绿、ARR=100%、rebuild 字节一致、CI 强制复验通过。
> 此时 T2C 的 text→code 环节在"codegraph 100% 利用"意义上完成。后续是否做应用层，另行决策。

---

## 附录 A：与历史版本的关系

| 版本 | 与 v6.0 的关系 |
|------|---------------|
| v4.0 | "编译器收口"哲学全部继承；12-gate 的"手写引用检查"部分由 C10（import 即验证）替代 |
| v5.0 | "结构先行 LLM 精化"全部已落地，构成本次的现状基座 |
| v5.1（原计划） | 原封不动升级为 M1；补充 C7（包级符号面）与 rebuild gate 同 commit 要求 |

## 附录 B：设计岔口决议记录

- **`__init__.py` 形态**：采用全量显式 re-export + `__all__`（约 1262 个符号）。理由：C7 包级导航要求；生成代码不怕文件大；显式 import 对 SCIP/Pyright 最友好。代价（import 时全模块加载、文件体积）对知识工件可接受。可逆，若实测性能问题再降级为模块句柄式。
