#if os(iOS)
import SwiftUI

extension ReaderViewPresenter {
    var loadingOverlay: some View {
        state.paperColor.ignoresSafeArea()
            .overlay {
                AppLoadingStateCard(
                    title: state.loadingPhase,
                    systemImage: "book.closed",
                    visualStyle: .vocab
                )
                .frame(maxWidth: ReaderPresentationMetrics.Overlay.loadingMaxWidth)
                .padding(.horizontal, ReaderPresentationMetrics.Overlay.loadingOuterInset)
            }
    }

    func underlineProgressOverlay(_ progress: Double) -> some View {
        VStack {
            AppSectionCard(style: .vocab(appSkin)) {
                HStack(spacing: AppSpacing.s2) {
                    AppLoadingProgressBar(progress: progress, tint: appSkin.palette.accent)
                        .frame(width: ReaderPresentationMetrics.Overlay.progressBarWidth)

                    Text("\(Int(min(max(progress, 0), 1) * 100))%")
                        .font(appSkin.typography.monoLabel)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .accessibilityHidden(true)
                        .frame(
                            width: ReaderPresentationMetrics.Overlay.progressTextWidth,
                            alignment: .trailing
                        )
                }
                .padding(.horizontal, ReaderPresentationMetrics.Overlay.progressHorizontalInset)
                .padding(.vertical, ReaderPresentationMetrics.Overlay.progressVerticalInset)
            }
            .padding(.top, ReaderPresentationMetrics.Overlay.topInset)

            Spacer()
        }
        .allowsHitTesting(false)
        .transition(.overlayFade)
    }

    /// 只剩翻譯面板：閱讀設定已於 APP-20260808-240a94 改由 `ReaderView` 的系統
    /// sheet 呈現，不再是自繪的底部 overlay 卡片。
    var bottomOverlay: some View {
        let placement = ReaderOverlayPanelPlacement(layoutMode: LayoutMode(horizontalSizeClass: sizeClass))

        return VStack {
            Spacer()

            if state.chrome.overlay == .translation {
                overlayPanelChrome(translationPanel, placement: placement)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("reader.translationPanel")
            }
        }
        .animation(AppMotion.panelState, value: state.chrome.overlay)
    }

    private func overlayPanelChrome<Content: View>(
        _ panel: Content,
        placement: ReaderOverlayPanelPlacement
    ) -> some View {
        panel
            .frame(maxWidth: placement.maxWidth)
            .frame(maxWidth: .infinity, alignment: placement.alignment)
            .padding(.horizontal, placement.horizontalInset)
            .padding(.bottom, placement.bottomInset)
            .transition(.readerPanelReveal)
    }

}
#endif
