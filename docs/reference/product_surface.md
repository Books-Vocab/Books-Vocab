<!-- doc-meta
tier: reference
authority: SoT
update_trigger: product-surface-changed
scope:
  - ios/BooksAndVocab/
  - backend/src/kg/
  - backend/static/
  - lab/podcast/
  - ops/ios_ops.sh
verified_against: 51ce9228ce64c1897850b8fcab672364b17f8731
-->
# Implemented Product Surface

這是產品能力索引，用來避免重複實作。一次變更的 Issue、優先序、驗收與 review 留在 GitHub；本文件只列穩定的產品邊界與程式入口。

## iOS (`ios/BooksAndVocab`)

- Auth：Apple／Google 登入、session、帳號刪除與多帳戶隔離。
- Bookshelf／Reader：EPUB、TXT、MD、PDF 匯入；Readium reader；進度、loading/error/retry/empty 狀態；Mac Catalyst workspace 與快捷鍵。
- Vocabulary：選詞、翻譯／解釋、單字本、卡片、同步、封存／刪除、CSV export。
- Knowledge graph：連結建立、隱藏／解除隱藏、optimistic sync 與 graph view。
- Today review：review event、SRS、複習卡版面、統計、月曆與跨裝置進度。
- Podcast：series／episode、音訊、字幕、逐字 highlight、下載、播放進度與單字本綁定；Release feature flag 以 code 為準。
- Explore：官方 shared decks 目錄、預覽、複製到私人單字本。
- Shared UI：design tokens、toast、state matrix、i18n、accessibility selectors、Sentry wiring。

主要驗證入口：`./ops/ios_ops.sh build`、`./ops/ios_ops.sh test`、`./ops/ios_ops.sh quality`。

## Backend (`backend/src/kg`)

- Auth／user：Apple／Google、profile、config、subscription、account lifecycle。
- Vocabulary／graph：詞條 CRUD、content enrichment、review events、cursor／incremental sync、graph links。
- Decks／catalog：官方 shared decks、preview、clone、idempotency 與 guest read path。
- Review／podcast：複習資料、podcast catalog、series／episode metadata、S3 upload／reconcile。
- Admin／observability：health、Sentry wiring、cost／quota、資料查詢與安全操作入口。

主要驗證入口：在 `backend/` 執行 `uv run --locked python -m pytest`；資料與 admin 操作一律走已定義的 CLI／安全 wrapper。

## Operations and delivery

- `.github/workflows/`：CI、design-system、docs／ops／backend／iOS checks。
- `ops/worktree_registry.py`、`ops/worktree_orchestrate.py`：只處理本機 worktree ownership、Scope 與 evidence。
- `ops/docs_lint.sh`、`ops/docs_impact.py`：文件 registry、impact、metadata 與 generated check。
- `ops/ios_ops.sh`、`ops/ios_release.sh`：iOS build、test、archive、TestFlight readiness。
- `ops/release.sh`、`ops/devops_kg_safe.sh`、`ops/kg_reconcile.sh`：版本、production safety、health gate 與 rollback。

## Source of truth

產品行為以 code／tests 為準；API、同步、card schema、host、UI、部署與安全邊界以 `docs/registry.yml` 指向的對應文件為準。若本索引與程式碼不一致，先修正索引或開 GitHub Issue，不複製出第三套實作。
