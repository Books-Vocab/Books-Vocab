"""Cost aggregator — parses workspace events.jsonl + pipeline_log.jsonl to
compute total USD spent across the 13-stage pipeline.

Pricing sources (verified 2026-05-30):
  - Anthropic Claude (stages 1-10): claude CLI's `result` event already
    contains `total_cost_usd` and `modelUsage[model].costUSD` computed using
    Anthropic's published per-token rates (incl. cache discounts and the
    1M-context premium). We just sum them — no manual rate table needed.
  - Vertex AI Gemini TTS (stage 11): Vertex billing applies to our
    `vertexai=True` client. Vertex pricing page lists Gemini 2.5 Pro at
    $1.25/1M input + $10/1M output (≤200K context). No TTS-specific row
    exists on Vertex's page; same base rate applies to all modalities.
    Source: https://cloud.google.com/vertex-ai/generative-ai/pricing
  - Gemini 2.5 Flash: $0.30/1M input + $2.50/1M output.
  - Audio output token conversion: 25 tokens / second of audio
    (Google official, https://ai.google.dev/gemini-api/docs/pricing).
  - Whisper subtitle (stage 13): runs locally on CPU/GPU — $0.

To override TTS pricing (e.g. switch to AI Studio's TTS-specific rates),
set PODCAST_TTS_PRICING env var to a JSON dict matching VERTEX_PRICING shape.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Pricing tables (per 1M tokens, USD) ───

VERTEX_PRICING: dict[str, dict] = {
    # Defaults match Vertex / AI Studio billing for our `vertexai=True` client.
    # Long-context tier kicks in above 200K input tokens.
    #
    # gemini-2.5-flash-tts is the current default in .env (since 2026-06-02).
    # gemini-3.1-flash-tts-preview (selectable via --tts-model):
    #   Source: https://ai.google.dev/gemini-api/docs/pricing (TTS-specific row)
    #   $1.00/1M input + $20.00/1M output (audio = 25 tok/sec). No long-tier.
    #   Vertex preview mirrors AI Studio rates for TTS models.
    "gemini-3.1-flash-tts-preview": {
        "input_short": 1.00, "input_long": 1.00,
        "output_short": 20.00, "output_long": 20.00,
        "long_threshold": 200_000,
    },
    "gemini-2.5-pro-tts": {
        "input_short": 1.25, "input_long": 2.50,
        "output_short": 10.00, "output_long": 15.00,
        "long_threshold": 200_000,
    },
    "gemini-2.5-pro": {
        "input_short": 1.25, "input_long": 2.50,
        "output_short": 10.00, "output_long": 15.00,
        "long_threshold": 200_000,
    },
    "gemini-2.5-flash-tts": {
        "input_short": 0.30, "input_long": 0.30,
        "output_short": 2.50, "output_long": 2.50,
        "long_threshold": 200_000,
    },
    "gemini-2.5-flash": {
        "input_short": 0.30, "input_long": 0.30,
        "output_short": 2.50, "output_long": 2.50,
        "long_threshold": 200_000,
    },
}

# Allow runtime override via env (JSON dict).
_override = os.getenv("PODCAST_TTS_PRICING", "").strip()
if _override:
    try:
        VERTEX_PRICING.update(json.loads(_override))
    except (json.JSONDecodeError, TypeError):
        # Keep defaults when override is malformed.
        logger.warning("Invalid PODCAST_TTS_PRICING override; using default pricing")
        print("[podcast_cost] PODCAST_TTS_PRICING override is invalid JSON/type; using default pricing", file=sys.stderr)

PRICING_META = {
    "vertex_source": "https://cloud.google.com/vertex-ai/generative-ai/pricing",
    "anthropic_source": "claude CLI result.modelUsage[*].costUSD (Anthropic published rates)",
    "audio_token_rate": 25,  # tokens per second of audio
    "long_context_threshold_tokens": 200_000,
    "verified_against": "2026-05-30",
}


def _resolve_pricing(model: str, table: dict[str, dict] | None = None) -> dict:
    """Resolve a model name to its pricing row.

    Exact key wins. Otherwise pick the longest (= most specific) key that is a
    substring of `model`, so e.g. 'gemini-2.5-flash-tts-experimental' resolves
    to 'gemini-2.5-flash-tts' rather than the shorter 'gemini-2.5-flash'.
    Crucially this is independent of `table` insertion order — a substring scan
    in dict order would silently depend on which prefix happens to be listed
    first. Fully unknown models fall back to pro rates (conservative: slightly
    overestimates cost for unknown smaller models, safer than under-reporting).
    """
    table = VERTEX_PRICING if table is None else table
    rates = table.get(model)
    if rates is not None:
        return rates
    for key in sorted(table, key=len, reverse=True):
        if key in model:
            return table[key]
    return table["gemini-2.5-pro"]


def _vertex_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD for a Vertex TTS / Gemini call. Falls back to pro rates
    for unknown models so we never silently report $0."""
    rates = _resolve_pricing(model)
    long = input_tokens > rates["long_threshold"]
    in_rate = rates["input_long"] if long else rates["input_short"]
    out_rate = rates["output_long"] if long else rates["output_short"]
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


# ─── Aggregator ───

@dataclass
class StageBucket:
    usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    audio_seconds: float = 0.0
    calls: int = 0
    model: str = ""
    episodes: dict = field(default_factory=dict)  # ep_num -> {usd, ...}


def _ep_from_label(label: str) -> int | None:
    """Extract EP number from labels like 'Scriptwriter EP4' / 'Synthesize EP12'."""
    m = re.search(r"EP\s*(\d+)", label or "", re.I)
    return int(m.group(1)) if m else None


# Stage-label → canonical-name resolution table. Iterated in this exact order:
# the first pair whose any substring matches wins, so MORE-SPECIFIC entries MUST
# come before their prefixes (e.g. 'enricher-gap' before bare 'enricher'). The
# ordering is load-bearing — a reordered or newly inserted rule can silently
# mis-bucket cost. Each entry lists every accepted spelling (hyphen + space
# variants).
_STAGE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("scriptwriter", "scriptwrite"), "scriptwrite"),
    (("script review", "script-review"), "script-review"),
    (("synthesize",), "synthesize"),
    (("series polish", "series-polish"), "series-polish"),
    (("plan review", "plan-review"), "plan-review"),
    (("tts-prep", "tts prep"), "tts-prep"),
    (("enricher-gap", "enricher gap"), "enricher-gap"),
    (("enricher",), "enricher"),
    (("architect",), "architect"),
    (("analyst",), "analyst"),
    (("cover",), "cover"),
    (("prep",), "prep"),
)


def _stage_from_label(label: str) -> str:
    """Map agent stage_label to its canonical pipeline stage name."""
    if not label:
        return "unknown"
    low = label.lower()
    for substrings, canonical in _STAGE_RULES:
        if any(s in low for s in substrings):
            return canonical
    return low


def aggregate_workspace(ws_dir: Path) -> dict:
    """Walk events.jsonl + return cost summary.

    Structure:
        {
          "workspace": "...",
          "total_usd": 12.34,
          "by_stage": {stage: StageBucket-as-dict},
          "by_model": {model: {usd, input_tokens, output_tokens, calls}},
          "pricing": PRICING_META,
          "warnings": [...],  # e.g. missing events.jsonl, fallback pricing used
        }
    """
    events_path = ws_dir / "events.jsonl"
    pipeline_log_path = ws_dir / "pipeline_log.jsonl"

    by_stage: dict[str, StageBucket] = defaultdict(StageBucket)
    by_model: dict[str, dict] = defaultdict(lambda: {
        "usd": 0.0, "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_create_tokens": 0,
        "audio_seconds": 0.0, "calls": 0,
    })
    warnings: list[str] = []

    if not events_path.exists():
        if pipeline_log_path.exists():
            warnings.append(
                "events.jsonl missing — pipeline ran without PODCAST_VERBOSE=1. "
                "Per-stage Claude costs are unavailable. Set PODCAST_VERBOSE=1 "
                "before re-running for full cost tracking."
            )
        else:
            warnings.append("No events.jsonl or pipeline_log.jsonl — workspace empty.")
        return {
            "workspace": ws_dir.name,
            "total_usd": 0.0,
            "by_stage": {},
            "by_model": {},
            "pricing": PRICING_META,
            "warnings": warnings,
        }

    with events_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Invalid event json in %s: %s", events_path, exc)
                continue

            stage_label = obj.get("stage_label", "")
            ev = obj.get("event", {})
            ev_type = ev.get("type")

            stage = _stage_from_label(stage_label)
            ep = _ep_from_label(stage_label)

            # ─── Anthropic claude `result` events ───
            if ev_type == "result" and "modelUsage" in ev:
                for model, mu in (ev.get("modelUsage") or {}).items():
                    cost = float(mu.get("costUSD") or 0.0)
                    in_tok = int(mu.get("inputTokens") or 0)
                    out_tok = int(mu.get("outputTokens") or 0)
                    cr_tok = int(mu.get("cacheReadInputTokens") or 0)
                    cc_tok = int(mu.get("cacheCreationInputTokens") or 0)

                    bucket = by_stage[stage]
                    bucket.usd += cost
                    bucket.input_tokens += in_tok
                    bucket.output_tokens += out_tok
                    bucket.cache_read_tokens += cr_tok
                    bucket.cache_create_tokens += cc_tok
                    bucket.calls += 1
                    bucket.model = model  # last write wins; stages use one model

                    if ep is not None:
                        ep_b = bucket.episodes.setdefault(str(ep), {
                            "usd": 0.0, "input_tokens": 0, "output_tokens": 0, "calls": 0,
                        })
                        ep_b["usd"] += cost
                        ep_b["input_tokens"] += in_tok
                        ep_b["output_tokens"] += out_tok
                        ep_b["calls"] += 1

                    bm = by_model[model]
                    bm["usd"] += cost
                    bm["input_tokens"] += in_tok
                    bm["output_tokens"] += out_tok
                    bm["cache_read_tokens"] += cr_tok
                    bm["cache_create_tokens"] += cc_tok
                    bm["calls"] += 1

            # ─── Our tts_usage events ───
            elif ev_type == "tts_usage":
                # Fallback only fires for malformed events; synthesize.py always
                # writes "model" into tts_usage. Match the live default (2.5-flash).
                model = ev.get("model", "gemini-2.5-flash-tts")
                in_tok = int(ev.get("input_tokens") or 0)
                out_tok = int(ev.get("output_tokens") or 0)
                audio_s = float(ev.get("audio_seconds") or 0.0)
                cost = _vertex_cost(model, in_tok, out_tok)

                bucket = by_stage["synthesize"]
                bucket.usd += cost
                bucket.input_tokens += in_tok
                bucket.output_tokens += out_tok
                bucket.audio_seconds += audio_s
                bucket.calls += 1
                bucket.model = model

                if ep is not None:
                    ep_b = bucket.episodes.setdefault(str(ep), {
                        "usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                        "audio_seconds": 0.0, "calls": 0,
                    })
                    ep_b["usd"] += cost
                    ep_b["input_tokens"] += in_tok
                    ep_b["output_tokens"] += out_tok
                    ep_b["audio_seconds"] += audio_s
                    ep_b["calls"] += 1

                bm = by_model[model]
                bm["usd"] += cost
                bm["input_tokens"] += in_tok
                bm["output_tokens"] += out_tok
                bm["audio_seconds"] += audio_s
                bm["calls"] += 1

                if ev.get("usage_source") == "estimated":
                    warnings.append(
                        f"synthesize batch {ev.get('batch_index')} EP{ep}: "
                        "used estimated tokens (Vertex usage_metadata missing)."
                    )

            # ─── Our image_usage events (cover stage) ───
            elif ev_type == "image_usage":
                # Pexels stock = free license → cost_usd 0. Tracked for the
                # provenance count (which photo, how many calls), not spend.
                bucket = by_stage["cover"]
                bucket.usd += float(ev.get("cost_usd") or 0.0)
                bucket.calls += 1

    total_usd = sum(b.usd for b in by_stage.values())

    # Dedup warnings, cap.
    seen, deduped = set(), []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            deduped.append(w)
        if len(deduped) >= 10:
            deduped.append(f"… {len(warnings) - 10} more suppressed")
            break

    return {
        "workspace": ws_dir.name,
        "total_usd": round(total_usd, 4),
        "by_stage": {s: asdict(b) for s, b in by_stage.items()},
        "by_model": dict(by_model),
        "pricing": PRICING_META,
        "warnings": deduped,
    }
