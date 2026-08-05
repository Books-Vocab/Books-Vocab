#if os(iOS)
import SwiftUI

struct QuotaBar: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    @Environment(\.appSkin) private var appSkin
    @Environment(\.quotaStore) private var store

    let isLoggedIn: Bool

    var body: some View {
        Group {
            if isLoggedIn {
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        AppRoundedRect(roundness: ReaderMetrics.quotaBarRoundness)
                            .fill(barColor.opacity(ReaderMetrics.quotaBarTrackOpacity))

                        AppRoundedRect(roundness: ReaderMetrics.quotaBarRoundness)
                            .fill(barColor.opacity(barOpacity))
                            .frame(width: geo.size.width * store.fraction)
                            .animateSpring(store.fraction)
                    }
                }
                .frame(height: ReaderMetrics.quotaBarHeight)
            }
        }
        .enableInjection()
    }

    private var barColor: Color {
        switch store.level {
        case .normal:    return appSkin.palette.success
        case .warning:   return appTheme.palette.warning
        case .critical:  return appSkin.palette.destructive
        case .exhausted: return appSkin.palette.destructive
        }
    }

    private var barOpacity: Double {
        switch store.level {
        case .normal:    return 0.3
        case .warning:   return 0.6
        case .critical:  return 1.0
        case .exhausted: return 1.0
        }
    }
}

struct QuotaBarPreviewHarness: View {
    let isLoggedIn: Bool
    let fraction: Double
    let level: QuotaStore.Level

    var body: some View {
        AppThemeContainer {
            QuotaBar(isLoggedIn: isLoggedIn)
                .environment(\.quotaStore, MockQuotaStore(fraction: fraction, level: level))
                .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private final class MockQuotaStore: QuotaProviding {
    var fraction: Double
    var level: QuotaStore.Level
    var isExhausted: Bool { fraction <= 0 }
    var resetText: String { "Resets in 1h" }

    init(fraction: Double, level: QuotaStore.Level) {
        self.fraction = fraction
        self.level = level
    }

    func update(from response: HTTPURLResponse) {}
}

#Preview("QuotaBar / Normal") {
    QuotaBarPreviewHarness(isLoggedIn: true, fraction: 0.75, level: .normal)
}
#endif
