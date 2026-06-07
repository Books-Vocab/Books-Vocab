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
warning: StoreKit Configuration file for scheme "BooksBrowser" can't be found at path "/tmp/missing.storekit"
/repo/ios/BooksBrowser/Views/VocabHighlightPreferences.swift:47:12: warning: Switch covers known cases, but 'ColorScheme' may have additional unknown values; this is an error in the Swift 6 language mode
/repo/ios/BooksBrowser/Views/PodcastSelectableSentenceTextView.swift:10:8: warning: umbrella header for module 'GoogleSignIn' does not include header 'GIDAppCheckError'
/repo/ios/BooksBrowser/Views/Reader/Foo.swift:12:3: error: cannot find 'missingSymbol' in scope
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
