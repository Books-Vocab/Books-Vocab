// swift-ast-dumper — SwiftUI → box-tree IR (AST front-end for the migration engine).
//
// Replaces the regex+indentation heuristic (lab/migration_engine/engine/extract_swiftui.py)
// with a real SwiftSyntax parse. Emits the SAME IR JSON schema that ir_contract.py pins
// and generate_css.py consumes — so the seam is unchanged; only the parser is upgraded.
//
// What AST buys over the regex: correct modifier-chain → nested-box ordering, ternary /
// nested-call argument parsing (e.g. `appSkin.typography.caption.weight(.semibold)`,
// `AppSpacing.s2 + 2`), and trailing-closure scope (content stays the decorated node,
// not flattened to its parent). Goal: drive `unparsed` to zero.
//
// Usage: swift-ast-dumper <file.swift> [--struct Name]

import Foundation
import SwiftSyntax
import SwiftParser

// ---------------------------------------------------------------------------
// IR node (mutable for chain-append; serialized to the contract's JSON shape)
// ---------------------------------------------------------------------------

final class Node {
    var kind: String
    var hint: String?
    var axis: String?
    var spacing: [String: Any]?
    var modifiers: [[String: Any]] = []
    var children: [Node] = []
    var unparsed: [String] = []
    var scoped: [String] = []   // visual modifiers deliberately out of component scope (in denominator)
    init(_ kind: String) { self.kind = kind }

    func json() -> [String: Any] {
        [
            "kind": kind,
            "selector_hint": hint ?? NSNull(),
            "axis": axis ?? NSNull(),
            "spacing": spacing ?? NSNull(),
            "modifiers": modifiers,
            "children": children.map { $0.json() },
            "unparsed": unparsed,
            "scoped": scoped,
        ]
    }
}

// ---------------------------------------------------------------------------
// small regex helper
// ---------------------------------------------------------------------------

func cap(_ s: String, _ pattern: String) -> String? {
    guard let re = try? NSRegularExpression(pattern: pattern) else { return nil }
    let r = NSRange(s.startIndex..., in: s)
    guard let m = re.firstMatch(in: s, range: r), m.numberOfRanges > 1,
          let g = Range(m.range(at: 1), in: s) else { return nil }
    return String(s[g])
}

func capD(_ s: String, _ pattern: String) -> Double? { cap(s, pattern).flatMap(Double.init) }

// ---------------------------------------------------------------------------
// value resolution (→ contract value objects)
// ---------------------------------------------------------------------------

func parseValue(_ e: ExprSyntax) -> [String: Any] {
    if let i = e.as(IntegerLiteralExprSyntax.self) {
        return ["kind": "literal", "value": Int(i.literal.text) ?? 0, "raw": i.trimmedDescription]
    }
    if let f = e.as(FloatLiteralExprSyntax.self) {
        return ["kind": "literal", "value": Double(f.literal.text) ?? 0, "raw": f.trimmedDescription]
    }
    if let op = e.as(InfixOperatorExprSyntax.self) {
        let opTxt = op.operator.as(BinaryOperatorExprSyntax.self)?.operator.text
            ?? op.operator.trimmedDescription
        return [
            "kind": "expr",
            "base": op.leftOperand.trimmedDescription,
            "op": opTxt,
            "addend": op.rightOperand.trimmedDescription,
            "raw": op.trimmedDescription,
        ]
    }
    // SwiftSyntax does NOT operator-fold by default: `A + B` parses as a 3-element
    // SequenceExpr [lhs, op, rhs], not InfixOperatorExpr. Handle the binary case.
    if let seq = e.as(SequenceExprSyntax.self) {
        let els = Array(seq.elements)
        if els.count == 3, let opExpr = els[1].as(BinaryOperatorExprSyntax.self) {
            return [
                "kind": "expr",
                "base": els[0].trimmedDescription,
                "op": opExpr.operator.text,
                "addend": els[2].trimmedDescription,
                "raw": seq.trimmedDescription,
            ]
        }
    }
    let txt = e.trimmedDescription
    if txt.hasPrefix("appSkin.spacing.") {
        return ["kind": "skin_spacing", "field": String(txt.dropFirst("appSkin.spacing.".count)), "raw": txt]
    }
    if txt.contains("Metrics.") {
        return ["kind": "metric", "name": txt, "raw": txt]
    }
    if txt.hasPrefix("AppSpacing.") || txt.hasPrefix("AppRadius.") || txt.hasPrefix("AppMetrics.") {
        return ["kind": "token", "token": txt, "raw": txt]
    }
    return ["kind": "unknown", "raw": txt]
}

func parseColor(_ e: ExprSyntax) -> (token: String, opacity: Double?) {
    let txt = e.trimmedDescription
    let opacity = capD(txt, "\\.opacity\\(([0-9.]+)\\)")
    if let name = cap(txt, "palette\\.([A-Za-z0-9]+)") { return (name, opacity) }
    // bare identifier / ternary → caller-injected param color (generator marks it orphan)
    let token = cap(txt, "^([A-Za-z_][A-Za-z0-9_]*)") ?? txt
    return (token, opacity)
}

// ---------------------------------------------------------------------------
// modifier resolution
// ---------------------------------------------------------------------------

enum ModResult { case mod([String: Any]); case skip; case scoped(String); case unparsed }

// NON_VISUAL — genuinely no CSS analog (lifecycle, a11y, text-fitting, layout hints,
// environment/identity). Dropped silently AND excluded from the coverage denominator:
// these are not transpilation work, so counting them would understate capability.
let NON_VISUAL: Set<String> = [
    // injection / lifecycle / events
    "enableInjection", "observeInjection", "task", "onAppear", "onDisappear",
    "onTapGesture", "onChange", "onReceive", "onSubmit", "refreshable", "gesture",
    // accessibility (+ haptics + scene plumbing)
    "accessibilityAddTraits", "accessibilityLabel", "accessibilityIdentifier",
    "accessibilityHint", "accessibilityElement", "accessibilityValue", "accessibilityHidden",
    "accessibilityAction", "help", "sensoryFeedback", "focusedSceneValue",
    // text fitting / typographic micro-hints (no box geometry)
    "lineLimit", "multilineTextAlignment", "truncationMode", "minimumScaleFactor",
    "lineSpacing", "textCase", "kerning", "tracking", "allowsTightening",
    // layout / interaction hints (no painted geometry)
    "fixedSize", "layoutPriority", "zIndex", "allowsHitTesting", "contentShape",
    "ignoresSafeArea", "focused", "focusable", "submitLabel", "keyboardType",
    "safeAreaInset",
    // environment / identity / state-handles / animation (no static geometry)
    "environment", "environmentObject", "id", "tag", "buttonStyle", "labelStyle",
    "animation", "transition", "disabled", "animatePhaseChange", "animateSpring",
    "animateContentFade", "appHoverLift", "appHoverRowTint",
]

// SCOPED_OUT — HAS visual effect (color/geometry/sub-view chrome) but deliberately not
// transpiled at the component level (navigation/screen chrome handled by the web shell;
// presented surfaces are separate components). CRITICAL: these ARE counted in the
// coverage denominator (as `scoped`), so moving a modifier here can NEVER inflate the
// metric — only true resolution raises coverage. This kills the IGNORE-shrink gameability
// the #962/5d073d59 review flagged. They stay distinct from `unparsed` so the
// implement-next histogram isn't polluted by deliberate scope decisions.
let SCOPED_OUT: Set<String> = [
    // control/list surface tints — real color, scoped to a later phase
    "tint", "scrollContentBackground", "listRowBackground", "listRowSeparator",
    "listRowInsets", "scrollIndicators", "appElevation",
    // navigation / screen-level chrome (web shell layer)
    "navigationTitle", "inlineNavigationBarTitle", "largeNavigationBarTitle",
    "navigationBarTitleDisplayMode", "navigationDestination", "navigationBarBackButtonHidden",
    "navigationBarHidden", "toolbar", "toolbarBackground", "toolbarColorScheme", "searchable",
    // presented surfaces (each its own component tree)
    "contextMenu", "toastSheet", "sheet", "fullScreenCover", "alert",
    "confirmationDialog", "popover",
]

func edgeName(_ e: ExprSyntax) -> String? {
    guard let m = e.as(MemberAccessExprSyntax.self), m.base == nil else { return nil }
    return m.declName.baseName.text
}

// `.stroke(color, lineWidth: w)` args → a stroke modifier (generate emits it as border).
func strokeModFromArgs(_ args: LabeledExprListSyntax) -> [String: Any]? {
    let argList = Array(args)
    guard let c = argList.first?.expression else { return nil }
    let (token, opacity) = parseColor(c)
    var mod: [String: Any] = ["name": "stroke", "token": token, "raw": ".stroke"]
    if let o = opacity { mod["opacity"] = o }
    for a in argList where a.label?.text == "lineWidth" {
        mod["line_width"] = a.expression.trimmedDescription
    }
    return mod
}

// find a `.stroke(...)` call in the outer chain of an expr (e.g. inside an .overlay).
func findStrokeCall(_ e: ExprSyntax) -> FunctionCallExprSyntax? {
    guard let call = e.as(FunctionCallExprSyntax.self),
          let ma = call.calledExpression.as(MemberAccessExprSyntax.self) else { return nil }
    if ma.declName.baseName.text == "stroke" { return call }
    if let base = ma.base { return findStrokeCall(base) }
    return nil
}

func parseModifier(_ name: String, _ args: LabeledExprListSyntax, _ trailing: ClosureExprSyntax?) -> ModResult {
    if NON_VISUAL.contains(name) { return .skip }
    if SCOPED_OUT.contains(name) { return .scoped(name) }
    let argList = Array(args)

    switch name {
    case "font":
        guard let a0 = argList.first?.expression else { return .unparsed }
        let txt = a0.trimmedDescription
        // two role sources: `appSkin.typography.<role>` and `AppFonts.<role>(…)`.
        if let role = cap(txt, "typography\\.([A-Za-z0-9]+)") ?? cap(txt, "AppFonts\\.([A-Za-z0-9]+)") {
            var mod: [String: Any] = ["name": "font", "role": role, "raw": ".font(\(txt))"]
            // weight from `.weight(.X)` or `AppFonts.role(weight: .X)`
            if let w = cap(txt, "\\.weight\\(\\.([A-Za-z0-9]+)\\)") ?? cap(txt, "weight:\\s*\\.([A-Za-z0-9]+)") {
                mod["weight_override"] = w
            }
            return .mod(mod)
        }
        return .unparsed

    case "foregroundStyle", "foregroundColor":
        guard let a0 = argList.first?.expression else { return .unparsed }
        let (token, opacity) = parseColor(a0)
        var mod: [String: Any] = ["name": "foreground", "token": token, "raw": ".\(name)(\(a0.trimmedDescription))"]
        if let o = opacity { mod["opacity"] = o }
        return .mod(mod)

    case "padding":
        if argList.isEmpty {
            return .mod(["name": "padding", "edge": "all",
                         "value": ["kind": "literal", "value": 16, "raw": "default"], "raw": ".padding()"])
        }
        if let edge = edgeName(argList[0].expression), argList.count >= 2 {
            return .mod(["name": "padding", "edge": edge,
                         "value": parseValue(argList[1].expression), "raw": ".padding"])
        }
        // single value form: .padding(X) → all
        return .mod(["name": "padding", "edge": "all",
                     "value": parseValue(argList[0].expression), "raw": ".padding"])

    case "frame":
        var dims: [String: Any] = [:]
        let frameDims: Set<String> = [
            "minWidth", "width", "maxWidth", "minHeight", "height", "maxHeight",
            "idealWidth", "idealHeight",
        ]
        for a in argList {
            guard let l = a.label?.text, frameDims.contains(l) else { continue }
            dims[l] = parseValue(a.expression)
        }
        if dims.isEmpty { return .unparsed }
        return .mod(["name": "frame", "dims": dims, "raw": ".frame"])

    case "background":
        // call form `.background(Capsule().fill(c))` → arg0; trailing-closure form
        // `.background { Capsule().fill(c) }` → descend into the closure's first
        // statement (NOT the closure expr itself — that fabricates a junk token and
        // silently loses shape/radius; see review of #962).
        var bgExpr = argList.first?.expression
        if bgExpr == nil, let t = trailing, let first = t.statements.first {
            bgExpr = exprOf(first)
        }
        guard let a0 = bgExpr else { return .unparsed }
        var mod: [String: Any] = ["name": "background", "raw": ".background(\(a0.trimmedDescription))"]
        // shape-wrapped fill: Capsule(...).fill(c) / RoundedRectangle(cornerRadius:R).fill(c)
        if let call = a0.as(FunctionCallExprSyntax.self),
           let ma = call.calledExpression.as(MemberAccessExprSyntax.self),
           ma.declName.baseName.text == "fill", let base = ma.base {
            let btxt = base.trimmedDescription
            if btxt.hasPrefix("Capsule") { mod["shape"] = "capsule" }
            else if btxt.hasPrefix("RoundedRectangle") {
                if let r = cap(btxt, "AppRadius\\.([A-Za-z0-9]+)") { mod["radius"] = "AppRadius.\(r)" }
            }
            if let c = call.arguments.first?.expression {
                let (token, opacity) = parseColor(c)
                mod["token"] = token
                if let o = opacity { mod["opacity"] = o }
            }
        } else {
            let (token, opacity) = parseColor(a0)
            mod["token"] = token
            if let o = opacity { mod["opacity"] = o }
        }
        return .mod(mod)

    case "fill":
        // shape fill (Circle().fill(c), Rectangle().fill(c)) → background color.
        guard let a0 = argList.first?.expression else { return .unparsed }
        let (token, opacity) = parseColor(a0)
        var mod: [String: Any] = ["name": "background", "token": token, "raw": ".fill(\(a0.trimmedDescription))"]
        if let o = opacity { mod["opacity"] = o }
        return .mod(mod)

    case "stroke":
        // shape stroke (Circle().stroke(c, lineWidth: w)) → border.
        if let m = strokeModFromArgs(args) { return .mod(m) }
        return .unparsed

    case "clipShape":
        // clip → border-radius only (no fill). Reuses generate's background shape/radius
        // path with no token, so it emits just border-radius. Only AppRadius.* tokens map
        // (literal cornerRadius has no CSS var → honest degrade).
        guard let a0 = argList.first?.expression else { return .unparsed }
        let txt = a0.trimmedDescription
        var mod: [String: Any] = ["name": "background", "raw": ".clipShape(\(txt))"]
        if txt.hasPrefix("Capsule") {
            mod["shape"] = "capsule"
        } else if txt.hasPrefix("RoundedRectangle"), let r = cap(txt, "AppRadius\\.([A-Za-z0-9]+)") {
            mod["radius"] = "AppRadius.\(r)"
        } else {
            return .unparsed
        }
        return .mod(mod)

    case "overlay":
        // common border idiom: .overlay(Shape().stroke(c, lineWidth: w)) → border.
        // an overlay of a sub-view (badge / divider) needs an overlay-layer model — not
        // yet supported, so it degrades honestly.
        var ovExpr = argList.first?.expression
        if ovExpr == nil, let t = trailing, let first = t.statements.first { ovExpr = exprOf(first) }
        if let e = ovExpr, let strokeCall = findStrokeCall(e),
           let m = strokeModFromArgs(strokeCall.arguments) {
            var border = m
            border["raw"] = ".overlay(stroke)"
            return .mod(border)
        }
        return .unparsed

    default:
        return .unparsed  // visual-but-unimplemented — honest degrade
    }
}

// ---------------------------------------------------------------------------
// expr → node (recursive lowering)
// ---------------------------------------------------------------------------

let STACKS: Set<String> = ["VStack", "HStack", "ZStack"]

func lower(_ expr: ExprSyntax) -> Node {
    // modifier call:  <base>.<name>(<args>) <trailing?>
    if let call = expr.as(FunctionCallExprSyntax.self),
       let ma = call.calledExpression.as(MemberAccessExprSyntax.self),
       let base = ma.base {
        let node = lower(base)                       // recurse base first → source order preserved
        let mname = ma.declName.baseName.text
        switch parseModifier(mname, call.arguments, call.trailingClosure) {
        case .mod(let m): node.modifiers.append(m)
        case .skip: break
        case .scoped(let nm): node.scoped.append(".\(nm)")
        // record ONLY the modifier itself, not the whole chain — appending
        // call.trimmedDescription would re-swallow the already-parsed base subtree
        // (massive duplicate pollution) and lump the chain into one opaque blob.
        case .unparsed: node.unparsed.append(".\(mname)")
        }
        return node
    }

    // view constructor:  Name(<args>) { <closure children> }
    if let call = expr.as(FunctionCallExprSyntax.self),
       let ref = call.calledExpression.as(DeclReferenceExprSyntax.self) {
        return constructorNode(ref.baseName.text, call.arguments, call.trailingClosure)
    }

    // bare identifier in body/ViewBuilder position. `content` is the @ViewBuilder
    // injection point; other identifiers (`coverView`, `progressBar`, `SomeView`) are
    // computed-property sub-views → child. KNOWN DEBT: this is unsound in the general
    // case (a non-View identifier would also become a phantom `child`), but the Swift
    // type system forbids non-View identifiers in bare ViewBuilder-statement position,
    // so it's empirically dormant (corpus scan: 0 spurious children). `child` nodes are
    // absent from the coverage denominator, so this cannot inflate the metric either.
    // Do NOT reuse lower() in argument position without re-adding a View-name guard.
    if let ref = expr.as(DeclReferenceExprSyntax.self) {
        let name = ref.baseName.text
        if name == "content" { return Node("container") }
        let n = Node("child"); n.hint = name; return n
    }

    // anything else is a degrade
    let n = Node("unparsed")
    n.unparsed.append(expr.trimmedDescription)
    return n
}

func constructorNode(_ name: String, _ args: LabeledExprListSyntax, _ trailing: ClosureExprSyntax?) -> Node {
    let node: Node
    if STACKS.contains(name) {
        node = Node(name)
        node.axis = name == "HStack" ? "row" : (name == "VStack" ? "column" : "stack")
        for a in args where a.label?.text == "spacing" {
            node.spacing = parseValue(a.expression)
        }
    } else if name == "Text" {
        node = Node("Text")
        if let s = args.first?.expression.as(StringLiteralExprSyntax.self) {
            node.hint = s.segments.trimmedDescription
        }
    } else if name == "Image" {
        node = Node("Image")
    } else if name == "Spacer" {
        node = Node("Spacer")
    } else {
        node = Node("child"); node.hint = name        // child-view call (delegating component)
    }
    // closure children (trailing or last labeled closure arg)
    let closure = trailing ?? args.last?.expression.as(ClosureExprSyntax.self)
    if let closure {
        for item in closure.statements {
            if let e = exprOf(item) { node.children.append(lower(e)) }
        }
    }
    return node
}

func exprOf(_ item: CodeBlockItemSyntax) -> ExprSyntax? {
    switch item.item {
    case .expr(let e): return e
    case .stmt(let s): return s.as(ReturnStmtSyntax.self)?.expression
    default: return nil
    }
}

// ---------------------------------------------------------------------------
// struct/body discovery
// ---------------------------------------------------------------------------

final class StructCollector: SyntaxVisitor {
    var found: [(name: String, body: ExprSyntax)] = []
    override func visit(_ node: StructDeclSyntax) -> SyntaxVisitorContinueKind {
        let inherits = node.inheritanceClause?.inheritedTypes
            .contains { $0.type.trimmedDescription == "View" } ?? false
        guard inherits else { return .visitChildren }
        for member in node.memberBlock.members {
            guard let v = member.decl.as(VariableDeclSyntax.self) else { continue }
            for b in v.bindings {
                guard b.pattern.as(IdentifierPatternSyntax.self)?.identifier.text == "body",
                      let accessor = b.accessorBlock?.accessors else { continue }
                var stmts: CodeBlockItemListSyntax?
                if case .getter(let g) = accessor { stmts = g }
                guard let stmts else { continue }
                // the returned view = last expression-bearing statement
                for item in stmts.reversed() {
                    if let e = exprOf(item) { found.append((node.name.text, e)); break }
                }
            }
        }
        return .visitChildren
    }
}

// ---------------------------------------------------------------------------
// driver
// ---------------------------------------------------------------------------

let argv = CommandLine.arguments
guard argv.count >= 2 else {
    FileHandle.standardError.write("usage: swift-ast-dumper <file.swift> [--struct Name]\n".data(using: .utf8)!)
    exit(2)
}
let path = argv[1]
var only: String?
if let i = argv.firstIndex(of: "--struct"), i + 1 < argv.count { only = argv[i + 1] }

let src = try String(contentsOfFile: path, encoding: .utf8)
let tree = Parser.parse(source: src)
let collector = StructCollector(viewMode: .sourceAccurate)
collector.walk(tree)

var structs: [[String: Any]] = []
for (name, bodyExpr) in collector.found {
    if let only, name != only { continue }
    structs.append(["name": name, "root": lower(bodyExpr).json()])
}

let out: [String: Any] = ["source": path, "structs": structs]
let data = try JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write("\n".data(using: .utf8)!)
