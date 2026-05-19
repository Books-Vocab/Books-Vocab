#if os(iOS)
import SwiftUI

extension ReaderViewPresenter {
    var loadingOverlay: some View {
        state.paperColor.ignoresSafeArea()
            .overlay {
                loadingOverlayContent(
                    progressTint: appSkin.palette.primaryText,
                    textFont: appSkin.typography.body.weight(.semibold),
                    textColor: appSkin.palette.primaryText
                )
                .modifier(VocabLoadingOverlayChrome(appSkin: appSkin))
                .frame(maxWidth: ReaderPresentationMetrics.Overlay.loadingMaxWidth)
                .padding(.horizontal, ReaderPresentationMetrics.Overlay.loadingOuterInset)
            }
    }

    func underlineProgressOverlay(_ progress: Double) -> some View {
        VStack {
            AppSectionCard(style: .vocab(appSkin)) {
                progressOverlayContent(
                    progress: progress,
                    trackColor: appSkin.palette.mutedFill,
                    fillColor: appSkin.palette.accent,
                    textFont: appSkin.typography.monoLabel,
                    textColor: appSkin.palette.secondaryText
                )
                .padding(.horizontal, ReaderPresentationMetrics.Overlay.progressHorizontalInset)
                .padding(.vertical, ReaderPresentationMetrics.Overlay.progressVerticalInset)
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
            } else if state.chrome.overlay == .settings {
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
                .animation(AppMotion.contentFade, value: state.loadingPhase)
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
    let appSkin: AppSkin

    func body(content: Content) -> some View {
        AppSectionCard(style: .vocab(appSkin)) {
            content
        }
    }
}
#endif
