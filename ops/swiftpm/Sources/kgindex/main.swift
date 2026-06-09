import Foundation
import IndexStoreDB

// kgindex — neutral Xcode IndexStore extractor.
//
// Usage:
//   kgindex <storePath> <sourceRootSubstring> [--kinds struct,class,enum,protocol]
//
// Emits a JSON document to stdout: for every symbol definition of the requested
// kinds whose definition file path contains <sourceRootSubstring>, the symbol's
// USR + definition location + every reference/call location (with roles + the
// enclosing TYPE that contains the reference). It applies NO policy — no
// Debug/Tests exclusion, no orphan judgement. That lives in the Python consumers
// (ops/ui_deadcode.py, ops/ui_graph.py) where it is unit-testable.
//
// The per-ref `container` is the nearest enclosing nominal type of the reference
// site, resolved structurally via the index's `containedBy` relation (ref →
// enclosing method/accessor) then walking `childOf` up to the nearest struct/
// class/enum/protocol. Extensions are collapsed onto the extended nominal type
// (see nominalByName) so a type and its extensions are one node. This is what
// lets a consumer build a type→type dependency graph ("type A references type
// B"). Resolution is pure structural fact, not policy.
//
// Design notes:
// - libIndexStore.dylib is discovered via `xcode-select -p`, never hardcoded, so
//   it survives Xcode upgrades.
// - Enumeration is two-pass and flat: PASS 1 drains the symbol-name table
//   (forEachSymbolName) into an array; PASS 2 resolves canonical definitions and
//   then references via occurrences(ofUSR:). Reference queries run in a flat loop
//   AFTER the name enumeration fully drains — never nested inside a read-txn
//   closure — to avoid LMDB MDB_BAD_RSLOT.

func fail(_ msg: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(code)
}

// MARK: - Args

var positional: [String] = []
var kindsArg = "struct,class,enum,protocol"
var it = CommandLine.arguments.dropFirst().makeIterator()
while let a = it.next() {
    switch a {
    case "--kinds":
        guard let v = it.next() else { fail("--kinds requires a value", code: 2) }
        kindsArg = v
    case "-h", "--help":
        print("usage: kgindex <storePath> <sourceRootSubstring> [--kinds struct,class,enum,protocol]")
        exit(0)
    default:
        positional.append(a)
    }
}
guard positional.count == 2 else {
    fail("usage: kgindex <storePath> <sourceRootSubstring> [--kinds struct,class,enum,protocol]", code: 2)
}
let storePath = positional[0]
let sourceRoot = positional[1]

// Each user-facing kind maps to the SET of IndexSymbolKinds it covers, so the
// input vocabulary matches the output `kindString` exactly. "func" deliberately
// enrolls the three method kinds too — otherwise `--kinds func` would silently
// return only free functions while the output still labels methods "func".
let kindMap: [String: [IndexSymbolKind]] = [
    "struct": [.struct], "class": [.class], "enum": [.enum], "protocol": [.protocol],
    "func": [.function, .instanceMethod, .staticMethod, .classMethod],
    "extension": [.extension],
]
var wantedKinds = Set<IndexSymbolKind>()
for token in kindsArg.split(separator: ",") {
    let key = token.trimmingCharacters(in: .whitespaces)
    guard let ks = kindMap[key] else { fail("unknown kind: \(key) (valid: \(kindMap.keys.sorted().joined(separator: ",")))", code: 2) }
    wantedKinds.formUnion(ks)
}

// MARK: - IndexStore open

let devDir: String
do {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/xcode-select")
    p.arguments = ["-p"]
    let pipe = Pipe()
    p.standardOutput = pipe
    try p.run()
    p.waitUntilExit()
    guard p.terminationStatus == 0 else { fail("xcode-select -p failed") }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    devDir = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    guard !devDir.isEmpty else { fail("xcode-select -p returned empty") }
} catch {
    fail("xcode-select -p error: \(error)")
}
let dylib = "\(devDir)/Toolchains/XcodeDefault.xctoolchain/usr/lib/libIndexStore.dylib"
guard FileManager.default.fileExists(atPath: dylib) else { fail("libIndexStore.dylib not found at \(dylib)") }
guard FileManager.default.fileExists(atPath: storePath) else { fail("IndexStore not found at \(storePath)") }

let lib: IndexStoreLibrary
let db: IndexStoreDB
do {
    lib = try IndexStoreLibrary(dylibPath: dylib)
    let tmpDB = NSTemporaryDirectory() + "kgindex-db-\(ProcessInfo.processInfo.processIdentifier)"
    db = try IndexStoreDB(storePath: storePath, databasePath: tmpDB, library: lib,
                          waitUntilDoneInitializing: true, listenToUnitEvents: false)
} catch {
    fail("failed to open IndexStore: \(error)")
}

// MARK: - Enumeration

// Filter compiler-synthesized symbols. #Preview and @Model macros emit names like
// `$s…PreviewRegistry…` and `_SwiftDataNoType`, all of which start with `_`/`$`.
// We match ONLY that prefix — not a broad `contains("Preview")` — so real user
// types such as `BookPreviewView` are NOT dropped. This keeps the extractor
// neutral; any further filtering is policy and belongs in ui_deadcode.py.
func isSynthetic(_ name: String) -> Bool {
    name.hasPrefix("_") || name.hasPrefix("$")
}

struct Def { let kind: IndexSymbolKind; let name: String; let usr: String; let path: String; let line: Int }

// PASS 1 — drain the symbol-name table into an array (no nested read txns).
var names: [String] = []
db.forEachSymbolName { name in names.append(name); return true }

// PASS 2 — resolve canonical definitions of wanted kinds under sourceRoot.
var defs: [Def] = []
var seenUSR = Set<String>()
for name in names {
    if isSynthetic(name) { continue }
    for occ in db.canonicalOccurrences(ofName: name) {
        guard occ.roles.contains(.definition) else { continue }
        let sym = occ.symbol
        guard wantedKinds.contains(sym.kind) else { continue }
        let path = occ.location.path
        guard path.contains(sourceRoot) else { continue }
        guard !seenUSR.contains(sym.usr) else { continue }
        seenUSR.insert(sym.usr)
        defs.append(Def(kind: sym.kind, name: sym.name, usr: sym.usr, path: path, line: occ.location.line))
    }
}

func kindString(_ k: IndexSymbolKind) -> String {
    switch k {
    case .struct: return "struct"
    case .class: return "class"
    case .enum: return "enum"
    case .protocol: return "protocol"
    case .function, .instanceMethod, .staticMethod, .classMethod: return "func"
    case .extension: return "extension"
    default: return "\(k)"
    }
}

func rolesStrings(_ roles: SymbolRole) -> [String] {
    var out: [String] = []
    if roles.contains(.definition) { out.append("definition") }
    if roles.contains(.declaration) { out.append("declaration") }
    if roles.contains(.reference) { out.append("reference") }
    if roles.contains(.call) { out.append("call") }
    if roles.contains(.read) { out.append("read") }
    if roles.contains(.write) { out.append("write") }
    return out
}

// MARK: - Container resolution (ref site → nearest enclosing type)

// Nominal types we stop the walk at. Extensions are handled specially: a member of
// `extension Foo` has childOf → the EXTENSION symbol (kind .extension, name "Foo",
// but a DISTINCT USR from Foo's nominal def). For a USR-keyed dependency graph that
// would split Foo's main decl and its extensions into separate nodes and drop real
// edges (bodies often live in extensions). So we collapse an extension to its
// extended nominal type by name lookup (preferring a definition under sourceRoot).
let nominalKinds: Set<IndexSymbolKind> = [.struct, .class, .enum, .protocol]

struct ContainerRecord: Encodable { let usr: String; let name: String; let kind: String }

// name → nominal type definition (collapses extensions onto the extended type).
var nominalByNameCache: [String: ContainerRecord?] = [:]
@MainActor
func nominalByName(_ name: String) -> ContainerRecord? {
    if let cached = nominalByNameCache[name] { return cached }
    var external: ContainerRecord? = nil
    var result: ContainerRecord? = nil
    var localUSRs = Set<String>()
    for occ in db.canonicalOccurrences(ofName: name) where occ.roles.contains(.definition) {
        let s = occ.symbol
        guard nominalKinds.contains(s.kind) else { continue }
        let rec = ContainerRecord(usr: s.usr, name: s.name, kind: kindString(s.kind))
        if occ.location.path.contains(sourceRoot) {       // prefer local
            localUSRs.insert(s.usr)
            if result == nil { result = rec }
        } else if external == nil {
            external = rec
        }
    }
    if localUSRs.count > 1 {
        // ambiguous collapse: don't silently pick a wrong edge — surface it.
        FileHandle.standardError.write(
            "kgindex: warning: \(localUSRs.count) local types named '\(name)'; extension collapse uses the first\n".data(using: .utf8)!)
    }
    let resolved = result ?? external
    nominalByNameCache[name] = resolved
    return resolved
}

// Memoized walk: a method/accessor/property symbol → its nearest enclosing nominal
// type. Returns nil for symbols with no type ancestor (free functions, top-level).
var containerCache: [String: ContainerRecord?] = [:]
var resolveInProgress = Set<String>()
@MainActor
func resolveEnclosingType(usr: String, name: String, kind: IndexSymbolKind) -> ContainerRecord? {
    if nominalKinds.contains(kind) {
        return ContainerRecord(usr: usr, name: name, kind: kindString(kind))
    }
    if kind == .extension {
        // collapse onto the extended nominal; fall back to the extension symbol if
        // the nominal is not indexed (e.g. an extension of a stdlib/SwiftUI type).
        return nominalByName(name) ?? ContainerRecord(usr: usr, name: name, kind: "extension")
    }
    if let cached = containerCache[usr] { return cached }
    if resolveInProgress.contains(usr) {
        // childOf cycle (not expected in valid Swift) — surface, don't silently swallow.
        FileHandle.standardError.write("kgindex: warning: childOf cycle at \(usr)\n".data(using: .utf8)!)
        return nil
    }
    resolveInProgress.insert(usr)
    var result: ContainerRecord? = nil
    outer: for occ in db.occurrences(ofUSR: usr, roles: [.definition, .declaration]) {
        for rel in occ.relations where rel.roles.contains(.childOf) {
            if let parent = resolveEnclosingType(usr: rel.symbol.usr, name: rel.symbol.name, kind: rel.symbol.kind) {
                result = parent
                break outer
            }
        }
    }
    resolveInProgress.remove(usr)
    containerCache[usr] = result
    return result
}

// The enclosing type of a reference occurrence, via its `containedBy` relation.
@MainActor
func containerOf(_ occ: SymbolOccurrence) -> ContainerRecord? {
    for rel in occ.relations where rel.roles.contains(.containedBy) {
        if let t = resolveEnclosingType(usr: rel.symbol.usr, name: rel.symbol.name, kind: rel.symbol.kind) {
            return t
        }
    }
    return nil
}

// MARK: - Emit neutral records (def + refs + container), zero policy.

struct RefRecord: Encodable { let path: String; let line: Int; let roles: [String]; let container: ContainerRecord? }
struct SymbolRecord: Encodable {
    let kind: String; let name: String; let usr: String
    let def: Location; let refs: [RefRecord]
    struct Location: Encodable { let path: String; let line: Int }
}

var records: [SymbolRecord] = []
records.reserveCapacity(defs.count)
for d in defs {
    let occs = db.occurrences(ofUSR: d.usr, roles: [.reference, .call])
    var refs: [RefRecord] = []
    for r in occs {
        if r.roles.contains(.definition) { continue }
        if r.location.path == d.path && r.location.line == d.line { continue }
        refs.append(RefRecord(path: r.location.path, line: r.location.line,
                              roles: rolesStrings(r.roles), container: containerOf(r)))
    }
    records.append(SymbolRecord(kind: kindString(d.kind), name: d.name, usr: d.usr,
                                def: .init(path: d.path, line: d.line), refs: refs))
}
records.sort { $0.name < $1.name }

struct Document: Encodable { let version: Int; let sourceRoot: String; let symbols: [SymbolRecord] }
let doc = Document(version: 1, sourceRoot: sourceRoot, symbols: records)

let enc = JSONEncoder()
enc.outputFormatting = [.prettyPrinted, .sortedKeys]
do {
    let data = try enc.encode(doc)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
} catch {
    fail("JSON encode failed: \(error)")
}
FileHandle.standardError.write("kgindex: \(records.count) defs under \(sourceRoot)\n".data(using: .utf8)!)
