#!/usr/bin/env -S uv run --with pyjwt --with cryptography python
"""asc_patch.py — App Store Connect 公開 REST 的 PATCH 寫入 helper（codemagic 未暴露的物件）。

asc_get.py 的「寫入」對應件：codemagic CLI 沒有 appStoreReviewDetail（送審備註 / demo 帳號 /
聯絡人）的修改指令，只能直接 PATCH raw API。本 helper 只負責「鑄 ES256 JWT → PATCH → 印 JSON」。
JSON body 由 stdin 餵入（asc.sh 用 jq 組好，含正確跳脫與 boolean），金鑰設定由 env 傳入
（與 asc.sh / asc_get.py 單一真相對齊，不在三處寫死）。

寫入 gate 由呼叫端（asc.sh）的 dry-run 預設 + --yes 把關；本 helper 一旦被呼叫即真送 PATCH。

用法：  ASC_KEY_ID=... ASC_ISSUER_ID=... ASC_KEY_DIR=... asc_patch.py /v1/<path>  < body.json
env（皆有預設，對齊 asc.sh）：
  ASC_KEY_ID    預設 TCXVHFRXMS（App Manager；只有可寫角色才改得動 metadata）
  ASC_ISSUER_ID 預設 d7f86188-7c56-46f7-bc99-f889421025fa
  ASC_KEY_DIR   預設 ~/.secrets/apple（內含 AuthKey_<KEY_ID>.p8）
HTTP 4xx/5xx 不裸 crash：印 {"_httpError": <code>, "_detail": ...} 供呼叫端判讀。
"""
import os, sys, time, json, urllib.request, urllib.error
import jwt  # pyjwt（+cryptography 提供 ES256）

KEY_ID = os.environ.get("ASC_KEY_ID", "TCXVHFRXMS")
ISSUER = os.environ.get("ASC_ISSUER_ID", "d7f86188-7c56-46f7-bc99-f889421025fa")
KEY_DIR = os.path.expanduser(os.environ.get("ASC_KEY_DIR", "~/.secrets/apple"))


def mint_token():
    p8_path = os.path.join(KEY_DIR, f"AuthKey_{KEY_ID}.p8")
    with open(p8_path) as f:
        p8 = f.read()
    now = int(time.time())
    return jwt.encode(
        {"iss": ISSUER, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"},
        p8, algorithm="ES256", headers={"kid": KEY_ID, "typ": "JWT"},
    )


def patch(path, token, body):
    req = urllib.request.Request(
        "https://api.appstoreconnect.apple.com" + path,
        data=body.encode("utf-8"),
        method="PATCH",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:  # 4xx/5xx：含 Apple 的 errors[] 細節
        raw = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw)
        except Exception:
            detail = {"raw": raw[:500]}
        return {"_httpError": e.code, "_detail": detail}
    except urllib.error.URLError as e:  # 斷網 / DNS / TLS / 連線被拒
        return {"_httpError": "network", "_detail": {"reason": str(e.reason)}}


def main():
    if len(sys.argv) < 2:
        sys.exit("用法：asc_patch.py /v1/<path>  < body.json")
    body = sys.stdin.read()
    if not body.strip():
        sys.exit("✗ asc_patch.py 需要從 stdin 提供 JSON body")
    out = patch(sys.argv[1], mint_token(), body)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
