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

// ---------------------------------------------------------------------------
// custom-modifier symbol table (cross-file): app-defined `extension View` funcs
// and `ViewModifier` structs. Populated by StructCollector over the WHOLE file set
// before any lowering, so a `.customModifier()` call can be resolved to its expansion.
// ---------------------------------------------------------------------------

// single-threaded CLI: the symbol table is built fully in pass 1 (main thread) before
// any read in pass 2, so the unchecked annotation is sound.
nonisolated(unsafe) var extFuncBodies: [String: ExprSyntax] = [:]      // ext View func → body expr
nonisolated(unsafe) var modifierStructBodies: [String: ExprSyntax] = [:]  // ViewModifier struct → body(content:)

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
// custom-modifier resolution
//
// A `.customModifier()` call earns coverage ONLY when it provably expands to a pure
// modifier chain anchored on `content`/`self` (fate 1). A chain terminating in a
// SCOPED_OUT presentation modifier (.sheet/…) is `.scoped` — no coverage credit. A
// body that structurally wraps `content` in another constructor (fate 3) is
// `.unresolved` → honest unparsed. This asymmetry is the honesty guarantee: the only
// path to +coverage is a provable visual modifier chain. Arg→body parameter
// substitution is NOT modeled; a body referencing a func parameter degrades to a
// literal/unknown value (honest), never a fabricated token.
// ---------------------------------------------------------------------------

enum CustomResolution { case modifiers([[String: Any]]); case scoped; case unresolved }

func resolveCustom(_ name: String, _ depth: Int) -> CustomResolution {
    if depth > 8 { return .unresolved }
    guard let body = extFuncBodies[name] else { return .unresolved }
    return resolveChain(body, depth + 1)
}

// Resolve a modifier-chain expression (anchored on content/self) into spliced
// modifiers / scoped / unresolved. Base-first (source) order preserved.
func resolveChain(_ expr: ExprSyntax, _ depth: Int) -> CustomResolution {
    if depth > 16 { return .unresolved }

    // anchor: `content` (ViewModifier) or `self` (View ext) → empty modifier prefix
    if let ref = expr.as(DeclReferenceExprSyntax.self) {
        let n = ref.baseName.text
        return (n == "content" || n == "self") ? .modifiers([]) : .unresolved
    }

    // bare call `name(args)` == `self.name(args)` (implicit-self anchor). Three sub-cases:
    // `modifier(StructName())`, a custom ext func, or a builtin modifier (sheet/…).
    if let call = expr.as(FunctionCallExprSyntax.self),
       let callee = call.calledExpression.as(DeclReferenceExprSyntax.self) {
        let fn = callee.baseName.text
        if fn == "modifier", let a0 = call.arguments.first?.expression,
           let structCall = a0.as(FunctionCallExprSyntax.self),
           let sref = structCall.calledExpression.as(DeclReferenceExprSyntax.self),
           let mbody = modifierStructBodies[sref.baseName.text] {
            return resolveChain(mbody, depth + 1)
        }
        if extFuncBodies[fn] != nil { return resolveCustom(fn, depth + 1) }
        switch parseModifier(fn, call.arguments, call.trailingClosure) {
        case .mod(let m): return .modifiers([m])
        case .skip: return .modifiers([])
        case .scoped: return .scoped
        case .unparsed: return .unresolved
        }
    }

    // `<base>.<name>(args) <trailing?>` — a modifier applied to base
    if let call = expr.as(FunctionCallExprSyntax.self),
       let ma = call.calledExpression.as(MemberAccessExprSyntax.self),
       let base = ma.base {
        let head = resolveChain(base, depth + 1)        // inner first → source order
        guard case .modifiers(let acc) = head else { return head }  // scoped/unresolved propagate
        let name = ma.declName.baseName.text
        switch parseModifier(name, call.arguments, call.trailingClosure) {
        case .mod(let m): return .modifiers(acc + [m])
        case .skip: return .modifiers(acc)
        case .scoped: return .scoped
        case .unparsed:
            // unknown builtin name — maybe another custom modifier
            if extFuncBodies[name] != nil {
                switch resolveCustom(name, depth + 1) {
                case .modifiers(let m2): return .modifiers(acc + m2)
                case .scoped: return .scoped
                case .unresolved: return .unresolved
                }
            }
            return .unresolved
        }
    }

    // constructor wrap (AppSectionCard(…){content}) / anything else → structural
    return .unresolved
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
        case .unparsed:
            // unknown builtin — try resolving as an app-defined custom modifier before
            // conceding. Record ONLY the modifier name, never the whole chain (appending
            // call.trimmedDescription would re-swallow the already-parsed base subtree).
            switch resolveCustom(mname, 0) {
            case .modifiers(let ms) where !ms.isEmpty:
                node.modifiers.append(contentsOf: ms)
            case .modifiers:
                break  // resolved to a no-op (only NON_VISUAL inside) — not debt
            case .scoped:
                node.scoped.append(".\(mname)")  // keep the custom name for the histogram
            case .unresolved:
                node.unparsed.append(".\(mname)")
            }
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

// the returned view of a getter/func body = its last expression-bearing statement.
func lastReturnedExpr(_ stmts: CodeBlockItemListSyntax) -> ExprSyntax? {
    for item in stmts.reversed() {
        if let e = exprOf(item) { return e }
    }
    return nil
}

func returnsSomeView(_ fn: FunctionDeclSyntax) -> Bool {
    guard let ret = fn.signature.returnClause?.type.trimmedDescription else { return false }
    return ret.contains("View")
}

// ---------------------------------------------------------------------------
// struct/body discovery
// ---------------------------------------------------------------------------

final class StructCollector: SyntaxVisitor {
    var found: [(name: String, body: ExprSyntax)] = []

    // `var body: some View { … }` getter expr, shared by View and ViewModifier.
    private func bodyGetterExpr(_ node: StructDeclSyntax) -> ExprSyntax? {
        for member in node.memberBlock.members {
            guard let v = member.decl.as(VariableDeclSyntax.self) else { continue }
            for b in v.bindings {
                guard b.pattern.as(IdentifierPatternSyntax.self)?.identifier.text == "body",
                      let accessor = b.accessorBlock?.accessors,
                      case .getter(let g) = accessor else { continue }
                if let e = lastReturnedExpr(g) { return e }
            }
        }
        return nil
    }

    // `func body(content: Content) -> some View { … }` returned expr (ViewModifier).
    private func modifierBodyExpr(_ node: StructDeclSyntax) -> ExprSyntax? {
        for member in node.memberBlock.members {
            guard let fn = member.decl.as(FunctionDeclSyntax.self),
                  fn.name.text == "body",
                  let block = fn.body else { continue }
            return lastReturnedExpr(block.statements)
        }
        return nil
    }

    override func visit(_ node: StructDeclSyntax) -> SyntaxVisitorContinueKind {
        let conforms = node.inheritanceClause?.inheritedTypes
            .map { $0.type.trimmedDescription } ?? []
        if conforms.contains("View"), let e = bodyGetterExpr(node) {
            found.append((node.name.text, e))
        }
        if conforms.contains("ViewModifier"), let e = modifierBodyExpr(node) {
            modifierStructBodies[node.name.text] = e
        }
        return .visitChildren
    }

    // `extension View { func foo() -> some View { … } }` → symbol table entry.
    override func visit(_ node: ExtensionDeclSyntax) -> SyntaxVisitorContinueKind {
        guard node.extendedType.trimmedDescription == "View" else { return .visitChildren }
        for member in node.memberBlock.members {
            guard let fn = member.decl.as(FunctionDeclSyntax.self),
                  returnsSomeView(fn), let block = fn.body,
                  let e = lastReturnedExpr(block.statements) else { continue }
            extFuncBodies[fn.name.text] = e
        }
        return .visitChildren
    }
}

// ---------------------------------------------------------------------------
// driver
// ---------------------------------------------------------------------------

let argv = CommandLine.arguments
var only: String?
if let i = argv.firstIndex(of: "--struct"), i + 1 < argv.count { only = argv[i + 1] }
// Symbol table is built from ALL passed files (app-wide custom modifiers live in
// UIComponents/, Platform/, …), but only structs whose source path contains `emitFilter`
// are emitted/measured. This separates "where definitions live" from "what we score".
var emitFilter: String?
if let i = argv.firstIndex(of: "--emit"), i + 1 < argv.count { emitFilter = argv[i + 1] }
let files = argv.dropFirst().filter { $0.hasSuffix(".swift") }
guard !files.isEmpty else {
    FileHandle.standardError.write("usage: swift-ast-dumper <file.swift>... [--struct Name]\n".data(using: .utf8)!)
    exit(2)
}

// pass 1: parse every file, populate the cross-file symbol table AND collect the
// View bodies to lower (with their source attribution). Lowering must wait until the
// symbol table is complete, so it cannot run inside this loop.
var pending: [(name: String, source: String, body: ExprSyntax)] = []
var skipped: [String] = []
for path in files {
    guard let src = try? String(contentsOfFile: path, encoding: .utf8) else {
        skipped.append(path)
        FileHandle.standardError.write("skip (unreadable): \(path)\n".data(using: .utf8)!)
        continue
    }
    let tree = Parser.parse(source: src)
    let collector = StructCollector(viewMode: .sourceAccurate)
    collector.walk(tree)   // populates global extFuncBodies / modifierStructBodies + .found
    for (name, body) in collector.found { pending.append((name, path, body)) }
}

// pass 2: lower with the full symbol table available for custom-modifier resolution.
var structs: [[String: Any]] = []
for (name, source, body) in pending {
    if let only, name != only { continue }
    if let emitFilter, !source.contains(emitFilter) { continue }
    structs.append(["name": name, "source": source, "root": lower(body).json()])
}

let out: [String: Any] = ["structs": structs, "skipped": skipped]
let data = try JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write("\n".data(using: .utf8)!)
