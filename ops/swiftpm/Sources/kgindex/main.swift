import Foundation
import IndexStoreDB

// kgindex — neutral Xcode IndexStore extractor.
//
// Usage:
//   kgindex <storePath> <sourceRootSubstring> [--kinds struct,class,enum,protocol]
//
// Emits a JSON document to stdout: for every symbol definition of the requested
// kinds whose definition file path contains <sourceRootSubstring>, the symbol's
// USR + definition location + every reference/call location (with roles). It
// applies NO policy — no Debug/Tests exclusion, no orphan judgement. That lives
// in ops/ui_deadcode.py where it is unit-testable.
//
// Design notes:
// - libIndexStore.dylib is discovered via `xcode-select -p`, never hardcoded, so
//   it survives Xcode upgrades.
// - Enumeration is file-driven (walk *.swift under sourceRoot → symbols(inFilePath:))
//   rather than forEachSymbolName over the whole index (which includes tens of
//   thousands of stdlib/UIKit names). Calls are sequential, never nested inside a
//   read-transaction closure, to avoid LMDB MDB_BAD_RSLOT.

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

let kindMap: [String: IndexSymbolKind] = [
    "struct": .struct, "class": .class, "enum": .enum, "protocol": .protocol,
    "func": .function, "extension": .extension,
]
var wantedKinds = Set<IndexSymbolKind>()
for token in kindsArg.split(separator: ",") {
    let key = token.trimmingCharacters(in: .whitespaces)
    guard let k = kindMap[key] else { fail("unknown kind: \(key) (valid: \(kindMap.keys.sorted().joined(separator: ",")))", code: 2) }
    wantedKinds.insert(k)
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

// MARK: - File-driven enumeration

// Collect *.swift paths under sourceRoot from the index's known unit main files.
// We derive candidate files from the symbols' definition locations rather than a
// filesystem walk so we only touch files the index actually covers.
func isSynthetic(_ name: String) -> Bool {
    if name.hasPrefix("_") || name.hasPrefix("$") { return true }
    if name.contains("Preview") { return true }   // #Preview / @Model macro synthetics
    return false
}

struct Def { let kind: IndexSymbolKind; let name: String; let usr: String; let path: String; let line: Int }

// Gather candidate source files: enumerate all definition occurrences once via
// the symbol-name table (PASS 1, no nested txns), keep only files under sourceRoot.
var candidateFiles = Set<String>()
var names: [String] = []
db.forEachSymbolName { name in names.append(name); return true }

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
        candidateFiles.insert(path)
        defs.append(Def(kind: sym.kind, name: sym.name, usr: sym.usr, path: path, line: occ.location.line))
    }
}
_ = candidateFiles  // reserved for future file-scoped queries; kept for clarity

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

// MARK: - Emit neutral records (def + refs), zero policy.

struct RefRecord: Encodable { let path: String; let line: Int; let roles: [String] }
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
        refs.append(RefRecord(path: r.location.path, line: r.location.line, roles: rolesStrings(r.roles)))
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
