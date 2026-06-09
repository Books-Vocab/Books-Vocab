import CoreGraphics
import Foundation
import Testing
@testable import BooksAndVocab

struct PodcastSeekBarGeometryTests {
    @Test func timeMapsTrackPositionToDuration() {
        #expect(PodcastSeekBarGeometry.time(locationX: 50, width: 200, duration: 120) == 30)
        #expect(PodcastSeekBarGeometry.time(locationX: 100, width: 200, duration: 120) == 60)
    }

    @Test func timeClampsOutsideTrack() {
        #expect(PodcastSeekBarGeometry.time(locationX: -20, width: 200, duration: 120) == 0)
        #expect(PodcastSeekBarGeometry.time(locationX: 260, width: 200, duration: 120) == 120)
    }

    @Test func timeReturnsZeroWhenUnavailable() {
        #expect(PodcastSeekBarGeometry.time(locationX: 50, width: 0, duration: 120) == 0)
        #expect(PodcastSeekBarGeometry.time(locationX: 50, width: 200, duration: 0) == 0)
    }

    @Test func progressWidthClampsToTrack() {
        #expect(PodcastSeekBarGeometry.progressWidth(time: 30, duration: 120, totalWidth: 200) == 50)
        #expect(PodcastSeekBarGeometry.progressWidth(time: -10, duration: 120, totalWidth: 200) == 0)
        #expect(PodcastSeekBarGeometry.progressWidth(time: 240, duration: 120, totalWidth: 200) == 200)
    }

    @Test func bufferedWidthClampsToTrack() {
        #expect(PodcastSeekBarGeometry.bufferedWidth(bufferedEnd: 90, duration: 120, totalWidth: 200) == 150)
        #expect(PodcastSeekBarGeometry.bufferedWidth(bufferedEnd: -1, duration: 120, totalWidth: 200) == 0)
        #expect(PodcastSeekBarGeometry.bufferedWidth(bufferedEnd: 300, duration: 120, totalWidth: 200) == 200)
    }
}
