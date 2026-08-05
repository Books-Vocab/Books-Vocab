#!/usr/bin/env -S uv run --with pyjwt --with cryptography python
"""asc_shipped.py — 印出 App Store 目前上架中的 (marketing version, build number)。

`ops/release.sh shipped ios` 用它把「哪顆 build 上架了」這個事實從 ASC 取回來。
輸出契約（呼叫端只認這個）：stdout 一行 `<marketing-version> <build-number>`。
查不到 / 不唯一 / HTTP 失敗一律非零 exit + stderr 訊息，**不印可能被誤讀的部分結果**。

為什麼要有這支：Apple 只保留**一筆** appStoreVersions 記錄，`versionString` 是可變欄位
（同一筆被 1.4→1.5→1.6→2.0.0→2.0.1→2.0.0 反覆改寫），且 build number 每個 marketing
version 重新計數（builds 清單裡 build 1 出現六次）。所以：
  * 上架中的版本只能「現在去問」，不能從 repo 推，也不該快取成 repo 內的事實；
  * build number 單獨沒有意義，必須 (version, build) 成對才唯一。

env：ASC_APP_ID（預設 6759816274）；金鑰設定沿用 asc_get.py 的 ASC_KEY_ID /
ASC_ISSUER_ID / ASC_KEY_DIR，與 asc.sh 的 config 單一真相對齊。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asc_get import get, mint_token  # noqa: E402

APP_ID = os.environ.get("ASC_APP_ID", "6759816274")


def die(msg):
    sys.exit(f"✗ {msg}")


def main():
    try:
        token = mint_token()
    except OSError as exc:
        die(f"讀不到 ASC 私鑰：{exc}（見 ASC_KEY_DIR / ASC_KEY_ID）")

    versions = get(f"/v1/apps/{APP_ID}/appStoreVersions?limit=200", token)
    if "_httpError" in versions:
        die(f"查 appStoreVersions 失敗：{versions['_httpError']} {versions.get('_detail')}")

    ready = [
        v for v in versions.get("data", [])
        if (v.get("attributes") or {}).get("appStoreState") == "READY_FOR_SALE"
    ]
    if not ready:
        states = sorted({
            (v.get("attributes") or {}).get("appStoreState", "?")
            for v in versions.get("data", [])
        })
        die(f"沒有 READY_FOR_SALE 的版本（目前 state：{', '.join(states) or '無記錄'}）")
    if len(ready) > 1:
        # Apple 的模型下不該發生；真發生了代表我們對這個 API 的理解是錯的，
        # 猜一個回去會讓錯誤以「一顆權威 tag」的形式固化下來。
        die(f"有 {len(ready)} 筆 READY_FOR_SALE 版本，無法判定唯一上架版本——請人工確認")

    version = (ready[0].get("attributes") or {}).get("versionString") or ""
    version_id = ready[0].get("id") or ""
    if not version or not version_id:
        die("READY_FOR_SALE 記錄缺 versionString 或 id")

    build = get(f"/v1/appStoreVersions/{version_id}/build", token)
    if "_httpError" in build:
        die(f"查該版本綁定的 build 失敗：{build['_httpError']} {build.get('_detail')}")
    data = build.get("data")
    if not data:
        die(f"版本 {version} 沒有綁定 build（尚未選 build 送審？）")
    number = (data.get("attributes") or {}).get("version") or ""
    if not number:
        die(f"版本 {version} 綁定的 build 沒有 version 欄位（= build number）")

    print(f"{version} {number}")


if __name__ == "__main__":
    main()
