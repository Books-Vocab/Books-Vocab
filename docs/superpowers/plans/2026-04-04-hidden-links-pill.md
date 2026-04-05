# Hidden Links Pill Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 隱藏連結改為底部 capsule pill 顯示
**Architecture:** CardPresentation 提供 hiddenLinks，WordDetailPresenter 渲染 pill 區
**Tech Stack:** SwiftUI, VocabSkin design tokens

### Task 1: CardPresentation 新增 hiddenLinks

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Presentation/CardPresentation.swift:108-110`

- [ ] **Step 1: 新增 hiddenLinks computed property**
在 `totalLinkCount` 上方加：
```swift
var hiddenLinks: [KGCardLinkSummary] {
    linkGroups.flatMap(\.items).filter(\.isHidden)
}
```

- [ ] **Step 2: Commit**

### Task 2: CollocationFlowLayout 改為 internal

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/CardDocumentView.swift:275`

- [ ] **Step 1: 移除 private**
```swift
// before
private struct CollocationFlowLayout: Layout {
// after
struct CollocationFlowLayout: Layout {
```

- [ ] **Step 2: Commit**

### Task 3: linksSection 重構 — 可見連結用 activeLinkGroups + 底部隱藏 pill 區

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailPresenter.swift:75,109-144`

- [ ] **Step 1: 更新顯示條件**
第 75 行：
```swift
// before
if !state.card.linkGroups.isEmpty || onAddLink != nil {
// after
if !state.card.activeLinkGroups.isEmpty || !state.card.hiddenLinks.isEmpty || onAddLink != nil {
```

- [ ] **Step 2: 重構 linksSection**
```swift
private var linksSection: some View {
    VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
        HStack {
            CardSectionLabel(title: "知識連結".localized, systemImage: "link")
            Spacer()
            if let onAddLink {
                Button(action: onAddLink) {
                    Image(systemName: "plus")
                        .font(vocabSkin.typography.iconSmall)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }
                .buttonStyle(.plain)
            }
        }

        ForEach(state.card.activeLinkGroups) { group in
            VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
                Text(group.label.localized)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)

                ForEach(group.items) { link in
                    WordDetailGraphLinkRow(
                        link: link,
                        onTap: state.navigableLinkCardIDs.contains(link.cardId) ? {
                            onLinkTapped(link)
                        } : nil,
                        onDelete: onDeleteLink != nil ? { onDeleteLink?(link) } : nil,
                        onHide: onHideLink != nil ? { onHideLink?(link) } : nil,
                        onUnhide: onUnhideLink != nil ? { onUnhideLink?(link) } : nil
                    )
                }
            }
        }

        if !state.card.hiddenLinks.isEmpty {
            CollocationFlowLayout(spacing: vocabSkin.metrics.cardBlockInnerGap) {
                ForEach(state.card.hiddenLinks) { link in
                    Text(link.word)
                        .font(vocabSkin.typography.monoBody)
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(
                            Capsule()
                                .fill(vocabSkin.palette.divider.opacity(0.5))
                        )
                        .contextMenu {
                            if let onUnhide = onUnhideLink {
                                Button {
                                    onUnhide(link)
                                } label: {
                                    Label("恢復連結".localized, systemImage: "eye")
                                }
                            }
                            if let onDelete = onDeleteLink {
                                Button(role: .destructive) {
                                    onDelete(link)
                                } label: {
                                    Label("刪除連結".localized, systemImage: "trash")
                                }
                            }
                        }
                }
            }
        }
    }
}
```

- [ ] **Step 3: 編譯驗證**
Run: `./ops/ios_build.sh`
Expected: EXIT 0

- [ ] **Step 4: Commit**
