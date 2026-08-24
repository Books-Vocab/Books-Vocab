import Foundation
import Testing
@testable import BooksAndVocab

struct NotebookSettingsSyncTests {
    @Test func remoteGroupsApplyIndependentlyAndResetKeepsTimestamp() {
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        let policy = ReviewPolicy.default
        let layout = ReviewCardLayoutProfile(recognition: .compact, production: .standard)
        projection.applyRemote(KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup(
                value: KGNotebookReviewPolicy(policy), updatedAt: 10
            ),
            cardLayout: KGNotebookSettingsGroup(
                value: KGNotebookCardLayout(layout), updatedAt: 10
            )
        ))
        #expect(projection.reviewPolicyOverride == policy)
        #expect(projection.cardLayoutOverride == layout)

        projection.applyRemote(KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup<KGNotebookReviewPolicy>(
                value: nil, updatedAt: 11
            ),
            cardLayout: KGNotebookSettingsGroup(
                value: KGNotebookCardLayout(layout), updatedAt: 10
            )
        ))
        #expect(projection.reviewPolicyOverride == nil)
        #expect(projection.reviewPolicyUpdatedAt == 11)
        #expect(projection.cardLayoutOverride == layout)
    }

    @Test func staleRemoteGroupCannotResurrectClearedPolicy() {
        let projection = NotebookSettingsProjection(notebookId: "nb-1")
        projection.applyRemote(KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup(
                value: nil, updatedAt: 20
            ),
            cardLayout: KGNotebookSettingsGroup<KGNotebookCardLayout>(
                value: nil, updatedAt: nil
            )
        ))
        projection.applyRemote(KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup(
                value: KGNotebookReviewPolicy(.default), updatedAt: 19
            ),
            cardLayout: KGNotebookSettingsGroup<KGNotebookCardLayout>(
                value: nil, updatedAt: nil
            )
        ))
        #expect(projection.reviewPolicyOverride == nil)
        #expect(projection.reviewPolicyUpdatedAt == 20)
    }

    @Test func notebookWireDecodeKeepsSettingsAndSupportsLegacyResponse() throws {
        let settings = KGNotebookSettings(
            reviewPolicy: KGNotebookSettingsGroup(
                value: KGNotebookReviewPolicy(.default), updatedAt: 10
            ),
            cardLayout: KGNotebookSettingsGroup<KGNotebookCardLayout>(
                value: nil, updatedAt: nil
            )
        )
        let current = KGNotebook(
            id: "nb-1",
            name: "本",
            color: nil,
            coverPattern: nil,
            sortOrder: 0,
            isDefault: false,
            isDeleted: false,
            cardCount: 0,
            updatedAt: nil,
            sourceSharedDeckId: nil,
            sourceVersion: nil,
            settings: settings
        )
        let decoded = try JSONDecoder().decode(
            KGNotebook.self,
            from: JSONEncoder().encode(current)
        )
        #expect(decoded.settings?.reviewPolicy.value?.reviewPolicy == .default)

        let legacy = try JSONDecoder().decode(
            KGNotebook.self,
            from: Data(#"{"id":"legacy","name":"舊本"}"#.utf8)
        )
        #expect(legacy.settings == nil)
    }
}
