#!/usr/bin/env python3
"""Live A/B test: 逐對 vs 批次，5 個 target word，28 個 candidate pair。

用法：
    cd backend && set -a && source .env && set +a
    PYTHONPATH=src python tests/test_batch_judge_30pairs.py
"""
from __future__ import annotations

import json
import os
import sys
import time

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-2.5-flash-lite"

# ── Prompts ──

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
        sys.exit("GEMINI_API_KEY not set")
    return OpenAI(api_key=api_key, base_url=GEMINI_BASE)


def call_single(client, target, candidate):
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
    u = resp.usage
    content = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {"link": "parse_error", "confidence": 0, "reason": ""}
    return data, u.prompt_tokens, u.completion_tokens


def call_batch(client, target, candidates):
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
    u = resp.usage
    content = resp.choices[0].message.content or "[]"
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            for key in ("results", "judgements", "items", "candidates"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                data = [data]
    except json.JSONDecodeError:
        data = []
    return data, u.prompt_tokens, u.completion_tokens


def main():
    client = make_client()
    test_data = json.loads(open("/tmp/test_words.json").read())

    total_in_a = total_out_a = total_in_b = total_out_b = 0
    total_match = total_pairs = 0
    all_results_a = {}
    all_results_b = {}

    t0_a = time.time()
    # Method A: 逐對
    print("Running Method A (逐對)...")
    for group in test_data:
        target = tuple(group["target"])
        for cand in group["candidates"]:
            data, pin, pout = call_single(client, target, tuple(cand))
            total_in_a += pin
            total_out_a += pout
            all_results_a[(target[0], cand[0])] = data
    time_a = time.time() - t0_a

    # Method B: 批次
    print("Running Method B (批次)...")
    t0_b = time.time()
    for group in test_data:
        target = tuple(group["target"])
        candidates = [tuple(c) for c in group["candidates"]]
        batch_data, pin, pout = call_batch(client, target, candidates)
        total_in_b += pin
        total_out_b += pout
        for item in batch_data:
            word = item.get("word", "?")
            all_results_b[(target[0], word)] = item
    time_b = time.time() - t0_b

    # ── 比較 ──
    print(f"\n{'=' * 75}")
    print(f"  RESULTS: 5 targets, {sum(len(g['candidates']) for g in test_data)} pairs")
    print(f"{'=' * 75}")

    for group in test_data:
        target = group["target"]
        print(f"\n  ── {target[0]} ({target[1][:15]}) ──")
        for cand in group["candidates"]:
            key_a = (target[0], cand[0])
            key_b = (target[0], cand[0])
            a = all_results_a.get(key_a, {})
            b = all_results_b.get(key_b, {})
            a_link = a.get("link", "?")
            b_link = b.get("link", "?")
            a_conf = a.get("confidence", 0)
            b_conf = b.get("confidence", 0)
            same = a_link == b_link
            if same:
                total_match += 1
            total_pairs += 1
            marker = "✓" if same else "✗"
            print(f"    {marker} {cand[0]:<18} A={a_link:<16} B={b_link:<16} Δconf={abs(a_conf-b_conf):.1f}")

    # ── Summary ──
    print(f"\n{'=' * 75}")
    print(f"  SUMMARY")
    print(f"{'=' * 75}")
    print(f"\n  Tokens:")
    print(f"    A (逐對): in={total_in_a:>6} out={total_out_a:>5} total={total_in_a+total_out_a:>6}")
    print(f"    B (批次): in={total_in_b:>6} out={total_out_b:>5} total={total_in_b+total_out_b:>6}")
    save_in = (1 - total_in_b / total_in_a) * 100 if total_in_a else 0
    save_total = (1 - (total_in_b+total_out_b) / (total_in_a+total_out_a)) * 100 if total_in_a else 0
    print(f"    Input 節省: {save_in:.0f}%")
    print(f"    Total 節省: {save_total:.0f}%")

    cost_a = total_in_a/1e6*0.10 + total_out_a/1e6*0.40
    cost_b = total_in_b/1e6*0.10 + total_out_b/1e6*0.40
    print(f"    Cost A: ${cost_a:.6f}")
    print(f"    Cost B: ${cost_b:.6f}")
    print(f"    Cost 節省: {(1-cost_b/cost_a)*100:.0f}%")

    print(f"\n  Time:")
    print(f"    A: {time_a:.1f}s  B: {time_b:.1f}s  加速: {time_a/time_b:.1f}x")

    print(f"\n  一致率: {total_match}/{total_pairs} ({total_match/total_pairs*100:.0f}%)")
    print()


if __name__ == "__main__":
    main()
