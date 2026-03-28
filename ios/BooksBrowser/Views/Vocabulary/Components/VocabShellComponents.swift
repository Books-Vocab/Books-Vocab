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
    @Environment(\.vocabSkin) private var vocabSkin
    let options: [VocabTabOption<ID>]
    @Binding var selection: ID

    var body: some View {
        AppTabSelector(
            options: options,
            selection: $selection,
            style: .vocab(vocabSkin)
        )
    }
}

struct VocabFilterChipBar<ID: Hashable>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let options: [VocabTabOption<ID>]
    @Binding var selection: Set<ID>

    var body: some View {
        AppFilterChipBar(
            options: options,
            selection: $selection,
            style: .vocab(vocabSkin)
        )
    }
}

struct VocabSearchField: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Binding var text: String
    let prompt: String

    var body: some View {
        AppSearchField(
            text: $text,
            prompt: prompt,
            style: .vocab(vocabSkin)
        )
    }
}

struct VocabToolbarGlyph: View {
    @Environment(\.vocabSkin) private var vocabSkin
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
            style: .vocab(vocabSkin, tone: tone)
        )
    }
}

struct VocabChromeIconButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let systemImage: String
    var tone: Color? = nil
    var label: String? = nil
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            VocabChromeSurface(
                fill: vocabSkin.palette.cardBackground,
                border: vocabSkin.palette.cardBorder
            ) {
                Image(systemName: systemImage)
                    .font(vocabSkin.typography.iconMedium)
                    .foregroundStyle(tone ?? vocabSkin.palette.secondaryText)
                    .frame(width: vocabSkin.metrics.chromeButtonSize, height: vocabSkin.metrics.chromeButtonSize)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label ?? systemImage)
    }
}

struct VocabChromeSurface<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
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
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(fill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(border, lineWidth: 1)
            )
    }
}

struct VocabOverlayHeader<LeadingAccessory: View, TrailingAccessory: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
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
        HStack(spacing: vocabSkin.metrics.sectionHeaderGap) {
            leadingAccessory

            Label(title.localized, systemImage: systemImage)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.tertiaryText)

            if let badgeText {
                Text(badgeText)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                    .padding(.horizontal, vocabSkin.spacing.compactChipHorizontalPadding)
                    .padding(.vertical, vocabSkin.spacing.compactChipVerticalPadding)
                    .background(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                            .fill(vocabSkin.palette.mutedFill)
                    )
            }

            Spacer()

            trailingAccessory

            VocabChromeIconButton(systemImage: "xmark", label: "關閉", action: onClose)
        }
        .padding(.horizontal, vocabSkin.metrics.overlayHeaderHorizontalInset)
        .padding(.vertical, vocabSkin.metrics.overlayHeaderVerticalInset)
    }
}

