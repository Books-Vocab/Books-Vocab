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
        AppSectionCard(padding: 0, style: .vocab(appSkin)) {
            HStack(spacing: 10) {
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

                Spacer()

                Text(state.bookTitle)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .lineLimit(1)
                    .frame(maxWidth: LayoutMode(horizontalSizeClass: sizeClass).readerTitleMaxWidth)

                Spacer()

                HStack(spacing: 6) {
                    VocabChromeIconButton(systemImage: "list.bullet", label: "目錄".localized, action: onShowTableOfContents)
                    VocabChromeIconButton(systemImage: "textformat.size", label: "閱讀設定".localized, action: onShowReaderSettings)
                    VocabChromeIconButton(systemImage: "text.book.closed", label: "選擇單字本".localized, action: onShowNotebookPicker)
                    VocabChromeIconButton(systemImage: "chevron.up", label: "收起標題列".localized, action: onCollapseHeader)
                }
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

            if state.totalProgression > 0 {
                VocabChromeSurface(
                    fill: appSkin.palette.cardBackground,
                    border: appSkin.palette.cardBorder
                ) {
                    HStack(spacing: 6) {
                        Image(systemName: "book.closed")
                            .font(appSkin.typography.iconSmall)
                        Text(String(format: "%.1f%%", state.totalProgression * 100))
                            .font(appSkin.typography.monoLabel)
                    }
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .padding(.horizontal, ReaderPresentationMetrics.Header.compactProgressInsetHorizontal)
                    .padding(.vertical, ReaderPresentationMetrics.Header.compactProgressInsetVertical)
                }
            }

            VocabChromeIconButton(systemImage: "ellipsis", label: "展開標題列".localized, action: onExpandHeader)
        }
        .padding(.trailing, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .padding(.top, ReaderPresentationMetrics.Header.outerTopInset)
        .transition(.headerSwap)
    }
}
#endif
