"""LLM batch cache — deterministic replay of LLM responses for a given input.

Design (see spec/llm_cost_cache_design.md):
  - Cache key is sha256 of a canonical JSON object containing the protocol
    version, model, prompt version, doc/chapter/batch coordinates, segment
    ids+hashes, the hash of the known entity map, and the option block
    (max_tokens, thinking_budget, temperature).
  - Wall clock, request id, retry count, token usage, and elapsed time are
    intentionally excluded so the same input always yields the same key.
  - Cache files live under <cache_dir>/llm/v1/<key>.json. The default
    cache_dir is .t2c_cache at the project root.
  - Four cache modes: off / read_write / read_only / refresh.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# Top-level cache directory layout. Bump the version segment (v1 → v2) when
# the cache key schema or entry shape changes incompatibly.
_CACHE_SUBDIR = "llm/v1"
_DEFAULT_CACHE_DIR = ".t2c_cache"


class CacheMode(str, Enum):
    """How the extractor should treat the cache for a given batch."""

    OFF = "off"
    READ_WRITE = "read_write"
    READ_ONLY = "read_only"
    REFRESH = "refresh"


@dataclass
class CacheEntry:
    """A persisted batch-level LLM exchange.

    Stores enough information to audit and replay: the request signature,
    the raw model response, the parsed candidates, and quality flags
    describing whether the response was truncated or had to be salvaged
    from a partial JSON.
    """

    cache_schema: str
    cache_key: str
    created_at: str
    request: dict[str, Any]
    response: dict[str, Any]
    quality: dict[str, Any] = field(default_factory=dict)


def _canonical_json(payload: Any) -> str:
    """Render `payload` as a deterministic JSON string.

    Sorted keys + compact separators keep the hash stable across
    Python versions and dict-iteration order.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_segment_map(
    segment_ids: list[str], segment_hashes: list[str]
) -> str:
    """Combine segment ids and their hashes into a single digest.

    The two lists are paired and ordered, so we serialize as a list of
    {id, hash} objects to keep the digest stable.
    """
    if len(segment_ids) != len(segment_hashes):
        raise ValueError("segment_ids and segment_hashes must have equal length")
    payload = [{"id": sid, "hash": h} for sid, h in zip(segment_ids, segment_hashes)]
    return _sha256_hex(_canonical_json(payload))


def _hash_string_list(values: list[str]) -> str:
    return _sha256_hex(_canonical_json(list(values)))


def _hash_entity_map(known_entities: dict[str, str] | None) -> str:
    """Hash a {name: id} entity map.

    Sorted by name so iteration order never affects the digest.
    """
    if not known_entities:
        return _sha256_hex("{}")
    items = sorted(known_entities.items(), key=lambda kv: kv[0])
    return _sha256_hex(_canonical_json(items))


def _hash_text(text: str) -> str:
    return "sha256:" + _sha256_hex(text)


def compute_cache_key(
    *,
    doc_id: str,
    chapter_num: int,
    chapter_title: str,
    batch_index: int,
    segment_ids: list[str],
    segment_hashes: list[str],
    known_entities: dict[str, str] | None,
    model: str,
    prompt_version: str,
    extractor_protocol: str,
    options: dict[str, Any],
    cache_schema: str = "t2c-llm-cache-v1",
) -> str:
    """Compute the cache key for a single batch.

    All inputs are part of the key. To intentionally invalidate the cache,
    change `prompt_version` or `extractor_protocol` (or bump `cache_schema`).
    """
    if not segment_ids:
        # Even an empty batch is cacheable — but the digest must be stable.
        segment_text_hash = _sha256_hex("")
    else:
        segment_text_hash = _hash_segment_map(segment_ids, segment_hashes)

    payload = {
        "cache_schema": cache_schema,
        "extractor_protocol": extractor_protocol,
        "model": model,
        "prompt_version": prompt_version,
        "doc_id": doc_id,
        "chapter_num": int(chapter_num),
        "chapter_title": chapter_title,
        "batch_index": int(batch_index),
        "segment_ids": list(segment_ids),
        "segment_hashes": list(segment_hashes),
        "segment_text_hash": segment_text_hash,
        "known_entity_map_hash": _hash_entity_map(known_entities),
        "options": dict(options),
    }
    digest = _sha256_hex(_canonical_json(payload))
    return f"{cache_schema}:{digest}"


def _normalize_cache_dir(cache_dir: str | os.PathLike[str] | None) -> str:
    if not cache_dir:
        return os.path.join(_DEFAULT_CACHE_DIR, _CACHE_SUBDIR)
    return os.path.join(str(cache_dir), _CACHE_SUBDIR)


class LLMCache:
    """Filesystem-backed LLM batch cache.

    The cache is intentionally minimal: one JSON file per batch keyed by
    the deterministic digest. There is no write-ahead log, no TTL, and no
    per-key locking — the contract is "same key → same value", and
    `refresh` mode is the only way to overwrite an existing entry.
    """

    def __init__(self, cache_dir: str | os.PathLike[str] | None = None) -> None:
        self._dir = _normalize_cache_dir(cache_dir)

    @property
    def cache_dir(self) -> str:
        return self._dir

    def _path_for(self, cache_key: str) -> str:
        if ":" in cache_key:
            # Strip schema prefix to keep file names filesystem-safe.
            _, _, key = cache_key.partition(":")
        else:
            key = cache_key
        return os.path.join(self._dir, key + ".json")

    def lookup(self, cache_key: str) -> CacheEntry | None:
        """Return the cached entry for `cache_key`, or None if absent.

        Returns None (not raising) on missing files, corrupt JSON, or
        schema mismatch — the caller is expected to treat both "missing"
        and "corrupt" as a cache miss.
        """
        path = self._path_for(cache_key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("LLMCache: corrupt cache file %s: %s", path, exc)
            return None
        if not isinstance(data, dict):
            return None
        if data.get("cache_key") != cache_key:
            logger.warning("LLMCache: cache key mismatch in %s", path)
            return None
        try:
            return CacheEntry(
                cache_schema=data.get("cache_schema", ""),
                cache_key=data["cache_key"],
                created_at=data.get("created_at", ""),
                request=data.get("request", {}),
                response=data.get("response", {}),
                quality=data.get("quality", {}),
            )
        except KeyError:
            return None

    def store(self, entry: CacheEntry) -> None:
        """Persist `entry` to disk, overwriting any existing file.

        Creates the cache directory if needed. The caller is responsible
        for choosing `refresh` (force overwrite) vs. `read_write`
        (only write on miss).
        """
        os.makedirs(self._dir, exist_ok=True)
        path = self._path_for(entry.cache_key)
        payload = asdict(entry)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)

    def clear(self) -> int:
        """Remove every entry in the cache directory. Returns count removed."""
        if not os.path.isdir(self._dir):
            return 0
        removed = 0
        for name in os.listdir(self._dir):
            if not name.endswith(".json"):
                continue
            try:
                os.remove(os.path.join(self._dir, name))
                removed += 1
            except OSError:
                pass
        return removed

    @staticmethod
    def now_iso() -> str:
        """Return current UTC timestamp in ISO 8601 form (no microseconds)."""
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


__all__ = [
    "CacheMode",
    "CacheEntry",
    "LLMCache",
    "compute_cache_key",
    "compute_options_digest",
    "hash_known_entities",
]


# A small helper for the tests and for callers that want a stable digest
# of the options block without re-implementing the canonical JSON dance.
def compute_options_digest(options: dict[str, Any]) -> str:
    return _sha256_hex(_canonical_json(dict(options)))


def hash_known_entities(known_entities: dict[str, str] | None) -> str:
    return _hash_entity_map(known_entities)


# Re-export the segment-list hasher for tests; the public name reads better
# than reaching into the private helper.
def hash_segment_batch(
    segment_ids: list[str], segment_hashes: list[str]
) -> str:
    return _hash_segment_map(segment_ids, segment_hashes)


# Re-export the text hashing helper for tests that want the prefixed form.
def hash_text(text: str) -> str:
    return _hash_text(text)


def hash_string_list(values: list[str]) -> str:
    return _hash_string_list(values)
