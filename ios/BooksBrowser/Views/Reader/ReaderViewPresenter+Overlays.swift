import SwiftUI

extension ReaderViewPresenter {
    var loadingOverlay: some View {
        Group {
            if state.panelMode == .vocab {
                state.paperColor.ignoresSafeArea()
                    .overlay {
                        loadingOverlayContent(
                            progressTint: vocabSkin.palette.primaryText,
                            textFont: vocabSkin.typography.body.weight(.semibold),
                            textColor: vocabSkin.palette.primaryText
                        )
                        .modifier(VocabLoadingOverlayChrome(vocabSkin: vocabSkin))
                        .frame(maxWidth: ReaderPresentationMetrics.Overlay.loadingMaxWidth)
                        .padding(.horizontal, ReaderPresentationMetrics.Overlay.loadingOuterInset)
                    }
            } else {
                state.paperColor.ignoresSafeArea()
                    .overlay {
                        loadingOverlayContent(
                            progressTint: vocabSkin.palette.primaryText,
                            textFont: ReaderGlassTypography.body.weight(.medium),
                            textColor: vocabSkin.palette.primaryText
                        )
                        .glassEffect(
                            .regular,
                            in: .rect(cornerRadius: ReaderPresentationMetrics.Panel.cornerRadius)
                        )
                    }
            }
        }
    }

    func underlineProgressOverlay(_ progress: Double) -> some View {
        VStack {
            Group {
                if state.panelMode == .vocab {
                    AppSectionCard(style: .vocab(vocabSkin)) {
                        progressOverlayContent(
                            progress: progress,
                            trackColor: vocabSkin.palette.mutedFill,
                            fillColor: vocabSkin.palette.accent,
                            textFont: vocabSkin.typography.monoLabel,
                            textColor: vocabSkin.palette.secondaryText
                        )
                        .padding(.horizontal, ReaderPresentationMetrics.Overlay.progressHorizontalInset)
                        .padding(.vertical, ReaderPresentationMetrics.Overlay.progressVerticalInset)
                    }
                } else {
                    progressOverlayContent(
                        progress: progress,
                        trackColor: vocabSkin.palette.divider,
                        fillColor: vocabSkin.palette.accent,
                        textFont: ReaderGlassTypography.progressText,
                        textColor: vocabSkin.palette.secondaryText
                    )
                    .padding(.horizontal, ReaderPresentationMetrics.Overlay.progressHorizontalInset)
                    .padding(.vertical, ReaderPresentationMetrics.Overlay.progressVerticalInset)
                    .glassEffect(.regular, in: .capsule)
                }
            }
            .padding(.top, ReaderPresentationMetrics.Overlay.topInset)

            Spacer()
        }
        .allowsHitTesting(false)
        .transition(.overlayFade)
    }

    var bottomOverlay: some View {
        VStack {
            Spacer()

            if state.chrome.overlay == .translation {
                translationPanel
                    .frame(maxWidth: ReaderPresentationMetrics.Overlay.panelMaxWidth)
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal)
                    .padding(.bottom, ReaderPresentationMetrics.Overlay.bottomInset)
                    .transition(.readerPanelReveal)
            } else if state.chrome.overlay == .settings && state.panelMode == .vocab {
                settingsPanel
                    .frame(maxWidth: ReaderPresentationMetrics.Overlay.panelMaxWidth)
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal)
                    .padding(.bottom, ReaderPresentationMetrics.Overlay.bottomInset)
                    .transition(.readerPanelReveal)
            }
        }
        .animation(AppMotion.panelState, value: state.chrome.overlay)
    }

    private func loadingOverlayContent(
        progressTint: Color,
        textFont: Font,
        textColor: Color
    ) -> some View {
        VStack(spacing: ReaderPresentationMetrics.Overlay.loadingSpacing) {
            ProgressView()
                .tint(progressTint)
            Text(state.loadingPhase)
                .font(textFont)
                .foregroundStyle(textColor)
                .contentTransition(.numericText())
                .animation(AppMotion.loadingState, value: state.loadingPhase)
        }
        .padding(.horizontal, ReaderPresentationMetrics.Overlay.loadingHorizontalInset)
        .padding(.vertical, ReaderPresentationMetrics.Overlay.loadingVerticalInset)
    }

    private func progressOverlayContent(
        progress: Double,
        trackColor: Color,
        fillColor: Color,
        textFont: Font,
        textColor: Color
    ) -> some View {
        HStack(spacing: 10) {
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(trackColor)
                    .frame(
                        width: ReaderPresentationMetrics.Overlay.progressBarWidth,
                        height: ReaderPresentationMetrics.Overlay.progressBarHeight
                    )
                Capsule()
                    .fill(fillColor)
                    .frame(
                        width: max(
                            ReaderPresentationMetrics.Overlay.progressBarHeight,
                            ReaderPresentationMetrics.Overlay.progressBarWidth * progress
                        ),
                        height: ReaderPresentationMetrics.Overlay.progressBarHeight
                    )
                    .animation(AppMotion.progressLinear, value: progress)
            }
            Text("\(Int(progress * 100))%")
                .font(textFont)
                .foregroundStyle(textColor)
                .frame(width: ReaderPresentationMetrics.Overlay.progressTextWidth, alignment: .trailing)
        }
    }
}

private struct VocabLoadingOverlayChrome: ViewModifier {
    let vocabSkin: VocabSkin

    func body(content: Content) -> some View {
        AppSectionCard(style: .vocab(vocabSkin)) {
            content
        }
    }
}
