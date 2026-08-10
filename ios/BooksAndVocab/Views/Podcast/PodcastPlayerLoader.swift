#if os(iOS)
import Foundation

enum PodcastPlayerResolvedSubtitle: Equatable {
    case content(String)
    case unavailable
    case failed
}

enum PodcastPlayerLoader {
    static func resolveSubtitle(
        from source: PodcastPlayerLoadPlan.SubtitleSource,
        kgService: any AuthTokenProviding,
        fetchRemote: @escaping (String, any AuthTokenProviding) async -> String? = fetchSubtitle
    ) async -> PodcastPlayerResolvedSubtitle {
        switch source {
        case .inline(let inline):
            return .content(inline)
        case .remote(let subtitleURLStr):
            if let subtitle = await fetchRemote(subtitleURLStr, kgService) {
                return .content(subtitle)
            }
            return .failed
        case .unavailable:
            return .unavailable
        }
    }

    static func resolveAudioHeaders(
        for plan: PodcastPlayerLoadPlan,
        kgService: any AuthTokenProviding,
        tokenProvider: @escaping (any AuthTokenProviding) async throws -> String = currentAuthToken
    ) async throws -> [String: String] {
        if plan.usesLocalAudio {
            return [:]
        }
        let token = try await tokenProvider(kgService)
        return ["Authorization": "Bearer \(token)"]
    }

    static func fetchSubtitle(urlString: String, kgService: any AuthTokenProviding) async -> String? {
        guard let data = try? await PodcastSyncService.authedData(
            from: urlString, kgService: kgService
        ) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func currentAuthToken(_ kgService: any AuthTokenProviding) async throws -> String {
        try await kgService.currentAuthToken()
    }
}
#endif
