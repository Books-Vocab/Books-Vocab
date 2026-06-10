#if os(iOS)
import SwiftUI

extension ReaderViewPresenter {
    var topOverlay: some View {
        VStack {
            if state.chrome.showsHeader {
                switch state.chrome.header {
                case .expanded:
                    vocabExpandedHeader
                case .compact:
                    vocabCompactHeader
                }
            }

            Spacer()
        }
    }

    var vocabExpandedHeader: some View {
        // Mochi 北極星 #1：top toolbar 與 paper 同色，去 chrome 分隔感。
        // 從 `.vocab(appSkin)`（有 border + z1）改為 `.flatVocab(appSkin)`（同色背景、無 border、無 elevation）。
        AppSectionCard(padding: 0, style: .flatVocab(appSkin)) {
            HStack(spacing: 10) {
                expandedHeaderBackButton

                Spacer()

                Text(state.bookTitle)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .frame(maxWidth: LayoutMode(horizontalSizeClass: sizeClass).readerTitleMaxWidth)

                Spacer()

                expandedHeaderToolbarButtons
            }
            .padding(.horizontal, ReaderPresentationMetrics.Header.contentHorizontalInsetExpanded)
            .padding(.vertical, ReaderPresentationMetrics.Header.contentVerticalInset)
        }
        .padding(.horizontal, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .padding(.top, ReaderPresentationMetrics.Header.outerTopInset)
        .transition(.headerSwap)
    }

    var vocabCompactHeader: some View {
        HStack(spacing: ReaderPresentationMetrics.Header.compactSpacing) {
            Spacer()

            compactHeaderProgressBadge

            VocabChromeIconButton(systemImage: "ellipsis", label: "展開標題列".localized, action: onExpandHeader)
        }
        .padding(.trailing, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .padding(.top, ReaderPresentationMetrics.Header.outerTopInset)
        .transition(.headerSwap)
    }

    private var expandedHeaderBackButton: some View {
        Button(action: onDismiss) {
            HStack(spacing: 6) {
                Image(systemName: "chevron.left")
                    .font(appSkin.typography.iconToolbar)
                Text("書庫".localized)
                    .font(appSkin.typography.body.weight(.semibold))
            }
            .foregroundStyle(appSkin.palette.primaryText)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var expandedHeaderToolbarButtons: some View {
        HStack(spacing: 6) {
            VocabChromeIconButton(systemImage: "list.bullet", label: "目錄".localized, action: onShowTableOfContents)
            VocabChromeIconButton(systemImage: "textformat.size", label: "閱讀設定".localized, action: onShowReaderSettings)
            VocabChromeIconButton(systemImage: "text.book.closed", label: "選擇單字本".localized, action: onShowNotebookPicker)
            VocabChromeIconButton(systemImage: "chevron.up", label: "收起標題列".localized, action: onCollapseHeader)
        }
    }

    @ViewBuilder private var compactHeaderProgressBadge: some View {
        if state.totalProgression > 0 {
            // Mochi 北極星 #2：border 退場 — 進度膠囊改用純 fill，不再描邊。
            VocabChromeSurface(
                fill: appSkin.palette.cardBackground,
                border: .clear
            ) {
                HStack(spacing: 6) {
                    Image(systemName: "book.closed")
                        .font(appSkin.typography.iconSmall)
                    Text(String(format: "%.1f%%", state.totalProgression * 100))
                        .font(appSkin.typography.monoLabel)
                        .accessibilityIdentifier("reader.header.progressBadge")
                }
                .foregroundStyle(appSkin.palette.secondaryText)
                .padding(.horizontal, ReaderPresentationMetrics.Header.compactProgressInsetHorizontal)
                .padding(.vertical, ReaderPresentationMetrics.Header.compactProgressInsetVertical)
            }
        }
    }
}
#endif
