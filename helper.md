# T2C Agent Helper

This repository treats Text2Code as a compiler.

Default user workflow:

```text
input_txt/<book>.txt
  -> output_code/<book>/
```

Product output is the generated Knowledge Code package:

```text
<output>/
  text.py
  entities.py
  events.py
  claims.py
  residuals.py
  derived.py
  coverage.py
  __init__.py
```

## Agent Protocol

1. Use the CLI as the product entry point. Do not call legacy extraction scripts for product output.
2. For the standard repository workflow, compile every `.txt` book in `input_txt/`:

```bash
t2c compile-library --llm --cache-mode read_write --json
```

This writes each book to `output_code/<book-name>/`.

3. For a single explicit file, run:

```bash
t2c compile <raw.txt> --output <output_dir> --llm --cache-mode read_write --json
```

4. For a cost-free text-map preflight only, run:

```bash
t2c compile-library --text-only --json
```

`--text-only` is not a semantic compile. It only verifies ingestion, block generation,
segmentation, deterministic codegen, and importability.

5. Prefer cache-safe reruns:

```bash
t2c compile-library --llm --cache-mode read_only --json
```

Use `refresh` only when the user explicitly accepts a fresh LLM call.

6. After compilation, verify the artifact against the v6.0 codegraph contract:

```bash
python scripts/verify_codegraph.py output_code/<book> --pyright
```

Report at least:

- `ARR` (ast_reference_rate — must be 1.0)
- `REF_zero_dangling` (dangling_count must be 0)
- `C11_evidence_presence` (Claim/Event evidence rate)
- `C12_hash_replay` (quote-hash replay over segment text)
- `C8_pyright` (error_count must be 0)

Legacy note: `scripts/test_matrix.py quality` evaluates the historical
`examples/knowledge/` fixtures, not freshly compiled output. Do not treat
its numbers as acceptance for new compiles.

7. Treat generated `.py` files as the source of truth for downstream codegraph tools.
Internal `ObjectStore`, graph helpers, and old scripts are implementation details unless
the user explicitly asks to work on them.
