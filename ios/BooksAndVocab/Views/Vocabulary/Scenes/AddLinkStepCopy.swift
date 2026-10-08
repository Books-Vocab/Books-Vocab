import Foundation

/// The six server-side steps of a missing-target Add Link operation, in the
/// order the backend reports them, plus the label that says what each one does.
///
/// The ids are the backend contract (`vocab_add_link_operation.py`); only the
/// copy is owned here.
enum AddLinkStep: String, CaseIterable {
    case resolveTarget = "resolve_target"
    case translate = "translate"
    case createCard = "create_card"
    case enrich = "enrich"
    case createLink = "create_link"
    case localProjection = "local_projection"

    var labelKey: String {
        switch self {
        case .resolveTarget: return "addLink.step.resolveTarget"
        case .translate: return "addLink.step.translate"
        case .createCard: return "addLink.step.createCard"
        case .enrich: return "addLink.step.enrich"
        case .createLink: return "addLink.step.createLink"
        case .localProjection: return "addLink.step.localProjection"
        }
    }

    var label: String { L10n.string(labelKey) }
}
