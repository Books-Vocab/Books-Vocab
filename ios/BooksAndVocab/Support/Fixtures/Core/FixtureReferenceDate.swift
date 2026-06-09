import Foundation
import SwiftUI

private struct FixtureReferenceDateKey: EnvironmentKey {
    static let defaultValue: Date? = nil
}

extension EnvironmentValues {
    var fixtureReferenceDate: Date? {
        get { self[FixtureReferenceDateKey.self] }
        set { self[FixtureReferenceDateKey.self] = newValue }
    }
}
