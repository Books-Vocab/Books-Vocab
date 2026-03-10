import Foundation
import SwiftData

struct ReviewSessionStore {
    private static let key = "kg.review.shuffledOrder"

    /// 保存洗牌後的 entry ID 順序
    static func saveOrder(_ ids: [UUID]) {
        let strings = ids.map(\.uuidString)
        UserDefaults.standard.set(strings, forKey: key)
    }

    /// 讀取已保存的順序，過濾掉已不存在的 entry，並附加新增的 entry
    static func loadOrder(availableEntries: [VocabularyEntry]) -> [VocabularyEntry]? {
        guard let strings = UserDefaults.standard.stringArray(forKey: key),
              !strings.isEmpty else { return nil }

        let savedIDs = strings.compactMap(UUID.init)
        let entryMap = Dictionary(uniqueKeysWithValues: availableEntries.map { ($0.id, $0) })
        let ordered = savedIDs.compactMap { entryMap[$0] }

        // 加入新增的 entry（不在已保存順序中的）
        let savedIDSet = Set(savedIDs)
        let newEntries = availableEntries.filter { !savedIDSet.contains($0.id) }

        let result = ordered + newEntries
        guard !result.isEmpty else { return nil }
        return result
    }

    /// 清除保存的順序
    static func clear() {
        UserDefaults.standard.removeObject(forKey: key)
    }
}
