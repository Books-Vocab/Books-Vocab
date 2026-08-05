import Foundation
import SwiftUI
import Testing
@testable import BooksAndVocab

@MainActor
struct ReviewCardLayoutProfileTests {
    @Test func fieldsAreExactlyTheSixOptionalReviewSections() {
        #expect(ReviewCardField.allCases == [
            .partOfSpeech,
            .difficultyTier,
            .example,
            .explanation,
            .collocations,
            .graphLinks,
        ])
    }

    @Test func defaultsMatchTheExistingRecognitionAndProductionCards() {
        let profile = ReviewCardLayoutProfile.default

        #expect(profile.recognition.front == [.partOfSpeech])
        #expect(profile.production.front == [.partOfSpeech, .example])
        #expect(profile.recognition.back == [
            .difficultyTier, .graphLinks, .example, .explanation, .collocations,
        ])
        #expect(profile.production.back == [
            .difficultyTier, .graphLinks, .example, .explanation, .collocations,
        ])
    }

    @Test func sameFieldCanAppearOnBothSides() {
        var profile = ReviewCardLayoutProfile.default
        profile.recognition.front.append(.example)

        #expect(profile.recognition.front.contains(.example))
        #expect(profile.recognition.back.contains(.example))
    }

    @Test func decodingSanitizesDuplicatesAndUnknownsAndDefaultsMissingSides() throws {
        let json = """
        {
          "recognition": {
            "front": ["example", "unknown", "example", "partOfSpeech"]
          },
          "production": {
            "front": [],
            "back": ["graphLinks", "futureField", "graphLinks"]
          }
        }
        """

        let decoded = try JSONDecoder().decode(
            ReviewCardLayoutProfile.self,
            from: Data(json.utf8)
        )

        #expect(decoded.recognition.front == [.example, .partOfSpeech])
        #expect(decoded.recognition.back == ReviewCardLayoutProfile.default.recognition.back)
        #expect(decoded.production.front == [])
        #expect(decoded.production.back == [.graphLinks])
    }
}

@MainActor
struct ReviewCardLayoutStoreTests {
    private let key = "review_card_layout_profile_v1"
    private let maximumSupportedUnixTimestamp: TimeInterval = 253_402_300_800
    private let maximumLegacyUnixTimestamp: TimeInterval =
        253_402_300_800 - (366 * 24 * 60 * 60)
    private let maximumV2UnixTimestamp: TimeInterval =
        253_402_300_800 - (24 * 60 * 60)

    private func makeDefaults() -> UserDefaults {
        let suite = "test.review-card-layout.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        return defaults
    }

    private func encodedEnvelope(
        profile: ReviewCardLayoutProfile,
        updatedAt: TimeInterval,
        version: Int = 1
    ) throws -> String {
        let object: [String: Any] = [
            "version": version,
            "updatedAt": updatedAt,
            "profile": try JSONSerialization.jsonObject(
                with: JSONEncoder().encode(profile)
            ),
        ]
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        return try #require(String(data: data, encoding: .utf8))
    }

    private func customProfile(_ field: ReviewCardField) -> ReviewCardLayoutProfile {
        ReviewCardLayoutProfile(
            recognition: ReviewCardModeLayout(front: [field], back: []),
            production: ReviewCardModeLayout(front: [], back: [field])
        )
    }

    @Test func cloudNewerWinsWithoutColdStartWriteback() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        let local = customProfile(.example)
        let remote = customProfile(.graphLinks)
        defaults.set(try encodedEnvelope(profile: local, updatedAt: 100), forKey: key)
        cloud.values[key] = try encodedEnvelope(profile: remote, updatedAt: 200)

        let store = ReviewCardLayoutStore(defaults: defaults, cloud: cloud)

        #expect(store.profile == remote)
        #expect(cloud.setCalls.isEmpty)
        let originalLocalEnvelope = try encodedEnvelope(profile: local, updatedAt: 100)
        #expect(defaults.string(forKey: key) == originalLocalEnvelope)
    }

    @Test func localNewerWins() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        let local = customProfile(.explanation)
        let remote = customProfile(.collocations)
        defaults.set(try encodedEnvelope(profile: local, updatedAt: 300), forKey: key)
        cloud.values[key] = try encodedEnvelope(profile: remote, updatedAt: 200)

        let store = ReviewCardLayoutStore(defaults: defaults, cloud: cloud)

        #expect(store.profile == local)
        #expect(cloud.setCalls.isEmpty)
    }

    @Test func timestampTieGoesToCloud() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        let local = customProfile(.difficultyTier)
        let remote = customProfile(.partOfSpeech)
        defaults.set(try encodedEnvelope(profile: local, updatedAt: 500), forKey: key)
        cloud.values[key] = try encodedEnvelope(profile: remote, updatedAt: 500)

        let store = ReviewCardLayoutStore(defaults: defaults, cloud: cloud)

        #expect(store.profile == remote)
    }

    @Test func corruptAndUnknownVersionsFallBackWithoutStartupOverwrite() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        defaults.set("not-json", forKey: key)
        cloud.values[key] = try encodedEnvelope(
            profile: customProfile(.example),
            updatedAt: 100,
            version: 99
        )

        let store = ReviewCardLayoutStore(defaults: defaults, cloud: cloud)

        #expect(store.profile == .default)
        #expect(defaults.string(forKey: key) == "not-json")
        #expect(cloud.setCalls.isEmpty)
    }

    @Test func greatestFiniteCloudTimestampFallsBackThenUpdateRepairsBothLayers() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        cloud.values[key] = try encodedEnvelope(
            profile: customProfile(.graphLinks),
            updatedAt: .greatestFiniteMagnitude
        )
        let store = ReviewCardLayoutStore(
            defaults: defaults,
            cloud: cloud,
            now: { Date(timeIntervalSince1970: 800) }
        )

        #expect(store.profile == .default)

        let changed = customProfile(.explanation)
        store.update(changed)

        let localJSON = try #require(defaults.string(forKey: key))
        #expect(cloud.values[key] == localJSON)
        #expect(store.profile == changed)
        let object = try #require(
            JSONSerialization.jsonObject(with: Data(localJSON.utf8)) as? [String: Any]
        )
        let timestamp = try #require(object["updatedAt"] as? Double)
        #expect(timestamp.isFinite)
        #expect(timestamp >= 0)
        #expect(timestamp < maximumSupportedUnixTimestamp)
    }

    @Test func invalidCloudTimestampDoesNotBeatValidLocalAndResetRepairsBothLayers() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        let local = customProfile(.collocations)
        defaults.set(try encodedEnvelope(profile: local, updatedAt: 600), forKey: key)
        cloud.values[key] = try encodedEnvelope(
            profile: customProfile(.graphLinks),
            updatedAt: .greatestFiniteMagnitude
        )
        let store = ReviewCardLayoutStore(
            defaults: defaults,
            cloud: cloud,
            now: { Date(timeIntervalSince1970: 700) }
        )

        #expect(store.profile == local)

        store.resetAll()

        let localJSON = try #require(defaults.string(forKey: key))
        #expect(cloud.values[key] == localJSON)
        #expect(store.profile == .default)
        let object = try #require(
            JSONSerialization.jsonObject(with: Data(localJSON.utf8)) as? [String: Any]
        )
        let timestamp = try #require(object["updatedAt"] as? Double)
        #expect(timestamp.isFinite)
        #expect(timestamp < maximumSupportedUnixTimestamp)
    }

    @Test func v2ExtremeCloudTimestampFallsBackThenUpdateRepairsBothLayers() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        cloud.values[key] = try encodedEnvelope(
            profile: customProfile(.graphLinks),
            updatedAt: maximumSupportedUnixTimestamp.nextDown,
            version: 2
        )
        let store = ReviewCardLayoutStore(
            defaults: defaults,
            cloud: cloud,
            now: { Date(timeIntervalSince1970: 850) }
        )

        #expect(store.profile == .default)

        let changed = customProfile(.explanation)
        store.update(changed)

        let localJSON = try #require(defaults.string(forKey: key))
        #expect(cloud.values[key] == localJSON)
        #expect(store.profile == changed)
        let object = try #require(
            JSONSerialization.jsonObject(with: Data(localJSON.utf8)) as? [String: Any]
        )
        let timestamp = try #require(object["updatedAt"] as? Double)
        #expect(object["version"] as? Int == 2)
        #expect(timestamp.isFinite)
        #expect(timestamp == 850)
        #expect(timestamp < maximumV2UnixTimestamp)
    }

    @Test func negativeTimestampIsCorruptAndDoesNotOverwriteOnStartup() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        let invalidEnvelope = try encodedEnvelope(
            profile: customProfile(.difficultyTier),
            updatedAt: -1
        )
        cloud.values[key] = invalidEnvelope

        let store = ReviewCardLayoutStore(defaults: defaults, cloud: cloud)

        #expect(store.profile == .default)
        #expect(defaults.string(forKey: key) == nil)
        #expect(cloud.values[key] == invalidEnvelope)
        #expect(cloud.setCalls.isEmpty)
    }

    @Test func unsupportedEdgeTimestampCannotOverwriteRepairWhenCloudReplaysIt() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        let center = NotificationCenter()
        let edgeTimestamp = maximumSupportedUnixTimestamp.nextDown.nextDown
        let edgeEnvelope = try encodedEnvelope(
            profile: customProfile(.example),
            updatedAt: edgeTimestamp
        )
        cloud.values[key] = edgeEnvelope
        let store = ReviewCardLayoutStore(
            defaults: defaults,
            cloud: cloud,
            now: { Date(timeIntervalSince1970: 900) },
            notificationCenter: center,
            cloudNotificationObject: nil
        )
        #expect(store.profile == .default)

        let changed = customProfile(.partOfSpeech)
        store.update(changed)

        let localJSON = try #require(defaults.string(forKey: key))
        #expect(cloud.values[key] == localJSON)
        #expect(store.profile == changed)
        let object = try #require(
            JSONSerialization.jsonObject(with: Data(localJSON.utf8)) as? [String: Any]
        )
        #expect(object["updatedAt"] as? Double == 900)

        cloud.values[key] = edgeEnvelope
        center.post(
            name: NSUbiquitousKeyValueStore.didChangeExternallyNotification,
            object: nil,
            userInfo: [NSUbiquitousKeyValueStoreChangedKeysKey: [key]]
        )

        #expect(store.profile == changed)
        #expect(defaults.string(forKey: key) == localJSON)
    }

    @Test func supportedNearCeilingBumpsRemainMonotonicAndReloadable() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        let nearCeiling = maximumLegacyUnixTimestamp.nextDown
        cloud.values[key] = try encodedEnvelope(
            profile: customProfile(.example),
            updatedAt: nearCeiling
        )
        let store = ReviewCardLayoutStore(
            defaults: defaults,
            cloud: cloud,
            now: { Date(timeIntervalSince1970: 900) }
        )
        #expect(store.profile == customProfile(.example))

        let changed = customProfile(.partOfSpeech)
        store.update(changed)

        let localJSON = try #require(defaults.string(forKey: key))
        #expect(cloud.values[key] == localJSON)
        let object = try #require(
            JSONSerialization.jsonObject(with: Data(localJSON.utf8)) as? [String: Any]
        )
        let repairedTimestamp = try #require(object["updatedAt"] as? Double)
        #expect(object["version"] as? Int == 2)
        #expect(repairedTimestamp > nearCeiling)
        #expect(repairedTimestamp == maximumLegacyUnixTimestamp)
        #expect(repairedTimestamp < maximumSupportedUnixTimestamp)

        let reloaded = ReviewCardLayoutStore(
            defaults: defaults,
            cloud: cloud,
            now: { Date(timeIntervalSince1970: 900) }
        )
        #expect(reloaded.profile == changed)

        let changedAgain = customProfile(.difficultyTier)
        reloaded.update(changedAgain)

        let twiceUpdatedJSON = try #require(defaults.string(forKey: key))
        #expect(cloud.values[key] == twiceUpdatedJSON)
        let twiceUpdatedObject = try #require(
            JSONSerialization.jsonObject(with: Data(twiceUpdatedJSON.utf8)) as? [String: Any]
        )
        let twiceUpdatedTimestamp = try #require(twiceUpdatedObject["updatedAt"] as? Double)
        #expect(twiceUpdatedObject["version"] as? Int == 2)
        #expect(twiceUpdatedTimestamp > repairedTimestamp)
        #expect(twiceUpdatedTimestamp < maximumSupportedUnixTimestamp)

        let reloadedAgain = ReviewCardLayoutStore(
            defaults: defaults,
            cloud: cloud,
            now: { Date(timeIntervalSince1970: 900) }
        )
        #expect(reloadedAgain.profile == changedAgain)
    }

    @Test func updateWritesOneIdenticalVersionedEnvelopeToEachLayer() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        let store = ReviewCardLayoutStore(
            defaults: defaults,
            cloud: cloud,
            now: { Date(timeIntervalSince1970: 700) }
        )
        let changed = customProfile(.collocations)

        store.update(changed)

        let localJSON = try #require(defaults.string(forKey: key))
        #expect(cloud.setCalls == [key])
        #expect(cloud.values[key] == localJSON)
        let object = try #require(
            JSONSerialization.jsonObject(with: Data(localJSON.utf8)) as? [String: Any]
        )
        #expect(object["version"] as? Int == 2)
        #expect(object["updatedAt"] as? Double == 700)
        #expect(object["profile"] != nil)
    }

    @Test func externalCloudUpdateAppliesOnlyWhenItWinsLWW() throws {
        let defaults = makeDefaults()
        let cloud = ReviewCardLayoutCloudSpy()
        let center = NotificationCenter()
        let initial = customProfile(.example)
        let newer = customProfile(.graphLinks)
        defaults.set(try encodedEnvelope(profile: initial, updatedAt: 100), forKey: key)
        let store = ReviewCardLayoutStore(
            defaults: defaults,
            cloud: cloud,
            notificationCenter: center,
            cloudNotificationObject: nil
        )

        cloud.values[key] = try encodedEnvelope(profile: newer, updatedAt: 200)
        center.post(
            name: NSUbiquitousKeyValueStore.didChangeExternallyNotification,
            object: nil,
            userInfo: [NSUbiquitousKeyValueStoreChangedKeysKey: [key]]
        )
        #expect(store.profile == newer)

        cloud.values[key] = try encodedEnvelope(profile: initial, updatedAt: 150)
        center.post(
            name: NSUbiquitousKeyValueStore.didChangeExternallyNotification,
            object: nil,
            userInfo: [NSUbiquitousKeyValueStoreChangedKeysKey: [key]]
        )
        #expect(store.profile == newer)
    }

    @Test func resetCurrentModeLeavesOtherModeUntouchedThenResetAllRestoresEverything() {
        let store = ReviewCardLayoutStore.inMemory(profile: customProfile(.example))
        let originalProduction = store.profile.production

        store.reset(.recognition)

        #expect(store.profile.recognition == ReviewCardLayoutProfile.default.recognition)
        #expect(store.profile.production == originalProduction)

        store.resetAll()
        #expect(store.profile == .default)
    }

    @Test func inMemoryStoreMutatesWithoutPersistence() {
        let changed = customProfile(.difficultyTier)
        let store = ReviewCardLayoutStore.inMemory()

        store.update(changed)

        #expect(store.profile == changed)
    }

    @Test func environmentValuesSupportsStoreInjection() {
        let store = ReviewCardLayoutStore.inMemory(profile: customProfile(.graphLinks))
        var values = EnvironmentValues()

        values.reviewCardLayoutStore = store

        #expect(values.reviewCardLayoutStore === store)
    }
}

private final class ReviewCardLayoutCloudSpy: CloudKeyValueStore {
    var values: [String: String] = [:]
    var setCalls: [String] = []

    func double(forKey key: String) -> Double? { nil }
    func set(_ value: Double, forKey key: String) {}
    func string(forKey key: String) -> String? { values[key] }
    func set(_ value: String, forKey key: String) {
        values[key] = value
        setCalls.append(key)
    }
}
