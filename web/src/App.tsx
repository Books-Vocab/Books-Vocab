import { PhoneFrame } from './harness/PhoneFrame'
import { resolveHarnessConfig } from './harness/scenarios'

export function App() {
  const search = window.location.search
  const config = resolveHarnessConfig(search)
  // ?shell=1 opt-in：把 surface 裝進 app 殼層（底部 tab bar）。預設不啟用，
  // 既有 ?surface=&scenario=&appearance= 行為與 parity capture 完全不變。
  const shell = new URLSearchParams(search).get('shell') === '1'
  return <PhoneFrame config={config} shell={shell} />
}
