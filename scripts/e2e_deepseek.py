#!/usr/bin/env python3
"""Task 6 E2E: Run ch10 extraction with DeepSeek."""
import json, re, time, sys, os
PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ_ROOT)
from t2c.llm_config import LLMConfig
from t2c.extractor import LLMExtractor
from t2c.corpus import CorpusManager
from t2c.segmenter import Segmenter

cfg = LLMConfig.from_env()
extractor = LLMExtractor(config=cfg)

raw_path = os.path.join(PROJ_ROOT, "data/rawtxt/红楼梦.txt")
raw_text = open(raw_path, encoding="utf-8").read()

ch_pattern = re.compile(r"第[一二三四五六七八九十百千零\d]+回")
matches = list(ch_pattern.finditer(raw_text))
ch10 = matches[9]
ch10_end = matches[10].start() if len(matches) > 10 else len(raw_text)
ch10_text = raw_text[ch10.start():ch10_end]
ch10_title = ch10_text[:60].split("\n")[0].strip()

print(f"Chapter 10: {ch10_title}")
print(f"Length: {len(ch10_text)} chars", flush=True)

cm = CorpusManager()
doc, text = cm.ingest_text(ch10_text, "hongloumeng_ch10")
blocks = cm.create_blocks(doc, text)
seger = Segmenter()
all_segs = []
for b in blocks:
    bt = cm.get_block_text(doc, b, text)
    all_segs.extend(seger.segment_block(doc.id, b, bt))
print(f"Segments: {len(all_segs)}", flush=True)

t0 = time.time()
objects = extractor.extract_chapter(
    doc_id="hongloumeng",
    chapter_num=10,
    chapter_title=ch10_title,
    segments=all_segs,
)
elapsed = time.time() - t0

print(f"Objects: {len(objects)}", flush=True)
print(f"Input tokens: {extractor._total_input_tokens}", flush=True)
print(f"Output tokens: {extractor._total_output_tokens}", flush=True)
print(f"API elapsed: {extractor._api_elapsed_sec:.1f}s", flush=True)
print(f"Total elapsed: {elapsed:.1f}s", flush=True)
print(f"Cache hits: {extractor._cache_hits}", flush=True)
print(f"Batch timings: {json.dumps(extractor._batch_timings, ensure_ascii=False)}", flush=True)

types = {}
for o in objects:
    t = o.get("type", "?")
    types[t] = types.get(t, 0) + 1
print(f"Types: {json.dumps(types, ensure_ascii=False)}", flush=True)

cost = extractor._total_input_tokens / 1_000_000 * 1 + extractor._total_output_tokens / 1_000_000 * 2
print(f"Estimated cost: ¥{cost:.4f}", flush=True)
