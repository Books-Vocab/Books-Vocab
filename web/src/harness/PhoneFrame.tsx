import type { HarnessConfig } from './scenarios'

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
      <TokenProbe config={config} />
    </div>
  )
}

/** Placeholder surface proving the token + font pipeline end to end.
 *  Replaced by the Bookshelf surface in the next slice. */
function TokenProbe({ config }: { config: HarnessConfig }) {
  return (
    <div className="token-probe">
      <h1 className="token-probe-title">書架</h1>
      <p className="token-probe-body">
        scenario: {config.scenario} / appearance: {config.appearance}
      </p>
    </div>
  )
}
