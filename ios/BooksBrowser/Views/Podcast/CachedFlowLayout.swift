import SwiftUI

/// Flow layout with cached sizeThatFits so placement doesn't re-measure.
struct CachedFlowLayout: Layout {
    let spacing: CGFloat

    struct LayoutData {
        var size: CGSize
        var offsets: [CGPoint]
    }

    func makeCache(subviews: Subviews) -> LayoutData {
        LayoutData(size: .zero, offsets: [])
    }

    func sizeThatFits(
        proposal: ProposedViewSize, subviews: Subviews, cache: inout LayoutData
    ) -> CGSize {
        cache = computeLayout(proposal: proposal, subviews: subviews)
        return cache.size
    }

    func placeSubviews(
        in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews,
        cache: inout LayoutData
    ) {
        for (index, offset) in cache.offsets.enumerated() {
            subviews[index].place(
                at: CGPoint(x: bounds.minX + offset.x, y: bounds.minY + offset.y),
                proposal: .unspecified
            )
        }
    }

    private func computeLayout(
        proposal: ProposedViewSize, subviews: Subviews
    ) -> LayoutData {
        let maxWidth = proposal.width ?? .infinity
        var offsets: [CGPoint] = []
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, maxX: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0; y += rowHeight + spacing; rowHeight = 0
            }
            offsets.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            maxX = max(maxX, x)
        }
        return LayoutData(
            size: CGSize(width: maxX, height: y + rowHeight),
            offsets: offsets
        )
    }
}
