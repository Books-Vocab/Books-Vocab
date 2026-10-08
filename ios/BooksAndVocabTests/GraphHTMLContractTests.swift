#if DEBUG
import Foundation
import Testing
@testable import BooksAndVocab

/// Source-level contract for graph.html interaction and force wiring.
struct GraphHTMLContractTests {
    private func html() throws -> String {
        let url = try #require(Bundle.main.url(forResource: "graph", withExtension: "html"))
        return try String(contentsOf: url, encoding: .utf8)
    }

    @Test func tappingSelectedNodeStillPostsNodeClick() throws {
        let source = try html()
        #expect(!source.contains("if (selectedId === node.id)"))
        #expect(source.contains("selectedId = node.id;\n            postBridge({ type: 'nodeClick', nodeId: node.id });"))
    }

    @Test func zeroCenterAndRepelAreNotReplacedByDefaults() throws {
        let source = try html()
        #expect(!source.contains("forces.centerStrength ||"))
        #expect(!source.contains("forces.repel ||"))
        #expect(source.contains("forces.centerStrength ?? 0.05"))
        #expect(source.contains("forces.repel ?? 80"))
    }
}
#endif
