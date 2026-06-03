"""T2C Pipeline — end-to-end processing: raw text → text map → semantic extraction → knowledge code."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from t2c.codegen import CodeGenerator
from t2c.corpus import CorpusManager
from t2c.extractor import LLMExtractor
from t2c.ontology import Block, Document, Segment
from t2c.segmenter import Segmenter
from t2c.validator import ValidationResult, Validator

logger = logging.getLogger(__name__)


class T2CPipeline:
    """End-to-end pipeline: raw text → text map → semantic extraction → knowledge code."""

    def __init__(
        self,
        output_dir: Path,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._output_dir = output_dir
        self._corpus = CorpusManager()
        self._segmenter = Segmenter()
        self._codegen = CodeGenerator()
        self._extractor = LLMExtractor(model=model, api_key=api_key, base_url=base_url)
        self._validator = Validator()

    def run_document(self, raw_text: str, doc_id: str) -> tuple[Document, list[Block]]:
        """Ingest raw text and generate Document + Blocks."""
        doc, _ = self._corpus.ingest_text(raw_text, doc_id)
        blocks = self._corpus.create_blocks(doc, raw_text)
        return doc, blocks

    def run_segments(
        self, doc: Document, blocks: list[Block], raw_text: str
    ) -> list[Segment]:
        """Generate segments for all blocks."""
        all_segments: list[Segment] = []
        for block in blocks:
            block_text = raw_text[block.start_offset:block.end_offset]
            segments = self._segmenter.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)
        return all_segments

    def find_chapter_boundaries(self, raw_text: str) -> list[tuple[int, str, int, int]]:
        """Find chapter boundaries in the raw text.

        Returns list of (chapter_num, title, start_offset, end_offset).
        Only matches chapter headings that appear at the start of a line.
        """
        chapters = list(re.finditer(r"(?<=\n)第[一二三四五六七八九十百千零\d]+回", raw_text))
        boundaries: list[tuple[int, str, int, int]] = []
        for i, m in enumerate(chapters):
            title = raw_text[m.start():m.start() + 40].split("\n")[0].strip()
            start = m.start()
            end = chapters[i + 1].start() if i + 1 < len(chapters) else len(raw_text)
            # Extract chapter number
            num_match = re.match(r"第([一二三四五六七八九十百千零\d]+)回", title)
            if not num_match:
                continue
            num_str = num_match.group(1)
            num = self._chinese_num_to_int(num_str)
            boundaries.append((num, title, start, end))
        return boundaries

    def _chinese_num_to_int(self, num_str: str) -> int:
        """Convert Chinese number string to integer."""
        mapping = {
            "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
            "百": 100, "零": 0,
        }
        # Try pure digit
        if num_str.isdigit():
            return int(num_str)
        # Simple Chinese numeral conversion
        if num_str in mapping:
            return mapping[num_str]
        result = 0
        for ch in num_str:
            if ch.isdigit():
                result = result * 10 + int(ch)
            elif ch in mapping:
                val = mapping[ch]
                if val >= 10:
                    result = result * val if result else val
                else:
                    result += val
        return result

    def run_chapter(
        self,
        doc_id: str,
        chapter_num: int,
        chapter_title: str,
        chapter_segments: list[Segment],
        existing_entities: dict[str, str] | None = None,
    ) -> tuple[list[dict], ValidationResult]:
        """Extract semantic objects for one chapter and validate.

        Returns (semantic_objects, validation_result).
        """
        objects = self._extractor.extract_chapter(
            doc_id, chapter_num, chapter_title, chapter_segments, existing_entities
        )
        # Validate extracted objects
        self._validator.set_raw_text(doc_id, "")  # No raw text for schema-only validation
        result = self._validator.validate_objects(objects)
        return objects, result

    def run_chapters(
        self,
        raw_text: str,
        doc_id: str,
        chapter_nums: list[int] | None = None,
        precomputed_segments: list[Segment] | None = None,
    ) -> list[dict]:
        """Process multiple chapters with cross-chapter entity resolution.

        Args:
            raw_text: Full novel text
            doc_id: Document ID
            chapter_nums: Which chapters to process (1-based). None = all.
            precomputed_segments: If provided, skip re-computing document+segments.

        Returns list of dicts with chapter results.
        """
        if precomputed_segments is not None:
            all_segments = precomputed_segments
        else:
            doc, blocks = self.run_document(raw_text, doc_id)
            all_segments = self.run_segments(doc, blocks, raw_text)
        boundaries = self.find_chapter_boundaries(raw_text)

        # Build segment-by-offset lookup
        seg_by_offset: dict[tuple[int, int], Segment] = {}
        for s in all_segments:
            seg_by_offset[(s.start_offset, s.end_offset)] = s

        entity_map: dict[str, str] = {}
        results: list[dict] = []

        for ch_num, ch_title, ch_start, ch_end in boundaries:
            if chapter_nums and ch_num not in chapter_nums:
                continue

            # Collect segments for this chapter
            ch_segments = [
                s for s in all_segments
                if s.start_offset >= ch_start and s.start_offset < ch_end
            ]

            if not ch_segments:
                continue

            logger.info(
                "Processing Ch%d %s: %d segments, %d known entities",
                ch_num, ch_title, len(ch_segments), len(entity_map),
            )

            objects, validation = self.run_chapter(
                doc_id, ch_num, ch_title, ch_segments, entity_map
            )

            # Update entity map with this chapter's entities
            pre_count = len(entity_map)
            new_entities = LLMExtractor.build_entity_map(objects)
            entity_map.update(new_entities)
            added = len(entity_map) - pre_count

            # Count by type
            type_counts = {}
            for o in objects:
                t = o.get("type", "?")
                type_counts[t] = type_counts.get(t, 0) + 1
            logger.info(
                "Ch%d extracted: %s, entities +%d (total %d)",
                ch_num, type_counts, added, len(entity_map),
            )
            if validation.errors:
                logger.warning("Ch%d validation errors: %d", ch_num, len(validation.errors))

            results.append({
                "chapter_num": ch_num,
                "title": ch_title,
                "segments": ch_segments,
                "semantic_objects": objects,
                "validation": validation,
                "entity_map": dict(entity_map),
            })

        return results

    def write_chapter_knowledge(
        self, chapter_num: int, objects: list[dict]
    ) -> Path:
        """Write semantic objects to a .t2c.py knowledge file."""
        from t2c.schema import SchemaValidator
        sv = SchemaValidator()
        models, _ = sv.validate_and_construct(objects)

        if not models:
            code = "# No valid semantic objects extracted\n"
        else:
            code = self._codegen.generate_knowledge_code(models)

        filename = f"hongloumeng_ch{chapter_num:02d}.knowledge.t2c.py"
        path = self._output_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        return path

    def write_text_map(
        self, doc: Document, blocks: list[Block], segments: list[Segment]
    ) -> tuple[Path, Path]:
        """Write Document+Blocks and Segments .t2c.py files."""
        self._output_dir.mkdir(parents=True, exist_ok=True)

        doc_code = self._codegen.generate_document_code(doc, blocks)
        doc_path = self._output_dir / "hongloumeng.document.t2c.py"
        doc_path.write_text(doc_code, encoding="utf-8")

        seg_code = self._codegen.generate_segments_code(segments)
        seg_path = self._output_dir / "hongloumeng.segments.t2c.py"
        seg_path.write_text(seg_code, encoding="utf-8")

        return doc_path, seg_path