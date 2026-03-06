import Foundation
import SwiftData

// Need to match the model exactly
@Model
final class VocabularyEntry {
    var word: String

    init(word: String) {
        self.word = word
    }
}
