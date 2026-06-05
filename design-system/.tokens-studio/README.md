# Tokens Studio sidecar（投影產物，唯讀）

本目錄是 `design-system/tokens.json` 的**單向投影**，供 Tokens Studio Figma plugin
匯入，讓設計師在 Figma 看見並切換 **light / dark / sepia** 三主題顏色。

## 規則

- **唯讀**。`tokens/` 下所有檔由 `ops/gen_figma_sets.py` 從 `tokens.json` 生成，**禁手改**。
- **SoT 是 `design-system/tokens.json`**（單檔，由 gen_web_tokens.py / token_drift_check.py /
  sd.config.mjs 三方以固定路徑消費）。**不是這裡** —— 本目錄不進任何生成鏈。
- 顏色**回流不經此目錄**：在 Figma 改色 → push 回 `tokens.json` → 過 `token_drift_check.py`
  + iOS `WCAGContrast` 測試 gate（顏色是 **iOS literal 為 SoT**，Figma 值是**提案**不是直接生效）。
  完整流程見 `docs/sop/figma-token-workflow.md` 的顏色專章。
- `tokens.json` 改了就重跑 `python ops/gen_figma_sets.py`；`--check` 已進
  `ops/verify_design_system.sh` 防 stale。

## 設計師怎麼用

在 Tokens Studio plugin 匯入 `tokens/` **整個資料夾**（含 `$themes.json` / `$metadata.json`）
即得三主題可切換 —— **不需 Tokens Studio Pro**（themes 預先寫在 sidecar，非在付費 plugin UI 建立）。
