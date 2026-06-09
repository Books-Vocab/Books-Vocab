"""Regression tests for ops/asc_text_bundle.py.

The script is an App Store Connect text review/apply helper. These tests keep
the risky part offline: deriving precise PATCH operations from edited JSON.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "asc_text_bundle.py"
PUBLIC_WEB_BASE_URL = "https://wordnexus.lol"
PRIVACY_POLICY_URL = PUBLIC_WEB_BASE_URL + "/privacy.html"


def _load_module():
    spec = importlib.util.spec_from_file_location("asc_text_bundle", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_compute_changes_limits_apply_to_editable_text_fields():
    mod = _load_module()
    current = {
        "appInfo": {
            "localizations": [
                {
                    "id": "appinfo-loc-1",
                    "locale": "zh-Hant",
                    "name": "Books & Vocab",
                    "subtitle": "便捷的生詞本閱讀器",
                    "privacyPolicyUrl": PRIVACY_POLICY_URL,
                    "privacyChoicesUrl": None,
                }
            ]
        },
        "eula": {"id": "eula-1", "agreementText": "old terms"},
        "appStoreVersion": {
            "id": "version-1",
            "copyright": "2026 BooksAndVocab",
            "localizations": [
                {
                    "id": "version-loc-1",
                    "locale": "zh-Hant",
                    "description": "old description",
                    "keywords": "old,keywords",
                    "marketingUrl": None,
                    "promotionalText": "old promo",
                    "supportUrl": PRIVACY_POLICY_URL,
                    "whatsNew": None,
                }
            ],
            "reviewDetail": {
                "id": "review-1",
                "contactFirstName": "Max",
                "contactLastName": "Chen",
                "contactPhone": "+886",
                "contactEmail": "max@example.com",
                "demoAccountName": "demo@example.com",
                "demoAccountPassword": "old-pass",
                "demoAccountRequired": True,
                "notes": "old notes",
            },
            "releaseType": "AFTER_APPROVAL",
        },
        "subscriptions": {
            "groups": [
                {
                    "id": "group-1",
                    "localizations": [
                        {
                            "id": "group-loc-1",
                            "locale": "zh-Hant",
                            "name": "Old group",
                            "customAppName": None,
                        }
                    ],
                    "subscriptions": [
                        {
                            "id": "sub-1",
                            "reviewNote": "old note",
                            "state": "WAITING_FOR_REVIEW",
                            "localizations": [
                                {
                                    "id": "sub-loc-1",
                                    "locale": "zh-Hant",
                                    "name": "Old sub",
                                    "description": "old desc",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }
    edited = {
        **current,
        "appInfo": {
            "localizations": [
                {
                    **current["appInfo"]["localizations"][0],
                    "subtitle": "閱讀器與生詞本",
                }
            ]
        },
        "eula": {"id": "eula-1", "agreementText": "new terms"},
        "appStoreVersion": {
            **current["appStoreVersion"],
            "copyright": "2026 Books & Vocab",
            "releaseType": "MANUAL",  # intentionally ignored by this text tool
            "localizations": [
                {
                    **current["appStoreVersion"]["localizations"][0],
                    "description": "new description",
                    "whatsNew": "new in this version",
                }
            ],
            "reviewDetail": {
                **current["appStoreVersion"]["reviewDetail"],
                "notes": "new notes",
                "demoAccountPassword": "new-pass",
            },
        },
        "subscriptions": {
            "groups": [
                {
                    **current["subscriptions"]["groups"][0],
                    "localizations": [
                        {
                            **current["subscriptions"]["groups"][0]["localizations"][0],
                            "name": "New group",
                        }
                    ],
                    "subscriptions": [
                        {
                            **current["subscriptions"]["groups"][0]["subscriptions"][0],
                            "reviewNote": "new note",
                            "localizations": [
                                {
                                    **current["subscriptions"]["groups"][0]["subscriptions"][0]["localizations"][0],
                                    "description": "new desc",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }

    changes = mod.compute_changes(current, edited)
    assert [(c.method, c.path, c.body["data"]["attributes"]) for c in changes] == [
        (
            "PATCH",
            "/v1/appInfoLocalizations/appinfo-loc-1",
            {"subtitle": "閱讀器與生詞本"},
        ),
        (
            "PATCH",
            "/v1/endUserLicenseAgreements/eula-1",
            {"agreementText": "new terms"},
        ),
        (
            "PATCH",
            "/v1/appStoreVersions/version-1",
            {"copyright": "2026 Books & Vocab"},
        ),
        (
            "PATCH",
            "/v1/appStoreVersionLocalizations/version-loc-1",
            {"description": "new description", "whatsNew": "new in this version"},
        ),
        (
            "PATCH",
            "/v1/appStoreReviewDetails/review-1",
            {"demoAccountPassword": "new-pass", "notes": "new notes"},
        ),
        (
            "PATCH",
            "/v1/subscriptionGroupLocalizations/group-loc-1",
            {"name": "New group"},
        ),
        (
            "PATCH",
            "/v1/subscriptions/sub-1",
            {"reviewNote": "new note"},
        ),
        (
            "PATCH",
            "/v1/subscriptionLocalizations/sub-loc-1",
            {"description": "new desc"},
        ),
    ]


def test_validate_changes_rejects_subscription_description_over_55_chars():
    mod = _load_module()
    change = mod.Change(
        method="PATCH",
        path="/v1/subscriptionLocalizations/sub-loc-1",
        type="subscriptionLocalizations",
        id="sub-loc-1",
        fields=("description",),
        body={
            "data": {
                "type": "subscriptionLocalizations",
                "id": "sub-loc-1",
                "attributes": {"description": "x" * 56},
            }
        },
    )

    errors = mod.validate_changes([change])
    assert errors == ["subscriptionLocalizations sub-loc-1 description is 56 chars; ASC max is 55"]
