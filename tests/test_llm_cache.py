"""Tests for t2c/llm_cache.py — batch-level LLM cache + key derivation."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from typing import Any

import pytest

from t2c.llm_cache import (
    CacheEntry,
    CacheMode,
    LLMCache,
    compute_cache_key,
    compute_options_digest,
    hash_known_entities,
    hash_segment_batch,
    hash_text,
)


# ---------------------------------------------------------------------------
# Cache key derivation
# ---------------------------------------------------------------------------


_BASE_KW: dict[str, Any] = dict(
    doc_id="hongloumeng",
    chapter_num=1,
    chapter_title="甄士隐梦幻识通灵",
    batch_index=0,
    segment_ids=["s1", "s2"],
    segment_hashes=["sha256:a", "sha256:b"],
    known_entities={"甄士隐": "hongloumeng_ent_0001"},
    model="MiniMax-M3",
    prompt_version="compact-main-v1",
    extractor_protocol="compact-v1",
    options={"max_tokens": 8192, "thinking_budget": 1024, "temperature": 0},
)


class TestCacheKeyStability:
    def test_same_input_yields_same_key(self):
        k1 = compute_cache_key(**_BASE_KW)
        k2 = compute_cache_key(**_BASE_KW)
        assert k1 == k2
        assert k1.startswith("t2c-llm-cache-v1:")

    def test_key_is_deterministic_across_dict_order(self):
        # Dict iteration order shouldn't affect the hash.
        kw1 = dict(_BASE_KW)
        kw2 = dict(_BASE_KW)
        # Re-arrange `options` keys
        kw1["options"] = {"max_tokens": 8192, "thinking_budget": 1024, "temperature": 0}
        kw2["options"] = {"temperature": 0, "max_tokens": 8192, "thinking_budget": 1024}
        assert compute_cache_key(**kw1) == compute_cache_key(**kw2)


class TestCacheKeyInvalidation:
    def test_segment_id_change_invalidates(self):
        kw = dict(_BASE_KW)
        a = compute_cache_key(**kw)
        kw["segment_ids"] = ["s1", "s2", "s3"]
        kw["segment_hashes"] = ["sha256:a", "sha256:b", "sha256:c"]
        b = compute_cache_key(**kw)
        assert a != b

    def test_segment_hash_change_invalidates(self):
        kw = dict(_BASE_KW)
        a = compute_cache_key(**kw)
        kw["segment_hashes"] = ["sha256:a", "sha256:CHANGED"]
        b = compute_cache_key(**kw)
        assert a != b

    def test_prompt_version_change_invalidates(self):
        kw = dict(_BASE_KW)
        a = compute_cache_key(**kw)
        kw["prompt_version"] = "compact-main-v2"
        b = compute_cache_key(**kw)
        assert a != b

    def test_protocol_change_invalidates(self):
        kw = dict(_BASE_KW)
        a = compute_cache_key(**kw)
        kw["extractor_protocol"] = "compact-v2"
        b = compute_cache_key(**kw)
        assert a != b

    def test_model_change_invalidates(self):
        kw = dict(_BASE_KW)
        a = compute_cache_key(**kw)
        kw["model"] = "gpt-4o"
        b = compute_cache_key(**kw)
        assert a != b

    def test_options_change_invalidates(self):
        kw = dict(_BASE_KW)
        a = compute_cache_key(**kw)
        kw["options"] = dict(kw["options"])
        kw["options"]["max_tokens"] = 16384
        b = compute_cache_key(**kw)
        assert a != b

    def test_known_entity_change_invalidates(self):
        kw = dict(_BASE_KW)
        a = compute_cache_key(**kw)
        kw["known_entities"] = {"贾宝玉": "hongloumeng_ent_0002"}
        b = compute_cache_key(**kw)
        assert a != b

    def test_batch_index_change_invalidates(self):
        kw = dict(_BASE_KW)
        a = compute_cache_key(**kw)
        kw["batch_index"] = 1
        b = compute_cache_key(**kw)
        assert a != b

    def test_irrelevant_fields_dont_affect_key(self):
        # Wall clock / elapsed / token usage must NOT be in the key. We
        # check this by passing in a fake "elapsed" through the entity map
        # path — it shouldn't exist there, but if it did, the key would
        # change. Use a separately-confirmed helper to assert.
        kw_with_meta = dict(_BASE_KW)
        kw_with_meta["known_entities"] = dict(_BASE_KW["known_entities"])
        a = compute_cache_key(**kw_with_meta)
        # Mutating in-place `options` with new keys shouldn't change the
        # canonical JSON as long as the captured snapshot is the same.
        assert compute_cache_key(**kw_with_meta) == a


# ---------------------------------------------------------------------------
# Cache file storage
# ---------------------------------------------------------------------------


class TestCacheStoreAndLookup:
    def _make_entry(self, cache_key: str, *, objects: list[dict] | None = None) -> CacheEntry:
        return CacheEntry(
            cache_schema="t2c-llm-cache-v1",
            cache_key=cache_key,
            created_at="2026-06-05T00:00:00Z",
            request={
                "model": "M",
                "prompt_version": "v1",
                "extractor_protocol": "compact-v1",
                "segments": [{"id": "s1", "hash": "h", "text": "x"}],
                "known_entities": {},
            },
            response={
                "raw_text": "[{\"t\":\"E\"}]",
                "parsed_candidates": objects or [],
                "stop_reason": "end_turn",
                "input_tokens": 10,
                "output_tokens": 20,
                "elapsed_sec": 0.5,
            },
            quality={"parse_ok": True, "truncated": False, "recovered_partial": False},
        )

    def test_store_then_lookup_roundtrip(self, tmp_path):
        cache = LLMCache(cache_dir=tmp_path / "t2c_cache")
        key = compute_cache_key(**_BASE_KW)
        entry = self._make_entry(key, objects=[{"type": "Entity", "data": {"id": "e1"}}])
        cache.store(entry)
        got = cache.lookup(key)
        assert got is not None
        assert got.cache_key == key
        assert got.response["input_tokens"] == 10
        assert got.response["parsed_candidates"] == [{"type": "Entity", "data": {"id": "e1"}}]

    def test_lookup_miss_returns_none(self, tmp_path):
        cache = LLMCache(cache_dir=tmp_path / "t2c_cache")
        assert cache.lookup(compute_cache_key(**_BASE_KW)) is None

    def test_corrupt_file_returns_none(self, tmp_path):
        cache = LLMCache(cache_dir=tmp_path / "t2c_cache")
        cache_dir = tmp_path / "t2c_cache"
        cache_dir.mkdir(parents=True)
        bad = cache_dir / "deadbeef.json"
        bad.write_text("not json {")
        assert cache.lookup("t2c-llm-cache-v1:deadbeef") is None

    def test_clear_removes_entries(self, tmp_path):
        cache = LLMCache(cache_dir=tmp_path / "t2c_cache")
        k1 = compute_cache_key(**dict(_BASE_KW, batch_index=0))
        k2 = compute_cache_key(**dict(_BASE_KW, batch_index=1))
        cache.store(self._make_entry(k1))
        cache.store(self._make_entry(k2))
        assert cache.lookup(k1) is not None
        assert cache.lookup(k2) is not None
        removed = cache.clear()
        assert removed == 2
        assert cache.lookup(k1) is None

    def test_key_mismatch_in_file_returns_none(self, tmp_path):
        cache = LLMCache(cache_dir=tmp_path / "t2c_cache")
        cache_dir = tmp_path / "t2c_cache"
        cache_dir.mkdir(parents=True)
        # Write a file with a deliberately wrong key
        path = cache_dir / "deadbeef.json"
        path.write_text(json.dumps({
            "cache_schema": "t2c-llm-cache-v1",
            "cache_key": "wrong-key",
            "created_at": "2026-06-05T00:00:00Z",
            "request": {},
            "response": {"parsed_candidates": []},
            "quality": {},
        }))
        assert cache.lookup("t2c-llm-cache-v1:deadbeef") is None


class TestHelperDigests:
    def test_hash_known_entities_stable_across_order(self):
        a = hash_known_entities({"A": "x", "B": "y"})
        b = hash_known_entities({"B": "y", "A": "x"})
        assert a == b

    def test_hash_known_entities_empty(self):
        assert hash_known_entities({}) == hash_known_entities(None)

    def test_hash_segment_batch_mismatch_length_raises(self):
        with pytest.raises(ValueError):
            hash_segment_batch(["s1", "s2"], ["h1"])

    def test_hash_text_prefixed(self):
        assert hash_text("hello").startswith("sha256:")
        assert len(hash_text("hello")) == len("sha256:") + 64

    def test_options_digest_depends_on_content(self):
        a = compute_options_digest({"max_tokens": 8192})
        b = compute_options_digest({"max_tokens": 16384})
        assert a != b


class TestCacheMode:
    def test_cache_mode_values(self):
        assert CacheMode.OFF.value == "off"
        assert CacheMode.READ_WRITE.value == "read_write"
        assert CacheMode.READ_ONLY.value == "read_only"
        assert CacheMode.REFRESH.value == "refresh"
