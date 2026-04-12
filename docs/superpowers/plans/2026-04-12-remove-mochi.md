# Remove Mochi Integration — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。
> **每個 Task 完成後立即 dispatch code reviewer 確認無殘留引用。**

**Goal:** 完全移除 Mochi 整合 — 刪除所有 Mochi 相關程式碼、模型、UI、測試、文件。
**Architecture:** 按模組邊界分 task，避免跨模組衝突。先移 backend core → backend admin/tests → iOS → docs。
**Tech Stack:** Python/FastAPI、SwiftUI、SwiftData

---

### Task 1: Backend — 刪除 Mochi core modules

**Files:**
- Delete: `backend/src/kg/mochi.py`
- Delete: `backend/src/kg/mochi_client.py`
- Delete: `backend/src/kg/mochi_sync.py`
- Delete: `backend/src/kg/renderer.py`
- Delete: `backend/src/kg/parser.py`
- Delete: `backend/mochi_theme.css`
- Modify: `backend/src/kg/pipeline_service.py` — 移除 Mochi sync step
- Modify: `backend/src/kg/api_models.py` — 移除 4 個 Mochi models
- Modify: `backend/src/kg/user_store.py` — 移除 Mochi key 遷移 + resolve
- Modify: `backend/src/kg/user_handlers.py` — 移除 Mochi key merge
- Modify: `backend/src/kg/exceptions.py` — 移除 docstring 中的 Mochi 提及

- [ ] **Step 1: 刪除 5 個 core modules + CSS**
```bash
rm backend/src/kg/mochi.py backend/src/kg/mochi_client.py backend/src/kg/mochi_sync.py backend/src/kg/renderer.py backend/src/kg/parser.py backend/mochi_theme.css
```

- [ ] **Step 2: 清理 pipeline_service.py**
讀檔，找到 Mochi sync step（約 line 351-375），移除整段：resolve key → MochiClient → MochiSync → sync → close。移除頂部 mochi 相關 import。

- [ ] **Step 3: 清理 api_models.py**
移除 `MochiIntegrationConfig`、`MochiIntegrationResponseConfig`、`IntegrationsConfig`、`IntegrationsResponseConfig` 四個 class。若 `IntegrationsConfig` 被其他地方引用（如 `UserConfigRequest`），需同步清理引用。

- [ ] **Step 4: 清理 user_store.py**
移除 `normalize_users_payload` 中所有 Mochi key 遷移邏輯（3 個 legacy path）。刪除 `resolve_mochi_api_key_from_config` 函數。移除 import。

- [ ] **Step 5: 清理 user_handlers.py**
移除 Mochi key merge 邏輯（讀取、回傳 `MochiIntegrationResponseConfig`、寫入）。移除 import。

- [ ] **Step 6: 清理 exceptions.py docstring**

- [ ] **Step 7: 跑 backend tests 確認不 import 已刪模組**
```bash
cd backend && uv run python -m pytest tests/ -x --timeout=30 2>&1 | tail -30
```
預期：部分 test 會 fail（因為 test 檔案引用了已刪模組），這些在 Task 2 處理。

- [ ] **Step 8: Commit**
`api: remove Mochi core modules and pipeline integration`

---

### Task 2: Backend — 清理 tests + admin + scripts

**Files:**
- Delete: `backend/tests/test_mochi_sync_lock.py`
- Delete: `backend/tests/test_parser.py`
- Delete: `backend/tests/test_data_safety_fixes.py`
- Delete: `backend/scripts/reset_system.py`
- Delete: `backend/scripts/migrate_to_apple.py`
- Modify: `backend/tests/test_robustness.py` — 移除 Mochi 相關 test classes/methods
- Modify: `backend/tests/test_user_handlers.py` — 移除 Mochi key merge tests
- Modify: `backend/tests/test_user_store.py` — 移除 Mochi normalize/resolve tests
- Modify: `backend/tests/test_secret_store.py` — 移除 Mochi encryption tests
- Modify: `backend/tests/test_api_surface.py` — 移除 Mochi API tests
- Modify: `backend/tests/test_pipeline_integration.py` — 移除 Mochi 提及
- Modify: `backend/tests/conftest.py` — 移除 Mochi fixture data
- Modify: `backend/src/kg/admin_handlers.py` — 移除 `has_mochi`
- Modify: `backend/src/kg/admin_dashboard.html` — 移除 Mochi 欄
- Modify: `backend/src/kg/admin_user_detail.html` — 移除 Mochi 狀態行
- Modify: `backend/src/kg/admin_test_matrix.py` — 移除 Mochi test group

- [ ] **Step 1: 刪除純 Mochi test 檔案 + scripts**
```bash
rm backend/tests/test_mochi_sync_lock.py backend/tests/test_parser.py backend/tests/test_data_safety_fixes.py backend/scripts/reset_system.py backend/scripts/migrate_to_apple.py
```

- [ ] **Step 2: 逐一清理剩餘 test 檔案**
讀每個檔案，移除 Mochi 相關的 test class / method / import / fixture。保留非 Mochi 測試完整。

- [ ] **Step 3: 清理 admin 相關**
- `admin_handlers.py`：移除 `has_mochi` 計算 + import
- `admin_dashboard.html`：移除 Mochi CSS class、table header、table cell
- `admin_user_detail.html`：移除 Mochi 整合狀態行
- `admin_test_matrix.py`：移除 Mochi test group

- [ ] **Step 4: 跑 backend tests 確認全過**
```bash
cd backend && uv run python -m pytest tests/ -x --timeout=30 2>&1 | tail -30
```
預期：全部 PASS

- [ ] **Step 5: Commit**
`api: remove Mochi tests, admin UI, and legacy scripts`

---

### Task 3: iOS — 移除 Mochi UI + service 層

**Files:**
- Delete: `ios/BooksBrowser/Views/Settings/SettingsPresenter+Mochi.swift`
- Delete: `ios/BooksBrowser/Views/Settings/SettingsPresenter+Sheet.swift`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsPresenter.swift` — 移除 `optionalIntegrationApiKey` 參數 + `mochiRow` 呼叫
- Modify: `ios/BooksBrowser/Views/Settings/SettingsPresentation.swift` — 移除 `OptionalIntegrationSection` + action
- Modify: `ios/BooksBrowser/Views/Settings/SettingsCoordinator.swift` — 移除 Mochi key state + save 邏輯
- Modify: `ios/BooksBrowser/Views/Settings/SettingsView.swift` — 移除 binding + onChange + sheet
- Modify: `ios/BooksBrowser/Views/Settings/SettingsView+Bindings.swift` — 移除 `optionalIntegrationApiKeyBinding`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsView+State.swift` — 移除 `optionalIntegration`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsPresenter+Preview.swift` — 移除 Mochi 參數
- Modify: `ios/BooksBrowser/Services/KGService.swift` — 移除 Mochi config types
- Modify: `ios/BooksBrowser/Services/KGUserConfigClient.swift` — 移除 `updateOptionalIntegrationKey`
- Modify: 5 個 `Localizable.strings` — 移除 Mochi 字串

- [ ] **Step 1: 刪除純 Mochi View 檔案**
```bash
rm ios/BooksBrowser/Views/Settings/SettingsPresenter+Mochi.swift ios/BooksBrowser/Views/Settings/SettingsPresenter+Sheet.swift
```

- [ ] **Step 2: 清理 Settings 層**
逐一讀並修改：SettingsPresenter、SettingsPresentation、SettingsCoordinator、SettingsView、SettingsView+Bindings、SettingsView+State、SettingsPresenter+Preview。移除所有 `optionalIntegration` / `mochi` 相關程式碼。

- [ ] **Step 3: 清理 Service 層**
- `KGService.swift`：移除 `KGOptionalIntegrationProviderConfig`、`KGIntegrationsConfig`、`optionalIntegrationApiKey`、`hasMochiApiKey`、`KGUserConfig` 中的 `optionalIntegrationKey` 參數
- `KGUserConfigClient.swift`：移除 `updateOptionalIntegrationKey` method

- [ ] **Step 4: 清理 Localizable.strings（5 個語言）**
移除所有 Mochi 相關字串 key。

- [ ] **Step 5: Build**
```bash
./ops/ios_build.sh
```

- [ ] **Step 6: 跑 test**
```bash
./ops/ios_test.sh
```

- [ ] **Step 7: Commit**
`ios: remove Mochi integration UI and service layer`

---

### Task 4: Docs — 清理文件引用

**Files:**
- Modify: `backend/README.md` — 移除 Mochi 架構文件段落
- Modify: `CLAUDE.md` — 移除 Implemented Product Surface 中的 Mochi 提及
- Modify: `docs/dev/debug.md` — 移除 Mochi 相關 debug 指引
- Modify: `docs/references/feature_boundary_settings.md` — 移除 Mochi 行
- Modify: `docs/references/backend_testing_strategy.md` — 移除 Mochi 引用

不修改歷史 spec/plan 文件（archive 性質）。

- [ ] **Step 1: 逐一讀取並清理上述文件**
- [ ] **Step 2: Commit**
`docs: remove Mochi references from active documentation`
