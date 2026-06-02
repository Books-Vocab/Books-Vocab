//
//  MacColumnResizeCursor.swift
//  BooksBrowser
//
//  可拖曳分隔線的欄寬調整游標 — Catalyst 專屬。
//  SwiftUI .pointerStyle(iOS 18+) 在 Mac Catalyst 不可用,故走 UIKit UIPointerInteraction。
//

import SwiftUI

#if targetEnvironment(macCatalyst)
/// 疊在 DraggableDivider hit area 上,hover 時把游標切成直立 beam(近似欄寬調整)。
///
/// 拖曳保護:UIPointerInteraction 需 view 參與 hit-test 才能收到 pointer region,
/// 但若 view 同時吃掉 touch 事件,底下 SwiftUI 的 `highPriorityGesture(dragGesture)` 就拖不動。
/// Catalyst 下滑鼠/觸控板拖曳以 `event.type == .touches` 遞送,而 hover 的 pointer region
/// 查詢不帶 touch event。故 `PassthroughPointerView` 對 touch hitTest 回 nil(讓拖曳穿透到
/// SwiftUI),其餘(hover)回 self(pointer interaction 生效)。
struct MacColumnResizeCursor: UIViewRepresentable {
    /// `.horizontal` 分隔線（調欄寬）→ 直立 beam；`.vertical` 分隔線（調 block 高）→ 橫向 beam。
    var axis: Axis = .horizontal

    func makeUIView(context: Context) -> UIView {
        let view = PassthroughPointerView()
        view.backgroundColor = .clear
        view.addInteraction(UIPointerInteraction(delegate: context.coordinator))
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(axis: axis) }

    final class Coordinator: NSObject, UIPointerInteractionDelegate {
        let axis: Axis
        init(axis: Axis) { self.axis = axis }

        func pointerInteraction(
            _ interaction: UIPointerInteraction,
            styleFor region: UIPointerRegion
        ) -> UIPointerStyle? {
            // beam = 分隔線上的尺寸調整提示(Catalyst 無原生 resize 游標,beam 為最接近近似)。
            // length 為 cursor glyph 長度(與 divider 實際長度無關),24pt 為經驗值。
            // 水平 divider(調寬)→ verticalBeam;垂直 divider(調高)→ horizontalBeam。
            let shape: UIPointerShape = axis == .horizontal
                ? .verticalBeam(length: 24)
                : .horizontalBeam(length: 24)
            return UIPointerStyle(shape: shape)
        }
    }

    /// touch 事件穿透到底下 SwiftUI gesture;hover(非 touch)保留以供 pointer interaction。
    private final class PassthroughPointerView: UIView {
        override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? {
            if event?.type == .touches { return nil }
            return super.hitTest(point, with: event)
        }
    }
}
#endif
