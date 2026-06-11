import { PhoneFrame } from './harness/PhoneFrame'
import { resolveHarnessConfig } from './harness/scenarios'

export function App() {
  const config = resolveHarnessConfig(window.location.search)
  return <PhoneFrame config={config} />
}
