import SwiftUI

enum VocabActionTone {
    case primary
    case neutral
    case success
    case warning
    case destructive
}

typealias VocabTabOption<ID: Hashable> = AppTabOption<ID>

struct VocabTabSelector<ID: Hashable>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let options: [VocabTabOption<ID>]
    @Binding var selection: ID

    var body: some View {
        AppTabSelector(
            options: options,
            selection: $selection,
            style: .vocab(appSkin)
        )
        .enableInjection()
    }
}

struct VocabFilterChipBar<ID: Hashable>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let options: [VocabTabOption<ID>]
    @Binding var selection: Set<ID>

    var body: some View {
        AppFilterChipBar(
            options: options,
            selection: $selection,
            style: .vocab(appSkin)
        )
        .enableInjection()
    }
}

struct VocabSearchField: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Binding var text: String
    let prompt: String
    var isFocused: FocusState<Bool>.Binding? = nil
    var accessibilityID: String = ""

    var body: some View {
        AppSearchField(
            text: $text,
            prompt: prompt,
            style: .vocab(appSkin),
            isFocused: isFocused,
            accessibilityID: accessibilityID
        )
        .enableInjection()
    }
}

struct VocabToolbarGlyph: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let systemImage: String
    let badge: String?
    let tone: Color?

    init(systemImage: String, badge: String? = nil, tone: Color? = nil) {
        self.systemImage = systemImage
        self.badge = badge
        self.tone = tone
    }

    var body: some View {
        AppToolbarGlyph(
            systemImage: systemImage,
            badge: badge,
            style: .vocab(appSkin, tone: tone)
        )
        .enableInjection()
    }
}

struct VocabChromeIconButton: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let systemImage: String
    var tone: Color? = nil
    var label: String? = nil
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            VocabChromeSurface(
                fill: appSkin.palette.cardBackground,
                border: appSkin.palette.cardBorder
            ) {
                Image(systemName: systemImage)
                    .font(appSkin.typography.iconMedium)
                    .foregroundStyle(tone ?? appSkin.palette.secondaryText)
                    .frame(width: appSkin.metrics.chromeButtonSize, height: appSkin.metrics.chromeButtonSize)
            }
            // 視覺維持 32pt（VocabChromeSurface），僅外擴觸控目標到 HIG 44pt 下限。
            // contentShape 確保整個 44pt 區域可點，但不撐大版面佔位（frame minWidth/minHeight 不放大視覺）。
            .frame(minWidth: 44, minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .appPointerHover()
        .accessibilityLabel(label ?? systemImage)
        .enableInjection()
    }
}

struct VocabChromeSurface<Content: View>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let fill: Color
    let border: Color
    let content: Content

    init(
        fill: Color? = nil,
        border: Color? = nil,
        @ViewBuilder content: () -> Content
    ) {
        self.fill = fill ?? .clear
        self.border = border ?? .clear
        self.content = content()
    }

    var body: some View {
        content
            .background(
                RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous)
                    .fill(fill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous)
                    .stroke(border, lineWidth: 1)
            )
            .enableInjection()
    }
}

struct VocabOverlayHeader<LeadingAccessory: View, TrailingAccessory: View>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let title: String
    let systemImage: String
    var badgeText: String? = nil
    let onClose: () -> Void
    @ViewBuilder let leadingAccessory: LeadingAccessory
    @ViewBuilder let trailingAccessory: TrailingAccessory

    init(
        title: String,
        systemImage: String,
        badgeText: String? = nil,
        onClose: @escaping () -> Void,
        @ViewBuilder trailing trailingAccessory: () -> TrailingAccessory = { EmptyView() },
        @ViewBuilder leadingAccessory: () -> LeadingAccessory = { EmptyView() }
    ) {
        self.title = title
        self.systemImage = systemImage
        self.badgeText = badgeText
        self.onClose = onClose
        self.trailingAccessory = trailingAccessory()
        self.leadingAccessory = leadingAccessory()
    }

    var body: some View {
        HStack(spacing: appSkin.metrics.sectionHeaderGap) {
            leadingAccessory

            Label(title.localized, systemImage: systemImage)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)

            if let badgeText {
                Text(badgeText)
                    .font(appSkin.typography.monoLabel)
                    .foregroundStyle(appSkin.palette.quaternaryText)
                    .padding(.horizontal, appSkin.spacing.compactChipHorizontalPadding)
                    .padding(.vertical, appSkin.spacing.compactChipVerticalPadding)
                    .background(
                        Capsule(style: .continuous)
                            .fill(appSkin.palette.mutedFill)
                    )
            }

            Spacer()

            trailingAccessory

            VocabChromeIconButton(systemImage: "xmark", label: L10n.string("a11y.action.close"), action: onClose)
        }
        .padding(.horizontal, appSkin.metrics.overlayHeaderHorizontalInset)
        .padding(.vertical, appSkin.metrics.overlayHeaderVerticalInset)
        .enableInjection()
    }
}

