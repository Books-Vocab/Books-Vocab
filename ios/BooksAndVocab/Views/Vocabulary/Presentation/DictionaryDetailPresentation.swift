import Foundation

struct DictionaryDetailPresentation: Equatable {
    struct Provenance: Equatable {
        let provider: String
        let sourceURL: String
        let licenseName: String
        let licenseURL: String
        let attributionText: String
    }

    let word: String
    let pronunciations: [String]
    let selectedSense: LexicalSense
    let selectedExample: LexicalExample?
    let otherSenses: [LexicalSense]
    let translations: [String]
    let forms: [String]
    let provenance: Provenance

    static func make(from entry: VocabularyEntry) -> Self? {
        guard let payload = entry.dictionaryPayloadJSON?.data(using: .utf8),
              let lexical = try? JSONDecoder().decode(LexicalEntry.self, from: payload),
              let selectedSense = lexical.senses.first(where: {
                  $0.id == entry.dictionarySelectedSenseKey
              }) ?? lexical.senses.first else {
            return nil
        }
        let selectedExample = selectedSense.examples.first(where: {
            $0.id == entry.dictionarySelectedExampleKey
        }) ?? selectedSense.examples.first
        return Self(
            word: lexical.word,
            pronunciations: lexical.pronunciations,
            selectedSense: selectedSense,
            selectedExample: selectedExample,
            otherSenses: lexical.senses.filter { $0.id != selectedSense.id },
            translations: selectedSense.translations,
            forms: lexical.forms,
            provenance: Provenance(
                provider: entry.dictionaryProvider ?? lexical.provider,
                sourceURL: entry.dictionarySourceURL ?? lexical.sourceUrl,
                licenseName: entry.dictionaryLicenseName ?? lexical.licenseName,
                licenseURL: entry.dictionaryLicenseURL ?? lexical.licenseUrl,
                attributionText: entry.dictionaryAttributionText ?? lexical.attributionText
            )
        )
    }

    var shareText: String {
        let lines: [String?] = [
            word,
            selectedSense.partOfSpeech,
            pronunciations.joined(separator: " · "),
            selectedSense.definition,
            selectedExample?.text,
            translations.joined(separator: " · "),
            "\(L10n.string("dictionary.provenance.provider")): \(provenance.provider)",
            "\(L10n.string("dictionary.provenance.source")): \(provenance.sourceURL)",
            "\(L10n.string("dictionary.provenance.license")): \(provenance.licenseName) \(provenance.licenseURL)",
            provenance.attributionText,
        ]
        return lines.compactMap { $0?.nilIfBlank }.joined(separator: "\n")
    }
}

enum DictionaryPromotionFailure: Equatable {
    case quotaExhausted
    case enrichmentFailed
    case timedOut
    case unknown(String?)

    /// Client-side code for "we stopped waiting", distinct from any server-supplied
    /// failure reason. Written by `WordDetailSceneState.promoteDictionary` when the
    /// poll budget runs out. Always retryable — enrichment may still be running
    /// server-side, and a retry just re-reads the card.
    static let timeoutErrorCode = "promotion_timeout"

    static func classify(code: String?) -> Self {
        switch code {
        case "quota_exhausted": .quotaExhausted
        case "enrichment_failed": .enrichmentFailed
        case Self.timeoutErrorCode: .timedOut
        default: .unknown(code)
        }
    }

    var message: String {
        switch self {
        case .quotaExhausted: L10n.string("dictionary.promotion.error.quota")
        case .enrichmentFailed: L10n.string("dictionary.promotion.error.enrichment")
        case .timedOut: L10n.string("dictionary.promotion.error.timeout")
        case .unknown: L10n.string("dictionary.promotion.error.unknown")
        }
    }
}

private extension String {
    var nilIfBlank: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
