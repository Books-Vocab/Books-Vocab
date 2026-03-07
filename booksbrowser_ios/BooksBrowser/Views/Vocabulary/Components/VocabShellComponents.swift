import SwiftUI

enum VocabActionTone {
    case primary
    case neutral
    case success
    case warning
    case destructive
}

struct VocabTabOption<ID: Hashable>: Identifiable, Hashable {
    let id: ID
    let title: String
    let count: Int?
    let systemImage: String?

    init(id: ID, title: String, count: Int? = nil, systemImage: String? = nil) {
        self.id = id
        self.title = title
        self.count = count
        self.systemImage = systemImage
    }
}

struct VocabTabSelector<ID: Hashable>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let options: [VocabTabOption<ID>]
    @Binding var selection: ID

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(options) { option in
                    Button {
                        withAnimation(.easeOut(duration: 0.18)) {
                            selection = option.id
                        }
                    } label: {
                        HStack(spacing: 8) {
                            if let systemImage = option.systemImage {
                                Image(systemName: systemImage)
                                    .font(.system(size: 12, weight: .medium))
                            }

                            Text(option.title)
                                .font(vocabSkin.typography.captionStrong)

                            if let count = option.count {
                                Text("\(count)")
                                    .font(vocabSkin.typography.monoLabel)
                                    .padding(.horizontal, 7)
                                    .padding(.vertical, 3)
                                    .background(
                                        RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                                            .fill((selection == option.id ? vocabSkin.palette.primaryText : vocabSkin.palette.mutedFill).opacity(selection == option.id ? 0.08 : 1))
                                    )
                            }
                        }
                        .foregroundStyle(selection == option.id ? vocabSkin.palette.primaryText : vocabSkin.palette.secondaryText)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(
                            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                .fill(selection == option.id ? vocabSkin.palette.cardBackground : vocabSkin.palette.stageBackground)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                .stroke(selection == option.id ? vocabSkin.palette.cardBorder : vocabSkin.palette.borderSoftOrDivider, lineWidth: 1)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(4)
        }
        .background(
            RoundedRectangle(cornerRadius: vocabSkin.radii.control + 4, style: .continuous)
                .fill(vocabSkin.palette.stageBackground)
        )
    }
}

struct VocabChromePill: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let systemImage: String
    var count: Int? = nil
    var emphasized: Bool = false

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: systemImage)
                .font(.system(size: 12, weight: .semibold))

            Text(title)
                .font(vocabSkin.typography.captionStrong)

            if let count {
                Text("\(count)")
                    .font(vocabSkin.typography.monoLabel)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                            .fill((emphasized ? Color.white.opacity(0.12) : vocabSkin.palette.mutedFill))
                    )
            }
        }
        .foregroundStyle(emphasized ? Color.white : vocabSkin.palette.secondaryText)
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                .fill(emphasized ? vocabSkin.palette.primaryText : vocabSkin.palette.cardBackground)
        )
        .overlay(
            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                .stroke(emphasized ? vocabSkin.palette.primaryText : vocabSkin.palette.cardBorder, lineWidth: 1)
        )
    }
}

struct VocabSearchField: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Binding var text: String
    let prompt: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(vocabSkin.palette.tertiaryText)

            TextField(prompt, text: $text)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.primaryText)

            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                .fill(vocabSkin.palette.cardBackground)
        )
        .overlay(
            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
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
        HStack(spacing: 4) {
            Image(systemName: systemImage)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(tone ?? vocabSkin.palette.secondaryText)

            if let badge {
                Text(badge)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 2)
                    .background(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                            .fill(tone ?? vocabSkin.palette.destructive)
                    )
            }
        }
    }
}

struct VocabActionButtonStyle: ButtonStyle {
    @Environment(\.vocabSkin) private var vocabSkin
    let tone: VocabActionTone

    func makeBody(configuration: Configuration) -> some View {
        let palette = stylePalette

        configuration.label
            .font(vocabSkin.typography.captionStrong)
            .foregroundStyle(palette.foreground)
            .padding(.horizontal, 16)
            .padding(.vertical, 13)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(palette.background)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(palette.border, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.82 : 1)
            .scaleEffect(configuration.isPressed ? 0.992 : 1)
            .animation(.easeOut(duration: 0.14), value: configuration.isPressed)
    }

    private var stylePalette: (foreground: Color, background: Color, border: Color) {
        switch tone {
        case .primary:
            return (.white, vocabSkin.palette.primaryText, vocabSkin.palette.primaryText)
        case .neutral:
            return (
                vocabSkin.palette.primaryText,
                vocabSkin.palette.cardBackground,
                vocabSkin.palette.cardBorder
            )
        case .success:
            return (
                vocabSkin.palette.success,
                vocabSkin.palette.success.opacity(0.10),
                vocabSkin.palette.success.opacity(0.22)
            )
        case .warning:
            let warning = vocabSkin.tierColor(for: "intermediate")
            return (
                warning,
                warning.opacity(0.12),
                warning.opacity(0.22)
            )
        case .destructive:
            return (
                vocabSkin.palette.destructive,
                vocabSkin.palette.destructive.opacity(0.10),
                vocabSkin.palette.destructive.opacity(0.22)
            )
        }
    }
}

extension ButtonStyle where Self == VocabActionButtonStyle {
    static func vocabAction(_ tone: VocabActionTone = .primary) -> VocabActionButtonStyle {
        VocabActionButtonStyle(tone: tone)
    }
}

private extension VocabSkin.Palette {
    var borderSoftOrDivider: Color {
        divider.opacity(0.8)
    }
}
