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

/// Semantic library controls for p11. The content scope is a native segmented
/// Picker; progress is a single explicit menu with an "all" option. They share
/// tokens, counts, and query state, but are not represented as interchangeable
/// chips because their selection semantics are different.
struct VocabLibraryFilterBar: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    let roleOptions: [VocabTabOption<VocabularyRoleFilter>]
    let reviewOptions: [VocabTabOption<VocabularyReviewState>]
    @Binding var query: VocabularyLibraryQuery
    let visibleCount: Int

    private var selectedRoleTitle: String {
        roleOptions.first(where: { $0.id == query.contentScope })?.title ?? query.contentScope.title
    }

    private var selectedReviewTitle: String {
        if query.reviewStates.isEmpty { return L10n.string("全部狀態") }
        guard query.reviewStates.count == 1,
              let state = query.reviewStates.first else {
            return L10n.format("已選 %@ 個狀態", "\(query.reviewStates.count)")
        }
        return reviewOptions.first(where: { $0.id == state })?.title ?? state.title
    }

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.rowMicroGap) {
            HStack(alignment: .firstTextBaseline, spacing: appSkin.spacing.inlineGap) {
                Label(L10n.string("檢視範圍"), systemImage: "rectangle.stack")
                    .font(appSkin.typography.caption.weight(.semibold))
                    .foregroundStyle(appSkin.palette.secondaryText)

                Spacer(minLength: 0)

                Text(L10n.format("%@ 張", "\(visibleCount)"))
                    .font(appSkin.typography.monoLabel)
                    .monospacedDigit()
                    .foregroundStyle(appSkin.palette.quaternaryText)
                    .accessibilityIdentifier("vocab.filter.visibleCount")
                    .accessibilityLabel(L10n.format("目前顯示 %@ 張", "\(visibleCount)"))
            }

            Picker(
                L10n.string("內容範圍"),
                selection: Binding(
                    get: { query.contentScope },
                    set: { query.setContentScope($0) }
                )
            ) {
                ForEach(roleOptions) { option in
                    Text(L10n.format("%@ · %@", option.title, "\(option.count ?? 0)"))
                        .accessibilityIdentifier("vocab.filter.scope.\(option.id.rawValue)")
                        .tag(option.id)
                }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("vocab.filter.scope")
            .accessibilityValue(L10n.format("目前為 %@", selectedRoleTitle))

            if query.contentScope != .dictionary {
                Menu {
                    Button {
                        query.setReviewState(nil)
                    } label: {
                        Label(
                            L10n.format("全部狀態 · %@", "\(reviewOptions.reduce(0) { $0 + ($1.count ?? 0) })"),
                            systemImage: query.reviewStates.isEmpty ? "checkmark" : ""
                        )
                        .accessibilityIdentifier("vocab.filter.reviewState.all")
                    }

                    Divider()

                    ForEach(reviewOptions) { option in
                        Button {
                            query.setReviewState(option.id)
                        } label: {
                            Label(
                                L10n.format("%@ · %@", option.title, "\(option.count ?? 0)"),
                                systemImage: query.reviewStates == [option.id] ? "checkmark" : ""
                            )
                            .accessibilityIdentifier("vocab.filter.reviewState.\(option.id.rawValue)")
                        }
                    }
                } label: {
                    HStack(spacing: appSkin.spacing.rowMicroGap) {
                        Image(systemName: "checklist")
                        Text(L10n.format("學習狀態：%@", selectedReviewTitle))
                        Image(systemName: "chevron.down")
                            .font(appSkin.typography.iconTiny)
                    }
                    .font(appSkin.typography.caption.weight(.medium))
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .frame(minHeight: 44)
                    .padding(.horizontal, appSkin.spacing.compactChipHorizontalPadding)
                    .contentShape(Rectangle())
                    .glassEffect(
                        .regular.interactive(),
                        in: AppRoundedRect(roundness: AppRoundness.control)
                    )
                }
                .accessibilityIdentifier("vocab.filter.reviewState")
                .accessibilityLabel(L10n.string("學習狀態篩選"))
                .accessibilityValue(selectedReviewTitle)
            }
        }
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
    var identifier: String? = nil
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
        .accessibilityIdentifier(identifier ?? "")
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
                AppRoundedRect(roundness: appSkin.roundness.control)
                    .fill(fill)
            )
            .overlay(
                AppRoundedRect(roundness: appSkin.roundness.control)
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
                        AppRoundedRect(roundness: AppRoundness.pill)
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
