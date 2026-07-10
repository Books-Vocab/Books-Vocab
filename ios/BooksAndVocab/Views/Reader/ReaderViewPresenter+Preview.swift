#if os(iOS)
import SwiftUI

/// Page-content mode for `ReaderChromePreviewScene`.
///
/// - `.skeleton`: synthetic block placeholders (default). Used by the UI-QA
///   Catalog scenarios that focus on chrome states — the live reader body is a
///   WKWebView and never appears in `layer.render(in:)` snapshots.
/// - `.prose`: native SwiftUI book prose with vocab-highlight bands. Used by the
///   marketing capture pipeline (`ops/capture_profiles/website.json`) so the App
///   Store / website reader shot shows real book text instead of a skeleton.
enum ReaderPreviewPageContent: Equatable {
    case skeleton
    case prose
}

struct ReaderChromePreviewScene: View {
    let state: ReaderViewPresenterState
    let showsErrorCard: Bool
    var pageContent: ReaderPreviewPageContent = .skeleton

    var body: some View {
        ReaderViewPresenter(
            state: state,
            onDismiss: {},
            onShowTableOfContents: {},
            onShowReaderSettings: {},
            onShowNotebookPicker: {},
            onExpandHeader: {},
            onCollapseHeader: {}
        ) {
            ZStack {
                if showsErrorCard {
                    errorPreviewContent
                } else {
                    readingPreviewContent
                }
            }
            .ignoresSafeArea()
        } translationPanel: {
            TranslationPanel(
                word: "resilient",
                result: TranslationResult(
                    translation: "有韌性的；能快速恢復的",
                    partOfSpeech: "adj.",
                    explanation: nil
                ),
                isLoading: false,
                isSaved: true,
                isLoggedIn: true,
                isExpanded: true,
                explanation: "在這段語境中指角色面對壓力後仍能迅速回到穩定狀態。",
                isLoadingExplanation: false,
                statusMessage: nil,
                isExplanationOnly: false,
                translationErrorMessage: nil,
                explanationErrorMessage: nil,
                onExpand: {},
                onDelete: {},
                onShowDetail: nil,
                onDismiss: {},
                isPanelLarge: false,
                onToggleHeight: {}
            )
        } settingsPanel: {
            EmptyView()
        }
    }

    private var readingPreviewContent: some View {
        ZStack {
            LinearGradient(
                colors: [
                    state.paperColor.opacity(ReaderPresentationMetrics.Preview.paperOpacityTop),
                    state.paperColor.opacity(ReaderPresentationMetrics.Preview.paperOpacityMid),
                    AppColors.warmNeutral.opacity(ReaderPresentationMetrics.Preview.paperOpacityFloor)
                ],
                startPoint: .top,
                endPoint: .bottom
            )

            switch pageContent {
            case .skeleton:
                skeletonPageContent
            case .prose:
                ReaderMarketingProse()
            }
        }
    }

    private var skeletonPageContent: some View {
        VStack(alignment: .leading, spacing: ReaderPresentationMetrics.Preview.blockSpacing) {
            ForEach(0..<8, id: \.self) { index in
                RoundedRectangle(cornerRadius: ReaderPresentationMetrics.Preview.blockCornerRadius, style: .continuous)
                    .fill(Color.primary.opacity(index == 2 ? ReaderPresentationMetrics.Preview.textBlockEmphasisOpacity : ReaderPresentationMetrics.Preview.textBlockBaseOpacity))
                    .frame(height: index.isMultiple(of: 3) ? ReaderPresentationMetrics.Preview.blockHeightTall : ReaderPresentationMetrics.Preview.blockHeightShort)
                    .padding(.trailing, CGFloat(index % 3) * ReaderPresentationMetrics.Preview.trailingStep)
            }
            Spacer()
        }
        .padding(.top, ReaderPresentationMetrics.Preview.topInset)
        .padding(.horizontal, ReaderPresentationMetrics.Preview.horizontalInset)
        .padding(.bottom, ReaderPresentationMetrics.Preview.bottomInset)
    }

    private var errorPreviewContent: some View {
        VStack {
            Spacer(minLength: ReaderPresentationMetrics.Preview.topInset)

            AppEmptyStateCard(
                title: "無法開啟書籍",
                systemImage: "exclamationmark.triangle",
                description: "Reader publication 載入失敗。請確認檔案是否完整，或稍後重新下載。"
            )
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

            Spacer(minLength: ReaderPresentationMetrics.Preview.bottomInset)
        }
        .background(state.paperColor)
    }
}

// MARK: - Marketing prose (real book content for App Store / website shot)

/// One rendered word of the marketing prose, with its highlight emphasis.
struct ProseToken: Equatable {
    enum Emphasis: Equatable {
        case none   // plain body text
        case vocab  // saved-vocab bottom band highlight
        case active // just-tapped word (band + outline), tied to translation overlay
    }

    let text: String
    let emphasis: Emphasis
}

/// Pure tokenizer: splits a paragraph into words and assigns highlight emphasis.
///
/// Punctuation is trimmed only for *matching* (so `"resilient,"` still matches
/// `"resilient"`); the rendered token keeps its original glyphs. Kept as a free
/// function so the highlight-assignment logic is unit-testable without SwiftUI.
enum ReaderProseTokenizer {
    private static let matchTrim = CharacterSet(charactersIn: ",.;:!?\u{201C}\u{201D}\u{2018}\u{2019}\"'")

    static func tokens(
        paragraph: String,
        vocab: Set<String>,
        active: Set<String>
    ) -> [ProseToken] {
        paragraph.split(separator: " ").map { raw in
            let word = String(raw)
            let bare = word.trimmingCharacters(in: matchTrim)
            let emphasis: ProseToken.Emphasis
            if active.contains(bare) {
                emphasis = .active
            } else if vocab.contains(bare) {
                emphasis = .vocab
            } else {
                emphasis = .none
            }
            return ProseToken(text: word, emphasis: emphasis)
        }
    }
}

/// Left-aligned, ragged-right word flow. Mirrors the reader's `text-align: left`
/// wrapping so highlighted words keep their bottom-band highlighter intact
/// (a single wrapping `Text` cannot carry per-word bottom bands).
struct ReaderProseFlowLayout: Layout {
    var spacing: CGFloat
    var lineSpacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var lineHeight: CGFloat = 0
        var widest: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0, x + spacing + size.width > maxWidth {
                widest = max(widest, x)
                y += lineHeight + lineSpacing
                x = 0
                lineHeight = 0
            }
            if x > 0 { x += spacing }
            x += size.width
            lineHeight = max(lineHeight, size.height)
        }
        widest = max(widest, x)
        let resolvedWidth = maxWidth.isFinite ? min(widest, maxWidth) : widest
        return CGSize(width: resolvedWidth, height: y + lineHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var lineHeight: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > bounds.minX, x + spacing + size.width > bounds.maxX {
                y += lineHeight + lineSpacing
                x = bounds.minX
                lineHeight = 0
            }
            if x > bounds.minX { x += spacing }
            subview.place(
                at: CGPoint(x: x, y: y),
                anchor: .topLeading,
                proposal: ProposedViewSize(size)
            )
            x += size.width
            lineHeight = max(lineHeight, size.height)
        }
    }
}

/// Native SwiftUI book prose used only for the marketing capture. Original
/// (non-copyrighted) literary text on the reader's sepia paper, in the reader's
/// default serif (Cormorant Garamond), with saved-vocab highlighter bands.
struct ReaderMarketingProse: View {
    // Reader default body font (ReaderFont.serif → Cormorant Garamond) so the
    // shot matches the shipped reader default. Registered via ios/Info.plist UIAppFonts.
    private static let fontName = "CormorantGaramond-Regular"
    private static let fontSize: CGFloat = 20
    private static let lineSpacing: CGFloat = 8
    private static let wordSpacing: CGFloat = 5
    private static let paragraphSpacing: CGFloat = 20
    private static let topInset: CGFloat = 118
    private static let horizontalInset: CGFloat = 30
    private static let bottomInset: CGFloat = 60

    // Sepia ink — warm dark brown mirroring the Readium sepia theme foreground.
    private static let sepiaInk = Color(red: 0.28, green: 0.22, blue: 0.16)

    // Vocab highlight band — reuses SoT highlight preference values so it matches
    // the live reader / podcast highlighter (paper preset, sepia → light scheme).
    private static let bandColor = VocabHighlightColorPreset.paper
        .swiftUIColor(for: .light)
        .opacity(VocabHighlightPreferences.defaultOpacity)
    private static let bandFraction = CGFloat(VocabHighlightPreferences.defaultBandFraction)
    private static let bandCornerRadius: CGFloat = 3
    private static let bandOverhang: CGFloat = 2

    // Active (just-tapped) word outline — mirrors ReaderContentStyle sepia.activeOutline
    // "1px solid rgba(126, 96, 66, 0.34)" with a 1.5px outline-offset.
    private static let activeOutline = Color(red: 126.0 / 255, green: 96.0 / 255, blue: 66.0 / 255).opacity(0.34)
    private static let activeCornerRadius: CGFloat = 4
    private static let activeOutlineWidth: CGFloat = 1
    private static let activeOutlineInset: CGFloat = 1.5

    // Original literary prose (NOT copyrighted book text). "resilient" is the
    // active word so the page reads as "just tapped 'resilient'" — matching the
    // translation overlay, which translates that exact word.
    private static let paragraphs: [String] = [
        "The road north taught patience to anyone who traveled it alone. Snow settled in the hollows where the wind could not reach, and the quiet there felt so complete that a traveler might mistake it for solitude rather than mere absence.",
        "She had learned, across many winters, to read the land the way others read a face. What looked barren often proved resilient in the end, holding its warmth close against the cold, waiting for a thaw it had every reason to trust would come."
    ]
    private static let vocabWords: Set<String> = ["solitude", "thaw"]
    private static let activeWords: Set<String> = ["resilient"]

    var body: some View {
        VStack(alignment: .leading, spacing: Self.paragraphSpacing) {
            ForEach(Array(Self.paragraphs.enumerated()), id: \.offset) { _, paragraph in
                ReaderProseFlowLayout(spacing: Self.wordSpacing, lineSpacing: Self.lineSpacing) {
                    ForEach(
                        Array(
                            ReaderProseTokenizer.tokens(
                                paragraph: paragraph,
                                vocab: Self.vocabWords,
                                active: Self.activeWords
                            ).enumerated()
                        ),
                        id: \.offset
                    ) { _, token in
                        proseWord(token)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.top, Self.topInset)
        .padding(.horizontal, Self.horizontalInset)
        .padding(.bottom, Self.bottomInset)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    @ViewBuilder
    private func proseWord(_ token: ProseToken) -> some View {
        let base = Text(token.text)
            .font(.custom(Self.fontName, size: Self.fontSize))
            .foregroundStyle(Self.sepiaInk)

        switch token.emphasis {
        case .none:
            base
        case .vocab:
            base.background(alignment: .bottom) { highlightBand }
        case .active:
            base
                .background(alignment: .bottom) { highlightBand }
                .overlay(
                    RoundedRectangle(cornerRadius: Self.activeCornerRadius, style: .continuous)
                        .inset(by: -Self.activeOutlineInset)
                        .stroke(Self.activeOutline, lineWidth: Self.activeOutlineWidth)
                )
        }
    }

    private var highlightBand: some View {
        RoundedRectangle(cornerRadius: Self.bandCornerRadius, style: .continuous)
            .fill(Self.bandColor)
            .frame(height: Self.fontSize * Self.bandFraction)
            .padding(.horizontal, -Self.bandOverhang)
    }
}

#Preview("Reader Chrome / Marketing Content") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepiaDeep,
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .compact, overlay: .translation),
            totalProgression: 0.37,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false,
        pageContent: .prose
    )
}

#Preview("Reader Chrome / Loading") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepiaDeep,
            isWebViewReady: false,
            loadingPhase: "渲染頁面…",
            underlineProgress: 0.42,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0.18,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}

#Preview("Reader Chrome / Loading Vocab") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepia,
            isWebViewReady: false,
            loadingPhase: "標記生字…",
            underlineProgress: 0.68,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0.18,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}

#Preview("Reader Chrome / Compact") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepia,
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0.37,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}

#Preview("Reader Chrome / Expanded") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepia,
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .expanded, overlay: .none),
            totalProgression: 0.37,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}

#Preview("Reader Chrome / Translation") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepiaDeep,
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .compact, overlay: .translation),
            totalProgression: 0.37,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}

#Preview("Reader Chrome / Error") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepiaDeep,
            isWebViewReady: true,
            loadingPhase: "開啟書本…",
            underlineProgress: nil,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: true
    )
}

#Preview("Reader Chrome / Underline Progress") {
    ReaderChromePreviewScene(
        state: .init(
            paperColor: AppColors.paperSepia,
            isWebViewReady: true,
            loadingPhase: "標記生字…",
            underlineProgress: 0.55,
            chrome: .init(header: .compact, overlay: .none),
            totalProgression: 0.22,
            bookTitle: "The Left Hand of Darkness",
        ),
        showsErrorCard: false
    )
}
#endif
