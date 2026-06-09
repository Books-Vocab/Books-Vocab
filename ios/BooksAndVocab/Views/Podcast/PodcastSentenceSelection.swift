#if os(iOS)
import Foundation

/// Selection state for the long-press → phrase-select flow. Shared between the
/// outer view (which owns it as `@State`) and the Equatable transcript child
/// (which reads it to swap a bubble into `PodcastSelectableSentenceTextView` and
/// clears it on phrase/explain commit). Kept top-level + `Equatable` so it can
/// participate in the transcript column's `EquatableView` short-circuit.
struct PodcastSentenceSelection: Equatable {
    let sentenceId: Int
    let initialRange: NSRange?
}
#endif
