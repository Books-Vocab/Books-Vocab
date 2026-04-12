import SwiftUI
import SwiftData

struct PodcastEpisodeDestination: Hashable {
    let episodeId: String
}

struct PodcastEpisodeListView: View {
    let seriesId: String
    @Environment(\.vocabSkin) private var skin
    @Environment(\.appTheme) private var theme
    @Environment(\.modelContext) private var modelContext

    @Query(sort: \PodcastEpisode.episodeNumber) private var allEpisodes: [PodcastEpisode]

    private var episodes: [PodcastEpisode] {
        allEpisodes.filter { $0.series?.remoteId == seriesId }
    }

    private var seriesTitle: String {
        episodes.first?.series?.title ?? ""
    }

    var body: some View {
        Group {
            if episodes.isEmpty {
                VStack(spacing: skin.spacing.sectionGap) {
                    Image(systemName: "waveform")
                        .font(.largeTitle)
                        .foregroundStyle(skin.palette.tertiaryText)
                    Text("尚無集數")
                        .font(skin.typography.sectionTitle)
                        .foregroundStyle(skin.palette.secondaryText)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List {
                    ForEach(episodes) { episode in
                        NavigationLink {
                            PodcastPlayerView(episodeId: episode.remoteId)
                        } label: {
                            PodcastEpisodeRow(episode: episode)
                        }
                        .disabled(!episode.audioAvailable)
                    }
                }
                .listStyle(.insetGrouped)
            }
        }
        .navigationTitle(seriesTitle)
    }
}
