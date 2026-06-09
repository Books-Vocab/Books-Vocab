from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "ios_diagnostics.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ios_diagnostics", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_xcode_log_groups_actionable_diagnostics():
    mod = _load_module()
    text = """
warning: StoreKit Configuration file for scheme "BooksAndVocab" can't be found at path "/tmp/missing.storekit"
/repo/ios/BooksAndVocab/Views/VocabHighlightPreferences.swift:47:12: warning: Switch covers known cases, but 'ColorScheme' may have additional unknown values; this is an error in the Swift 6 language mode
/repo/ios/BooksAndVocab/Views/PodcastSelectableSentenceTextView.swift:10:8: warning: umbrella header for module 'GoogleSignIn' does not include header 'GIDAppCheckError'
/repo/ios/BooksAndVocab/Views/Reader/Foo.swift:12:3: error: cannot find 'missingSymbol' in scope
** BUILD FAILED **
"""
    summary = mod.parse_log(text)

    assert summary["counts"] == {
        "errors": 1,
        "warnings": 3,
        "swift6": 1,
        "storekit": 1,
        "spm": 1,
        "signing": 0,
    }
    assert summary["result"] == "fail"
    assert summary["diagnostics"][0]["severity"] == "error"
    assert summary["diagnostics"][0]["file"].endswith("Foo.swift")
    assert summary["diagnostics"][1]["category"] == "storekit"
    assert summary["diagnostics"][2]["category"] == "swift6"


def test_json_output_is_stable(tmp_path, capsys):
    mod = _load_module()
    log = tmp_path / "build.log"
    log.write_text("warning: StoreKit Configuration file missing\n** BUILD SUCCEEDED **\n", encoding="utf-8")

    rc = mod.main(["--log", str(log), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["warnings"] == 1
    assert payload["result"] == "pass"


def test_parse_xcresult_build_results_uses_official_counts():
    mod = _load_module()
    payload = {
        "status": "succeeded",
        "errorCount": 0,
        "warningCount": 2,
        "errors": [],
        "warnings": [
            {"message": "StoreKit Configuration file for scheme missing"},
            {"message": "Switch covers known cases; this is an error in the Swift 6 language mode"},
        ],
    }

    summary = mod.parse_xcresult_build_results(payload)
    assert summary["source"] == "xcresult-build-results"
    assert summary["result"] == "pass"
    assert summary["counts"]["warnings"] == 2
    assert summary["counts"]["storekit"] == 1
    assert summary["counts"]["swift6"] == 1


def test_result_override_handles_quiet_xcodebuild_logs(tmp_path, capsys):
    mod = _load_module()
    log = tmp_path / "build.log"
    log.write_text("", encoding="utf-8")

    rc = mod.main(["--log", str(log), "--result", "pass", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "pass"


def test_parse_xcresult_test_results_uses_official_summary_and_failures():
    mod = _load_module()
    summary_payload = {
        "result": "Failed",
        "totalTestCount": 7,
        "passedTests": 5,
        "failedTests": 1,
        "skippedTests": 1,
        "expectedFailures": 0,
        "testFailures": [
            {
                "testName": "BooksAndVocabTests.testSyncFails()",
                "targetName": "BooksAndVocabTests",
                "failureText": "XCTAssertEqual failed",
                "testIdentifierString": "BooksAndVocabTests/testSyncFails()",
            }
        ],
    }

    parsed = mod.parse_xcresult_test_results(summary_payload, {"testNodes": []})

    assert parsed["source"] == "xcresult-test-results"
    assert parsed["result"] == "fail"
    assert parsed["counts"]["tests"] == 7
    assert parsed["counts"]["failedTests"] == 1
    assert parsed["timings"]["testBodyMs"] == 0
    assert parsed["timings"]["xcresultSessionMs"] is None
    assert parsed["diagnostics"][0]["category"] == "test"
    assert "testSyncFails" in parsed["diagnostics"][0]["message"]


def test_format_text_includes_test_counts():
    mod = _load_module()
    parsed = mod.parse_xcresult_test_results(
        {
            "result": "Passed",
            "totalTestCount": 3,
            "passedTests": 3,
            "failedTests": 0,
            "skippedTests": 0,
            "expectedFailures": 0,
            "testFailures": [],
        },
        {"testNodes": []},
    )

    text = mod.format_text(parsed, xcresult_path="/tmp/Test.xcresult")

    assert "source=xcresult-test-results" in text
    assert "tests=3 passed=3 failed=0 skipped=0" in text
    assert "testBodyMs=0 xcresultSessionMs=None" in text


def test_parse_xcresult_test_results_extracts_case_durations():
    mod = _load_module()
    parsed = mod.parse_xcresult_test_results(
        {
            "result": "Passed",
            "totalTestCount": 2,
            "passedTests": 2,
            "failedTests": 0,
            "skippedTests": 0,
            "expectedFailures": 0,
            "testFailures": [],
            "startTime": 100.0,
            "finishTime": 103.5,
        },
        {
            "testNodes": [
                {
                    "nodeType": "Test Plan",
                    "children": [
                        {
                            "nodeType": "Unit test bundle",
                            "children": [
                                {
                                    "nodeType": "Test Case",
                                    "name": "a()",
                                    "result": "Passed",
                                    "duration": "0.2500s",
                                },
                                {
                                    "nodeType": "Test Case",
                                    "name": "b()",
                                    "result": "Passed",
                                    "duration": "1.5秒",
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    )

    assert parsed["timings"]["testBodyMs"] == 1750
    assert parsed["timings"]["xcresultSessionMs"] == 3500


def test_parse_xcresult_test_results_extracts_app_launch_metric_summary():
    mod = _load_module()
    parsed = mod.parse_xcresult_test_results(
        {
            "result": "Passed",
            "totalTestCount": 1,
            "passedTests": 1,
            "failedTests": 0,
            "skippedTests": 0,
            "expectedFailures": 0,
            "testFailures": [],
        },
        {"testNodes": []},
        [
            {
                "testIdentifier": "BooksAndVocabUITests/testLaunchPerformance()",
                "testRuns": [
                    {
                        "metrics": [
                            {
                                "displayName": "Duration (AppLaunch)",
                                "identifier": "com.apple.dt.XCTMetric_ApplicationLaunch-AppLaunch.duration",
                                "measurements": [1.54, 1.42, 1.50],
                                "unitOfMeasurement": "s",
                            }
                        ]
                    }
                ],
            }
        ],
    )

    app_launch = parsed["performanceMetrics"]["appLaunch"]
    assert app_launch == {
        "tests": 1,
        "samples": 3,
        "averageMs": 1487,
        "minMs": 1420,
        "maxMs": 1540,
    }


def test_format_text_includes_app_launch_perf_summary():
    mod = _load_module()
    parsed = mod.parse_xcresult_test_results(
        {
            "result": "Passed",
            "totalTestCount": 1,
            "passedTests": 1,
            "failedTests": 0,
            "skippedTests": 0,
            "expectedFailures": 0,
            "testFailures": [],
        },
        {"testNodes": []},
        [
            {
                "testIdentifier": "BooksAndVocabUITests/testLaunchPerformance()",
                "testRuns": [
                    {
                        "metrics": [
                            {
                                "displayName": "Duration (AppLaunch)",
                                "identifier": "com.apple.dt.XCTMetric_ApplicationLaunch-AppLaunch.duration",
                                "measurements": [1.4, 1.5],
                                "unitOfMeasurement": "s",
                            }
                        ]
                    }
                ],
            }
        ],
    )

    text = mod.format_text(parsed, xcresult_path="/tmp/Test.xcresult")

    assert "metric=AppLaunch" in text
    assert "samples=2" in text
    assert "averageMs=1450" in text
