#if os(iOS)
import SwiftUI

// 契約（同 ReviewTopBar，由 ReviewChromeSliceTests 的 Mirror 驗證）：所有會影響
// chrome 渲染的值必須收進 model，其餘 stored property 只允許 intent 閉包。
// 否則拖曳期間每一幀都要重新求值整條 header。
struct ReaderTopChromeModel: Equatable {
    var isExpanded: Bool
    var bookTitle: String
    var totalProgression: Double
    var titleMaxWidth: CGFloat
}

struct ReaderTopChrome: View, Equatable {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Namespace private var glass

    let model: ReaderTopChromeModel
    let onDismiss: () -> Void
    let onShowTableOfContents: () -> Void
    let onShowReaderSettings: () -> Void
    let onShowNotebookPicker: () -> Void
    let onCollapseHeader: () -> Void
    let onExpandHeader: () -> Void

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.model == rhs.model
    }

    var body: some View {
        AppFloatingChrome {
            if model.isExpanded {
                expandedChrome
            } else {
                compactChrome
            }
        }
        .padding(.horizontal, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .padding(.top, ReaderPresentationMetrics.Header.outerTopInset)
        .animation(AppMotion.controlEaseOut, value: model.isExpanded)
        .enableInjection()
    }

    // MARK: - Expanded

    // 兩組 union：nav（返回）與 tools（四顆功能鍵）各自合成一塊共享膠囊，書名置於兩組
    // 之間。這同時滿足 Apple「不要在共享背景的 item 之間混文字與圖示」，也是「書庫 /
    // Library 直排」的真正修法——返回鍵不再與四顆 icon 擠同一個壓縮情境。
    private var expandedChrome: some View {
        HStack(spacing: AppSpacing.s2) {
            backButton
                .appFloatingChromeItem(union: "nav", in: glass)

            Spacer(minLength: AppSpacing.s2)

            Text(model.bookTitle)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(maxWidth: model.titleMaxWidth)

            Spacer(minLength: AppSpacing.s2)

            HStack(spacing: AppSpacing.s1) {
                toolButton("list.bullet", "目錄".localized, onShowTableOfContents)
                toolButton("textformat.size", "閱讀設定".localized, onShowReaderSettings)
                toolButton("text.book.closed", "選擇單字本".localized, onShowNotebookPicker)
                toolButton("chevron.up", "收起標題列".localized, onCollapseHeader)
                    .appFloatingChromeMorph(id: "more", in: glass)
            }
        }
    }

    private var backButton: some View {
        AppFloatingChromeButton(
            accessibilityLabel: "書庫".localized,
            accessibilityIdentifier: "reader.header.backButton",
            action: onDismiss
        ) {
            HStack(spacing: AppSpacing.s1) {
                Image(systemName: "chevron.left")
                    .font(appSkin.typography.iconToolbar)
                Text("書庫".localized)
                    .font(appSkin.typography.body.weight(.semibold))
                    // 直排修法之二：不讓 label 在壓縮情境下換行。repo 的 Component
                    // Hard Rules 本就要求，這裡是補上而非新增約束。
                    .lineLimit(1)
                    .fixedSize(horizontal: true, vertical: false)
            }
            .foregroundStyle(appSkin.palette.primaryText)
            .padding(.horizontal, AppSpacing.s2)
        }
    }

    private func toolButton(
        _ systemImage: String,
        _ label: String,
        _ action: @escaping () -> Void
    ) -> some View {
        AppFloatingChromeButton(accessibilityLabel: label, action: action) {
            Image(systemName: systemImage)
                .font(appSkin.typography.iconToolbar)
                .foregroundStyle(appSkin.palette.secondaryText)
        }
        .appFloatingChromeItem(union: "tools", in: glass)
    }

    // MARK: - Compact

    private var compactChrome: some View {
        HStack(spacing: AppSpacing.s2) {
            Spacer()

            // 刻意不給進度膠囊 morph id：它是條件式的（totalProgression == 0 時整個
            // 不存在），而 morph 需要兩態都有對象。曾經把 `chrome` 掛在這裡，新書／
            // PDF 首次事件前就會變成「有時 morph、有時直接消失」的不一致動畫。
            if model.totalProgression > 0 {
                progressBadge
                    .appFloatingChromeItem(union: "nav", in: glass, interactive: false)
            }

            AppFloatingChromeButton(
                accessibilityLabel: "展開標題列".localized,
                accessibilityIdentifier: "reader.header.expandButton",
                action: onExpandHeader
            ) {
                Image(systemName: "ellipsis")
                    .font(appSkin.typography.iconToolbar)
                    .foregroundStyle(appSkin.palette.secondaryText)
            }
            .appFloatingChromeItem(union: "tools", in: glass)
            .appFloatingChromeMorph(id: "more", in: glass)
        }
    }

    // 格式 `%.1f%%` 與 identifier 是 UITest 契約：ReaderPage.progressPercent() 靠剝掉
    // "%" 再餵 Double(_:)（C-locale 解析），ReaderFlowUITests 拿它當翻頁證據。
    // locale-aware 化要連同 ReaderPage 的解析一起改，走獨立 PR。
    private var progressBadge: some View {
        HStack(spacing: AppSpacing.s1) {
            Image(systemName: "book.closed")
                .font(appSkin.typography.iconSmall)
            Text(String(format: "%.1f%%", model.totalProgression * 100))
                .font(appSkin.typography.monoLabel)
                .accessibilityIdentifier("reader.header.progressBadge")
        }
        .foregroundStyle(appSkin.palette.secondaryText)
        .padding(.horizontal, AppSpacing.s2)
    }
}

extension ReaderViewPresenter {
    var topOverlay: some View {
        VStack {
            // showsHeader 管的是「翻譯/設定面板升起時把 chrome 收掉」，與 compact ↔
            // expanded 的形變正交——後者現在由 glassEffectID 表達，前者仍需要它。
            if state.chrome.showsHeader {
                ReaderTopChrome(
                    model: ReaderTopChromeModel(
                        isExpanded: state.chrome.header == .expanded,
                        bookTitle: state.bookTitle,
                        totalProgression: state.totalProgression,
                        titleMaxWidth: LayoutMode(horizontalSizeClass: sizeClass).readerTitleMaxWidth
                    ),
                    onDismiss: onDismiss,
                    onShowTableOfContents: onShowTableOfContents,
                    onShowReaderSettings: onShowReaderSettings,
                    onShowNotebookPicker: onShowNotebookPicker,
                    onCollapseHeader: onCollapseHeader,
                    onExpandHeader: onExpandHeader
                )
                // 契約的消費端。少了它，Equatable 與 Mirror 測試都是空轉——
                // 7 個閉包每次 parent body 都是新值，SwiftUI 預設比較必然重繪。
                // repo 另外三個 `View, Equatable` 的 call site 都掛（ReviewTopBar /
                // ReviewToolbarControls / PodcastBubbleCell）。
                .equatable()
            }

            Spacer()
        }
    }
}
#endif
