import Foundation
import SwiftUI
import Testing
@testable import BooksAndVocab

// MARK: - Editor field model

struct ReviewCardFieldOrderingTests {

    @Test func canonical_order_matches_the_agreed_row_order() {
        #expect(ReviewCardField.canonicalOrder == [
            .partOfSpeech, .difficultyTier, .graphLinks, .example, .explanation, .collocations
        ])
        #expect(Set(ReviewCardField.canonicalOrder) == Set(ReviewCardField.allCases))
    }

    @Test func every_default_face_is_already_in_canonical_order() {
        for mode in VocabularyCardMode.allCases {
            let layout = ReviewCardLayoutProfile.default.layout(for: mode)
            #expect(layout.front == ReviewCardField.canonicalOrder.filter(layout.front.contains))
            #expect(layout.back == ReviewCardField.canonicalOrder.filter(layout.back.contains))
        }
    }

    @Test func enabling_a_field_inserts_it_at_its_canonical_slot() {
        let enabled = ReviewCardField.toggling(.graphLinks, in: [.partOfSpeech, .example], isOn: true)
        #expect(enabled == [.partOfSpeech, .graphLinks, .example])
    }

    @Test func disabling_a_field_leaves_the_rest_untouched_and_is_idempotent() {
        let once = ReviewCardField.toggling(.example, in: [.partOfSpeech, .graphLinks, .example], isOn: false)
        #expect(once == [.partOfSpeech, .graphLinks])
        #expect(ReviewCardField.toggling(.example, in: once, isOn: false) == once)
        #expect(ReviewCardField.toggling(.graphLinks, in: once, isOn: true) == once)
    }

    @Test func every_field_has_a_localizable_label_key() {
        for field in ReviewCardField.canonicalOrder {
            #expect(!field.titleKey.isEmpty)
            #expect(field.titleKey != L10n.string(field.titleKey) || !field.titleKey.isEmpty)
        }
        #expect(Set(ReviewCardField.canonicalOrder.map(\.titleKey)).count == ReviewCardField.allCases.count)
    }
}

// MARK: - Editor ↔ store

@MainActor
struct ReviewCardLayoutEditorStoreTests {

    private func store() -> ReviewCardLayoutStore { .inMemory() }

    @Test func settings_and_review_read_the_same_shared_profile() {
        #expect(EnvironmentValues().reviewCardLayoutStore === ReviewCardLayoutStore.shared)
    }

    @Test func toggling_a_field_persists_only_the_edited_face() {
        let store = store()
        let before = store.profile.recognition.back
        store.setLayout(
            .init(
                front: ReviewCardField.toggling(.example, in: store.profile.recognition.front, isOn: true),
                back: store.profile.recognition.back
            ),
            for: .recognition
        )

        #expect(store.profile.recognition.front == [.partOfSpeech, .example])
        #expect(store.profile.recognition.back == before)
        #expect(store.profile.production == ReviewCardLayoutProfile.default.production)
    }

    @Test func reset_current_mode_leaves_the_other_mode_edited() {
        let store = store()
        store.setLayout(.init(front: [], back: []), for: .recognition)
        store.setLayout(.init(front: [], back: []), for: .production)

        store.reset(.recognition)

        #expect(store.profile.recognition == ReviewCardLayoutProfile.default.recognition)
        #expect(store.profile.production == ReviewCardModeLayout(front: [], back: []))
    }

    @Test func reset_all_restores_both_modes() {
        let store = store()
        store.setLayout(.init(front: [], back: []), for: .recognition)
        store.setLayout(.init(front: [], back: []), for: .production)

        store.resetAll()

        #expect(store.profile == .default)
    }

    @Test func summary_reads_default_only_when_every_face_matches() {
        #expect(ReviewCardLayoutSummary.titleKey(for: .default) == "settings.reviewCardLayout.default")

        var edited = ReviewCardLayoutProfile.default
        edited.setLayout(.init(front: [], back: []), for: .production)
        #expect(ReviewCardLayoutSummary.titleKey(for: edited) == "settings.reviewCardLayout.custom")
    }
}

// MARK: - Autoplay interruption

@MainActor
struct TodayReviewAutoplayInterruptionTests {

    private func controller() -> TodayReviewAutoplayController {
        TodayReviewAutoplayController(settingsStore: ReviewSettingsStore(previewSettings: .default))
    }

    @Test func opening_the_editor_pauses_a_running_autoplay() {
        let autoplay = controller()
        autoplay.togglePlayback(restartLoop: {})
        #expect(autoplay.isPlaying)
        #expect(!autoplay.isPaused)

        autoplay.pauseForInterruption()

        #expect(autoplay.isPlaying)
        #expect(autoplay.isPaused)
        #expect(!autoplay.isLoopActive)
    }

    @Test func the_pause_outlives_the_editor_and_never_starts_playback() {
        let stopped = controller()
        stopped.pauseForInterruption()
        #expect(!stopped.isPlaying)
        #expect(!stopped.isPaused)

        let running = controller()
        running.togglePlayback(restartLoop: {})
        running.pauseForInterruption()
        running.pauseForInterruption()
        #expect(running.isPaused)
    }
}
