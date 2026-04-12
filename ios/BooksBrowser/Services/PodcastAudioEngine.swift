import Foundation
import AVFoundation
import QuartzCore

final class PodcastAudioEngine: NSObject {
    private var audioEngine = AVAudioEngine()
    private var playerNode = AVAudioPlayerNode()
    private var timePitchNode = AVAudioUnitTimePitch()
    private var audioFile: AVAudioFile?
    private var segmentStartTime: TimeInterval = 0
    private var ignoreNextCompletion = false
    private var displayLink: CADisplayLink?

    private(set) var playbackRate: Float = 1.0
    var onTimeUpdate: ((TimeInterval) -> Void)?
    var onPlaybackFinished: (() -> Void)?

    static let rateSteps: [Float] = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

    static func nextRate(after current: Float) -> Float {
        guard let idx = rateSteps.firstIndex(where: { abs($0 - current) < 0.01 }) else {
            return 1.0
        }
        return rateSteps[(idx + 1) % rateSteps.count]
    }

    override init() {
        super.init()
        audioEngine.attach(playerNode)
        audioEngine.attach(timePitchNode)
    }

    deinit {
        displayLink?.invalidate()
        audioEngine.stop()
    }

    func loadAudio(url: URL) throws {
        if audioEngine.isRunning { audioEngine.stop() }
        ignoreNextCompletion = true
        playerNode.stop()

        audioFile = try AVAudioFile(forReading: url)
        guard let audioFile else { throw PodcastAudioEngineError.invalidFile }

        let format = audioFile.processingFormat
        audioEngine.disconnectNodeOutput(playerNode)
        audioEngine.disconnectNodeOutput(timePitchNode)
        audioEngine.connect(playerNode, to: timePitchNode, format: format)
        audioEngine.connect(timePitchNode, to: audioEngine.mainMixerNode, format: format)
        timePitchNode.rate = playbackRate

        try audioEngine.start()
        segmentStartTime = 0
        scheduleFile()
        ignoreNextCompletion = false
    }

    func play() {
        if !audioEngine.isRunning { try? audioEngine.start() }
        playerNode.play()
        startDisplayLink()
    }

    func pause() {
        playerNode.pause()
        stopDisplayLink()
    }

    func seek(to time: TimeInterval, autoResume: Bool) {
        guard let audioFile else { return }
        let sampleRate = audioFile.processingFormat.sampleRate
        let startFrame = AVAudioFramePosition(time * sampleRate)
        let frameCount = audioFile.length - startFrame
        guard startFrame >= 0, frameCount > 0 else { return }

        ignoreNextCompletion = true
        playerNode.stop()
        playerNode.scheduleSegment(
            audioFile,
            startingFrame: startFrame,
            frameCount: AVAudioFrameCount(frameCount),
            at: nil
        ) { [weak self] in self?.handleCompletion() }
        segmentStartTime = time
        if autoResume { play() }
        ignoreNextCompletion = false
    }

    func setRate(_ rate: Float) {
        playbackRate = max(0.5, min(rate, 2.0))
        timePitchNode.rate = playbackRate
    }

    var duration: TimeInterval {
        guard let f = audioFile else { return 0 }
        return Double(f.length) / f.processingFormat.sampleRate
    }

    var currentTime: TimeInterval {
        guard let nodeTime = playerNode.lastRenderTime,
              let playerTime = playerNode.playerTime(forNodeTime: nodeTime) else {
            return segmentStartTime
        }
        let sampleRate = audioFile?.processingFormat.sampleRate ?? 44100
        return segmentStartTime + Double(playerTime.sampleTime) / sampleRate
    }

    var isPlaying: Bool { playerNode.isPlaying }

    // MARK: - Private

    private func scheduleFile() {
        guard let audioFile else { return }
        playerNode.scheduleFile(audioFile, at: nil) { [weak self] in
            self?.handleCompletion()
        }
    }

    private func handleCompletion() {
        guard !ignoreNextCompletion else {
            ignoreNextCompletion = false
            return
        }
        DispatchQueue.main.async { [weak self] in
            self?.stopDisplayLink()
            self?.onPlaybackFinished?()
        }
    }

    private func startDisplayLink() {
        guard displayLink == nil else { return }
        displayLink = CADisplayLink(target: self, selector: #selector(displayLinkFired))
        displayLink?.preferredFrameRateRange = CAFrameRateRange(minimum: 15, maximum: 30, preferred: 30)
        displayLink?.add(to: .main, forMode: .common)
    }

    private func stopDisplayLink() {
        displayLink?.invalidate()
        displayLink = nil
    }

    @objc private func displayLinkFired() {
        onTimeUpdate?(currentTime)
    }
}

enum PodcastAudioEngineError: LocalizedError {
    case invalidFile
    var errorDescription: String? { "Invalid audio file" }
}
