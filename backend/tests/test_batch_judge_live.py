#!/usr/bin/env python3
"""Live A/B test: 逐對 judge vs 批次 judge。

直接呼叫 Gemini LLM，比較：
1. 結果一致性（link type、confidence 差異）
2. Token 消耗差異

用法：
    cd backend && PYTHONPATH=src python tests/test_batch_judge_live.py
"""
from __future__ import annotations

import json
import os
import sys
import time

# ── 測試資料：真實詞對（從 00287 的 graph 中挑選） ──

TARGET = ("cowering", "畏縮、退縮")

CANDIDATES = [
    ("hunkered", "蹲伏"),
    ("scuttled forward", "匆忙向前跑"),
    ("demure", "端莊的、矜持的"),
    ("stately", "莊嚴的、堂皇的"),
    ("wriggling", "扭動、蠕動"),
    ("flinching", "畏縮、退縮"),
    ("trembling", "顫抖"),
    ("unadorned", "未裝飾的、樸素的"),
]

# ── LLM 設定 ──

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-2.5-flash-lite"

# 現有的逐對 prompt
SINGLE_SYSTEM = """Judge vocabulary relationship. Choose ONE type:
- contrasts_with: Genuinely opposite or contrasting meanings
  YES: unkempt/primped, hunkered/loped, meticulous/sloppy
  NO: bust/midriff (different body parts, not opposites)
- shares_usage: Used in similar contexts or fill similar grammatical roles
  YES: luster/resplendent, haggling/extorting, cacophony/clang
- not_applicable: No meaningful learning relationship

Write "reason" in 繁體中文 (1-2 sentences). Explain the relationship AND highlight the nuance/difference between the two words to help learners distinguish them.
Example: "都形容光彩奪目，但 luster 偏指物體表面的光澤質感，resplendent 則強調整體華麗壯觀的視覺效果。"

Respond JSON: {"link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}"""

SINGLE_USER = """Word A: {word_a}
Meaning A: {meaning_a}

Word B: {word_b}
Meaning B: {meaning_b}

Determine the relationship type and your confidence (0.0-1.0)."""

# 新的批次 prompt
BATCH_SYSTEM = """Judge vocabulary relationships for the TARGET word against each CANDIDATE.
For each candidate, choose ONE type:
- contrasts_with: Genuinely opposite or contrasting meanings
- shares_usage: Used in similar contexts or fill similar grammatical roles
- not_applicable: No meaningful learning relationship

Write each "reason" in 繁體中文 (1-2 sentences). Highlight the nuance/difference to help learners.

Respond as a JSON array, one object per candidate (in order):
[{"word": "<candidate>", "link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}, ...]"""

BATCH_USER = """TARGET: {target_word} ({target_meaning})

Candidates:
{candidate_list}"""


def make_client():
    from openai import OpenAI
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set. Run: source backend/.env && export GEMINI_API_KEY")
    return OpenAI(api_key=api_key, base_url=GEMINI_BASE)


def call_single(client, target, candidate):
    """現有方式：一對一呼叫。"""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SINGLE_SYSTEM},
            {"role": "user", "content": SINGLE_USER.format(
                word_a=target[0], meaning_a=target[1],
                word_b=candidate[0], meaning_b=candidate[1],
            )},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    usage = resp.usage
    content = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {"link": "parse_error", "confidence": 0, "reason": content[:100]}
    return data, usage.prompt_tokens, usage.completion_tokens


def call_batch(client, target, candidates):
    """新方式：一次呼叫，所有 candidates 打包。"""
    cand_lines = "\n".join(
        f"{i+1}. {w} ({m})" for i, (w, m) in enumerate(candidates)
    )
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": BATCH_SYSTEM},
            {"role": "user", "content": BATCH_USER.format(
                target_word=target[0],
                target_meaning=target[1],
                candidate_list=cand_lines,
            )},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    usage = resp.usage
    content = resp.choices[0].message.content or "[]"
    try:
        data = json.loads(content)
        # Gemini 可能回傳 {"results": [...]} 而非裸 array
        if isinstance(data, dict):
            for key in ("results", "judgements", "items", "candidates"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                data = [data]
    except json.JSONDecodeError:
        data = []
    return data, usage.prompt_tokens, usage.completion_tokens


def main():
    client = make_client()

    print("=" * 70)
    print(f"  TARGET: {TARGET[0]} ({TARGET[1]})")
    print(f"  CANDIDATES: {len(CANDIDATES)}")
    print("=" * 70)

    # ── A: 逐對呼叫 ──
    print(f"\n--- Method A: 逐對呼叫 ({len(CANDIDATES)} 次 LLM call) ---\n")
    single_results = {}
    total_in_a = 0
    total_out_a = 0
    t0 = time.time()
    for word, meaning in CANDIDATES:
        data, pin, pout = call_single(client, TARGET, (word, meaning))
        single_results[word] = data
        total_in_a += pin
        total_out_a += pout
        link = data.get("link", "?")
        conf = data.get("confidence", 0)
        reason = data.get("reason", "")[:40]
        print(f"  {word:<20} {link:<18} conf={conf:.1f}  {reason}")
    time_a = time.time() - t0

    # ── B: 批次呼叫 ──
    print(f"\n--- Method B: 批次呼叫 (1 次 LLM call) ---\n")
    t0 = time.time()
    batch_data, total_in_b, total_out_b = call_batch(client, TARGET, CANDIDATES)
    time_b = time.time() - t0

    batch_results = {}
    for item in batch_data:
        word = item.get("word", "?")
        batch_results[word] = item
        link = item.get("link", "?")
        conf = item.get("confidence", 0)
        reason = item.get("reason", "")[:40]
        print(f"  {word:<20} {link:<18} conf={conf:.1f}  {reason}")

    # ── 比較 ──
    print(f"\n{'=' * 70}")
    print(f"  COMPARISON")
    print(f"{'=' * 70}")

    print(f"\n  Token 消耗:")
    print(f"    Method A (逐對): input={total_in_a:>6}, output={total_out_a:>5}, total={total_in_a+total_out_a:>6}")
    print(f"    Method B (批次): input={total_in_b:>6}, output={total_out_b:>5}, total={total_in_b+total_out_b:>6}")
    savings_in = (1 - total_in_b / total_in_a) * 100 if total_in_a else 0
    savings_total = (1 - (total_in_b + total_out_b) / (total_in_a + total_out_a)) * 100 if total_in_a else 0
    print(f"    Input 節省: {savings_in:.0f}%")
    print(f"    Total 節省: {savings_total:.0f}%")

    print(f"\n  時間:")
    print(f"    Method A: {time_a:.1f}s ({time_a/len(CANDIDATES):.1f}s/call)")
    print(f"    Method B: {time_b:.1f}s")
    print(f"    加速: {time_a/time_b:.1f}x")

    print(f"\n  結果一致性:")
    match = 0
    total = 0
    for word, _ in CANDIDATES:
        a = single_results.get(word, {})
        b = batch_results.get(word, {})
        a_link = a.get("link", "?")
        b_link = b.get("link", "?")
        a_conf = a.get("confidence", 0)
        b_conf = b.get("confidence", 0)
        same = a_link == b_link
        if same:
            match += 1
        total += 1
        marker = "✓" if same else "✗"
        print(f"    {marker} {word:<20} A={a_link:<18} B={b_link:<18} conf_diff={abs(a_conf-b_conf):.1f}")

    print(f"\n  一致率: {match}/{total} ({match/total*100:.0f}%)")
    print()


if __name__ == "__main__":
    main()
