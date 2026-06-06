"""Tests for private corpus CLI entrypoints."""

from __future__ import annotations

import json

from llm_eval.corpus_cli import main


def test_build_private_corpus_cli_writes_outputs_and_summary(tmp_path, capsys):
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "content": "resplendent",
                        "meaning": "輝煌的",
                        "pos": "adj.",
                        "root_form": "resplendent",
                        "examples": ["The robe was **resplendent**."],
                        "review_count": 2,
                        "last_review_feedback": 1,
                    },
                    {
                        "content": "stamped out",
                        "meaning": "被徹底消滅",
                        "pos": "phr.",
                        "examples": ["The fire was **stamped out**."],
                        "review_count": 4,
                        "last_review_feedback": 0,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "private_corpus"

    exit_code = main([str(dump_path), "--output-dir", str(output_dir), "--limit", "10"])

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["output_dir"] == str(output_dir)
    assert summary["files"]["translate_quick"]["rows"] == 2
    assert summary["files"]["translate_phrase"]["rows"] == 1
    assert summary["files"]["translate_explain"]["rows"] == 2
    assert (output_dir / "translate_quick_candidates.jsonl").exists()
