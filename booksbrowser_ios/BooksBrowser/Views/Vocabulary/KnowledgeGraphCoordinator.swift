import Foundation
import SwiftUI

@MainActor
final class KnowledgeGraphCoordinator: ObservableObject {
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var isShowingSettings = false
    @Published var links: [KGGraphLink] = []
    @Published var selectedEntry: VocabularyEntry?

    @Published var centerForce: Double = 0.05
    @Published var repelForce: Double = 0.20
    @Published var linkForce: Double = 0.50
    @Published var linkDistance: Double = 50
    @Published var nodeSize: Double = 5.0
    @Published var linkThickness: Double = 1.0

    func toggleSettings() {
        withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
            isShowingSettings.toggle()
        }
    }

    func resetForces() {
        centerForce = 0.05
        repelForce = 0.20
        linkForce = 0.50
        linkDistance = 50
        nodeSize = 5.0
        linkThickness = 1.0
    }

    func handleNodeTap(_ nodeID: String, allEntries: [VocabularyEntry]) {
        selectedEntry = allEntries.first { $0.kgCardId == nodeID }
    }

    func loadGraphData(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) async {
        guard authManager.isLoggedIn else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            links = try await kgService.pullGraphLinks()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
