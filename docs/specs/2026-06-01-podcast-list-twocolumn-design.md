<!-- doc-meta
tier: archive
authority: derived
update_trigger: plan-execution
scope:
  - ios/BooksAndVocab/Views/Podcast/
verified_against: frozen
-->

# Podcast 集數列表：對齊單字列表組件 + 電腦版左右雙欄

> ⚠️ **已撤回（frozen）：** 本規格的「電腦版左右雙欄 master-detail」已於後續重構收斂回**單欄 push**。權威現況見 `ios/BooksAndVocab/Views/Podcast/PodcastDetailRouter.swift` 檔頭。此檔僅存歷史。（對齊 `WordRow` 的 `ListSectionCard` 組件部分仍存活。）

## 問題

1. **視覺不一致**：podcast `PodcastEpisodeRow` 與單字本 `WordRow` 各寫一套，雖結構相近但 token/容器分歧；使用者要求「幾乎一樣的組件」。
2. **電腦版浪費橫向空間**：Mac Catalyst 上集數列表單欄、點集數 `NavigationLink` push 全螢幕 player，無法邊瀏覽列表邊播放。單字本已有左列表 + 右 inline detail 的雙欄體驗，podcast 沒有。

## 目標

- iPhone/iPad compact：行為不變（點集數 push 全螢幕 `PodcastPlayerView`）。
- Mac/iPad regular：左欄集數列表常駐，右欄 inline 掛**完整** `PodcastPlayerView`（now-playing 模型）；點不同集數即時 swap，不撕裂音訊。
- 集數 row 與單字 row 共用同一套視覺契約（design token + list-card 容器）。

## 關鍵發現（決定可行性）

`PodcastPlayerView` 已用 `.task(id: episodeId)` 支援「**同一 view 實例內切換集數**」（存舊進度 → stop 舊 VM → loadEpisode 新 VM，音訊 session 不重啟）。
→ 右欄只需掛**單一** `PodcastPlayerView(episodeId: router.selectedEpisodeRemoteId)`，改 selected id 即觸發既有 swap 路徑。**不需要**全域 audio singleton / mini-player 重構（YAGNI）。

## 設計決策

| # | 決策 | 理由 |
|---|------|------|
| D1 | 右欄 = 完整 `PodcastPlayerView`（使用者選定） | now-playing 模型，桌面播客體驗最大化 |
| D2 | 新 `PodcastDetailRouter`（@Observable，`selectedEpisodeRemoteId: String?` + `var hasDetail: Bool { selectedEpisodeRemoteId != nil }`），鏡射 `DetailRouter` | 隔離播放狀態與導航；`hasDetail` 供 D4 guard 空欄（鏡射 vocab L36） |
| D3 | 複用 `DraggableDivider` / `MacDetailPanelMetrics` / `MacColumnResizeCursor`（已泛型） | 不重造拖拉欄 |
| D4 | 新 `PodcastDetailPresentation` modifier（rebuild 自 `NotebookDetailPresentation`，去掉 review/edit 分支）。inline 分支 `if router.hasDetail` 才掛 panel；**空選態（無集數選定）右欄不顯示**，左列表佔滿 | 與 vocab 同構但不耦合 `VocabularyEntry`；`PodcastPlayerView.episodeId` 為非選擇性 `String`，必須由 `hasDetail` guard 才能安全解包 selected id |
| D5 | `PodcastPlayerView` 加 `wrapInNavigation: Bool = true`（net-new，非既有 mirror）。inline 模式：自帶 `NavigationStack` host 住設定 `ToolbarItem(.topBarTrailing)`（`.topBarTrailing` 需 ambient nav bar，否則設定鍵靜默消失）；Catalyst/inline 跳過 `.toolbar(.hidden, for: .tabBar)` | 範圍化 toolbar，避免設定鍵漏到父 nav bar 或消失 |
| D6 | row 復用：對齊視覺契約 + 抽共用 list-card 容器，**不**強做泛型 row | 兩域資料形狀不同，泛型 row 會變漏抽象；真正重複的是 token 與卡片容器（YAGNI / 長期最佳平衡） |
| D7 | 抽 `ListSectionCard`（LazyVStack + Divider + card bg）；podcast 立即採用，vocab 遷移列為**獨立 task**、review gate | 限制 blast radius，避免動到已穩定的 500-row 單字列表 |

## 行為界定（明確化，避免被當 bug）

- **空選態**：regular 下尚未選任何集數時，右欄不顯示，左列表佔滿（`router.hasDetail == false`）。
- **inline player teardown 即停音訊**：右欄因列表 nav-pop / 縮回 compact / `dismiss()` 而拆除時，`PodcastPlayerView.onDisappear → viewModel.shutdown()` 觸發、**音訊停止**。本案接受此行為（非背景播放）；這正是方案 B 才能解的「邊離開邊播」取捨，本案不做。

## 非目標

- 背景播放 / 鎖屏持續播放（現況不支援，不在本案）。
- mini-player 全域常駐。
- compact（iPhone）改雙欄。
- 強制 `WordRow`/`PodcastEpisodeRow` 合一泛型。

## 方案比較（右欄 player 狀態管理）

| 方案 | 做法 | 取捨 | 採用 |
|------|------|------|------|
| A 單一 inline player 實例 + id swap | 右欄掛一個 `PodcastPlayerView`，`.task(id:)` 自動換集 | 零新狀態、複用既有 swap、無音訊撕裂 | ✅ |
| B 全域 audio singleton + mini-player | 抽 `PodcastPlaybackCoordinator` 持有 AVPlayer | 支援邊離開邊播，但工作量大、動到音訊核心、本案不需要 | ❌ YAGNI |
| C 右欄每選一集重建 player view | selected id 當 `.id()` | 每次換集整個 view 重建 → 音訊 ducking / 閃爍 | ❌ 體驗差 |

## 影響檔案

- 新增：`PodcastDetailRouter.swift`、`PodcastDetailPresentation.swift`、`ListSectionCard.swift`
- 修改：`PodcastEpisodeListView.swift`（注入 router、regular 改 set selected 而非 push、套 presentation modifier、列表改 `ListSectionCard`）、`PodcastEpisodeRow.swift`（對齊 token）、`PodcastPlayerView.swift`（加 presentation 參數 + Catalyst toolbar 分支）
- 復用：`DraggableDivider` / `MacDetailPanelMetrics` / `LayoutMode` / `AppMotion` / `AppSpacing`

## 風險

| 風險 | 緩解 |
|------|------|
| inline player toolbar 設定鍵漏到父 nav bar | D5 `wrapInNavigation` 自帶 NavigationStack 範圍化 |
| `.toolbar(.hidden, for: .tabBar)` 在 inline 造成 layout 異常 | Catalyst/inline 分支跳過 |
| 切 compact 時殘留 selection | `onChange(layoutMode)` 非 inline 即 `router.dismiss()`（鏡射 vocab L101-106） |
| 動到 `PodcastPlayerView` 觸發先前 Catalyst popover crash 回歸 | catalyst_lint --strict gate；player 設定已是 .sheet |
| vocab list 遷移 `ListSectionCard` 回歸 | 切為獨立 task + opus review gate（D7） |

## 驗證

- `ops/ios_build.sh` exit 0；`ops/i18n_lint.sh` 0；`ops/catalyst_lint.sh --strict` 0。
- Catalyst：點集數 → 右欄載入 player → 點另一集 → 即時換集不撕裂 → 拖拉分隔線 → player 設定彈 sheet 不崩。
- iPhone：點集數仍 push 全螢幕，行為不變。
- 視窗縮到 compact → 右欄收起、無殘留 selection。
- 逐項 review（鐵律4）：每 task opus code-review PASS 才下一個。
