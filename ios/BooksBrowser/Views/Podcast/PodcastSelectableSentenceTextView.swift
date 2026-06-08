#if os(iOS)
import SwiftUI
import UIKit

/// The UNIFIED transcript-sentence renderer (issue ③, 3-A). One `UITextView`
/// instance renders BOTH the normal display state and the long-press selection
/// state — only `isSelectable` (and the long-press recognizer) flips between them.
///
/// ## Why one engine
///
/// The bubble used to render two layout engines: a SwiftUI per-word `Text` flow
/// layout (display) and a TextKit `UITextView` (selecting). Their kerning
/// and line-break points differ, so the long-press swap reflowed the text — the
/// "選取時排版跳版" bug. Driving both states from ONE `UITextView` with a
/// byte-identical `NSAttributedString` means the TextKit layout is identical before
/// and after the swap: zero reflow. The continuous reading underline then resolves
/// its per-word rects from this same TextKit layout (`PodcastTextKitWordRects`)
/// instead of from SwiftUI anchor preferences.
///
/// CRITICAL: the caller must keep this as ONE view instance whose `isSelectable`
/// prop changes — NOT an `if/else` between two instances. An `if/else` makes SwiftUI
/// rebuild the `UITextView` (`makeUIView` again) and reflow on every swap, defeating
/// the whole fix. The underline lives in a SwiftUI `.overlay` ON this representable
/// (so its coordinate space == the text view's, origin top-left), applied BEFORE the
/// bubble padding (★B2) so the resolved rects need no inset compensation.
struct PodcastSelectableSentenceTextView: UIViewRepresentable {
    let text: String
    let font: UIFont
    let textColor: UIColor
    let tintColor: UIColor
    /// Selecting mode → native selection + edit menu (translate/explain). Display
    /// mode → non-selectable; a long-press enters selection on the pressed word and
    /// per-word rects are published for the underline.
    let isSelectable: Bool
    /// Pre-selected range when entering selection (the long-pressed word). nil in
    /// display mode.
    let initialSelectionRange: NSRange?
    /// The sentence's words, in order — `text == words.joined(separator: " ")`. Used
    /// to build the word→range map for rect resolution + long-press word hit-testing.
    let words: [String]
    /// Per-word rects (text-view coordinate space) published after each layout pass,
    /// cache-guarded so it fires once per real layout, never per frame. Display mode.
    var onResolveWordRects: ([Int: CGRect]) -> Void = { _ in }
    /// Display-mode long-press on a word index → enter selection there.
    var onLongPressWord: (Int) -> Void = { _ in }
    /// Single-word translate → word path (`translateQuick` + root-form stem + vocab
    /// dedupe). Phrase translate → `onTranslateSelection` (phrase path). The edit menu
    /// routes by `PodcastSelectionRouting`, mirroring reader's word/phrase split.
    let onWordSelection: (String, String) -> Void
    let onTranslateSelection: (String, String) -> Void
    let onExplainSelection: (String, String) -> Void

    /// M1 fallback escape hatch (issue ③, plan-mandated). The primary path keeps the
    /// display-mode text view INTERACTIVE so its own long-press recognizer can
    /// pre-select the pressed word (tap-seek still falls through to the cell). If
    /// on-device testing shows the display-mode `UITextView` swallowing taps or
    /// contending with the cell gestures, flip this to `false`: the display-mode view
    /// becomes inert (`isUserInteractionEnabled = false`, custom long-press disabled)
    /// and gestures fall entirely to the SwiftUI cell layer. Tap-seek already lives on
    /// the cell (`PodcastBubbleCell`'s `.onTapGesture`); to keep long-press → select,
    /// ALSO add to that cell, gated on `!displayTextIsInteractive`:
    ///   `.onLongPressGesture(minimumDuration: 0.35) { if !isSelecting { onEnterSelection(0) } }`
    /// (word-0 start — the cell has no per-word geometry in the inert path). Selecting
    /// mode stays interactive regardless of this flag.
    static let displayTextIsInteractive = true

    func makeCoordinator() -> Coordinator {
        Coordinator(
            onWordSelection: onWordSelection,
            onTranslateSelection: onTranslateSelection,
            onExplainSelection: onExplainSelection
        )
    }

    func makeUIView(context: Context) -> PodcastSentenceUITextView {
        // TextKit1 explicitly: the underline rect resolution drives `NSLayoutManager`
        // (`PodcastTextKitWordRects.resolve`), and accessing `.layoutManager` would
        // otherwise migrate a TextKit2 view mid-flight. Constructing TextKit1 up front
        // keeps layout deterministic.
        let textView = PodcastSentenceUITextView(usingTextLayoutManager: false)
        textView.backgroundColor = .clear
        textView.delegate = context.coordinator
        textView.isEditable = false
        textView.isScrollEnabled = false
        textView.textContainerInset = .zero
        textView.textContainer.lineFragmentPadding = 0
        textView.textContainer.maximumNumberOfLines = 0
        textView.textContainer.lineBreakMode = .byWordWrapping
        textView.adjustsFontForContentSizeCategory = false
        textView.showsHorizontalScrollIndicator = false
        textView.showsVerticalScrollIndicator = false
        textView.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        textView.setContentCompressionResistancePriority(.required, for: .vertical)
        // Rects flow out of the persistent text view (which survives isSelectable
        // flips) through the coordinator's LATEST closure — never the stale closure
        // captured at make time.
        textView.onResolveRects = { [weak coordinator = context.coordinator] rects in
            coordinator?.onResolveWordRects(rects)
        }
        let menuInteraction = UIEditMenuInteraction(delegate: context.coordinator)
        textView.addInteraction(menuInteraction)
        textView.menuInteraction = menuInteraction
        // Display-mode long-press → pressed word index. Kept on the text view so the
        // hit-test can use TextKit's `characterIndex(for:)`. Disabled in selecting
        // mode so the native selection gesture owns the long-press. The cell-level
        // `.onTapGesture` still owns seek — taps fall through this non-selectable,
        // non-editable view. (If a device shows tap/long-press contention, the M1
        // fallback is `isUserInteractionEnabled = false` + cell-layer long-press.)
        let longPress = UILongPressGestureRecognizer(
            target: context.coordinator, action: #selector(Coordinator.handleLongPress(_:))
        )
        longPress.minimumPressDuration = 0.35
        textView.addGestureRecognizer(longPress)
        context.coordinator.longPress = longPress
        update(textView, coordinator: context.coordinator)
        return textView
    }

    func updateUIView(_ uiView: PodcastSentenceUITextView, context: Context) {
        update(uiView, coordinator: context.coordinator)
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize,
        uiView: PodcastSentenceUITextView,
        context: Context
    ) -> CGSize? {
        let targetWidth = proposal.width ?? uiView.bounds.width
        guard targetWidth > 0 else { return nil }
        let fit = uiView.sizeThatFits(CGSize(width: targetWidth, height: .greatestFiniteMagnitude))
        // Shrink-to-content width so the bubble background hugs the text (matches the
        // old cached flow layout, which returned the tight `maxX`). `min` keeps us
        // within the proposed width while collapsing to intrinsic width for a short
        // sentence.
        return CGSize(width: min(fit.width, targetWidth), height: fit.height)
    }

    private func update(_ uiView: PodcastSentenceUITextView, coordinator: Coordinator) {
        if uiView.text != text {
            uiView.text = text
        }
        if uiView.font?.fontName != font.fontName || uiView.font?.pointSize != font.pointSize {
            uiView.font = font
        }
        if uiView.textColor != textColor {
            uiView.textColor = textColor
        }
        uiView.tintColor = tintColor
        if uiView.isSelectable != isSelectable {
            uiView.isSelectable = isSelectable
        }
        // Selecting mode is always interactive (native selection); display mode is
        // interactive only on the primary path (M1 fallback flips it inert).
        uiView.isUserInteractionEnabled = isSelectable || Self.displayTextIsInteractive
        // Word ranges + latest closures live on the coordinator / text view so the
        // persistent UITextView always resolves against the current text.
        let ranges = PodcastTextKitWordRects.wordRanges(for: words)
        uiView.wordRanges = ranges
        coordinator.wordRanges = ranges
        coordinator.currentText = text
        coordinator.onResolveWordRects = onResolveWordRects
        coordinator.onLongPressWord = onLongPressWord
        coordinator.pendingSelectionRange = initialSelectionRange
        // Custom long-press only in the interactive display path; native selection
        // owns the long-press while selecting, and the inert fallback drops it.
        coordinator.longPress?.isEnabled = !isSelectable && Self.displayTextIsInteractive

        if coordinator.appliedSelectionKey != selectionKey {
            DispatchQueue.main.async {
                guard uiView.window != nil else { return }
                coordinator.applyInitialSelection(to: uiView)
                coordinator.appliedSelectionKey = selectionKey
            }
        }
    }

    private var selectionKey: String {
        "\(isSelectable)::\(text)::\(initialSelectionRange?.location ?? -1)::\(initialSelectionRange?.length ?? 0)"
    }

    @MainActor
    final class Coordinator: NSObject, UITextViewDelegate, @preconcurrency UIEditMenuInteractionDelegate {
        let onWordSelection: (String, String) -> Void
        let onTranslateSelection: (String, String) -> Void
        let onExplainSelection: (String, String) -> Void
        var onResolveWordRects: ([Int: CGRect]) -> Void = { _ in }
        var onLongPressWord: (Int) -> Void = { _ in }
        var currentText: String = ""
        var pendingSelectionRange: NSRange?
        var appliedSelectionKey: String?
        var wordRanges: [Int: NSRange] = [:]
        weak var longPress: UILongPressGestureRecognizer?

        init(
            onWordSelection: @escaping (String, String) -> Void,
            onTranslateSelection: @escaping (String, String) -> Void,
            onExplainSelection: @escaping (String, String) -> Void
        ) {
            self.onWordSelection = onWordSelection
            self.onTranslateSelection = onTranslateSelection
            self.onExplainSelection = onExplainSelection
        }

        /// Display-mode long-press: map the press point → character → word index and
        /// enter selection there, so a long-press pre-selects the pressed word (parity
        /// with the old per-word `.onLongPressGesture`).
        @objc func handleLongPress(_ gesture: UILongPressGestureRecognizer) {
            guard gesture.state == .began,
                  let textView = gesture.view as? UITextView else { return }
            let point = gesture.location(in: textView)
            let charIndex = textView.layoutManager.characterIndex(
                for: point, in: textView.textContainer,
                fractionOfDistanceBetweenInsertionPoints: nil
            )
            onLongPressWord(wordIndex(forCharacter: charIndex))
        }

        /// The word whose range contains `charIndex` (or the nearest preceding word).
        /// Falls back to 0 so a press in trailing whitespace still enters selection.
        private func wordIndex(forCharacter charIndex: Int) -> Int {
            var best = 0
            var bestLocation = -1
            for (index, range) in wordRanges {
                if NSLocationInRange(charIndex, range) { return index }
                if range.location <= charIndex, range.location > bestLocation {
                    bestLocation = range.location
                    best = index
                }
            }
            return best
        }

        func applyInitialSelection(to textView: UITextView) {
            guard let range = pendingSelectionRange,
                  range.location != NSNotFound,
                  range.length > 0,
                  NSMaxRange(range) <= (textView.text as NSString).length
            else { return }

            textView.becomeFirstResponder()
            textView.selectedRange = range
            // 進入選取後主動呈現 edit menu。`editMenuForTextIn` delegate 是被動的，
            // UIKit 只在自己決定要顯示選單時才求值，所以只設 selectedRange 不會跳出
            // 選單 → 使用者得「再點一下選取框」才出現。設好 range 後排到下一個 run
            // loop（待 selection rect 完成 layout）主動 present。
            DispatchQueue.main.async { [weak textView] in
                guard let textView, textView.window != nil else { return }
                Self.presentEditMenu(in: textView)
            }
        }

        /// Present UITextView 內建的 edit menu，錨定在選取範圍的矩形中心。
        private static func presentEditMenu(in textView: UITextView) {
            guard let textView = textView as? PodcastSentenceUITextView,
                  let interaction = textView.menuInteraction,
                  let selectedTextRange = textView.selectedTextRange
            else { return }
            let rect = textView.firstRect(for: selectedTextRange)
            let sourcePoint = CGPoint(x: rect.midX, y: rect.minY)
            let config = UIEditMenuConfiguration(identifier: nil, sourcePoint: sourcePoint)
            interaction.presentEditMenu(with: config)
        }

        func textView(
            _ textView: UITextView,
            editMenuForTextIn range: NSRange,
            suggestedActions: [UIMenuElement]
        ) -> UIMenu? {
            menu(for: range, suggestedActions: suggestedActions, textView: textView)
        }

        func editMenuInteraction(
            _ interaction: UIEditMenuInteraction,
            menuFor configuration: UIEditMenuConfiguration,
            suggestedActions: [UIMenuElement]
        ) -> UIMenu? {
            guard let textView = interaction.view as? UITextView else { return nil }
            return menu(
                for: textView.selectedRange,
                suggestedActions: suggestedActions,
                textView: textView
            )
        }

        private func menu(
            for range: NSRange,
            suggestedActions: [UIMenuElement],
            textView: UITextView
        ) -> UIMenu? {
            guard let selection = selectionPayload(for: range) else { return nil }

            // [診斷] DEBUG-gated：確認 editMenu delegate 對任意選取(含多詞片語)都被
            // 呼叫且回兩個 action。若實機片語選取時這條沒印 → delegate 沒被觸發；
            // 印了但 UI 缺「解釋」→ menu 呈現層問題。RELEASE 零成本。
            PerfLog.general.mark(
                "podcastEditMenu",
                "len=\(range.length) route=\(PodcastSelectionRouting.route(for: selection.text)) text=\(selection.text)"
            )

            // Translate routes single-word → word path, multi-word → phrase path
            // (mirrors reader). Explain is offered for BOTH word and phrase, matching
            // reader's gate-free edit menu.
            let translateAction = UIAction(
                title: L10n.string("翻譯"),
                image: UIImage(systemName: "character.book.closed")
            ) { [weak self, weak textView] _ in
                guard let self, let textView else { return }
                switch PodcastSelectionRouting.route(for: selection.text) {
                case .word: self.onWordSelection(selection.text, selection.context)
                case .phrase: self.onTranslateSelection(selection.text, selection.context)
                }
                textView.resignFirstResponder()
            }

            let explainAction = UIAction(
                title: L10n.string("解釋"),
                image: UIImage(systemName: "text.magnifyingglass")
            ) { [weak self, weak textView] _ in
                guard let self, let textView else { return }
                self.onExplainSelection(selection.text, selection.context)
                textView.resignFirstResponder()
            }

            // 自訂「翻譯/解釋」置前，再併回系統建議項（複製/查詢/分享…）。先前直接
            // 丟棄 suggestedActions 導致原生選項全部消失。
            return UIMenu(children: [translateAction, explainAction] + suggestedActions)
        }

        private func selectionPayload(for range: NSRange) -> (text: String, context: String)? {
            guard let swiftRange = Range(range, in: currentText) else { return nil }

            let selected = String(currentText[swiftRange])
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard !selected.isEmpty else { return nil }

            let context = buildMarkedContext(text: currentText, selectedRange: range)
            return (selected, context)
        }

        private func buildMarkedContext(text: String, selectedRange: NSRange) -> String {
            guard let range = Range(selectedRange, in: text) else { return text }
            let before = text[..<range.lowerBound]
            let selected = text[range]
            let after = text[range.upperBound...]
            return String(before) + "**" + selected + "**" + String(after)
        }
    }
}

/// `UITextView` subclass that publishes its laid-out per-word rects after each
/// layout pass, cache-guarded by `LayoutKey` (text + font + width) so a stable
/// layout never re-resolves — re-resolving (and re-publishing) every frame is the
/// exact path that reintroduces the scroll-freeze. `layoutSubviews` is a UIKit
/// callback OUTSIDE the SwiftUI update cycle, so invoking the publish closure here
/// (which sets `@State` upstream) is safe.
final class PodcastSentenceUITextView: UITextView {
    var onResolveRects: (@MainActor ([Int: CGRect]) -> Void)?
    var wordRanges: [Int: NSRange] = [:]
    weak var menuInteraction: UIEditMenuInteraction?
    private var lastKey: PodcastTextKitWordRects.LayoutKey?

    override func layoutSubviews() {
        super.layoutSubviews()
        guard !wordRanges.isEmpty, let font, let text, bounds.width > 0 else { return }
        let key = PodcastTextKitWordRects.LayoutKey(text: text, font: font, width: bounds.width)
        guard key != lastKey else { return }
        lastKey = key
        let rects = PodcastTextKitWordRects.resolve(
            layoutManager: layoutManager,
            textContainer: textContainer,
            wordRanges: wordRanges
        )
        onResolveRects?(rects)
    }
}
#endif
