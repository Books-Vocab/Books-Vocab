import SwiftUI

enum NotebookCoverImageCache {
    private static let cache: NSCache<NSString, UIImage> = {
        let cache = NSCache<NSString, UIImage>()
        cache.countLimit = 96
        cache.totalCostLimit = 32 * 1024 * 1024
        return cache
    }()

    static func image(
        path: String,
        displaySize: CGSize,
        scale: CGFloat,
        loadData: (String) -> Data? = { path in try? Data(contentsOf: URL(fileURLWithPath: path)) }
    ) -> UIImage? {
        let maxDimensionPoints = max(displaySize.width, displaySize.height)
        guard maxDimensionPoints.isFinite, maxDimensionPoints > 0, scale.isFinite, scale > 0 else {
            return nil
        }
        let pixelBound = max(1, Int((maxDimensionPoints * scale).rounded(.up)))
        let key = "\(path)#\(pixelBound)#\(fileSignature(path: path))" as NSString
        if let cached = cache.object(forKey: key) {
            return cached
        }
        guard let data = loadData(path),
              let image = CoverImageDownsampler.downsample(
                data: data,
                maxDimensionPoints: maxDimensionPoints,
                scale: scale
              ) ?? UIImage(data: data) else {
            return nil
        }
        let pixels = Int((image.size.width * image.scale * image.size.height * image.scale).rounded(.up))
        cache.setObject(image, forKey: key, cost: max(1, pixels * 4))
        return image
    }

    static func removeAll() {
        cache.removeAllObjects()
    }

    private static func fileSignature(path: String) -> String {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path) else {
            return "missing"
        }
        let size = (attrs[.size] as? NSNumber)?.intValue ?? 0
        let mtime = (attrs[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        return "\(size):\(mtime)"
    }
}

enum NotebookCoverPattern: String, CaseIterable, Identifiable {
    case dots
    case lines
    case grid
    case waves
    case circles
    case noise

    var id: String { rawValue }

    var label: String {
        switch self {
        case .dots: return L10n.string("圓點")
        case .lines: return L10n.string("條紋")
        case .grid: return L10n.string("格線")
        case .waves: return L10n.string("波浪")
        case .circles: return L10n.string("同心圓")
        case .noise: return L10n.string("噪點")
        }
    }

    @ViewBuilder
    func patternOverlay(size: CGSize) -> some View {
        Canvas { context, canvasSize in
            let w = canvasSize.width
            let h = canvasSize.height
            switch self {
            case .dots:
                let spacing: CGFloat = 16
                let radius: CGFloat = 2.5
                var y: CGFloat = spacing / 2
                while y < h {
                    var x: CGFloat = spacing / 2
                    while x < w {
                        context.fill(
                            Path(ellipseIn: CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2)),
                            with: .color(.white.opacity(NotebookStackMetrics.patternOpacity))
                        )
                        x += spacing
                    }
                    y += spacing
                }
            case .lines:
                let spacing: CGFloat = 12
                let lineWidth: CGFloat = 1.5
                var offset: CGFloat = -h
                while offset < w + h {
                    var path = Path()
                    path.move(to: CGPoint(x: offset, y: 0))
                    path.addLine(to: CGPoint(x: offset - h, y: h))
                    context.stroke(path, with: .color(.white.opacity(NotebookStackMetrics.patternOpacity)), lineWidth: lineWidth)
                    offset += spacing
                }
            case .grid:
                let spacing: CGFloat = 20
                let lineWidth: CGFloat = 0.8
                var x: CGFloat = 0
                while x <= w {
                    var path = Path()
                    path.move(to: CGPoint(x: x, y: 0))
                    path.addLine(to: CGPoint(x: x, y: h))
                    context.stroke(path, with: .color(.white.opacity(NotebookStackMetrics.patternOpacity)), lineWidth: lineWidth)
                    x += spacing
                }
                var y: CGFloat = 0
                while y <= h {
                    var path = Path()
                    path.move(to: CGPoint(x: 0, y: y))
                    path.addLine(to: CGPoint(x: w, y: y))
                    context.stroke(path, with: .color(.white.opacity(NotebookStackMetrics.patternOpacity)), lineWidth: lineWidth)
                    y += spacing
                }
            case .waves:
                let amplitude: CGFloat = 8
                let wavelength: CGFloat = 30
                let spacing: CGFloat = 20
                var yOffset: CGFloat = spacing / 2
                while yOffset < h + amplitude {
                    var path = Path()
                    path.move(to: CGPoint(x: 0, y: yOffset))
                    var x: CGFloat = 0
                    while x <= w {
                        let y = yOffset + amplitude * sin(x / wavelength * .pi * 2)
                        path.addLine(to: CGPoint(x: x, y: y))
                        x += 2
                    }
                    context.stroke(path, with: .color(.white.opacity(NotebookStackMetrics.patternOpacity)), lineWidth: 1.2)
                    yOffset += spacing
                }
            case .circles:
                let centerX = w / 2
                let centerY = h / 2
                let maxRadius = max(w, h) / 2
                var r: CGFloat = 15
                while r < maxRadius {
                    let rect = CGRect(x: centerX - r, y: centerY - r, width: r * 2, height: r * 2)
                    context.stroke(
                        Path(ellipseIn: rect),
                        with: .color(.white.opacity(NotebookStackMetrics.patternOpacity)),
                        lineWidth: 1.0
                    )
                    r += 15
                }
            case .noise:
                let step: CGFloat = 4
                var y: CGFloat = 0
                var seed: UInt64 = 42
                while y < h {
                    var x: CGFloat = 0
                    while x < w {
                        seed = seed &* 6364136223846793005 &+ 1442695040888963407
                        let val = Double((seed >> 33) & 0xFF) / 255.0
                        if val > 0.6 {
                            // noise pattern 維持動態 opacity (per-pixel rand-driven, max ≈ 0.15)。
                            // **不**統一 patternOpacity token — noise 的視覺特色就是 per-pixel
                            // 隨機變化,夾平會變一坨灰塊。Task 7 review 確認 noise 結構上
                            // 必然 < 0.18 = 既有 token,顯式豁免。
                            let opacity = (val - 0.6) * 0.375
                            context.fill(
                                Path(CGRect(x: x, y: y, width: step, height: step)),
                                with: .color(.white.opacity(opacity))
                            )
                        }
                        x += step
                    }
                    y += step
                }
            }
        }
        .allowsHitTesting(false)
    }
}

struct NotebookCoverView: View {
    @ObserveInjection private var inject
    @Environment(\.displayScale) private var displayScale
    let color: Color
    let pattern: NotebookCoverPattern?
    let coverImagePath: String?
    let name: String
    /// 是否在 cover 中央渲染白色 name text。預設 true 保留既有行為(Bookshelf / Podcast /
    /// EditSheet preview / #Preview 等 5 處 callsite zero-touch);NotebookCard 在
    /// 套 editorial overlay 時傳 false,避免雙層 name 疊字。
    var showsName: Bool = true

    var body: some View {
        GeometryReader { geo in
            ZStack {
                color

                if let imagePath = coverImagePath,
                   let coverImage = loadImage(from: imagePath, displaySize: geo.size) {
                    platformImage(coverImage)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(width: geo.size.width, height: geo.size.height)
                        .clipped()
                } else if let pattern {
                    pattern.patternOverlay(size: geo.size)
                }

                if showsName {
                    Text(name)
                        .font(AppFonts.body(weight: .semibold))
                        .foregroundStyle(.white)
                        .shadow(color: .black.opacity(0.3), radius: 2, y: 1) // token-allow: cover text legibility shadow, not UI elevation
                        .lineLimit(2)
                        .truncationMode(.tail)
                        .minimumScaleFactor(0.85)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, AppSpacing.s2)
                }
            }
        }
        .enableInjection()
    }

    private func loadImage(from path: String, displaySize: CGSize) -> UIImage? {
        NotebookCoverImageCache.image(path: path, displaySize: displaySize, scale: displayScale)
    }
    private func platformImage(_ image: UIImage) -> Image {
        Image(uiImage: image)
    }
}

#Preview {
    LazyVGrid(columns: [GridItem(.adaptive(minimum: 120))], spacing: AppSpacing.s3) {
        ForEach(NotebookCoverPattern.allCases) { pattern in
            NotebookCoverView(
                color: Color(hex: "#4A90D9") ?? .blue, // token-allow: preview fixture notebook data color
                pattern: pattern,
                coverImagePath: nil,
                name: pattern.label
            )
            .frame(height: 80)
            .clipShape(AppRoundedRect(roundness: AppRoundness.card))
        }
    }
    .padding()
}
