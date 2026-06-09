"""Unit tests for ops/ios_perf_naming.py + ops/ios_log_assert.py (pure, no device).

Both modules are test/ops-side only — they never touch the iOS app's logging
implementation. The parser consumes either the `kg.ios.logs.v1` envelope emitted
by `ios_ops.sh logs --json` or raw `log stream/show --style ndjson` lines.
"""
import importlib.util
import json
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parent.parent


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, OPS / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # dataclass annotation resolution needs this
    spec.loader.exec_module(mod)
    return mod


naming = _load("ios_perf_naming")
log_assert = _load("ios_log_assert")


# ─────────────────────────────── naming contract ───────────────────────────────

def test_parse_valid_four_segment_name():
    m = naming.parse("podcast.player.play.readyLatency")
    assert (m.feature, m.scenario, m.action, m.metric) == (
        "podcast", "player", "play", "readyLatency"
    )
    assert m.kind == "latency"


def test_parse_classifies_frame_metric():
    assert naming.parse("notebook.list.scroll.frames").kind == "frame"
    assert naming.parse("reader.scroll.fling.hitchRatio").kind == "frame"


def test_parse_classifies_first_paint_as_latency():
    assert naming.parse("reader.open.load.firstPaint").kind == "latency"


def test_classify_metric_buckets():
    assert naming.classify_metric("frames") == "frame"
    assert naming.classify_metric("hitchRatio") == "frame"
    assert naming.classify_metric("readyLatency") == "latency"
    assert naming.classify_metric("durationMs") == "latency"
    assert naming.classify_metric("firstPaint") == "latency"
    assert naming.classify_metric("count") == "count"


def test_classify_metric_word_boundaries_not_substrings():
    # `ms` must not leak into words that merely contain it
    assert naming.classify_metric("itemsCount") == "count"
    assert naming.classify_metric("msgCount") == "count"
    assert naming.classify_metric("streams") == "count"
    # `drop`/`jank`/`time`/`paint` only match as whole camelCase words
    assert naming.classify_metric("dropdownState") == "count"
    assert naming.classify_metric("runtimeId") == "count"
    # genuine signals still classify
    assert naming.classify_metric("droppedFrames") == "frame"
    assert naming.classify_metric("scrollLatency") == "latency"


def test_parse_rejects_wrong_arity():
    for bad in ("podcast.player.play", "a.b.c.d.e", "justone"):
        try:
            naming.parse(bad)
            assert False, f"expected ValueError for {bad!r}"
        except ValueError:
            pass


def test_parse_rejects_uppercase_leading_segment():
    try:
        naming.parse("Podcast.player.play.readyLatency")
        assert False, "expected ValueError for uppercase feature"
    except ValueError:
        pass


def test_strict_mode_gates_unknown_feature():
    # grammar-valid but feature not in the registry
    assert naming.is_valid("zzz.scenario.action.metric") is True  # lenient default
    assert naming.is_valid("zzz.scenario.action.metric", strict=True) is False
    assert naming.is_valid("podcast.player.play.readyLatency", strict=True) is True


def test_known_features_cover_app_surfaces():
    for f in ("podcast", "reader", "notebook", "bookshelf", "vocabulary", "settings"):
        assert f in naming.KNOWN_FEATURES


# ─────────────────────────────── log parser ───────────────────────────────

ENVELOPE = {
    "schema": "kg.ios.logs.v1",
    "entries": [
        {"timestamp": "t1", "eventType": "logEvent", "subsystem": "com.Max0228.BooksBrowser",
         "category": "Sync", "message": "sync completed reader.open.load.firstPaint=812ms"},
        {"timestamp": "t2", "eventType": "logEvent", "subsystem": "com.Max0228.BooksBrowser",
         "category": "Reader", "message": "notebook.list.scroll.frames=119"},
    ],
}

NDJSON = "\n".join([
    json.dumps({"timestamp": "t1", "eventType": "logEvent", "messageType": "Default",
                "subsystem": "com.Max0228.BooksBrowser", "category": "Sync",
                "eventMessage": "podcast.player.play.readyLatency=240ms"}),
    json.dumps({"timestamp": "t2", "eventType": "logEvent", "messageType": "Error",
                "subsystem": "com.Max0228.BooksBrowser", "category": "Reader",
                "eventMessage": "decode failed"}),
    "",  # blank line tolerated
    json.dumps({"timestamp": "t3", "eventType": "logEvent", "messageType": "Fault",
                "subsystem": "com.Max0228.BooksBrowser", "category": "Reader",
                "eventMessage": "fatal"}),
])


def test_normalize_detects_envelope():
    events = log_assert.normalize_events(json.dumps(ENVELOPE))
    assert len(events) == 2
    assert events[0].category == "Sync"
    assert events[0].message.startswith("sync completed")


def test_normalize_detects_ndjson_with_levels():
    events = log_assert.normalize_events(NDJSON)
    assert len(events) == 3
    assert [e.level for e in events] == ["Default", "Error", "Fault"]


def test_normalize_tolerates_bad_lines():
    text = NDJSON + "\nnot json at all\n{also bad"
    events = log_assert.normalize_events(text)
    assert len(events) == 3  # the two garbage lines are skipped


def test_summarize_counts_and_error_rate():
    events = log_assert.normalize_events(NDJSON)
    s = log_assert.summarize(events)
    assert s["byCategory"] == {"Sync": 1, "Reader": 2}
    assert s["byLevel"] == {"Default": 1, "Error": 1, "Fault": 1}
    # Error + Fault over 3 events
    assert abs(s["errorRate"] - (2 / 3)) < 1e-9


def test_summarize_error_rate_null_without_levels():
    events = log_assert.normalize_events(json.dumps(ENVELOPE))
    s = log_assert.summarize(events)
    assert s["errorRate"] is None  # envelope projection drops messageType


def test_metric_token_regex_rejects_over_long_dotted_path():
    # 5 dotted segments must NOT silently truncate to the first 4
    text = json.dumps({"category": "Reader",
                       "eventMessage": "x.reader.open.load.firstPaint=5"})
    s = log_assert.summarize(log_assert.normalize_events(text))
    assert s["metrics"] == {}  # over-long path is rejected, not truncated


def test_metric_token_regex_ignores_dotted_prefix():
    # a contract-valid token glued behind a dotted prefix must not match
    text = json.dumps({"category": "Reader",
                       "eventMessage": "ns.podcast.player.play.readyLatency=9"})
    s = log_assert.summarize(log_assert.normalize_events(text))
    assert "podcast.player.play.readyLatency" not in s["metrics"]


def test_two_metrics_one_message():
    text = json.dumps({"category": "Reader",
                       "eventMessage": "two podcast.player.play.readyLatency=1 and notebook.list.scroll.frames=2"})
    s = log_assert.summarize(log_assert.normalize_events(text))
    assert s["metrics"]["podcast.player.play.readyLatency"]["avg"] == 1.0
    assert s["metrics"]["notebook.list.scroll.frames"]["avg"] == 2.0


def test_extract_metrics_from_messages():
    events = log_assert.normalize_events(NDJSON)
    s = log_assert.summarize(events)
    assert "podcast.player.play.readyLatency" in s["metrics"]
    agg = s["metrics"]["podcast.player.play.readyLatency"]
    assert agg["count"] == 1
    assert agg["avg"] == 240.0
    assert agg["unit"] == "ms"
    assert agg["kind"] == "latency"


def test_frame_metrics_are_bucketed_separately():
    events = log_assert.normalize_events(json.dumps(ENVELOPE))
    s = log_assert.summarize(events)
    assert "notebook.list.scroll.frames" in s["frames"]
    assert "reader.open.load.firstPaint" not in s["frames"]  # latency, not frame
    assert "reader.open.load.firstPaint" in s["metrics"]


def test_metric_aggregates_min_max_avg():
    text = "\n".join(
        json.dumps({"category": "Reader", "eventMessage": f"reader.open.load.firstPaint={v}ms"})
        for v in (100, 200, 300)
    )
    s = log_assert.summarize(log_assert.normalize_events(text))
    agg = s["metrics"]["reader.open.load.firstPaint"]
    assert (agg["min"], agg["max"], agg["avg"]) == (100.0, 300.0, 200.0)


def test_features_summary_groups_by_feature():
    events = log_assert.normalize_events(NDJSON)
    s = log_assert.summarize(events)
    assert "podcast" in s["features"]
    assert "podcast.player.play.readyLatency" in s["features"]["podcast"]["metrics"]
    assert s["features"]["podcast"]["events"] == 1  # one event carried a podcast metric


# ─────────────────────────────── assertions ───────────────────────────────

def test_assert_max_error_rate_fails_when_exceeded():
    s = log_assert.summarize(log_assert.normalize_events(NDJSON))
    failures = log_assert.run_assertions(s, max_error_rate=0.1)
    assert any("error rate" in f.lower() for f in failures)


def test_assert_max_error_rate_passes_when_within():
    s = log_assert.summarize(log_assert.normalize_events(NDJSON))
    assert log_assert.run_assertions(s, max_error_rate=0.9) == []


def test_assert_require_feature_missing():
    s = log_assert.summarize(log_assert.normalize_events(json.dumps(ENVELOPE)))
    failures = log_assert.run_assertions(s, require_features=["podcast"])
    assert any("podcast" in f for f in failures)


def test_assert_min_events():
    s = log_assert.summarize(log_assert.normalize_events(NDJSON))
    assert log_assert.run_assertions(s, min_events=99)
    assert log_assert.run_assertions(s, min_events=1) == []
