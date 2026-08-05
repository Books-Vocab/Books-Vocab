import SwiftUI

struct ProgressCapsule: View {
    @ObserveInjection private var inject
    let progress: Double
    let label: String?
    var fillColor: Color
    var trackColor: Color
    var labelFont: Font = AppFonts.monoNumbers(size: 11)
    var height: CGFloat = 6

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                AppRoundedRect(roundness: AppRoundness.pill)
                    .fill(trackColor)

                AppRoundedRect(roundness: AppRoundness.pill)
                    .fill(fillColor)
                    .frame(width: max(0, geo.size.width * min(1, max(0, progress))))
            }
        }
        .frame(height: height)
        .overlay(alignment: .trailing) {
            if let label {
                Text(label)
                    .font(labelFont)
                    .foregroundStyle(fillColor)
                    .padding(.trailing, AppSpacing.microGap)
            }
        }
        .enableInjection()
    }
}

#Preview {
    VStack(spacing: AppSpacing.s4) {
        ProgressCapsule(progress: 0.67, label: "67%", fillColor: .blue, trackColor: .blue.opacity(0.15))
        ProgressCapsule(progress: 0.0, label: "0%", fillColor: .green, trackColor: .green.opacity(0.15))
        ProgressCapsule(progress: 1.0, label: "100%", fillColor: .orange, trackColor: .orange.opacity(0.15))
    }
    .padding()
}
