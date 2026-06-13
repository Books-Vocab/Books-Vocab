import { lazy, Suspense } from 'react'
import { ApiProvider } from './api/ApiContext'
import { LoginGate, useAuth } from './auth'
import { resolveShellAccess } from './auth/devSession'
import { PhoneFrame } from './harness/PhoneFrame'
import { resolveHarnessConfig } from './harness/scenarios'
import { ResponsiveShell } from './shell/ResponsiveShell'
import { QueryProvider } from './data'
import { isAppPath } from './shell/route'

// Reader 引擎 spike（探索性）：?surface=reader-live 走獨立 lazy 路徑，epub.js 不進
// parity bundle，既有 ?surface=reader 等 capture 路徑與 DOM 完全不變。
const ReaderLiveScreen = lazy(() =>
  import('./surfaces/reader-live/ReaderLiveScreen').then((m) => ({ default: m.ReaderLiveScreen })),
)

// Import-flow surface（功能型）：?surface=import-flow 走獨立 lazy 路徑，與 reader-live
// 同理把 epub.js（解析封面 / OPF metadata）擋在 parity bundle 之外。此 surface 必用
// useApi（library.create）→ 恆包 ApiProvider；可獨立到達、不依賴 shell/bookshelf，
// 故未進 PhoneFrame 的 parity 路由表（不接 ?scenario/?appearance capture 軸）。
const ImportFlowScreen = lazy(() =>
  import('./surfaces/import-flow/ImportFlowScreen').then((m) => ({ default: m.ImportFlowScreen })),
)

export function App() {
  const { isLoggedIn, isLoading } = useAuth()
  const search = window.location.search

  if (new URLSearchParams(search).get('surface') === 'reader-live') {
    const readerShell = new URLSearchParams(search).get('shell') === '1'
    const readerFrame = (
      <div className="phone-frame" data-surface="reader-live" data-harness="phone-frame">
        <Suspense fallback={null}>
          <ReaderLiveScreen />
        </Suspense>
      </div>
    )
    // shell=1 時 ReaderLive 需 useApi 同步閱讀位置 → 包 ApiProvider；
    // 無 shell（純 spike / parity 觀察）維持原樣，不掛 provider、零 API 呼叫。
    return readerShell ? <ApiProvider>{readerFrame}</ApiProvider> : readerFrame
  }

  // Import-flow surface — 獨立、自足、可直接到達（不依賴 shell/bookshelf）。恆包
  // ApiProvider（confirm-import 走 library.create）。OUT OF SCOPE（reconverge 補）：
  // 從 bookshelf 開啟匯入的入口按鈕（觸及 shell/bookshelf，由並行 run 持有）。
  if (new URLSearchParams(search).get('surface') === 'import-flow') {
    return (
      <ApiProvider>
        <div className="phone-frame" data-surface="import-flow" data-harness="phone-frame">
          <Suspense fallback={null}>
            <ImportFlowScreen />
          </Suspense>
        </div>
      </ApiProvider>
    )
  }

  const config = resolveHarnessConfig(search)
  const params = new URLSearchParams(search)
  // D0（parity teardown 第一刀）：**功能型 app shell 是 DEFAULT**，parity capture 改為
  // opt-in。對拍 pipeline 一律帶 ?surface=（capture 定址），故「?surface= 存在且非
  // explicit-app」= parity 模式；其餘（裸 /、/app/* pathname、?shell=1）一律進 app。
  //   explicit app 訊號：?shell=1 或 /app/* pathname（含 legacy ?shell=1&surface=X，
  //   仍視為 app deep-link，由 useShellHistory normalize 到 /app）。
  //   reader-live / import-flow 兩個 functional lazy surface 已在上方早退，不受影響。
  const explicitApp = params.get('shell') === '1' || isAppPath(window.location.pathname)
  const parityCapture = !explicitApp && params.get('surface') !== null
  const shell = !parityCapture
  // ?crop=component：元件級 parity case 把 surface 切到「純元件」呈現（收掉 in-app
  // safe-area / 全幅留白）。僅在 parity capture 路徑有意義。
  const crop = params.get('crop') === 'component'

  // ?login=1 opt-in：明確要求登入閘門（LoginGate）。預設走 guest 進場（鏡像 iOS
  // guest tier），故 LoginGate 仍可達且 devLogin 入口仍渲染。
  const wantLoginGate = params.get('login') === '1'

  // hydration spinner — 與原行為一致，套用所有路徑（含 parity，timing 上 isLoading
  // 於首次 effect 同步翻 false，故 capture 不受影響）。
  if (isLoading) {
    return (
      <div className="phone-frame" data-harness="phone-frame" data-auth-hydrating="1">
        <div className="login-sheet-overlay" style={{ position: 'absolute', inset: 0 }}>
          <div className="login-sheet-spinner" />
        </div>
      </div>
    )
  }

  // 功能型 app（shell=1）的 auth 進場；parity harness（無 shell）完全不經過此分支，
  // 維持原樣 frame，DOM 與 capture 行為逐位元不變。
  if (shell) {
    const access = resolveShellAccess({ isLoading, isLoggedIn })
    // 未登入：預設以 guest 進場（podcast 瀏覽可用、寫入面由下游 surface 提示登入）；
    // 僅 ?login=1 時改顯 LoginGate（含 dev/demo 入口），devLogin 由此進場。
    if (access === 'guest' && wantLoginGate) {
      return <LoginGate />
    }
  }

  // shell===true → functional web app: mount the ResponsiveShell (it owns the
  // mobile-breakpoint delegation back to AppShell/PhoneFrame incl. hotzone
  // overlay, so no parity-path code changes). shell===false (parity capture)
  // stays byte-identical: render the bare PhoneFrame surface, no ApiProvider.
  if (shell) {
    return (
      <ApiProvider>
        <QueryProvider>
          <ResponsiveShell config={config} />
        </QueryProvider>
      </ApiProvider>
    )
  }
  return <PhoneFrame config={config} shell={false} crop={crop} />
}
