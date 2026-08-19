"""Tests for t2c/codegen.py — CodeGenerator."""
from t2c.codegen import CodeGenerator
from t2c.corpus import CorpusManager
from t2c.ontology import Block, Document, Segment


def _sha256(text: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestDocumentCodeGeneration:
    def test_generates_valid_python(self):
        gen = CodeGenerator()
        doc = Document(
            id="test", source_path="test.txt",
            raw_text_hash=_sha256("Hello world"), total_length=100,
            block_count=1, created_at="2026-05-27T10:00:00Z",
        )
        block = Block(
            id="test_blk_0000",
            doc_id="test", index=0, block_type="paragraph",
            start_offset=0, end_offset=100, text_slice="Hello world",
            hash=_sha256("Hello world"),
        )
        code = gen.generate_document_code(doc, [block])
        # Should be valid Python syntax
        compile(code, "<test>", "exec")

    def test_contains_document_constructor(self):
        gen = CodeGenerator()
        doc = Document(
            id="test", source_path="test.txt",
            raw_text_hash=_sha256("Hello world"), total_length=100,
            block_count=1, created_at="2026-05-27T10:00:00Z",
        )
        code = gen.generate_document_code(doc, [])
        assert "Document(" in code
        assert "from t2c.ontology import" in code

    def test_contains_block_constructor(self):
        gen = CodeGenerator()
        doc = Document(
            id="test", source_path="test.txt",
            raw_text_hash=_sha256("Hello world"), total_length=100,
            block_count=1, created_at="2026-05-27T10:00:00Z",
        )
        block = Block(
            id="test_blk_0000",
            doc_id="test", index=0, block_type="paragraph",
            start_offset=0, end_offset=100, text_slice="Hello world",
            hash=_sha256("Hello world"),
        )
        code = gen.generate_document_code(doc, [block])
        assert "Block(" in code


class TestSegmentsCodeGeneration:
    def test_generates_valid_python(self):
        gen = CodeGenerator()
        seg = Segment(
            id="test_seg_0001", doc_id="test", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=5,
            text_slice="Hello", hash=_sha256("Hello"),
        )
        code = gen.generate_segments_code([seg])
        compile(code, "<test>", "exec")

    def test_contains_segment_constructor(self):
        gen = CodeGenerator()
        seg = Segment(
            id="test_seg_0001", doc_id="test", block_index=0,
            segment_type="sentence", start_offset=0, end_offset=5,
            text_slice="Hello", hash=_sha256("Hello"),
        )
        code = gen.generate_segments_code([seg])
        assert "Segment(" in code


class TestKnowledgeCodeGeneration:
    def test_entity_with_evidence(self):
        gen = CodeGenerator()
        from t2c.ontology import Entity, EvidenceRef
        ev = EvidenceRef(segment_id="s1", start=0, end=5, quote_hash=_sha256("Hello"))
        entity = Entity(id="e1", name="Alice", kind="person", evidence_refs=[ev])
        code = gen.generate_knowledge_code([entity])
        compile(code, "<test>", "exec")
        assert "Entity(" in code
        assert "EvidenceRef(" in code
        assert "Alice" in code


class TestCase001Roundtrip:
    def test_case_001_codegen(self, case_001_path, case_001_text):
        cm = CorpusManager()
        doc, text = cm.ingest(case_001_path)
        blocks = cm.create_blocks(doc, text)

        gen = CodeGenerator()
        doc_code = gen.generate_document_code(doc, blocks)
        # Verify generated code is valid Python
        compile(doc_code, "<doc>", "exec")
        assert "Document(" in doc_code
        assert "Block(" in doc_code

        # Generate segments
        from t2c.segmenter import Segmenter
        seg = Segmenter()
        all_segments = []
        for block in blocks:
            block_text = cm.get_block_text(doc, block, text)
            segments = seg.segment_block(doc.id, block, block_text)
            all_segments.extend(segments)

        seg_code = gen.generate_segments_code(all_segments)
        compile(seg_code, "<seg>", "exec")
        assert "Segment(" in seg_code


class TestCodegenVersion:
    """v4.1: CodeGenerator version tag."""

    def test_default_header_is_current(self):
        from t2c.ontology import Entity
        gen = CodeGenerator()
        ent = Entity(id="e1", name="x", kind="person")
        code = gen.generate_knowledge_code([ent])
        assert "v6.0" in code

    def test_custom_version(self):
        from t2c.ontology import Entity
        gen = CodeGenerator(version="v3.5-flash")
        ent = Entity(id="e1", name="x", kind="person")
        code = gen.generate_knowledge_code([ent])
        assert "v3.5-flash" in code

    def test_version_applied_to_document_code(self):
        gen = CodeGenerator(version="v3.4.1-flash")
        doc = Document(
            id="t", source_path="t.txt",
            raw_text_hash=_sha256("x"), total_length=1,
            block_count=0, created_at="2026-01-01T00:00:00Z",
        )
        code = gen.generate_document_code(doc, [])
        assert "v3.4.1-flash" in code

    def test_version_applied_to_segments_code(self):
        gen = CodeGenerator()
        seg = Segment(
            id="s1", doc_id="d", block_index=0, segment_type="sentence",
            start_offset=0, end_offset=1, text_slice="x", hash=_sha256("x"),
        )
        code = gen.generate_segments_code([seg])
        assert "v6.0" in code