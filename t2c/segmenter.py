"""Segmenter — rule-based text splitting into Segment objects (Chinese + English)."""
from __future__ import annotations

import hashlib
import re

from t2c.ontology import Block, Segment


class Segmenter:
    """Rule-based text segmenter producing Segment objects with stable offsets."""

    def __init__(self) -> None:
        self._doc_seg_counters: dict[str, int] = {}

    def segment_block(
        self,
        doc_id: str,
        block: Block,
        block_text: str,
    ) -> list[Segment]:
        """Split a block's text into segments. Routes by block_type."""
        splitter = {
            "paragraph": self._segment_paragraph,
            "heading": self._segment_heading,
            "table": self._segment_table,
            "list": self._segment_list,
            "quote": self._segment_paragraph,
            "code_block": self._segment_code,
            "raw": self._segment_raw,
        }.get(block.block_type, self._segment_raw)
        spans = splitter(block_text)
        return self._spans_to_segments(doc_id, block, block_text, spans)

    # -- Span extraction methods -----------------------------------------

    def _segment_paragraph(self, text: str) -> list[tuple[int, int, str]]:
        """Split paragraph into sentences (Chinese + English) and dialogue."""
        # Detect dialogue segments first
        dialogue_spans = self._extract_dialogue_spans(text)
        if dialogue_spans and len(dialogue_spans) >= 2:
            # If significant dialogue content, split by dialogue
            result: list[tuple[int, int, str]] = []
            prev_end = 0
            for d_start, d_end, d_text in dialogue_spans:
                # Text before this dialogue
                if d_start > prev_end:
                    between_raw = text[prev_end:d_start]
                    between = between_raw.strip()
                    if between:
                        lstrip_len = len(between_raw) - len(between_raw.lstrip())
                        actual_start = prev_end + lstrip_len
                        between_spans = self._split_sentences(between, actual_start)
                        result.extend(between_spans)
                result.append((d_start, d_end, "dialogue"))
                prev_end = d_end
            # Text after last dialogue
            if prev_end < len(text):
                after_raw = text[prev_end:]
                after = after_raw.strip()
                if after:
                    lstrip_len = len(after_raw) - len(after_raw.lstrip())
                    actual_start = prev_end + lstrip_len
                    after_spans = self._split_sentences(after, actual_start)
                    result.extend(after_spans)
            return result if result else self._split_sentences(text, 0)

        # No significant dialogue — split by sentences
        return self._split_sentences(text, 0)

    def _segment_heading(self, text: str) -> list[tuple[int, int, str]]:
        """Heading is its own segment."""
        stripped = text.strip()
        if stripped:
            start = text.index(stripped)
            return [(start, start + len(stripped), "heading")]
        return []

    def _segment_table(self, text: str) -> list[tuple[int, int, str]]:
        """One table row = one segment."""
        result: list[tuple[int, int, str]] = []
        offset = 0
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                local_start = text.find(stripped, offset)
                result.append((local_start, local_start + len(stripped), "table_row"))
                offset = local_start + len(stripped)
        return result

    def _segment_list(self, text: str) -> list[tuple[int, int, str]]:
        """One list item = one segment."""
        result: list[tuple[int, int, str]] = []
        offset = 0
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                local_start = text.find(stripped, offset)
                result.append((local_start, local_start + len(stripped), "list_item"))
                offset = local_start + len(stripped)
        return result

    def _segment_code(self, text: str) -> list[tuple[int, int, str]]:
        """Code block as a single raw segment."""
        stripped = text.strip()
        if stripped:
            start = text.find(stripped)
            return [(start, start + len(stripped), "raw")]
        return []

    def _segment_raw(self, text: str) -> list[tuple[int, int, str]]:
        """Raw text as a single raw segment."""
        stripped = text.strip()
        if stripped:
            start = text.find(stripped)
            return [(start, start + len(stripped), "raw")]
        return []

    # -- Sentence splitting (Chinese + English) --------------------------

    def _split_sentences(
        self, text: str, global_offset: int,
    ) -> list[tuple[int, int, str]]:
        """Split text into sentences using Chinese and English boundary rules."""
        # Pattern covers Chinese (。！？) and English (.!? + space/capital)
        # Also handles clause markers: 第X条, （一）, etc.
        pattern = re.compile(
            r"[^。！？.!?\n]+[。！？.!?]+"
            r'|第[一二三四五六七八九十百千\d]+条[^\n]*'
            r"|（[一二三四五六七八九十\d]+）[^\n]*"
            r"|[\d]+[\.、][^\n]*",
        )
        spans: list[tuple[int, int, str]] = []
        pos = 0
        for match in pattern.finditer(text):
            sent = match.group().strip()
            if sent:
                local_start = text.find(sent, pos)
                local_end = local_start + len(sent)
                spans.append((global_offset + local_start, global_offset + local_end, "sentence"))
                pos = local_end

        # Fallback: entire text as one sentence if no splits found
        if not spans and text.strip():
            stripped = text.strip()
            local_start = text.find(stripped)
            spans.append((global_offset + local_start, global_offset + local_start + len(stripped), "sentence"))

        # Merge very short segments (< 2 chars) with previous
        merged: list[tuple[int, int, str]] = []
        for span in spans:
            span_text = text[span[0] - global_offset : span[1] - global_offset] if global_offset else text[span[0]:span[1]]
            span_len = span[1] - span[0]
            if merged and span_len < 2:
                prev = merged[-1]
                merged[-1] = (prev[0], span[1], prev[2])
            else:
                merged.append(span)

        return merged

    # -- Dialogue extraction ---------------------------------------------

    def _extract_dialogue_spans(self, text: str) -> list[tuple[int, int, str]]:
        """Extract dialogue spans from Chinese 「」『』 and English "" markers."""
        spans: list[tuple[int, int, str]] = []
        # Chinese dialogue: 「...」 and 『...』
        for m in re.finditer(r"[「『][^」』]+[」』]", text):
            spans.append((m.start(), m.end(), "dialogue"))
        # English dialogue: "..." (balanced double quotes, straight or curly)
        for m in re.finditer(r'["“][^"”]*["”]', text):
            spans.append((m.start(), m.end(), "dialogue"))
        return spans

    # -- Convert spans to Segment objects --------------------------------

    def _spans_to_segments(
        self,
        doc_id: str,
        block: Block,
        block_text: str,
        spans: list[tuple[int, int, str]],
    ) -> list[Segment]:
        """Convert (start, end, type) spans into Segment Pydantic models."""
        segments: list[Segment] = []
        global_offset = block.start_offset
        counter = self._doc_seg_counters.get(doc_id, 0)

        for local_start, local_end, seg_type in spans:
            g_start = global_offset + local_start
            g_end = global_offset + local_end

            slice_text = block_text[local_start:local_end]
            text_hash = f"sha256:{hashlib.sha256(slice_text.encode('utf-8')).hexdigest()}"

            seg_id = f"{doc_id}_seg_{counter + 1:04d}"
            counter += 1

            segment = Segment(
                id=seg_id,
                doc_id=doc_id,
                block_index=block.index,
                segment_type=seg_type,
                start_offset=g_start,
                end_offset=g_end,
                text_slice=slice_text,
                hash=text_hash,
            )
            segments.append(segment)

        self._doc_seg_counters[doc_id] = counter
        return segments