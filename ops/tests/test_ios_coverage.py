import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "ios_coverage.py"


def run_coverage(fixture: dict, *args: str) -> subprocess.CompletedProcess[str]:
    fixture_path = ROOT / ".cache" / "test-ios-coverage-fixture.json"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    return subprocess.run(
        [
            "uv",
            "run",
            "--python",
            "3.13",
            "python",
            str(SCRIPT),
            "--xcresult",
            "/tmp/fake.xcresult",
            "--fixture-xccov-json",
            str(fixture_path),
            "--json",
            *args,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_ios_coverage_reports_app_target_line_rate() -> None:
    fixture = {
        "targets": [
            {
                "name": "BooksAndVocabTests",
                "lineCoverage": 0.25,
                "coveredLines": 5,
                "executableLines": 20,
            },
            {
                "name": "BooksAndVocab",
                "lineCoverage": 0.8125,
                "coveredLines": 65,
                "executableLines": 80,
            },
        ]
    }

    proc = run_coverage(
        fixture, "--target", "BooksAndVocab", "--fail-under-lines", "80"
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema"] == "kg.ios.coverage.v1"
    assert payload["verdict"] == "pass"
    assert payload["summary"]["target"] == "BooksAndVocab"
    assert payload["summary"]["lineCoverage"] == 81.25
    assert payload["summary"]["coveredLines"] == 65
    assert payload["summary"]["executableLines"] == 80
    assert payload["thresholds"]["lineCoverage"]["failUnder"] == 80.0


def test_ios_coverage_matches_xcode_app_target_suffix() -> None:
    fixture = {
        "targets": [
            {
                "name": "BooksAndVocab.app",
                "lineCoverage": 0.25313034308355431,
                "coveredLines": 24724,
                "executableLines": 97673,
            },
            {
                "name": "BooksAndVocabTests.xctest",
                "lineCoverage": 0.98635117900849323,
                "coveredLines": 36350,
                "executableLines": 36853,
            },
        ]
    }

    proc = run_coverage(fixture, "--target", "BooksAndVocab")

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "pass"
    assert payload["summary"]["target"] == "BooksAndVocab"
    assert payload["summary"]["lineCoverage"] == 25.31
    assert payload["summary"]["coveredLines"] == 24724
    assert payload["summary"]["executableLines"] == 97673


def test_ios_coverage_default_selects_suffixed_app_target() -> None:
    fixture = {
        "targets": [
            {
                "name": "BooksAndVocabTests.xctest",
                "lineCoverage": 0.98635117900849323,
                "coveredLines": 36350,
                "executableLines": 36853,
            },
            {
                "name": "BooksAndVocab.app",
                "lineCoverage": 0.25313034308355431,
                "coveredLines": 24724,
                "executableLines": 97673,
            },
        ]
    }

    proc = run_coverage(fixture)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["summary"]["target"] == "BooksAndVocab"
    assert payload["summary"]["lineCoverage"] == 25.31


def test_ios_coverage_fails_under_threshold_with_machine_readable_error() -> None:
    fixture = {
        "targets": [
            {
                "name": "BooksAndVocab",
                "lineCoverage": 0.799,
                "coveredLines": 799,
                "executableLines": 1000,
            }
        ]
    }

    proc = run_coverage(
        fixture, "--target", "BooksAndVocab", "--fail-under-lines", "80"
    )

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "fail"
    assert payload["summary"]["lineCoverage"] == 79.9
    assert payload["errors"][0]["key"] == "coverage-threshold"


def test_ios_coverage_keeps_tests_out_of_default_app_target_selection() -> None:
    fixture = {
        "targets": [
            {
                "name": "BooksAndVocabTests",
                "lineCoverage": 1.0,
                "coveredLines": 100,
                "executableLines": 100,
            },
            {
                "name": "BooksAndVocab",
                "lineCoverage": 0.5,
                "coveredLines": 50,
                "executableLines": 100,
            },
        ]
    }

    proc = run_coverage(fixture)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["summary"]["target"] == "BooksAndVocab"
    assert payload["summary"]["lineCoverage"] == 50.0


def test_ios_coverage_fails_closed_for_unknown_explicit_target() -> None:
    fixture = {
        "targets": [
            {
                "name": "BooksAndVocab",
                "lineCoverage": 0.5,
                "coveredLines": 50,
                "executableLines": 100,
            }
        ]
    }

    proc = run_coverage(fixture, "--target", "MissingTarget")

    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "error"
    assert payload["summary"]["target"] == "MissingTarget"
    assert payload["errors"][0]["key"] == "coverage-unavailable"


def test_ios_coverage_reports_lowest_covered_files_for_selected_target() -> None:
    fixture = {
        "targets": [
            {
                "name": "BooksAndVocab",
                "lineCoverage": 0.75,
                "coveredLines": 75,
                "executableLines": 100,
                "files": [
                    {
                        "name": "High.swift",
                        "path": "/repo/ios/BooksAndVocab/High.swift",
                        "lineCoverage": 0.9,
                        "coveredLines": 90,
                        "executableLines": 100,
                    },
                    {
                        "name": "Low.swift",
                        "path": "/repo/ios/BooksAndVocab/Low.swift",
                        "lineCoverage": 0.2,
                        "coveredLines": 2,
                        "executableLines": 10,
                    },
                    {
                        "name": "NoExecutableLines.swift",
                        "path": "/repo/ios/BooksAndVocab/NoExecutableLines.swift",
                        "lineCoverage": 0,
                        "coveredLines": 0,
                        "executableLines": 0,
                    },
                ],
            }
        ]
    }

    proc = run_coverage(fixture, "--max-low-files", "1")

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["summary"]["fileCount"] == 3
    assert payload["summary"]["lowestFiles"] == [
        {
            "name": "Low.swift",
            "path": "/repo/ios/BooksAndVocab/Low.swift",
            "lineCoverage": 20.0,
            "coveredLines": 2,
            "executableLines": 10,
        }
    ]
