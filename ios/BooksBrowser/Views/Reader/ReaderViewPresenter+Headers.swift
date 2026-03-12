import SwiftUI

extension ReaderViewPresenter {
    var topOverlay: some View {
        VStack {
            if state.chrome.showsHeader {
                switch (state.panelMode, state.chrome.header) {
                case (.vocab, .expanded):
                    vocabExpandedHeader
                case (.vocab, .compact):
                    vocabCompactHeader
                case (_, .expanded):
                    glassExpandedHeader
                case (_, .compact):
                    glassCompactHeader
                }
            }

            Spacer()
        }
    }

    var glassExpandedHeader: some View {
        GlassEffectContainer {
            HStack(spacing: 0) {
                Button(action: onDismiss) {
                    HStack(spacing: 4) {
                        Image(systemName: "chevron.left")
                            .font(ReaderGlassTypography.headerBackIcon)
                        Text("書庫".localized)
                            .font(ReaderGlassTypography.headerBackLabel)
                    }
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .padding(.leading, ReaderPresentationMetrics.Header.trailingInset)
                }

                Spacer()

                Text(state.bookTitle)
                    .font(ReaderGlassTypography.headerTitle)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .lineLimit(1)
                    .frame(maxWidth: sizeClass == .regular
                        ? ReaderPresentationMetrics.Header.titleMaxWidthRegular
                        : ReaderPresentationMetrics.Header.titleMaxWidth)

                Spacer()

                HStack(spacing: 2) {
                    Button(action: onShowTableOfContents) {
                        Image(systemName: "list.bullet")
                            .font(ReaderGlassTypography.headerAction)
                            .foregroundStyle(vocabSkin.palette.primaryText)
                            .frame(
                                width: ReaderPresentationMetrics.Header.buttonSize,
                                height: ReaderPresentationMetrics.Header.buttonSize
                            )
                            .contentShape(Rectangle())
                    }
                    .accessibilityLabel("目錄".localized)

                    Button(action: onShowReaderSettings) {
                        Image(systemName: "textformat.size")
                            .font(ReaderGlassTypography.headerAction)
                            .foregroundStyle(vocabSkin.palette.primaryText)
                            .frame(
                                width: ReaderPresentationMetrics.Header.buttonSize,
                                height: ReaderPresentationMetrics.Header.buttonSize
                            )
                            .contentShape(Rectangle())
                    }
                    .accessibilityLabel("閱讀設定".localized)

                    Button(action: onCollapseHeader) {
                        Image(systemName: "chevron.up")
                            .font(ReaderGlassTypography.headerCollapse)
                            .foregroundStyle(vocabSkin.palette.primaryText)
                            .frame(
                                width: ReaderPresentationMetrics.Header.buttonSize,
                                height: ReaderPresentationMetrics.Header.buttonSize
                            )
                            .contentShape(Rectangle())
                    }
                    .accessibilityLabel("收起標題列".localized)
                }
                .padding(.trailing, ReaderPresentationMetrics.Header.trailingInset)
            }
            .padding(.horizontal, ReaderPresentationMetrics.Header.contentHorizontalInset)
            .padding(.vertical, ReaderPresentationMetrics.Header.contentVerticalInset)
        }
        .glassEffect(in: Capsule())
        .shadow(
            color: .black.opacity(ReaderPresentationMetrics.Header.shadowOpacity),
            radius: ReaderPresentationMetrics.Header.expandedShadowRadius,
            x: 0,
            y: ReaderPresentationMetrics.Header.shadowY
        )
        .padding(.horizontal, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .padding(.top, ReaderPresentationMetrics.Header.outerTopInset)
        .transition(.headerSwap)
    }

    var glassCompactHeader: some View {
        HStack(spacing: ReaderPresentationMetrics.Header.compactSpacing) {
            Spacer()

            if state.totalProgression > 0 {
                Text(String(format: "%.1f%%", state.totalProgression * 100))
                    .font(ReaderGlassTypography.progressText)
                    .foregroundStyle(.tertiary)
                    .padding(.trailing, ReaderPresentationMetrics.Header.trailingInset)
            }

            Button(action: onExpandHeader) {
                GlassEffectContainer {
                    Image(systemName: "ellipsis")
                        .font(ReaderGlassTypography.compactMenuIcon)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .frame(
                            width: ReaderPresentationMetrics.Header.compactButtonSize,
                            height: ReaderPresentationMetrics.Header.compactButtonSize
                        )
                        .contentShape(Circle())
                }
                .glassEffect(in: Circle())
                .shadow(
                    color: .black.opacity(ReaderPresentationMetrics.Header.shadowOpacity),
                    radius: ReaderPresentationMetrics.Header.compactShadowRadius,
                    x: 0,
                    y: ReaderPresentationMetrics.Header.shadowY
                )
            }
            .accessibilityLabel("展開標題列".localized)
        }
        .padding(.trailing, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .transition(.headerSwap)
    }

    var vocabExpandedHeader: some View {
        AppSectionCard(padding: 0, style: .vocab(vocabSkin)) {
            HStack(spacing: 10) {
                Button(action: onDismiss) {
                    HStack(spacing: 6) {
                        Image(systemName: "chevron.left")
                            .font(vocabSkin.typography.iconToolbar)
                        Text("書庫".localized)
                            .font(vocabSkin.typography.body.weight(.semibold))
                    }
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                Spacer()

                Text(state.bookTitle)
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                    .lineLimit(1)
                    .frame(maxWidth: sizeClass == .regular
                        ? ReaderPresentationMetrics.Header.titleMaxWidthRegular
                        : ReaderPresentationMetrics.Header.titleMaxWidth)

                Spacer()

                HStack(spacing: 6) {
                    VocabChromeIconButton(systemImage: "list.bullet", label: "目錄".localized, action: onShowTableOfContents)
                    VocabChromeIconButton(systemImage: "textformat.size", label: "閱讀設定".localized, action: onShowReaderSettings)
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
                HStack(spacing: 6) {
                    Image(systemName: "book.closed")
                        .font(vocabSkin.typography.iconSmall)
                    Text(String(format: "%.1f%%", state.totalProgression * 100))
                        .font(vocabSkin.typography.monoLabel)
                }
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .padding(.horizontal, ReaderPresentationMetrics.Header.compactProgressInsetHorizontal)
                .padding(.vertical, ReaderPresentationMetrics.Header.compactProgressInsetVertical)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.cardBackground)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                )
            }

            VocabChromeIconButton(systemImage: "ellipsis", label: "展開標題列".localized, action: onExpandHeader)
        }
        .padding(.trailing, ReaderPresentationMetrics.Header.outerHorizontalInset)
        .padding(.top, ReaderPresentationMetrics.Header.outerTopInset)
        .transition(.headerSwap)
    }
}
