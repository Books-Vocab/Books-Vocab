/**
 * 殼層 404 — 當 /app URL 不合法或 nav-graph 不可達時渲染（取代靜默落回預設）。
 * 全幅置中卡片 + 回書庫動作（goHome）。raw zh-Hant 字串（web 不在 iOS i18n lint 範圍）。
 */
export function NotFoundScreen({ onHome }: { onHome: () => void }) {
  return (
    <div className="shell-notfound" role="alert">
      <p className="shell-notfound-code">404</p>
      <p className="shell-notfound-title">找不到這個頁面</p>
      <p className="shell-notfound-note">這個連結可能已失效，或網址有誤。</p>
      <button type="button" className="kg-btn kg-btn--primary shell-notfound-home" onClick={onHome}>
        回書庫
      </button>
    </div>
  )
}
