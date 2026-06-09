struct TodayReviewSessionState<Entry> {
    var queue: [Entry]
    var currentIndex = 0
    var revealStage: TodayReviewRevealStage = .front

    var currentEntry: Entry? {
        guard currentIndex >= 0, currentIndex < queue.count else { return nil }
        return queue[currentIndex]
    }

    var progressText: String {
        "\(min(currentIndex + 1, queue.count)) / \(queue.count)"
    }

    var canGoPrevious: Bool { currentIndex > 0 }
    var canGoNext: Bool { currentIndex < queue.count - 1 }
    var canShuffle: Bool { queue.count - currentIndex > 1 }
    var remainingCount: Int { max(queue.count - currentIndex - 1, 0) }
    var isComplete: Bool { currentIndex >= queue.count }

    @discardableResult
    mutating func advanceReveal() -> Bool {
        guard revealStage == .front else { return false }
        revealStage.advance()
        return true
    }

    @discardableResult
    mutating func retractReveal() -> Bool {
        guard revealStage == .back else { return false }
        revealStage.retract()
        return true
    }

    @discardableResult
    mutating func goPrevious() -> Bool {
        guard canGoPrevious else { return false }
        revealStage = .front
        currentIndex -= 1
        return true
    }

    @discardableResult
    mutating func goNext() -> Bool {
        guard canGoNext else { return false }
        revealStage = .front
        currentIndex += 1
        return true
    }

    @discardableResult
    mutating func advanceAfterSubmission() -> Bool {
        revealStage = .front
        currentIndex += 1
        return isComplete
    }

    @discardableResult
    mutating func shuffleRemaining() -> Bool {
        var rng = SystemRandomNumberGenerator()
        return shuffleRemaining(using: &rng)
    }

    @discardableResult
    mutating func shuffleRemaining<RNG: RandomNumberGenerator>(using rng: inout RNG) -> Bool {
        guard canShuffle else { return false }
        var tail = Array(queue[currentIndex...])
        tail.shuffle(using: &rng)
        queue.replaceSubrange(currentIndex..., with: tail)
        revealStage = .front
        return true
    }
}
