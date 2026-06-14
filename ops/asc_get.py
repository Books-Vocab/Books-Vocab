#!/usr/bin/env -S uv run --with pyjwt --with cryptography python
"""asc_get.py — App Store Connect 公開 REST 的唯讀 GET helper。

codemagic CLI 暴露不到的物件（審查聯絡 / 截圖 / app-info 副標 / 分類 / build 加密宣告）
須直接打 raw API。本 helper 只負責「鑄 ES256 JWT → GET → 印 JSON」，唯讀、不寫。
asc.sh 的 review-detail / screenshots 子命令 shell-out 到這裡，金鑰設定由 env 傳入
（與 asc.sh config 單一真相對齊，不在兩處寫死）。

用法：  ASC_KEY_ID=... ASC_ISSUER_ID=... ASC_KEY_DIR=... asc_get.py /v1/<path>
env（皆有預設，對齊 asc.sh）：
  ASC_KEY_ID    預設 TCXVHFRXMS（App Manager）
  ASC_ISSUER_ID 預設 d7f86188-7c56-46f7-bc99-f889421025fa
  ASC_KEY_DIR   預設 ~/.secrets/apple（內含 AuthKey_<KEY_ID>.p8）
HTTP 4xx/5xx 不裸 crash：印 {"_httpError": <code>, "_detail": ...} 供呼叫端判讀。
"""
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import jwt  # pyjwt（+cryptography 提供 ES256）

KEY_ID = os.environ.get("ASC_KEY_ID", "TCXVHFRXMS")
ISSUER = os.environ.get("ASC_ISSUER_ID", "d7f86188-7c56-46f7-bc99-f889421025fa")
KEY_DIR = os.path.expanduser(os.environ.get("ASC_KEY_DIR", "~/.secrets/apple"))
LOGGER = logging.getLogger("ops.asc_get")


def mint_token():
    p8_path = os.path.join(KEY_DIR, f"AuthKey_{KEY_ID}.p8")
    with open(p8_path) as f:
        p8 = f.read()
    now = int(time.time())
    return jwt.encode(
        {"iss": ISSUER, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"},
        p8, algorithm="ES256", headers={"kid": KEY_ID, "typ": "JWT"},
    )


def get(path, token):
    req = urllib.request.Request(
        "https://api.appstoreconnect.apple.com" + path,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:  # 4xx/5xx：含 Apple 的 errors[] 細節
        body = e.read().decode("utf-8", "replace")
        LOGGER.warning("ASC GET failed with HTTP %s for %s", e.code, path)
        try:
            detail = json.loads(body)
        except Exception as exc:
            LOGGER.warning("ASC GET non-JSON error body for %s: %s", path, exc)
            detail = {"raw": body[:500]}
        return {"_httpError": e.code, "_detail": detail}
    except urllib.error.URLError as e:  # 斷網 / DNS / TLS / 連線被拒：HTTPError 之外的 URLError
        LOGGER.warning("ASC GET network error for %s: %s", path, e)
        return {"_httpError": "network", "_detail": {"reason": str(e.reason)}}


def main():
    if len(sys.argv) < 2:
        sys.exit("用法：asc_get.py /v1/<path>")
    out = get(sys.argv[1], mint_token())
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
