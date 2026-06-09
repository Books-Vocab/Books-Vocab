import SwiftUI

@propertyWrapper
struct ObserveInjection {
    var wrappedValue: Int = 0

    init() {}
}

extension View {
    @ViewBuilder
    func enableInjection() -> some View {
        self
    }
}
