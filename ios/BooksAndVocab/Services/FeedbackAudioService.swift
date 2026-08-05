import AVFoundation
import Foundation

enum FeedbackSound: Hashable {
    case tap
    case review
    case success
    case warning
    case error
}

/// Short, non-verbal UI sounds. TTS and Podcast playback deliberately use
/// their existing services and are not routed through this type.
final class FeedbackAudioService: NSObject {
    static let shared = FeedbackAudioService()

    private var players: [FeedbackSound: AVAudioPlayer] = [:]

    override init() {
        super.init()
        preparePlayers()
    }

    func play(_ sound: FeedbackSound) {
        guard let player = players[sound] else { return }
        player.currentTime = 0
        player.play()
    }

    private func preparePlayers() {
        let sounds: [(FeedbackSound, [(frequency: Double, duration: Double)])] = [
            (.tap, [(880, 0.035)]),
            (.review, [(520, 0.055)]),
            (.success, [(660, 0.06), (880, 0.08)]),
            (.warning, [(440, 0.08), (350, 0.08)]),
            (.error, [(300, 0.10), (220, 0.12)])
        ]

        for (sound, tones) in sounds {
            guard let player = try? AVAudioPlayer(data: Self.makeWAVData(tones: tones)) else { continue }
            player.volume = 0.35
            player.prepareToPlay()
            players[sound] = player
        }
    }

    /// Generates tiny PCM assets in memory so the app does not need a sound
    /// asset bundle for five simple UI feedback tones.
    private static func makeWAVData(
        tones: [(frequency: Double, duration: Double)],
        sampleRate: Double = 44_100
    ) -> Data {
        var samples: [Int16] = []
        var phase = 0.0

        for tone in tones {
            let sampleCount = Int(tone.duration * sampleRate)
            for index in 0..<sampleCount {
                let progress = Double(index) / Double(max(sampleCount - 1, 1))
                let envelope = min(progress / 0.08, (1 - progress) / 0.16, 1.0)
                let value = sin(phase) * 0.55 * max(envelope, 0)
                samples.append(Int16(value * Double(Int16.max)))
                phase += (2 * .pi * tone.frequency) / sampleRate
            }
        }

        let dataSize = UInt32(samples.count * MemoryLayout<Int16>.size)
        let byteRate = UInt32(sampleRate) * 2
        var data = Data()
        data.append(contentsOf: Array("RIFF".utf8))
        data.appendLittleEndian(36 + dataSize)
        data.append(contentsOf: Array("WAVE".utf8))
        data.append(contentsOf: Array("fmt ".utf8))
        data.appendLittleEndian(UInt32(16))
        data.appendLittleEndian(UInt16(1))
        data.appendLittleEndian(UInt16(1))
        data.appendLittleEndian(UInt32(sampleRate))
        data.appendLittleEndian(byteRate)
        data.appendLittleEndian(UInt16(2))
        data.appendLittleEndian(UInt16(16))
        data.append(contentsOf: Array("data".utf8))
        data.appendLittleEndian(dataSize)
        for sample in samples {
            data.appendLittleEndian(sample)
        }
        return data
    }
}

private extension Data {
    mutating func appendLittleEndian<T: FixedWidthInteger>(_ value: T) {
        var littleEndian = value.littleEndian
        Swift.withUnsafeBytes(of: &littleEndian) { append(contentsOf: $0) }
    }
}
