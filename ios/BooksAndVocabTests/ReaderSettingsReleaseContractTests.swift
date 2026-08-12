#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

struct ReaderSettingsReleaseContractTests {
    private static let debugDOMAPI = "window.__toggleDebugBoxes"

    @Test func hitTestingDebugAvailabilityFollowsBuildConfiguration() {
        #if DEBUG
        #expect(ReaderDebugTools.isAvailable)
        #else
        #expect(!ReaderDebugTools.isAvailable)
        #endif
    }

    @Test func productionReaderBundleExcludesDebugDOMSurface() throws {
        let navigatorSource = try String(
            contentsOf: sourceURL(named: "ReadiumNavigatorJS.swift"),
            encoding: .utf8
        )
        let debugSource = try String(
            contentsOf: sourceURL(named: "ReadiumNavigatorJS+Debug.swift"),
            encoding: .utf8
        )

        #expect(navigatorSource.contains("#if DEBUG"))
        #expect(debugSource.contains("#if os(iOS) && DEBUG"))

        let productionBundleSource = releaseProjection(of: navigatorSource + "\n" + debugSource)
        #expect(
            !productionBundleSource.contains(Self.debugDOMAPI),
            "Release Reader injection must not contain the hit-testing DOM API"
        )
        #expect(
            !productionBundleSource.contains("buildDebugScript"),
            "Release Reader source must not reference the DEBUG-only script builder"
        )
    }

    private static func sourceURL(named name: String) -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("BooksAndVocab/Views/Reader/\(name)")
    }

    /// Static Release projection for the two Reader JS source files.  It keeps
    /// the contract test independent from whichever Xcode configuration runs
    /// the unit test target while modelling the conditions that matter here:
    /// `os(iOS)` is active and `DEBUG` is not.
    private static func releaseProjection(of source: String) -> String {
        struct ConditionalFrame {
            let parentActive: Bool
            var branchTaken: Bool
        }

        var frames: [ConditionalFrame] = []
        var active = true
        var output: [String] = []

        for rawLine in source.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(rawLine)
            let directive = line.trimmingCharacters(in: .whitespacesAndNewlines)

            if directive.hasPrefix("#if ") {
                let parentActive = active
                let branchActive = parentActive && releaseConditionIsActive(
                    String(directive.dropFirst(4))
                )
                frames.append(
                    ConditionalFrame(parentActive: parentActive, branchTaken: branchActive)
                )
                active = branchActive
            } else if directive.hasPrefix("#elseif ") {
                guard var frame = frames.popLast() else { continue }
                let branchActive = frame.parentActive
                    && !frame.branchTaken
                    && releaseConditionIsActive(String(directive.dropFirst(8)))
                frame.branchTaken = frame.branchTaken || branchActive
                frames.append(frame)
                active = branchActive
            } else if directive == "#else" {
                guard var frame = frames.popLast() else { continue }
                let branchActive = frame.parentActive && !frame.branchTaken
                frame.branchTaken = true
                frames.append(frame)
                active = branchActive
            } else if directive == "#endif" {
                active = frames.removeLast().parentActive
            } else if active {
                output.append(line)
            }
        }

        return output.joined(separator: "\n")
    }

    private static func releaseConditionIsActive(_ condition: String) -> Bool {
        let normalized = condition.replacingOccurrences(of: " ", with: "")
        if normalized == "DEBUG" || normalized.contains("&&DEBUG") {
            return false
        }
        return true
    }
}
#endif
