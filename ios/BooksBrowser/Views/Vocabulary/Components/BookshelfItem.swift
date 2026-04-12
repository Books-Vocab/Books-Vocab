import Foundation

enum BookshelfDestination: Hashable {
    case notebook(String)
    case podcast(String)
}

// SwiftData @Model classes conform to Hashable via PersistentModel.
enum BookshelfItem: Identifiable, Hashable {
    case notebook(Notebook)
    case podcastSeries(PodcastSeries)

    var id: String {
        switch self {
        case .notebook(let n): "nb-\(n.remoteId)"
        case .podcastSeries(let p): "ps-\(p.remoteId)"
        }
    }

    var sortDate: Date {
        switch self {
        case .notebook(let n): n.updatedAt
        case .podcastSeries(let p): p.updatedAt
        }
    }
}
