import SwiftUI

/// Podcast 播放器專用版面參數（seek bar、控制列）。
enum PodcastPlayerMetrics {
    static let seekBarTrackHeight: CGFloat = 5
    static let seekBarThumbSize: CGFloat = 16
    static let seekBarThumbOffset: CGFloat = 8
    static let seekBarHitArea: CGFloat = 20
    static let controlsClusterSpacing: CGFloat = 8
    static let controlsBottomPadding: CGFloat = 20
}

enum PodcastSeekBarGeometry {
    static func time(
        locationX: CGFloat,
        width: CGFloat,
        duration: TimeInterval
    ) -> TimeInterval {
        guard width > 0, duration > 0 else { return 0 }
        let ratio = max(0, min(1, Double(locationX / width)))
        return ratio * duration
    }

    static func progressWidth(
        time: TimeInterval,
        duration: TimeInterval,
        totalWidth: CGFloat
    ) -> CGFloat {
        guard duration > 0, totalWidth > 0 else { return 0 }
        let ratio = max(0, min(1, time / duration))
        return CGFloat(ratio) * totalWidth
    }

    static func bufferedWidth(
        bufferedEnd: TimeInterval,
        duration: TimeInterval,
        totalWidth: CGFloat
    ) -> CGFloat {
        guard duration > 0, totalWidth > 0 else { return 0 }
        let ratio = max(0, min(1, bufferedEnd / duration))
        return CGFloat(ratio) * totalWidth
    }
}
