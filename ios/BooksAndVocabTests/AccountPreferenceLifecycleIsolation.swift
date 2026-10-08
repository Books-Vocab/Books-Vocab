import Foundation
import Testing
@testable import BooksAndVocab

/// An `AccountPreferenceLifecycle` that touches no process-wide state.
///
/// `AuthManager.init` activates the persisted account's preferences, and every
/// login/logout suspends or re-activates them. With the default
/// `AccountPreferenceLifecycleCoordinator` that reaches
/// `TranslationLanguage.activateAccount` / `suspendForAccountBoundary`, which
/// flips the account namespace under `TranslationLanguageTests` (serialized
/// only within its own suite tree) when parallel testing is on (#2117). Every
/// test-side `AuthManager` therefore injects this instead.
final class NoopAccountPreferenceLifecycle: AccountPreferenceLifecycle {
    func activate(accountID: String?) {}
    func suspend() {}
}

/// Guards the convention above: a test that builds an `AuthManager` with the
/// default lifecycle would silently reintroduce the cross-suite race.
struct AccountPreferenceLifecycleIsolationTests {
    @Test func everyTestAuthManagerInjectsAnAccountPreferenceLifecycle() throws {
        let testsDirectory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        let files = try FileManager.default.contentsOfDirectory(
            at: testsDirectory,
            includingPropertiesForKeys: nil
        ).filter { $0.pathExtension == "swift" && $0.lastPathComponent != URL(fileURLWithPath: #filePath).lastPathComponent }
        #expect(!files.isEmpty)

        let constructor = "AuthManager" + "("
        var constructions = 0
        var offenders: [String] = []
        for file in files {
            let source = try String(contentsOf: file, encoding: .utf8)
            for call in Self.calls(of: constructor, in: source) {
                constructions += 1
                if !call.contains("accountPreferenceLifecycle:") {
                    offenders.append(file.lastPathComponent)
                }
            }
        }

        // Positive control: the scan really sees the known construction sites.
        #expect(constructions >= 5, "scan found only \(constructions) AuthManager constructions")
        #expect(offenders.isEmpty, "AuthManager built with the default (global-state) lifecycle in: \(offenders)")
    }

    /// Source text of each `constructor` call (through its balanced closing
    /// paren), skipping comment lines and longer identifiers such as
    /// `TestAuthManager(`.
    private static func calls(of constructor: String, in source: String) -> [String] {
        var results: [String] = []
        var searchStart = source.startIndex
        while let range = source.range(of: constructor, range: searchStart..<source.endIndex) {
            searchStart = range.upperBound
            if range.lowerBound > source.startIndex {
                let previous = source[source.index(before: range.lowerBound)]
                if previous.isLetter || previous.isNumber || previous == "_" { continue }
            }
            let lineStart = source[..<range.lowerBound].lastIndex(of: "\n").map { source.index(after: $0) } ?? source.startIndex
            if source[lineStart..<range.lowerBound].trimmingCharacters(in: .whitespaces).hasPrefix("//") { continue }
            var depth = 1
            var cursor = range.upperBound
            while cursor < source.endIndex, depth > 0 {
                if source[cursor] == "(" { depth += 1 } else if source[cursor] == ")" { depth -= 1 }
                cursor = source.index(after: cursor)
            }
            results.append(String(source[range.lowerBound..<cursor]))
        }
        return results
    }
}
