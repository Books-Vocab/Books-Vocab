import SwiftUI

struct StyleDemoView: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var glassMode: DemoGlassMode = .paper
    @State private var overlayStack: [DemoCard] = []

    private let rootCard = DemoCard.rootDetail
    private let libraryCards = DemoCard.sampleLibrary

    private var isCompact: Bool {
        horizontalSizeClass == .compact
    }

    var body: some View {
        NavigationStack {
            ZStack {
                MochiDemoTheme.canvas
                    .ignoresSafeArea()

                ScrollView {
                    VStack(alignment: .leading, spacing: 28) {
                        directionSection
                        workspaceSection
                        detailOverlaySection
                        settingsSection
                        componentsSection
                    }
                    .padding(.horizontal, isCompact ? 16 : 28)
                    .padding(.top, 14)
                    .padding(.bottom, 120)
                }
            }
            .navigationTitle("Demo")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    MochiModeSelector(selection: $glassMode)
                }
            }
            .overlay {
                DemoLinkedOverlayStack(stack: $overlayStack)
            }
        }
    }

    private var directionSection: some View {
        DemoSection("Style Direction") {
            MochiPanel {
                VStack(alignment: .leading, spacing: 18) {
                    HStack(alignment: .top, spacing: 14) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Mochi-like, not Morandi")
                                .font(.system(size: 28, weight: .semibold, design: .default))
                                .foregroundStyle(MochiDemoTheme.primary)

                            Text("差異不在於更柔和，而在於更中性、更克制。主畫面是白卡和灰階，色彩只留給 highlight 與 tier。")
                                .font(.system(size: 17, weight: .regular, design: .default))
                                .foregroundStyle(MochiDemoTheme.secondary)
                                .lineSpacing(4)
                        }

                        Spacer(minLength: 0)

                        VStack(alignment: .trailing, spacing: 8) {
                            MochiMetaChip("paper cards")
                            MochiMetaChip("neutral chrome")
                            MochiMetaChip("quiet accents")
                        }
                    }

                    VStack(spacing: 10) {
                        DemoRuleRow(title: "Canvas", detail: "暖灰背景，不帶藍、棕、霧玫瑰語氣。")
                        DemoRuleRow(title: "Cards", detail: "白卡 + 細邊 + 輕陰影，圓角偏小。")
                        DemoRuleRow(title: "Type", detail: "詞頭等寬，例句斜體，UI 字級小而穩定。")
                        DemoRuleRow(title: "Glass", detail: "只保留在 selector / toolbar / 小控制元件。")
                    }
                }
            }
        }
    }

    private var workspaceSection: some View {
        DemoSection("Library Workspace") {
            MochiStage {
                VStack(alignment: .leading, spacing: 18) {
                    workspaceTopBar
                    workspaceFilterBar

                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: isCompact ? 160 : 188, maximum: 228), spacing: 16)],
                        spacing: 16
                    ) {
                        MochiCreateCard()

                        ForEach(libraryCards) { card in
                            MochiGridCard(card: card)
                        }
                    }
                }
            }
        }
    }

    private var workspaceTopBar: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) {
                HStack(spacing: 10) {
                    MochiToolbarIcon(systemName: "chevron.left")
                    MochiToolbarIcon(systemName: "chevron.right")

                    HStack(spacing: 8) {
                        Image(systemName: "square.fill")
                            .font(.system(size: 9))
                        Text("Knowledge")
                            .font(MochiDemoTheme.uiLabel)
                    }
                    .foregroundStyle(MochiDemoTheme.primary)
                }

                Spacer()

                HStack(spacing: 10) {
                    MochiToolbarAction(title: "Share", systemName: "square.and.arrow.up", glassMode: glassMode)
                    MochiReviewPill(count: 47, glassMode: glassMode)
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 10) {
                    MochiToolbarIcon(systemName: "chevron.left")
                    MochiToolbarIcon(systemName: "chevron.right")
                    Text("Knowledge")
                        .font(MochiDemoTheme.uiLabel)
                        .foregroundStyle(MochiDemoTheme.primary)
                }

                HStack(spacing: 10) {
                    MochiToolbarAction(title: "Share", systemName: "square.and.arrow.up", glassMode: glassMode)
                    Spacer()
                    MochiReviewPill(count: 47, glassMode: glassMode)
                }
            }
        }
    }

    private var workspaceFilterBar: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "square.grid.2x2")
                    Text("Grid View")
                        .font(MochiDemoTheme.sectionControl)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 11, weight: .semibold))
                }
                .foregroundStyle(MochiDemoTheme.primary)

                Spacer()

                MochiSearchStub()

                HStack(spacing: 10) {
                    MochiToolbarAction(title: "Filters", systemName: "slider.horizontal.3", glassMode: glassMode, compact: true)
                    MochiToolbarAction(title: "Search", systemName: "magnifyingglass", glassMode: glassMode, compact: true)
                    MochiToolbarAction(title: "New Card", systemName: "plus", glassMode: glassMode, compact: true)
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "square.grid.2x2")
                    Text("Grid View")
                        .font(MochiDemoTheme.sectionControl)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 11, weight: .semibold))
                }
                .foregroundStyle(MochiDemoTheme.primary)

                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        MochiToolbarAction(title: "Filters", systemName: "slider.horizontal.3", glassMode: glassMode, compact: true)
                        MochiToolbarAction(title: "Search", systemName: "magnifyingglass", glassMode: glassMode, compact: true)
                        MochiToolbarAction(title: "New Card", systemName: "plus", glassMode: glassMode, compact: true)
                    }
                }
            }
        }
    }

    private var detailOverlaySection: some View {
        DemoSection("Detail Overlay") {
            VStack(alignment: .leading, spacing: 14) {
                MochiStage(fill: MochiDemoTheme.canvas.opacity(0.72), borderOpacity: 0.03) {
                    ZStack {
                        MochiBackdropGrid(cards: Array(libraryCards.prefix(4)))
                            .opacity(0.42)

                        MochiDetailModal(card: rootCard) { target in
                            overlayStack.append(target)
                        }
                        .padding(isCompact ? 10 : 26)
                    }
                }

                HStack(spacing: 10) {
                    Button("開啟 linked overlay") {
                        overlayStack = [rootCard]
                    }
                    .buttonStyle(.ghost(MochiDemoTheme.link))

                    Button("連開兩層") {
                        overlayStack = [rootCard]
                        if let nested = rootCard.links.first?.target {
                            overlayStack.append(nested)
                        }
                    }
                    .buttonStyle(.ghost(.secondary))
                }
            }
        }
    }

    private var settingsSection: some View {
        DemoSection("Settings Sheet") {
            MochiStage(fill: MochiDemoTheme.canvas.opacity(0.72), borderOpacity: 0.03) {
                ZStack {
                    MochiBackdropGrid(cards: Array(libraryCards.prefix(3)))
                        .opacity(0.28)

                    MochiSettingsSheet()
                        .padding(isCompact ? 10 : 32)
                }
            }
        }
    }

    private var componentsSection: some View {
        DemoSection("Components") {
            VStack(spacing: 14) {
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 14) {
                        componentChromeCard
                        componentLinksCard
                    }

                    VStack(spacing: 14) {
                        componentChromeCard
                        componentLinksCard
                    }
                }
            }
        }
    }

    private var componentChromeCard: some View {
        MochiPanel {
            VStack(alignment: .leading, spacing: 16) {
                Text("Micro Chrome")
                    .font(MochiDemoTheme.blockTitle)
                    .foregroundStyle(MochiDemoTheme.primary)

                MochiSearchStub(fullWidth: true)

                HStack(spacing: 10) {
                    MochiToneChip(text: "core", tone: MochiDemoTheme.core)
                    MochiToneChip(text: "intermediate", tone: MochiDemoTheme.intermediate)
                    MochiToneChip(text: "rare", tone: MochiDemoTheme.rare)
                }

                HStack(spacing: 10) {
                    Button("Forgot") { }
                        .buttonStyle(.ghost(MochiDemoTheme.rare))
                    Button("Remembered") { }
                        .buttonStyle(.ghost(MochiDemoTheme.primary))
                }
            }
        }
    }

    private var componentLinksCard: some View {
        MochiPanel {
            VStack(alignment: .leading, spacing: 16) {
                Text("Link Strip")
                    .font(MochiDemoTheme.blockTitle)
                    .foregroundStyle(MochiDemoTheme.primary)

                MochiLinkStrip(card: rootCard) { target in
                    overlayStack.append(target)
                }
            }
        }
    }
}

private enum MochiDemoTheme {
    static let canvas = Color(red: 0.953, green: 0.952, blue: 0.946)
    static let panel = Color(red: 0.976, green: 0.975, blue: 0.970)
    static let card = Color(red: 0.993, green: 0.992, blue: 0.989)
    static let chrome = Color.white.opacity(0.70)
    static let chromeActive = Color.white.opacity(0.92)
    static let border = Color.black.opacity(0.055)
    static let borderSoft = Color.black.opacity(0.035)
    static let shadow = Color.black.opacity(0.045)
    static let primary = Color(red: 0.14, green: 0.14, blue: 0.14)
    static let secondary = Color(red: 0.50, green: 0.50, blue: 0.50)
    static let tertiary = Color(red: 0.70, green: 0.70, blue: 0.70)
    static let mutedFill = Color.black.opacity(0.035)
    static let highlight = Color(red: 0.92, green: 0.84, blue: 0.47)
    static let core = Color(red: 0.43, green: 0.67, blue: 0.42)
    static let intermediate = Color(red: 0.72, green: 0.63, blue: 0.36)
    static let advanced = Color(red: 0.84, green: 0.54, blue: 0.28)
    static let rare = Color(red: 0.86, green: 0.41, blue: 0.38)
    static let link = Color(red: 0.44, green: 0.55, blue: 0.72)

    static let sectionLabel = Font.system(size: 13, weight: .semibold, design: .default)
    static let uiLabel = Font.system(size: 14, weight: .medium, design: .default)
    static let sectionControl = Font.system(size: 15, weight: .semibold, design: .default)
    static let blockTitle = Font.system(size: 20, weight: .semibold, design: .default)
    static let wordHeader = Font.system(size: 30, weight: .semibold, design: .monospaced)
    static let cardWord = Font.system(size: 19, weight: .semibold, design: .monospaced)
    static let cardExample = Font.system(size: 18, weight: .regular, design: .default)
    static let detailExample = Font.system(size: 21, weight: .regular, design: .default)

    static let stageRadius: CGFloat = 18
    static let panelRadius: CGFloat = 16
    static let cardRadius: CGFloat = 15
    static let overlayRadius: CGFloat = 16
    static let controlRadius: CGFloat = 12
    static let chipRadius: CGFloat = 10
    static let tinyRadius: CGFloat = 8
}

private struct DemoSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title.uppercased())
                .font(MochiDemoTheme.sectionLabel)
                .foregroundStyle(MochiDemoTheme.tertiary)
                .tracking(2.2)

            content
        }
    }
}

private struct DemoRuleRow: View {
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            Text(title)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(MochiDemoTheme.primary)
                .frame(width: 68, alignment: .leading)

            Text(detail)
                .font(.system(size: 15, weight: .regular))
                .foregroundStyle(MochiDemoTheme.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct MochiPanel<Content: View>: View {
    @ViewBuilder let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(22)
            .background(MochiDemoTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.panelRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: MochiDemoTheme.panelRadius, style: .continuous)
                    .stroke(MochiDemoTheme.borderSoft, lineWidth: 1)
            )
            .shadow(color: MochiDemoTheme.shadow, radius: 10, y: 4)
    }
}

private struct MochiStage<Content: View>: View {
    let fill: Color
    let borderOpacity: Double
    @ViewBuilder let content: Content

    init(
        fill: Color = MochiDemoTheme.panel,
        borderOpacity: Double = 0.05,
        @ViewBuilder content: () -> Content
    ) {
        self.fill = fill
        self.borderOpacity = borderOpacity
        self.content = content()
    }

    var body: some View {
        content
            .padding(18)
            .background(fill)
            .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.stageRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: MochiDemoTheme.stageRadius, style: .continuous)
                    .stroke(Color.black.opacity(borderOpacity), lineWidth: 1)
            )
            .shadow(color: MochiDemoTheme.shadow.opacity(0.7), radius: 16, y: 5)
    }
}

private struct MochiModeSelector: View {
    @Binding var selection: DemoGlassMode

    var body: some View {
        HStack(spacing: 4) {
            selectorButton(.paper, title: "Paper")
            selectorButton(.selective, title: "Glass")
        }
        .padding(4)
        .background(selectorBackground)
        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius + 6, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius + 6, style: .continuous)
                .stroke(MochiDemoTheme.borderSoft, lineWidth: 1)
        )
        .shadow(color: MochiDemoTheme.shadow, radius: 10, y: 4)
    }

    private func selectorButton(_ mode: DemoGlassMode, title: String) -> some View {
        Button(title) {
            withAnimation(.easeOut(duration: 0.18)) {
                selection = mode
            }
        }
        .buttonStyle(.plain)
        .font(.system(size: 16, weight: .semibold))
        .foregroundStyle(selection == mode ? MochiDemoTheme.primary : MochiDemoTheme.secondary)
        .padding(.horizontal, 22)
        .padding(.vertical, 14)
        .background(
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous)
                .fill(selection == mode ? MochiDemoTheme.chromeActive : Color.clear)
        )
        .contentShape(RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous))
    }

    @ViewBuilder
    private var selectorBackground: some View {
        if selection == .selective {
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius + 6, style: .continuous)
                .fill(Color.white.opacity(0.42))
                .compatibleGlass(
                    in: RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius + 6, style: .continuous),
                    interactive: true
                )
        } else {
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius + 6, style: .continuous)
                .fill(MochiDemoTheme.chrome)
        }
    }
}

private struct MochiMetaChip: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.system(size: 12, weight: .semibold, design: .default))
            .foregroundStyle(MochiDemoTheme.secondary)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(MochiDemoTheme.mutedFill)
            .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.chipRadius, style: .continuous))
    }
}

private struct MochiToolbarIcon: View {
    let systemName: String

    var body: some View {
        Image(systemName: systemName)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(MochiDemoTheme.secondary)
            .frame(width: 28, height: 28)
    }
}

private struct MochiToolbarAction: View {
    let title: String
    let systemName: String
    let glassMode: DemoGlassMode
    var compact: Bool = false

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: systemName)
                .font(.system(size: 12, weight: .semibold))
            Text(title)
                .font(.system(size: compact ? 13 : 14, weight: .medium))
                .lineLimit(1)
        }
        .foregroundStyle(MochiDemoTheme.secondary)
        .padding(.horizontal, compact ? 11 : 13)
        .padding(.vertical, compact ? 8 : 9)
        .background(background)
        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous)
                .stroke(MochiDemoTheme.borderSoft, lineWidth: 1)
        )
    }

    @ViewBuilder
    private var background: some View {
        if glassMode == .selective {
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous)
                .fill(Color.white.opacity(0.36))
                .compatibleGlass(
                    in: RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous),
                    interactive: true
                )
        } else {
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous)
                .fill(MochiDemoTheme.chromeActive)
        }
    }
}

private struct MochiReviewPill: View {
    let count: Int
    let glassMode: DemoGlassMode

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "tray.full")
                .font(.system(size: 12, weight: .semibold))
            Text("Review")
                .font(.system(size: 15, weight: .semibold))
            Text("\(count)")
                .font(.system(size: 13, weight: .semibold, design: .monospaced))
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(Color.black.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.tinyRadius, style: .continuous))
            Image(systemName: "chevron.down")
                .font(.system(size: 11, weight: .semibold))
        }
        .foregroundStyle(MochiDemoTheme.primary)
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(background)
        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous))
    }

    @ViewBuilder
    private var background: some View {
        if glassMode == .selective {
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous)
                .fill(Color.white.opacity(0.32))
                .compatibleGlass(
                    in: RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous),
                    interactive: true
                )
        } else {
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous)
                .fill(Color.black.opacity(0.84))
        }
    }
}

private struct MochiSearchStub: View {
    var fullWidth: Bool = false

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(MochiDemoTheme.tertiary)
            Text("Search")
                .font(.system(size: 14, weight: .regular))
                .foregroundStyle(MochiDemoTheme.tertiary)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: fullWidth ? .infinity : 132, minHeight: 38)
        .padding(.horizontal, 12)
        .background(MochiDemoTheme.chromeActive)
        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous)
                .stroke(MochiDemoTheme.borderSoft, lineWidth: 1)
        )
    }
}

private struct MochiCreateCard: View {
    var body: some View {
        RoundedRectangle(cornerRadius: MochiDemoTheme.cardRadius, style: .continuous)
            .fill(Color.clear)
            .frame(minHeight: 300)
            .overlay(
                RoundedRectangle(cornerRadius: MochiDemoTheme.cardRadius, style: .continuous)
                    .strokeBorder(
                        style: StrokeStyle(lineWidth: 1, dash: [5, 4])
                    )
                    .foregroundStyle(MochiDemoTheme.border)
            )
            .overlay {
                HStack(spacing: 10) {
                    Image(systemName: "plus")
                    Text("New Card")
                        .font(.system(size: 15, weight: .medium))
                    Text("N")
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        .foregroundStyle(MochiDemoTheme.tertiary)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(MochiDemoTheme.mutedFill)
                        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.tinyRadius, style: .continuous))
                }
                .foregroundStyle(MochiDemoTheme.tertiary)
            }
    }
}

private struct MochiGridCard: View {
    let card: DemoCard

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(card.word)
                        .font(MochiDemoTheme.cardWord)
                        .foregroundStyle(MochiDemoTheme.primary)
                        .lineLimit(1)

                    Text(card.partOfSpeech)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(MochiDemoTheme.secondary)

                    Spacer(minLength: 0)
                }

                Text(card.tierLabel)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(card.tierColor)
                    .lineLimit(1)

                CardRichTextRenderer.text(
                    card.example,
                    style: CardRichTextStyle(
                        font: MochiDemoTheme.cardExample,
                        textColor: MochiDemoTheme.secondary,
                        highlightColor: MochiDemoTheme.highlight,
                        italic: true,
                        underlineHighlights: false,
                        useBackgroundMark: true,
                        highlightWeight: .medium
                    ),
                    truncateAroundMarkedWordRadius: 5
                )
                .lineSpacing(4)
                .frame(maxHeight: 142, alignment: .topLeading)

                HStack {
                    Spacer()
                    Text("SHOW MORE")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(MochiDemoTheme.primary)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(MochiDemoTheme.mutedFill)
                        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous))
                }
                .padding(.top, 4)
            }
            .padding(.horizontal, 18)
            .padding(.top, 18)
            .padding(.bottom, 14)
            .frame(maxWidth: .infinity, minHeight: 252, alignment: .topLeading)

            Divider()
                .overlay(MochiDemoTheme.borderSoft)

            VStack(alignment: .leading, spacing: 8) {
                Text("+ 1 HIDDEN SIDE")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(MochiDemoTheme.tertiary)

                HStack(spacing: 10) {
                    HStack(spacing: 6) {
                        Circle()
                            .stroke(MochiDemoTheme.border, lineWidth: 1)
                            .frame(width: 14, height: 14)
                        Text("NEW")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(MochiDemoTheme.tertiary)
                    }

                    MochiToneChip(text: "#\(card.tierLabel)", tone: card.tierColor)
                    Spacer()
                }
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 14)
        }
        .background(MochiDemoTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.cardRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: MochiDemoTheme.cardRadius, style: .continuous)
                .stroke(MochiDemoTheme.borderSoft, lineWidth: 1)
        )
        .shadow(color: MochiDemoTheme.shadow.opacity(0.85), radius: 9, y: 4)
    }
}

private struct MochiBackdropGrid: View {
    let cards: [DemoCard]

    var body: some View {
        VStack(spacing: 16) {
            ForEach(cards) { card in
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 8) {
                        Text(card.word)
                            .font(.system(size: 18, weight: .semibold, design: .monospaced))
                        Text(card.partOfSpeech)
                            .font(.system(size: 14, weight: .medium))
                    }
                    .foregroundStyle(MochiDemoTheme.secondary)

                    CardRichTextRenderer.text(
                        card.example,
                        style: CardRichTextStyle(
                            font: .system(size: 16, weight: .regular),
                            textColor: MochiDemoTheme.tertiary,
                            highlightColor: MochiDemoTheme.highlight.opacity(0.75),
                            italic: true,
                            underlineHighlights: false,
                            useBackgroundMark: true,
                            highlightWeight: .medium
                        ),
                        truncateAroundMarkedWordRadius: 4
                    )
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.white.opacity(0.72))
                .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.cardRadius, style: .continuous))
            }
        }
    }
}

private struct MochiDetailModal: View {
    let card: DemoCard
    let onOpenLink: (DemoCard) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Spacer()
                HStack(spacing: 8) {
                    Image(systemName: "cube")
                        .font(.system(size: 11, weight: .medium))
                    Text("KG Vocab v3")
                        .font(.system(size: 13, weight: .medium))
                }
                .foregroundStyle(MochiDemoTheme.tertiary)
                Spacer()

                Image(systemName: "ellipsis")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(MochiDemoTheme.secondary)
            }
            .padding(.horizontal, 22)
            .padding(.top, 20)

            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(card.word)
                        .font(MochiDemoTheme.wordHeader)
                        .foregroundStyle(MochiDemoTheme.primary)

                    Text(card.partOfSpeech)
                        .font(.system(size: 17, weight: .medium))
                        .foregroundStyle(MochiDemoTheme.secondary)

                    Text(card.tierLabel)
                        .font(.system(size: 12, weight: .medium, design: .monospaced))
                        .foregroundStyle(card.tierColor)
                }

                CardRichTextRenderer.text(
                    card.example,
                    style: CardRichTextStyle(
                        font: MochiDemoTheme.detailExample,
                        textColor: MochiDemoTheme.secondary,
                        highlightColor: MochiDemoTheme.highlight,
                        italic: true,
                        underlineHighlights: false,
                        useBackgroundMark: true,
                        highlightWeight: .medium
                    ),
                    truncateAroundMarkedWordRadius: 6
                )
                .lineSpacing(5)
            }
            .padding(.horizontal, 26)
            .padding(.top, 24)
            .padding(.bottom, 28)

            Divider()
                .overlay(MochiDemoTheme.borderSoft)

            VStack(alignment: .leading, spacing: 18) {
                Text(card.translation)
                    .font(.system(size: 25, weight: .semibold))
                    .foregroundStyle(MochiDemoTheme.primary)

                Text(card.note)
                    .font(.system(size: 17, weight: .regular))
                    .foregroundStyle(MochiDemoTheme.secondary)
                    .lineSpacing(5)

                MochiLinkStrip(card: card, onTap: onOpenLink)
            }
            .padding(26)

            Divider()
                .overlay(MochiDemoTheme.borderSoft)

            HStack(spacing: 10) {
                HStack(spacing: 8) {
                    Image(systemName: "books.vertical")
                    Text("Knowledge")
                        .font(.system(size: 14, weight: .medium))
                }
                .foregroundStyle(MochiDemoTheme.secondary)

                Spacer()

                HStack(spacing: 8) {
                    Image(systemName: "at")
                    Text("1 Reference")
                }
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(MochiDemoTheme.secondary)
            }
            .padding(.horizontal, 26)
            .padding(.vertical, 16)
        }
        .frame(maxWidth: 960)
        .background(MochiDemoTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.overlayRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: MochiDemoTheme.overlayRadius, style: .continuous)
                .stroke(MochiDemoTheme.border, lineWidth: 1)
        )
        .shadow(color: MochiDemoTheme.shadow, radius: 20, y: 10)
    }
}

private struct MochiSettingsSheet: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private var isCompact: Bool {
        horizontalSizeClass == .compact
    }

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 0) {
                sidebar
                    .frame(width: 182)

                Divider()
                    .overlay(MochiDemoTheme.borderSoft)

                settingsBody
                    .frame(width: 430, alignment: .leading)
            }
            .frame(maxWidth: 760, alignment: .topLeading)

            VStack(spacing: 0) {
                compactSidebar
                Divider()
                    .overlay(MochiDemoTheme.borderSoft)
                settingsBody
            }
            .frame(maxWidth: 520, alignment: .leading)
        }
        .background(MochiDemoTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.overlayRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: MochiDemoTheme.overlayRadius, style: .continuous)
                .stroke(MochiDemoTheme.border, lineWidth: 1)
        )
        .shadow(color: MochiDemoTheme.shadow, radius: 20, y: 10)
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("PREFERENCES")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(MochiDemoTheme.tertiary)
                .tracking(1.3)

            VStack(alignment: .leading, spacing: 6) {
                sidebarRow("Appearance", selected: true)
                sidebarRow("Cards")
                sidebarRow("Editing")
                sidebarRow("Decks")
                sidebarRow("Attachments")
                sidebarRow("Notifications")
            }

            Spacer(minLength: 0)
        }
        .padding(18)
        .background(MochiDemoTheme.panel.opacity(0.92))
    }

    private var compactSidebar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                sidebarChip("Appearance", selected: true)
                sidebarChip("Cards")
                sidebarChip("Editing")
                sidebarChip("Decks")
                sidebarChip("Attachments")
            }
            .padding(14)
        }
        .background(MochiDemoTheme.panel.opacity(0.92))
    }

    private var settingsBody: some View {
        VStack(alignment: .leading, spacing: 22) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Base theme")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(MochiDemoTheme.primary)
                settingsFieldStub(label: "System")
            }

            settingsDivider

            VStack(alignment: .leading, spacing: 10) {
                Text("Font size")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(MochiDemoTheme.primary)

                HStack(spacing: 12) {
                    settingsValuePill("18")
                    sliderStub
                }
            }

            settingsDivider

            VStack(alignment: .leading, spacing: 10) {
                Text("Font style")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(MochiDemoTheme.primary)

                HStack(spacing: 10) {
                    styleBox("Sans")
                    styleBox("Serif")
                    styleBox("Mono", selected: true)
                }
            }

            settingsDivider

            VStack(alignment: .leading, spacing: 10) {
                Text("Card width")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(MochiDemoTheme.primary)

                HStack(spacing: 12) {
                    settingsFieldStub(label: "View: Default")
                        .frame(width: 150)
                    sliderStub
                }
            }
        }
        .padding(22)
    }

    private var sliderStub: some View {
        ZStack(alignment: .leading) {
            Capsule()
                .fill(MochiDemoTheme.mutedFill)
                .frame(height: 4)

            Capsule()
                .fill(MochiDemoTheme.border)
                .frame(width: 90, height: 4)

            Circle()
                .fill(Color.white)
                .frame(width: 14, height: 14)
                .overlay(Circle().stroke(MochiDemoTheme.border, lineWidth: 1))
                .offset(x: 82)
        }
        .frame(maxWidth: .infinity)
    }

    private var settingsDivider: some View {
        Rectangle()
            .fill(MochiDemoTheme.borderSoft)
            .frame(height: 1)
    }

    private func sidebarRow(_ title: String, selected: Bool = false) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "circle.grid.2x1")
                .font(.system(size: 11, weight: .medium))
            Text(title)
                .font(.system(size: 14, weight: selected ? .semibold : .medium))
        }
        .foregroundStyle(selected ? MochiDemoTheme.primary : MochiDemoTheme.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(selected ? MochiDemoTheme.mutedFill : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.tinyRadius, style: .continuous))
    }

    private func sidebarChip(_ title: String, selected: Bool = false) -> some View {
        Text(title)
            .font(.system(size: 13, weight: selected ? .semibold : .medium))
            .foregroundStyle(selected ? MochiDemoTheme.primary : MochiDemoTheme.secondary)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(selected ? MochiDemoTheme.mutedFill : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.tinyRadius, style: .continuous))
    }

    private func settingsFieldStub(label: String) -> some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(MochiDemoTheme.secondary)
            Spacer(minLength: 0)
            Image(systemName: "chevron.down")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(MochiDemoTheme.tertiary)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(MochiDemoTheme.panel)
        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.tinyRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: MochiDemoTheme.tinyRadius, style: .continuous)
                .stroke(MochiDemoTheme.borderSoft, lineWidth: 1)
        )
    }

    private func settingsValuePill(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 14, weight: .medium))
            .foregroundStyle(MochiDemoTheme.secondary)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(MochiDemoTheme.panel)
            .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.tinyRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: MochiDemoTheme.tinyRadius, style: .continuous)
                    .stroke(MochiDemoTheme.borderSoft, lineWidth: 1)
            )
    }

    private func styleBox(_ title: String, selected: Bool = false) -> some View {
        VStack(spacing: 6) {
            Text("Aa")
                .font(.system(size: 24, weight: .medium, design: title == "Mono" ? .monospaced : .default))
                .foregroundStyle(MochiDemoTheme.primary)
            Text(title)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(MochiDemoTheme.secondary)
        }
        .frame(width: 72, height: 70)
        .background(selected ? Color(red: 0.90, green: 0.95, blue: 0.98) : MochiDemoTheme.panel)
        .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous)
                .stroke(selected ? Color(red: 0.63, green: 0.76, blue: 0.86) : MochiDemoTheme.borderSoft, lineWidth: 1)
        )
    }
}

private struct MochiToneChip: View {
    let text: String
    let tone: Color

    var body: some View {
        Text(text)
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(tone)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(tone.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.chipRadius, style: .continuous))
    }
}

private struct MochiLinkStrip: View {
    let card: DemoCard
    let onTap: (DemoCard) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(card.linkGroups) { group in
                HStack(spacing: 10) {
                    Image(systemName: "paperclip")
                        .font(.system(size: 16, weight: .medium))
                        .foregroundStyle(MochiDemoTheme.secondary)

                    Text(group.label)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(MochiDemoTheme.secondary)

                    if let first = group.items.first {
                        Button(first.word) {
                            onTap(first.target)
                        }
                        .buttonStyle(.plain)
                        .font(.system(size: 18, weight: .semibold, design: .monospaced))
                        .foregroundStyle(MochiDemoTheme.primary)
                    }

                    Spacer()
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 13)
                .background(MochiDemoTheme.mutedFill)
                .clipShape(RoundedRectangle(cornerRadius: MochiDemoTheme.controlRadius, style: .continuous))
            }
        }
    }
}

private struct DemoLinkedOverlayStack: View {
    @Binding var stack: [DemoCard]

    var body: some View {
        if !stack.isEmpty {
            ZStack {
                Color.black.opacity(0.16)
                    .ignoresSafeArea()
                    .onTapGesture {
                        stack.removeLast()
                    }

                ForEach(Array(stack.enumerated()), id: \.element.id) { index, card in
                    VStack(spacing: 14) {
                        HStack {
                            Spacer()

                            Button {
                                stack.removeLast()
                            } label: {
                                Image(systemName: "xmark")
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(MochiDemoTheme.secondary)
                                    .padding(10)
                                    .background(MochiDemoTheme.chromeActive)
                                    .clipShape(Circle())
                            }
                            .buttonStyle(.plain)
                        }

                        MochiDetailModal(card: card) { target in
                            stack.append(target)
                        }
                    }
                    .frame(maxWidth: 980, maxHeight: .infinity, alignment: .top)
                    .padding(.horizontal, 18 + CGFloat(index) * 10)
                    .padding(.top, 58 + CGFloat(index) * 18)
                    .padding(.bottom, 28)
                    .allowsHitTesting(index == stack.count - 1)
                }
            }
            .transition(.opacity)
        }
    }
}

private enum DemoGlassMode: String, CaseIterable, Identifiable {
    case paper
    case selective

    var id: String { rawValue }
}

private struct DemoLink: Identifiable {
    let id = UUID()
    let word: String
    let target: DemoCard
}

private struct DemoLinkGroup: Identifiable {
    let id = UUID()
    let label: String
    let items: [DemoLink]
}

private struct DemoCard: Identifiable {
    let id = UUID()
    let word: String
    let partOfSpeech: String
    let tier: String
    let translation: String
    let example: String
    let note: String
    let linkGroups: [DemoLinkGroup]

    var links: [DemoLink] {
        linkGroups.flatMap(\.items)
    }

    var tierLabel: String { tier }

    var tierColor: Color {
        switch tier {
        case "core":
            return MochiDemoTheme.core
        case "intermediate":
            return MochiDemoTheme.intermediate
        case "advanced":
            return MochiDemoTheme.advanced
        case "rare":
            return MochiDemoTheme.rare
        default:
            return MochiDemoTheme.secondary
        }
    }
}

private extension DemoCard {
    static let rootDetail: DemoCard = {
        let snarls = DemoCard(
            word: "snarls",
            partOfSpeech: "v.",
            tier: "advanced",
            translation: "咆哮、怒聲回應",
            example: "...he **snarls** under his breath when challenged...",
            note: "比 growl 更尖銳、更帶攻擊性，常用於人或野獸帶怒氣的短促出聲。",
            linkGroups: []
        )

        let rile = DemoCard(
            word: "rile",
            partOfSpeech: "v.",
            tier: "intermediate",
            translation: "激怒、惹毛",
            example: "...the taunt began to **rile** him more than he expected...",
            note: "通常指把人情緒撩起來、弄得火大，比 anger 更口語，也更輕快。",
            linkGroups: []
        )

        return DemoCard(
            word: "unravel",
            partOfSpeech: "v.",
            tier: "intermediate",
            translation: "解開",
            example: "...knot within him, started to **unravel** and he began to feel...",
            note: "解開，闡明。常用於解開謎團、複雜情況或情緒。例：unravel a mystery、unravel the truth。與 untangle 相似，但 unravel 更偏重於理解或梳理。",
            linkGroups: [
                DemoLinkGroup(label: "對比：", items: [DemoLink(word: "snarls", target: snarls)]),
                DemoLinkGroup(label: "易混：", items: [DemoLink(word: "rile", target: rile)])
            ]
        )
    }()

    static let sampleLibrary: [DemoCard] = [
        rootDetail,
        DemoCard(
            word: "audacity",
            partOfSpeech: "n.",
            tier: "intermediate",
            translation: "厚顏、大膽",
            example: "...barely dared consider for its **audacity**.",
            note: "可指勇氣，也常帶冒犯意味的膽大妄為；語氣比 courage 更尖銳。",
            linkGroups: []
        ),
        DemoCard(
            word: "eons",
            partOfSpeech: "n.",
            tier: "advanced",
            translation: "極漫長時間",
            example: "...many treasures. A couple of **eons** ago I found a book...",
            note: "既可指地質年代，也可作誇飾語氣表示非常久。",
            linkGroups: []
        ),
        DemoCard(
            word: "scrawl",
            partOfSpeech: "n.",
            tier: "rare",
            translation: "潦草字跡",
            example: "...the **scrawl** on the page read.",
            note: "多指難辨識、匆忙寫成的字跡，也可作動詞表示潦草書寫。",
            linkGroups: []
        ),
        DemoCard(
            word: "frippery",
            partOfSpeech: "n.",
            tier: "rare",
            translation: "華而不實的裝飾",
            example: "...he was wearing some ridiculous **frippery** on his head...",
            note: "帶貶義，指浮誇裝飾、矯揉造作的配件或表面玩意。",
            linkGroups: []
        ),
        DemoCard(
            word: "tapped her foot",
            partOfSpeech: "phr.",
            tier: "core",
            translation: "不耐地跺腳",
            example: "...would little Vivenna **tapped her foot** as she stood beside...",
            note: "常見肢體動作，表示等待、焦躁或不耐煩。",
            linkGroups: []
        ),
        DemoCard(
            word: "croaked",
            partOfSpeech: "v.",
            tier: "rare",
            translation: "沙啞地說",
            example: "...tips of his fingers. Shezler **croaked** a final attempt at breath...",
            note: "也可指青蛙叫聲；作人聲時多帶乾啞、虛弱感。",
            linkGroups: []
        )
    ]
}

#Preview {
    StyleDemoView()
        .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
}
