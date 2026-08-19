<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![Python][python-shield]][python-url]

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/Codyzzz-zach/Text2Code">
    <img src="images/logo.png" alt="Text2Code Logo" width="120" height="120">
  </a>

  <h3 align="center">Text2Code</h3>

  <p align="center">
    A cognitive engine that transforms natural language text into executable Knowledge Code.
    <br />
    <a href="README.zh-CN.md">中文文档</a>
    &middot;
    <a href="https://github.com/Codyzzz-zach/Text2Code/issues/new?labels=bug&template=bug-report---.md">Report Bug</a>
    &middot;
    <a href="https://github.com/Codyzzz-zach/Text2Code/issues/new?labels=enhancement&template=feature-request---.md">Request Feature</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>📑 Table of Contents</summary>
  <ol>
    <li><a href="#about-the-project">About The Project</a></li>
    <li><a href="#how-it-works">How It Works</a></li>
    <li><a href="#output-format">Output Format</a></li>
    <li><a href="#getting-started">Getting Started</a></li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#project-structure">Project Structure</a></li>
    <li><a href="#design-documents">Design Documents</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
  </ol>
</details>

---

<!-- ABOUT THE PROJECT -->
## About The Project

Text2Code (T2C) is a **text-to-knowledge-code compiler**. It takes raw natural language text — novels, legal documents, news articles — and compiles it into importable Python Knowledge Code packages through a multi-stage pipeline powered by LLM extraction and validation gates.

The output is not a database or a graph — it's **code**. Every entity, event, claim, and relation becomes a typed Python variable with precise source evidence, stable IDs, cross-file imports, and full traceability. The resulting `.py` files are importable, verifiable, and natively navigable by code intelligence tools (CodeGraph, Pyright, Sourcegraph).

**Why "code as knowledge"?**

- 🔍 **Traceable** — Every knowledge object carries `EvidenceRef` pointing to exact character offsets in the source text
- 🧩 **Composable** — Cross-file Python imports connect entities, claims, and relations into a navigable knowledge graph
- ✅ **Verifiable** — 12-gate validation pipeline ensures structural correctness, reference integrity, and epistemic safety
- 🔧 **Tool-native** — Standard code intelligence (go-to-definition, find-references) works out of the box

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

<!-- HOW IT WORKS -->
## How It Works

```
input_txt/*.txt ──► Segment ──► Extract(LLM) ──► Validate ──► Compact ──► CodeGen ──► output_code/<book>/
```

| Stage | Module | Description |
|:------|:-------|:------------|
| **Ingest** | `corpus.py` | Text ingestion, block detection, hash computation |
| **Segment** | `segmenter.py` | Semantic segmentation (Chinese/English sentence boundaries, dialogue, tables) |
| **Extract** | `extractor.py` | LLM-driven extraction of entities, events, claims, and relations |
| **Validate** | `validator.py` + `schema.py` | 12-gate structural & epistemic validation with repair |
| **Compact** | `compact_candidate.py` | Deduplication, compression, relation derivation |
| **CodeGen** | `codegen.py` | Deterministic Python Knowledge Code generation with stable symbols |
| **Compile** | `compile_target.py` | Multi-file compilation output |

**Core infrastructure:** `ontology.py` (Pydantic type system) · `llm_config.py` (multi-provider LLM config) · `llm_cache.py` (deterministic cache) · `claim_safety.py` (6 epistemic rules)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

<!-- OUTPUT FORMAT -->
## Output Format

Each document is compiled into a Python package of 8 files:

```
output_code/hongloumeng/
├── __init__.py        # Package marker
├── text.py            # Document + Block + Segment objects
├── entities.py        # Entity objects (with evidence refs)
├── events.py          # Event objects (with participant refs)
├── claims.py          # Claim objects (with modality & polarity)
├── residuals.py       # Uncovered segment residuals
├── derived.py         # Derived Relation objects
└── coverage.py        # Coverage report
```

**Example output** — a claim about an entity, fully traceable (from a real compiled package):

```python
# entities.py
from t2c.ontology import Entity, EvidenceRef
from .text import seg_0102, seg_0107, ...

ent_zh_9d88d8 = Entity(
    id='红楼梦1_3_ent_0001',
    symbol='ent_zh_9d88d8',        # self-declared symbol
    name='女娲氏',
    kind='person',
    ...
)  # 女娲氏 (person)

# claims.py
from t2c.ontology import Claim, EvidenceRef
from .entities import ent_zh_692c5f, ent_zh_ed17f5, ...   # real live imports
from .text import seg_0099, ...

claim_zh_37b1d1 = Claim(
    id='红楼梦1_3_clm_0005',
    symbol='claim_zh_37b1d1',
    subject='红楼梦1_3_ent_0007',          # data face: string ID
    subject_symbol=ent_zh_ed17f5,          # navigation face: real AST reference
    predicate='is_child_of',
    object='红楼梦1_3_ent_0005',
    object_symbol=ent_zh_692c5f,
    modality='reported',
    polarity='positive',
    evidence_refs=[EvidenceRef(
        segment_id='红楼梦1_3_seg_0099',
        segment_symbol=seg_0099,
        start=11, end=14,
        quote_hash='sha256:...',
    )],
)
```

Key properties:
- **Data/navigation separation** — FK fields stay string IDs (Pydantic-safe); `*_symbol` fields are real AST references (find-references / go-to-definition work)
- **Import-as-validation** — a dangling reference is an ImportError; a broken package simply cannot be loaded
- **Package-level surface** — `__init__.py` re-exports every symbol with `__all__`; `from <book> import ent_zh_xxxx` just works
- **Inline comments** (`# 女娲氏 (person)`) — FTS5 full-text search finds Chinese names
- **Evidence traceability** — every claim links back to exact source offsets; quote hashes replay programmatically
- **Reproducible builds** — same input + cache → byte-identical output (rebuild gate)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

<!-- GETTING STARTED -->
## Getting Started

### Prerequisites

- Python 3.11+
- An LLM API key for full extraction. The default provider is DeepSeek
  `deepseek-v4-flash`; non-LLM compilation works without a key.

### Installation

```bash
# Clone the repository
git clone https://github.com/Codyzzz-zach/Text2Code.git
cd Text2Code

# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"
```

### Configure LLM

```bash
cp .env.example .env
# Edit .env — set T2C_LLM_API_KEY or DEEPSEEK_API_KEY
```

Supported providers:

| Provider | Env var | Default model |
|:---------|:--------|:--------------|
| DeepSeek | `T2C_LLM_PROVIDER=deepseek` | `deepseek-v4-flash` |
| MiniMax | `T2C_LLM_PROVIDER=minimax` | `MiniMax-M3` |
| Anthropic | `T2C_LLM_PROVIDER=anthropic` | `claude-3-5-sonnet` |
| OpenAI-compatible | `T2C_LLM_PROVIDER=openai` | `gpt-4o` |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

<!-- USAGE -->
## Usage

### Standard Book Workflow

Put `.txt` books in `input_txt/`. T2C writes each book to
`output_code/<book-name>/`.

```bash
t2c compile-library --llm --cache-mode read_write --json
```

### Text Map Preflight (no LLM required)

```bash
t2c compile-library --text-only --json
```

This scans `input_txt/` and generates replayable text map packages under
`output_code/`. It is a low-cost preflight, not a semantic Text2Code compile.

### Single File Compile

```bash
t2c compile input_txt/红楼梦.txt \
  --output output_code/红楼梦 \
  --llm \
  --cache-mode read_write
```

Use `--cache-mode read_only` for replay-only runs and `refresh` only when you
explicitly want to pay for a fresh model call.

### Run Tests

```bash
pytest                            # Full test suite
pytest tests/test_codegen_v3_3.py # Single module
pytest -x -q                      # Stop on first failure
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

<!-- PROJECT STRUCTURE -->
## Project Structure

```
Text2Code/
├── input_txt/                  # Put source .txt books here
├── output_code/                # Generated Knowledge Code packages
├── t2c/                        # Core engine
│   ├── pipeline.py             # Pipeline orchestration
│   ├── cli.py                  # Public t2c compile-library / compile entry point
│   ├── extractor.py            # LLM extractor (compact-v1 protocol)
│   ├── codegen.py              # Knowledge code generation
│   ├── compile_target.py       # Multi-file compilation
│   ├── validator.py            # 12-gate validation
│   ├── compact_candidate.py    # Compact protocol parser & expander
│   ├── ontology.py             # Pydantic type system (symbol self-declaration + unwrap validators)
│   ├── symbols.py              # v6.0: single-point symbol assignment (package-unique, deterministic)
│   ├── schema.py               # Schema validation layer
│   ├── claim_safety.py         # 6 epistemic safety rules
│   ├── llm_config.py           # Multi-provider LLM configuration
│   ├── llm_cache.py            # Deterministic LLM response cache
│   ├── segmenter.py            # Semantic text segmentation
│   ├── corpus.py               # Raw text ingestion
│   ├── coverage.py             # Coverage report generation
│   ├── parser.py               # Historical .t2c.py AST parser
│   ├── symbol_analyzer.py      # CodeGraph compatibility verification
│   ├── graph_builder.py        # Legacy/experimental graph helper
│   ├── graph_api.py            # Legacy/experimental graph query helper
│   └── object_store.py         # Internal staging store
├── tests/                      # Test suite
├── scripts/                    # Extraction scripts & tools (verify_codegraph.py = v6.0 acceptance gate)
├── spec/                       # Design documents (t2c_design_v6.0.md = current; archive/ = history)
├── .env.example                # Environment variable template
└── pyproject.toml
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

<!-- DESIGN DOCUMENTS -->
## Design Documents

| Version | Document | Key Innovation |
|:--------|:---------|:---------------|
| v6.0 | [t2c_design_v6.0.md](spec/t2c_design_v6.0.md) | Boundary re-convergence: single text→code link; CodeGraph capability matrix acceptance |
| v5.0 and earlier | [archive/](spec/archive/) | Structure-first / compiler model / symbol assignment / graph evolution |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

<!-- LICENSE -->
## License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/Codyzzz-zach/Text2Code.svg?style=for-the-badge
[contributors-url]: https://github.com/Codyzzz-zach/Text2Code/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/Codyzzz-zach/Text2Code.svg?style=for-the-badge
[forks-url]: https://github.com/Codyzzz-zach/Text2Code/network/members
[stars-shield]: https://img.shields.io/github/stars/Codyzzz-zach/Text2Code.svg?style=for-the-badge
[stars-url]: https://github.com/Codyzzz-zach/Text2Code/stargazers
[issues-shield]: https://img.shields.io/github/issues/Codyzzz-zach/Text2Code.svg?style=for-the-badge
[issues-url]: https://github.com/Codyzzz-zach/Text2Code/issues
[license-shield]: https://img.shields.io/github/license/Codyzzz-zach/Text2Code.svg?style=for-the-badge
[license-url]: https://github.com/Codyzzz-zach/Text2Code/blob/main/LICENSE
[python-shield]: https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white
[python-url]: https://www.python.org/
