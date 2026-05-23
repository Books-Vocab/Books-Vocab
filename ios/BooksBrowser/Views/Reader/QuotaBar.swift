#if os(iOS)
import SwiftUI
import Inject

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
                        RoundedRectangle(cornerRadius: 1, style: .continuous)
                            .fill(barColor.opacity(0.15))

                        RoundedRectangle(cornerRadius: 1, style: .continuous)
                            .fill(barColor.opacity(barOpacity))
                            .frame(width: geo.size.width * store.fraction)
                            .animateSpring(store.fraction)
                    }
                }
                .frame(height: 2)
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

#Preview("QuotaBar / Normal") {
    AppThemeContainer {
        QuotaBar(isLoggedIn: true)
            .padding()
    }
    .environmentObject(AppAppearanceStore.preview)
}
#endif
