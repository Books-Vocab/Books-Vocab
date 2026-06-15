#!/usr/bin/env -S uv run --with pyjwt --with cryptography python
"""asc_write.py — App Store Connect 公開 REST 的寫入 helper（codemagic 未暴露的物件）。

asc_get.py 的「寫入」對應件：codemagic CLI 沒有 appStoreReviewDetail / appInfoLocalization /
customerReviewResponses 等物件的修改指令，只能直接打 raw API。本 helper 只負責
「鑄 ES256 JWT → 依 method 送出 → 印 JSON」，支援 PATCH（改）/ POST（建）/ DELETE（刪）。
JSON body 由 stdin 餵入（asc.sh 用 jq 組好，含正確跳脫與 boolean）；DELETE 可無 body。
金鑰設定由 env 傳入（與 asc.sh / asc_get.py 單一真相對齊，不在三處寫死）。

寫入 gate 由呼叫端（asc.sh）的 dry-run 預設 + --yes 把關；本 helper 一旦被呼叫即真送。

用法：  ASC_KEY_ID=... ASC_ISSUER_ID=... ASC_KEY_DIR=... asc_write.py /v1/<path> [METHOD]  < body.json
        METHOD 預設 PATCH，可為 PATCH / POST / DELETE。
env（皆有預設，對齊 asc.sh）：
  ASC_KEY_ID    預設 TCXVHFRXMS（App Manager；只有可寫角色才改得動）
  ASC_ISSUER_ID 預設 d7f86188-7c56-46f7-bc99-f889421025fa
  ASC_KEY_DIR   預設 ~/.secrets/apple（內含 AuthKey_<KEY_ID>.p8）
HTTP 4xx/5xx 不裸 crash：印 {"_httpError": <code>, "_detail": ...} 供呼叫端判讀。
204 No Content（常見於 DELETE）回 {"_ok": <status>}。
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
ALLOWED = {"PATCH", "POST", "DELETE"}
LOGGER = logging.getLogger("ops.asc_write")


def mint_token():
    p8_path = os.path.join(KEY_DIR, f"AuthKey_{KEY_ID}.p8")
    with open(p8_path) as f:
        p8 = f.read()
    now = int(time.time())
    return jwt.encode(
        {"iss": ISSUER, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"},
        p8, algorithm="ES256", headers={"kid": KEY_ID, "typ": "JWT"},
    )


def write(path, token, body, method):
    data = body.encode("utf-8") if body else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        "https://api.appstoreconnect.apple.com" + path,
        data=data, method=method, headers=headers,
    )
    try:
        resp = urllib.request.urlopen(req)
        raw = resp.read().decode("utf-8", "replace")
        if not raw.strip():                  # 204 No Content（DELETE / 部分 POST）
            return {"_ok": resp.status}
        return json.loads(raw)
    except urllib.error.HTTPError as e:       # 4xx/5xx：含 Apple 的 errors[] 細節
        raw = e.read().decode("utf-8", "replace")
        LOGGER.warning("ASC %s failed with HTTP %s for %s", method, e.code, path)
        try:
            detail = json.loads(raw)
        except Exception as exc:
            LOGGER.warning("ASC %s non-JSON response for %s: %s", method, path, exc)
            detail = {"raw": raw[:500]}
        return {"_httpError": e.code, "_detail": detail}
    except urllib.error.URLError as e:        # 斷網 / DNS / TLS / 連線被拒
        LOGGER.warning("ASC %s network error for %s: %s", method, path, e)
        return {"_httpError": "network", "_detail": {"reason": str(e.reason)}}


def main():
    if len(sys.argv) < 2:
        sys.exit("用法：asc_write.py /v1/<path> [PATCH|POST|DELETE]  < body.json")
    path = sys.argv[1]
    method = (sys.argv[2] if len(sys.argv) > 2 else "PATCH").upper()
    if method not in ALLOWED:
        sys.exit(f"✗ 不支援的 method：{method}（只允許 PATCH/POST/DELETE）")
    body = sys.stdin.read()
    if method in ("PATCH", "POST") and not body.strip():
        sys.exit(f"✗ asc_write.py {method} 需要從 stdin 提供 JSON body")
    out = write(path, mint_token(), body, method)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
