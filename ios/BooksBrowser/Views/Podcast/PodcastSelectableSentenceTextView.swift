#if os(iOS)
import SwiftUI
import UIKit

struct PodcastSelectableSentenceTextView: UIViewRepresentable {
    let text: String
    let font: UIFont
    let textColor: UIColor
    let tintColor: UIColor
    let initialSelectionRange: NSRange?
    let onTranslateSelection: (String, String) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onTranslateSelection: onTranslateSelection)
    }

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.backgroundColor = .clear
        textView.delegate = context.coordinator
        textView.isEditable = false
        textView.isSelectable = true
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
        update(textView, coordinator: context.coordinator)
        return textView
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        update(uiView, coordinator: context.coordinator)
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize,
        uiView: UITextView,
        context: Context
    ) -> CGSize? {
        let targetWidth = proposal.width ?? uiView.bounds.width
        guard targetWidth > 0 else { return nil }
        let fit = uiView.sizeThatFits(CGSize(width: targetWidth, height: .greatestFiniteMagnitude))
        return CGSize(width: targetWidth, height: fit.height)
    }

    private func update(_ uiView: UITextView, coordinator: Coordinator) {
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
        coordinator.currentText = text
        coordinator.pendingSelectionRange = initialSelectionRange

        if coordinator.appliedSelectionKey != selectionKey {
            DispatchQueue.main.async {
                guard uiView.window != nil else { return }
                coordinator.applyInitialSelection(to: uiView)
                coordinator.appliedSelectionKey = selectionKey
            }
        }
    }

    private var selectionKey: String {
        "\(text)::\(initialSelectionRange?.location ?? -1)::\(initialSelectionRange?.length ?? 0)"
    }

    final class Coordinator: NSObject, UITextViewDelegate {
        let onTranslateSelection: (String, String) -> Void
        var currentText: String = ""
        var pendingSelectionRange: NSRange?
        var appliedSelectionKey: String?

        init(onTranslateSelection: @escaping (String, String) -> Void) {
            self.onTranslateSelection = onTranslateSelection
        }

        func applyInitialSelection(to textView: UITextView) {
            guard let range = pendingSelectionRange,
                  range.location != NSNotFound,
                  range.length > 0,
                  NSMaxRange(range) <= (textView.text as NSString).length
            else { return }

            textView.becomeFirstResponder()
            textView.selectedRange = range
        }

        func textView(
            _ textView: UITextView,
            editMenuForTextIn range: NSRange,
            suggestedActions: [UIMenuElement]
        ) -> UIMenu? {
            guard range.length > 0 else {
                return UIMenu(children: suggestedActions)
            }

            let translateAction = UIAction(
                title: "翻譯",
                image: UIImage(systemName: "character.book.closed")
            ) { [weak self, weak textView] _ in
                guard let self, let textView else { return }
                self.translateSelection(in: textView, range: range)
            }

            return UIMenu(children: [translateAction] + suggestedActions)
        }

        private func translateSelection(in textView: UITextView, range: NSRange) {
            guard let swiftRange = Range(range, in: currentText) else { return }

            let phrase = currentText[swiftRange]
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard !phrase.isEmpty else { return }

            let context = buildMarkedContext(text: currentText, selectedRange: range)
            onTranslateSelection(phrase, context)
            textView.resignFirstResponder()
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
#endif
