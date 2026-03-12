import SwiftUI

struct QuotaBar: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.quotaStore) private var store

    let isLoggedIn: Bool

    var body: some View {
        if isLoggedIn, store.fraction < 1.0 {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 1, style: .continuous)
                        .fill(barColor.opacity(0.15))

                    RoundedRectangle(cornerRadius: 1, style: .continuous)
                        .fill(barColor.opacity(barOpacity))
                        .frame(width: geo.size.width * store.fraction)
                        .animation(AppMotion.standardSpring, value: store.fraction)
                }
            }
            .frame(height: 2)
        }
    }

    private var barColor: Color {
        switch store.level {
        case .normal:    return vocabSkin.palette.success
        case .warning:   return appTheme.palette.warning
        case .critical:  return vocabSkin.palette.destructive
        case .exhausted: return vocabSkin.palette.destructive
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
}
