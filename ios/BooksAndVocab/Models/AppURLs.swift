import Foundation

enum AppURLs {
    static let domain = BrandIdentity.publicBaseURL
    // swiftlint:disable force_unwrapping
    static let privacy = URL(string: "\(domain)/privacy.html")!
    static let terms = URL(string: "\(domain)/terms.html")!
    static let support = URL(string: "\(domain)/support.html")!
    static let guide = URL(string: "\(domain)/guide.html")!
    // swiftlint:enable force_unwrapping
}
