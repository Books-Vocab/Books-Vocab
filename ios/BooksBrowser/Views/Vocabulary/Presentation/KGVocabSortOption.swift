import Foundation

enum KGVocabSortOption: String, CaseIterable, Identifiable {
    case `default`
    case alphabetical
    case dateAdded
    case difficulty

    var id: String { rawValue }

    var label: String {
        switch self {
        case .default: return L10n.string("複習優先")
        case .alphabetical: return L10n.string("字母序")
        case .dateAdded: return L10n.string("最近新增")
        case .difficulty: return L10n.string("難度")
        }
    }

    var systemImage: String {
        switch self {
        case .default: return "flame"
        case .alphabetical: return "textformat.abc"
        case .dateAdded: return "calendar"
        case .difficulty: return "chart.bar"
        }
    }
}
