import type { HarnessConfig } from './scenarios'
import { BookshelfScreen } from '../surfaces/bookshelf/BookshelfScreen'

/**
 * 393×852pt stage — iPhone 15 Pro portrait, the same logical size the iOS
 * Catalog renders surfaces at. Playwright captures this element at
 * deviceScaleFactor 3 → 1179×2556, pixel-aligned with Catalog snapshot PNGs.
 *
 * Surface routing lives here: each rewritten surface mounts inside the frame
 * keyed by the harness config (the pilot ships Bookshelf first).
 */
export function PhoneFrame({ config }: { config: HarnessConfig }) {
  return (
    <div
      className="phone-frame"
      data-theme={config.appearance}
      data-scenario={config.scenario}
      data-harness="phone-frame"
    >
      <BookshelfScreen scenario={config.scenario} />
    </div>
  )
}
