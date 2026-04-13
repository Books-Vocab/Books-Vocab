#if os(iOS)
import SwiftUI

/// 字幕大小（與 Reader 概念對齊，但 persisted 分開）
enum PodcastSubtitleSize: String, CaseIterable, Identifiable {
    case small, medium, large, xLarge, xxLarge
    var id: String { rawValue }
    var label: String {
        switch self {
        case .small:   return "S"
        case .medium:  return "M"
        case .large:   return "L"
        case .xLarge:  return "XL"
        case .xxLarge: return "XXL"
        }
    }
    var dynamicTypeSize: DynamicTypeSize {
        switch self {
        case .small:   return .small
        case .medium:  return .medium
        case .large:   return .large
        case .xLarge:  return .xLarge
        case .xxLarge: return .xxLarge
        }
    }
}

struct PodcastSettingsPopover: View {
    @Binding var subtitleSize: PodcastSubtitleSize
    @Binding var autoPauseOnLookup: Bool
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        VStack(alignment: .leading, spacing: skin.spacing.sectionGap) {
            VStack(alignment: .leading, spacing: skin.spacing.inlineGap) {
                Text("字幕大小")
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
                Picker("字幕大小", selection: $subtitleSize) {
                    ForEach(PodcastSubtitleSize.allCases) { size in
                        Text(size.label).tag(size)
                    }
                }
                .pickerStyle(.segmented)
            }

            Toggle(isOn: $autoPauseOnLookup) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("查詞時自動暫停")
                        .font(skin.typography.body)
                    Text("點字幕查單字時暫停播放，關閉後恢復")
                        .font(skin.typography.caption)
                        .foregroundStyle(skin.palette.secondaryText)
                }
            }
        }
        .padding(skin.spacing.cardPadding)
        .frame(minWidth: 280)
    }
}
#endif
