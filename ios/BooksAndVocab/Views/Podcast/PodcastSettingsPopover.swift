#if os(iOS)
import SwiftUI
import UIKit

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

    var subtitleFont: Font {
        switch self {
        case .small:   return AppFonts.sans(size: 13)
        case .medium:  return AppFonts.sans(size: 15)
        case .large:   return AppFonts.sans(size: 17)
        case .xLarge:  return AppFonts.sans(size: 19)
        case .xxLarge: return AppFonts.sans(size: 22)
        }
    }

    var speakerFont: Font {
        switch self {
        case .small:   return AppFonts.mono(size: 9, bold: true)
        case .medium:  return AppFonts.mono(size: 10, bold: true)
        case .large:   return AppFonts.mono(size: 11, bold: true)
        case .xLarge:  return AppFonts.mono(size: 12, bold: true)
        case .xxLarge: return AppFonts.mono(size: 13, bold: true)
        }
    }

    var uiSubtitleFont: UIFont {
        switch self {
        case .small:   return AppFonts.uiSans(size: 13)
        case .medium:  return AppFonts.uiSans(size: 15)
        case .large:   return AppFonts.uiSans(size: 17)
        case .xLarge:  return AppFonts.uiSans(size: 19)
        case .xxLarge: return AppFonts.uiSans(size: 22)
        }
    }
}

struct PodcastSettingsPopover: View {
    @ObserveInjection private var inject
    @Binding var subtitleSize: PodcastSubtitleSize
    @Binding var autoPauseOnLookup: Bool
    @Binding var sleepTimerMode: SleepTimerMode
    let sleepDeadline: Date?
    @AppStorage("podcast.wordFollowEnabled") private var wordFollowEnabled: Bool = true
    @Environment(\.appSkin) private var skin
    @Environment(\.readerSettings) private var readerSettings

    var body: some View {
        VStack(alignment: .leading, spacing: skin.spacing.sectionGap) {
            VStack(alignment: .leading, spacing: skin.spacing.inlineGap) {
                Text(L10n.string("字幕大小"))
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
                Picker(L10n.string("字幕大小"), selection: $subtitleSize) {
                    ForEach(PodcastSubtitleSize.allCases) { size in
                        Text(size.label).tag(size)
                    }
                }
                .pickerStyle(.segmented)
            }

            VocabHighlightColorPresetPicker(
                selection: highlightColorPresetBinding,
                title: L10n.string("vocab.highlight.color.label")
            )

            Toggle(isOn: $wordFollowEnabled) {
                VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                    Text(L10n.string("逐字跟隨"))
                        .font(skin.typography.body)
                    Text(L10n.string("顯示目前播放到的單字底線，關閉後改為純句子跟隨"))
                        .font(skin.typography.caption)
                        .foregroundStyle(skin.palette.secondaryText)
                }
            }

            Toggle(isOn: $autoPauseOnLookup) {
                VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                    Text(L10n.string("查詞時自動暫停"))
                        .font(skin.typography.body)
                    Text(L10n.string("點字幕查單字時暫停播放，關閉後恢復"))
                        .font(skin.typography.caption)
                        .foregroundStyle(skin.palette.secondaryText)
                }
            }

            VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                Picker(L10n.string("睡眠定時"), selection: $sleepTimerMode) {
                    Text(L10n.string("關閉")).tag(SleepTimerMode.off)
                    Text(L10n.string("5 分鐘")).tag(SleepTimerMode.minutes(5))
                    Text(L10n.string("15 分鐘")).tag(SleepTimerMode.minutes(15))
                    Text(L10n.string("30 分鐘")).tag(SleepTimerMode.minutes(30))
                    Text(L10n.string("60 分鐘")).tag(SleepTimerMode.minutes(60))
                    Text(L10n.string("結束本集")).tag(SleepTimerMode.endOfEpisode)
                }
                .pickerStyle(.menu)

                if let deadline = sleepDeadline {
                    TimelineView(.periodic(from: .now, by: 1)) { ctx in
                        let remaining = max(0, Int(deadline.timeIntervalSince(ctx.date)))
                        Text(L10n.format("剩餘 %@", Self.formatMMSS(remaining)))
                            .font(skin.typography.caption)
                            .foregroundStyle(skin.palette.secondaryText)
                    }
                }
            }
        }
        .padding(skin.spacing.cardPadding)
        .frame(minWidth: 280)
        .enableInjection()
    }

    private static func formatMMSS(_ seconds: Int) -> String {
        String(format: "%d:%02d", seconds / 60, seconds % 60)
    }

    private var highlightColorPresetBinding: Binding<VocabHighlightColorPreset> {
        Binding(
            get: { readerSettings.vocabHighlightColorPreset },
            set: { readerSettings.vocabHighlightColorPreset = $0 }
        )
    }
}
#endif
