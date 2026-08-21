from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "asc_shipped.py"


def load_module():
    spec = importlib.util.spec_from_file_location("asc_shipped", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_asc_get(monkeypatch, responses):
    calls = []

    def fake_get(path, token):
        calls.append((path, token))
        return responses.pop(0)

    monkeypatch.setenv("ASC_APP_ID", "test-app")
    monkeypatch.setitem(
        sys.modules,
        "asc_get",
        SimpleNamespace(get=fake_get, mint_token=lambda: "test-token"),
    )
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    return load_module(), calls


@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        ({"data": None}, "✗ 查 appStoreVersions 失敗：data 必須是 JSON 陣列"),
        ({"data": {}}, "✗ 查 appStoreVersions 失敗：data 必須是 JSON 陣列"),
        ({"data": [None]}, "✗ 查 appStoreVersions 失敗：data[0] 必須是 JSON 物件"),
        (
            {"data": ["not-an-object"]},
            "✗ 查 appStoreVersions 失敗：data[0] 必須是 JSON 物件",
        ),
    ],
)
def test_malformed_app_store_versions_data_fails_closed(
    monkeypatch, versions, expected
):
    module, calls = install_asc_get(monkeypatch, [versions])

    with pytest.raises(SystemExit) as error:
        module.main()

    assert error.value.code == expected
    assert calls == [
        (f"/v1/apps/{module.APP_ID}/appStoreVersions?limit=200", "test-token")
    ]


def test_ready_for_sale_version_and_build_remain_a_read_only_pair(monkeypatch, capsys):
    module, calls = install_asc_get(
        monkeypatch,
        [
            {
                "data": [
                    {
                        "id": "version-1",
                        "attributes": {
                            "appStoreState": "READY_FOR_SALE",
                            "versionString": "2.0.1",
                        },
                    }
                ]
            },
            {"data": {"attributes": {"version": "9"}}},
        ],
    )

    module.main()

    assert capsys.readouterr().out == "2.0.1 9\n"
    assert calls == [
        (f"/v1/apps/{module.APP_ID}/appStoreVersions?limit=200", "test-token"),
        ("/v1/appStoreVersions/version-1/build", "test-token"),
    ]
