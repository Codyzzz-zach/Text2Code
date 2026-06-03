"""Corpus Manager — raw text ingestion, block generation, hash computation."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from t2c.ontology import Block, Document


def compute_hash(text: str) -> str:
    """SHA-256 hash of text, prefixed with 'sha256:'."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class CorpusManager:
    """Ingest raw text files, generate Document and Block objects."""

    def __init__(self, corpus_root: Path | None = None) -> None:
        self._corpus_root = corpus_root
        self._raw_texts: dict[str, str] = {}

    # -- Ingest ----------------------------------------------------------

    def ingest(self, file_path: Path) -> tuple[Document, str]:
        """Read raw text file, compute hash, return (Document, raw_text)."""
        text = file_path.read_text(encoding="utf-8")
        doc_id = file_path.stem
        doc = self._make_document(doc_id, str(file_path), text)
        self._raw_texts[doc_id] = text
        return doc, text

    def ingest_text(self, text: str, doc_id: str, source_path: str = "") -> tuple[Document, str]:
        """Ingest raw text directly, return (Document, raw_text)."""
        doc = self._make_document(doc_id, source_path, text)
        self._raw_texts[doc_id] = text
        return doc, text

    def _make_document(self, doc_id: str, source_path: str, text: str) -> Document:
        raw_text_hash = compute_hash(text)
        created_at = datetime.now(timezone.utc).isoformat()
        # block_count is computed after create_blocks, set placeholder 0
        return Document(
            id=doc_id,
            source_path=source_path,
            raw_text_hash=raw_text_hash,
            total_length=len(text),
            block_count=0,
            created_at=created_at,
        )

    # -- Block generation ------------------------------------------------

    def create_blocks(self, doc: Document, text: str) -> list[Block]:
        """Split text into blocks by structural boundaries."""
        spans = self._split_into_block_spans(text)
        blocks: list[Block] = []
        for idx, (start, end, block_type) in enumerate(spans):
            slice_text = text[start:end]
            block = Block(
                id=f"{doc.id}_blk_{idx:04d}",
                doc_id=doc.id,
                index=idx,
                block_type=block_type,
                start_offset=start,
                end_offset=end,
                text_slice=slice_text,
                hash=compute_hash(slice_text),
            )
            blocks.append(block)
        return blocks

    def _split_into_block_spans(self, text: str) -> list[tuple[int, int, str]]:
        """Return list of (start, end, block_type) tuples."""
        lines = text.split("\n")
        spans: list[tuple[int, int, str]] = []
        current_start: int = 0
        current_lines: list[str] = []
        current_type: str = "raw"

        def _flush(start: int, lines: list[str], btype: str) -> tuple[int, int, str] | None:
            content = "\n".join(lines)
            if not content.strip():
                return None
            end = start + len(content)
            return (start, end, btype)

        i = 0
        while i < len(lines):
            line = lines[i]
            detected_type = self._detect_line_type(line)

            # Type change or blank line → flush previous block
            if detected_type != current_type and current_lines:
                result = _flush(current_start, current_lines, current_type)
                if result:
                    spans.append(result)
                # Advance past the flushed content including trailing newline
                current_start += len("\n".join(current_lines)) + 1
                current_lines = []
                current_type = detected_type

            # Blank line → paragraph boundary
            if not line.strip():
                if current_lines:
                    result = _flush(current_start, current_lines, current_type)
                    if result:
                        spans.append(result)
                    current_start += len("\n".join(current_lines)) + 1
                    current_lines = []
                    current_type = "raw"
                i += 1
                # Skip consecutive blank lines
                while i < len(lines) and not lines[i].strip():
                    current_start += len(lines[i]) + 1
                    i += 1
                continue

            # Accumulate line into current block
            if not current_lines:
                # Recalculate start for first line of new block
                current_start = sum(len(lines[j]) + 1 for j in range(0, i))
                current_type = detected_type
            current_lines.append(line)
            i += 1

        # Flush final block
        if current_lines:
            result = _flush(current_start, current_lines, current_type)
            if result:
                spans.append(result)

        # Merge adjacent blocks of same type
        merged: list[tuple[int, int, str]] = []
        for span in spans:
            if merged and merged[-1][2] == span[2] and merged[-1][1] == span[0]:
                merged[-1] = (merged[-1][0], span[1], span[2])
            else:
                merged.append(span)

        return merged

    def _detect_line_type(self, line: str) -> str:
        stripped = line.strip()
        if stripped.startswith("#"):
            return "heading"
        if re.match(r"^第[一二三四五六七八九十百千零\d]+[回章节卷篇部]", stripped):
            return "heading"
        if stripped.startswith("|"):
            return "table"
        if stripped.startswith(">"):
            return "quote"
        if stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\. ", stripped):
            return "list"
        if stripped.startswith("```") or (line.startswith("    ") and stripped):
            return "code_block"
        return "paragraph"

    # -- Retrieval -------------------------------------------------------

    def get_raw_text(self, doc_id: str) -> str:
        return self._raw_texts[doc_id]

    def get_block_text(self, doc: Document, block: Block, text: str) -> str:
        """Slice exact text for a block using offsets."""
        return text[block.start_offset:block.end_offset]

    # -- Hash verification -----------------------------------------------

    def verify_hash(self, doc: Document, text: str) -> bool:
        """Verify document content hash matches stored text."""
        return compute_hash(text) == doc.raw_text_hash

    def verify_block_hash(self, block: Block, text: str) -> bool:
        """Verify block hash matches actual text slice."""
        slice_text = text[block.start_offset:block.end_offset]
        return compute_hash(slice_text) == block.hash