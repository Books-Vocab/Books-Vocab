import { lazy, Suspense } from 'react'
import { PhoneFrame } from './harness/PhoneFrame'
import { resolveHarnessConfig } from './harness/scenarios'

// Reader 引擎 spike（探索性）：?surface=reader-live 走獨立 lazy 路徑，epub.js 不進
// parity bundle，既有 ?surface=reader 等 capture 路徑與 DOM 完全不變。
const ReaderLiveScreen = lazy(() =>
  import('./surfaces/reader-live/ReaderLiveScreen').then((m) => ({ default: m.ReaderLiveScreen })),
)

export function App() {
  const search = window.location.search
  if (new URLSearchParams(search).get('surface') === 'reader-live') {
    return (
      <div className="phone-frame" data-surface="reader-live" data-harness="phone-frame">
        <Suspense fallback={null}>
          <ReaderLiveScreen />
        </Suspense>
      </div>
    )
  }
  const config = resolveHarnessConfig(search)
  // ?shell=1 opt-in：把 surface 裝進 app 殼層（底部 tab bar）。預設不啟用，
  // 既有 ?surface=&scenario=&appearance= 行為與 parity capture 完全不變。
  const shell = new URLSearchParams(search).get('shell') === '1'
  return <PhoneFrame config={config} shell={shell} />
}
