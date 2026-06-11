import type { HarnessConfig } from './scenarios'
import { BookshelfScreen } from '../surfaces/bookshelf/BookshelfScreen'
import { SettingsScreen } from '../surfaces/settings/SettingsScreen'

/**
 * 393×852pt stage — iPhone 15 Pro portrait, the same logical size the iOS
 * Catalog renders surfaces at. Playwright captures this element at
 * deviceScaleFactor 3 → 1179×2556, pixel-aligned with Catalog snapshot PNGs.
 *
 * Surface routing lives here: each rewritten surface mounts inside the frame
 * keyed by the harness config（switch 的 exhaustiveness 由 HarnessConfig
 * discriminated union 保證——新 surface 不接路由就編不過）。
 */
function SurfaceView({ config }: { config: HarnessConfig }) {
  switch (config.surface) {
    case 'bookshelf':
      return <BookshelfScreen scenario={config.scenario} />
    case 'settings':
      return <SettingsScreen scenario={config.scenario} />
  }
}

export function PhoneFrame({ config }: { config: HarnessConfig }) {
  return (
    <div
      className="phone-frame"
      data-theme={config.appearance}
      data-surface={config.surface}
      data-scenario={config.scenario}
      data-harness="phone-frame"
    >
      <SurfaceView config={config} />
    </div>
  )
}
