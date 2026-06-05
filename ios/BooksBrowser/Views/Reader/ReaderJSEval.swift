#if os(iOS)
import Foundation
import ReadiumNavigator

/// Centralized observability for fire-and-forget `navigator.evaluateJavaScript`
/// calls. The Readium EPUB navigator returns `Result<Any, Error>`; the prior
/// `_ = await …` pattern discarded it, creating an exception blind spot — a
/// failed highlight/DOM injection produced no signal, so a tapped word could
/// silently appear unselected with no trace to diagnose.
///
/// `.spreadNotLoaded` is the EXPECTED race when JS runs before the visible
/// resource finishes loading (initial load / mid page-turn). It is demoted to
/// `debug` so it never floods the log; every other failure is a real anomaly
/// surfaced at `error`.
enum ReaderJSEval {
    enum Outcome: Equatable {
        case ok
        /// Expected timing race — resource not yet loaded. Benign, not an error.
        case spreadNotLoaded
        /// Genuine JS execution / bridge failure.
        case failed(String)
    }

    /// Pure classification seam — unit-testable without a live navigator.
    static func classify(_ result: Result<Any, Error>) -> Outcome {
        switch result {
        case .success:
            return .ok
        case .failure(EPUBNavigatorViewController.EPUBError.spreadNotLoaded):
            return .spreadNotLoaded
        case .failure(let error):
            return .failed(error.localizedDescription)
        }
    }

    /// Classify + log. Call at every `evaluateJavaScript` site that previously
    /// discarded its `Result`. `label` identifies the call site in the log.
    static func log(_ result: Result<Any, Error>, _ label: StaticString) {
        switch classify(result) {
        case .ok:
            break
        case .spreadNotLoaded:
            AppLog.reader.debug("JS eval skipped — spread not loaded (\(label))")
        case .failed(let message):
            AppLog.reader.error("JS eval failed (\(label)): \(message, privacy: .public)")
        }
    }

    /// JSON-encode `value` into a JS string literal (incl. surrounding quotes),
    /// safe to splice into an `evaluateJavaScript` script. Falls back to `""`.
    static func quotedLiteral(_ value: String) -> String {
        (try? JSONEncoder().encode(value)).flatMap { String(data: $0, encoding: .utf8) } ?? "\"\""
    }
}
#endif
