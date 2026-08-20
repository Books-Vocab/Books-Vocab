<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ios/BooksAndVocab/Services/
  - ios/BooksAndVocab.xcodeproj/
  - ops/sentry_*.py
  - ops/lib/ios_ops_release.sh
-->
# iOS 可觀測性契約

這份文件定義 iOS runtime diagnostics 與 agent read-only tooling 的邊界；產品分析仍由 `AppAnalytics` 負責，Sentry 不承擔所有使用者行為事件。

## App-side seams

- `AppCrashReporting`：產品 call site 的 facade。
- `SentryReporter`：唯一接觸 `SentrySDK` 的 adapter；SDK 不可用時維持 no-op path。
- `SentryConfiguration`：DSN、environment、release、dist、debug enable 與 trace sample rate。
- `SentryPrivacyPolicy`：query stripping、opaque ID 驗證、breadcrumb/event allowlist 與 cancellation 排除。
- `AppDiagnosticContext`：最多 20 筆 redacted observations、request IDs 與最近 event ID 的本機 bounded buffer。

Sentry 只收 crash、exception、network/sync/auth failure、重要 breadcrumbs 與少量 traces。禁止 session replay、UI interaction tracing、原始 request/response body、使用者輸入、email、token、cookie、IP、書籍或卡片內容。

## Release identity

所有事件使用：

```text
release = bundleId@MARKETING_VERSION+CURRENT_PROJECT_VERSION
dist = CURRENT_PROJECT_VERSION
```

`request_id` 必須由該次 call site 明確傳入，不能依賴全域 mutable context 代替 async correlation。user context 只接受 opaque internal ID，`sendDefaultPii` 固定為 false。

## Readiness

`./ops/ios_ops.sh sentry --json` 的 `kg.ios.sentry.v1` 同時輸出靜態 wiring 與尚未驗證的 runtime readiness：

```text
source_present
package_present
target_linked
build_can_import
api_configured
api_authenticated
project_reachable
runtime_event_seen
symbolication_ready
```

缺 source、`sentry-cocoa` pin 或 app target link 直接列在 `issues[]`，並將 verdict 設為 `blocked`。只有實際 build、QA event、API readback 與 dSYM 檢查提供足夠 evidence 後，才可由 `partial` 變成 `ready`；source guard 不可單獨使 gate 變綠。

## Agent boundary

後續 `ops/sentry_tool.py` 是 read-only CLI facade，透過 `sentry_api.py` 呼叫 Sentry Web API，經 `sentry_contract.py` 做 normalization、redaction 與 routing。工具不得 resolve、assign、comment、create issue 或寫 GitHub；routing 只產生建議，交由 IM／協作控制面處理。

其穩定輸出 schema 為：

- `kg.sentry.health.v1`
- `kg.sentry.issue.v1`

任何缺少 API secret 的情況回報 `unchecked`，不把 token 或 Authorization header 寫入 stdout、stderr、artifact 或測試 fixture。
