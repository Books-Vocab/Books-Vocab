import SwiftUI

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
        case .dots: return "圓點"
        case .lines: return "條紋"
        case .grid: return "格線"
        case .waves: return "波浪"
        case .circles: return "同心圓"
        case .noise: return "噪點"
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
                            with: .color(.white.opacity(0.15))
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
                    context.stroke(path, with: .color(.white.opacity(0.12)), lineWidth: lineWidth)
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
                    context.stroke(path, with: .color(.white.opacity(0.10)), lineWidth: lineWidth)
                    x += spacing
                }
                var y: CGFloat = 0
                while y <= h {
                    var path = Path()
                    path.move(to: CGPoint(x: 0, y: y))
                    path.addLine(to: CGPoint(x: w, y: y))
                    context.stroke(path, with: .color(.white.opacity(0.10)), lineWidth: lineWidth)
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
                    context.stroke(path, with: .color(.white.opacity(0.12)), lineWidth: 1.2)
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
                        with: .color(.white.opacity(0.10)),
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
    let color: Color
    let pattern: NotebookCoverPattern?
    let coverImagePath: String?
    let name: String

    var body: some View {
        GeometryReader { geo in
            ZStack {
                color

                if let imagePath = coverImagePath, let uiImage = loadImage(from: imagePath) {
                    Image(uiImage: uiImage)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(width: geo.size.width, height: geo.size.height)
                        .clipped()
                } else if let pattern {
                    pattern.patternOverlay(size: geo.size)
                }

                Text(name)
                    .font(.system(size: 15, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)
                    .shadow(color: .black.opacity(0.3), radius: 2, y: 1)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 8)
            }
        }
    }

    #if os(macOS)
    private func loadImage(from path: String) -> NSImage? {
        NSImage(contentsOfFile: path)
    }
    #else
    private func loadImage(from path: String) -> UIImage? {
        UIImage(contentsOfFile: path)
    }
    #endif
}

#Preview {
    LazyVGrid(columns: [GridItem(.adaptive(minimum: 120))], spacing: 12) {
        ForEach(NotebookCoverPattern.allCases) { pattern in
            NotebookCoverView(
                color: Color(hex: "#4A90D9") ?? .blue,
                pattern: pattern,
                coverImagePath: nil,
                name: pattern.label
            )
            .frame(height: 80)
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
    }
    .padding()
}
