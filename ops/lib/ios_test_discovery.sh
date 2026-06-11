#!/usr/bin/env bash
# ios_test_discovery.sh — sourceable test-discovery for ops/ios_test.sh -g.
#
# discover_only_flags <test_dir> <grep_pattern> [target_name]
#   Scans every *.swift under <test_dir> and prints one
#   `-only-testing:<target_name>/<Container>/<func>` line per matching test
#   func, attributing each func to its OWN enclosing test container.
#
# Discovery contract (replaces the old `grep '^struct' | head -1`, which
# misattributed every func to the file's first struct and silently skipped
# files whose container was `@Suite struct` / `class`):
#
#   - A *container* is a TOP-LEVEL (column-0) declaration of:
#       `struct X`, `@Suite struct X`, `final class X`, `class X`,
#       `actor X`, `final actor X`, optionally preceded by access modifiers.
#     Top-level is the reliable discriminator: Swift Testing / XCTest test
#     containers are always declared at file scope, whereas nested helper
#     types (e.g. `struct E: Error {}` inside a func body) are indented and
#     must NOT be treated as containers.
#   - `@Suite(...)` may sit on the same line as `struct` or on its own line
#     above it; either way the following/!current top-level struct is the
#     container.
#   - A *test func* is a column-indented (member) func that is EITHER
#       (a) Swift Testing: carries `@Test` on the same line OR on an attribute
#           line immediately above it (`@Test @MainActor\n    func ...`), OR
#       (b) XCTest: bare `func testXxx(` (name starts with `test`).
#     Plain member helper funcs (`func increment()`, `func save(...)`) are NOT
#     attributed — this is what keeps helpers out of the -only-testing set.
#     Each test func is attributed to the most recent container seen above it.
#   - `<grep_pattern>` (case-insensitive, empty = match all) filters by func
#     name OR container (suite) name: a pattern matching a container selects
#     ALL test funcs attributed to it. File names are never matched.
#
# No Xcode, no PTY, no external deps beyond coreutils — drivable from fixtures.

# Print -only-testing flags for one file. $1=file, $2=pattern (may be empty).
_discover_file() {
  local file="$1" pattern="$2" target="${3:-BooksAndVocabTests}"
  awk -v pattern="$pattern" -v target="$target" '
    # SINGLE source of truth for `-g` pattern semantics, shared by emit() and
    # the multiline-params suite-level fallback below — any third matching
    # expression is drift. Pattern matches the func name OR its enclosing
    # container (suite) name, case-insensitively; empty pattern matches all.
    # `-g <SuiteName>` therefore runs the whole suite instead of wasting a
    # build+test round on "no tests matching" (2026-06-11 friction fix).
    # Helper funcs are still excluded upstream: only attributed test funcs
    # reach either call site.
    function match_fn_or_container(fn, container) {
      if (pattern == "") return 1
      return (tolower(fn) ~ tolower(pattern) || tolower(container) ~ tolower(pattern))
    }
    function emit(fn, is_swift, sig) {
      if (container == "") return
      if (!match_fn_or_container(fn, container)) return
      # Swift Testing requires the FULL func signature in the -only-testing
      # identifier: `name()` for zero-param funcs, `name(_:)` / `name(label:)`
      # for parameterized @Test(arguments:) funcs. XCTest uses the bare method
      # name. Emitting the wrong arity (historically a hardcoded "()") makes
      # xcodebuild match 0 tests → "TEST SUCCEEDED" with nothing run — a silent
      # FALSE GREEN only caught by the post-run zero-tests guard in ios_test.sh.
      print "-only-testing:" target "/" container "/" fn (is_swift ? sig : "")
    }
    # `(label1:label2:)` from the raw parameter-list text (between the func
    # declaration parens). Splits on TOP-LEVEL commas only — depth-tracked over
    # ( [ < so tuple types `(Int, String)`, generics and default-value calls do
    # not split a parameter; `>` preceded by `-` (function-type arrow) is not a
    # depth closer. Each parameter contributes its EXTERNAL label (first token
    # before whitespace/colon; `_` for unlabeled).
    function sig_from_params(params,   i, c, d, n, piece, sig) {
      gsub(/^[ \t]+|[ \t]+$/, "", params)
      if (params == "") return "()"
      d = 0; n = length(params); piece = ""; sig = "("
      for (i = 1; i <= n; i++) {
        c = substr(params, i, 1)
        if (c == "(" || c == "[" || c == "<") d++
        else if (c == ")" || c == "]") d--
        else if (c == ">" && d > 0 && substr(params, i - 1, 1) != "-") d--
        if (c == "," && d == 0) { sig = sig param_label(piece) ":"; piece = "" }
        else piece = piece c
      }
      return sig param_label(piece) ":)"
    }
    function param_label(piece) {
      gsub(/^[ \t]+/, "", piece)
      sub(/[ \t:].*$/, "", piece)
      return piece
    }
    # Parameter-list text of a single-line func declaration → PARAMS_OUT.
    # Returns 1 when the list closes on this line; 0 when it spans lines
    # (no test in this repo does — helpers with multiline params are not
    # tests — but the caller still degrades to a suite-level selector rather
    # than guessing a wrong signature).
    function extract_params(line,   tmp, i, c, d, n) {
      tmp = line
      if (!sub(/^.*func[ \t]+[A-Za-z0-9_]+[ \t]*\(/, "(", tmp)) return 0
      d = 0; n = length(tmp); PARAMS_OUT = ""
      for (i = 1; i <= n; i++) {
        c = substr(tmp, i, 1)
        if (c == "(") { d++; if (d == 1) continue }
        else if (c == ")") { d--; if (d == 0) return 1 }
        PARAMS_OUT = PARAMS_OUT c
      }
      return 0
    }
    {
      line = $0
      # Top-level container declaration (column 0, optional modifiers / @Suite).
      # Matches:  struct X | @Suite struct X | final class X | class X | actor X
      if (line ~ /^(@Suite([ \t]*\([^)]*\))?[ \t]+)?((public|internal|private|fileprivate|final)[ \t]+)*(struct|class|actor)[ \t]+[A-Za-z0-9_]+/) {
        name = line
        sub(/^(@Suite([ \t]*\([^)]*\))?[ \t]+)?((public|internal|private|fileprivate|final)[ \t]+)*(struct|class|actor)[ \t]+/, "", name)
        sub(/[^A-Za-z0-9_].*$/, "", name)
        container = name
        pending_test = 0   # a new container boundary cancels any dangling arm
        next
      }
      # Bare top-level @Suite line (attribute above the struct) — keep scanning;
      # the struct on the next line sets the container.
      if (line ~ /^@Suite([ \t]*\([^)]*\))?[ \t]*$/) next

      # A @Test attribute line that does NOT itself declare the func arms the
      # next member func as a Swift Testing test. This covers every form whose
      # `func` lands on a later line:
      #   @Test                         (bare)
      #   @Test @MainActor              (chained attribute, no func yet)
      #   @Test("display name")         (display-name only)
      #   @Test(.tags(...))             (trait only)
      #   @Test(arguments: [1, 2, 3])   (single-line argument list)
      #   @Test(arguments: [           (MULTILINE argument list — paren stays
      #       ...                        open; intervening rows are ignored by
      #   ])                             the awaiting-func state below)
      # The arm persists across argument/comment rows until a `func` consumes
      # it; a container declaration (handled above) resets it.
      if (line ~ /^[ \t]*@Test([ \t(]|$)/ && line !~ /(^|[ \t])func[ \t]/) {
        pending_test = 1
        next
      }
      # While a @Test arm is pending, swallow intervening rows (argument tuples,
      # closing `])`, blank lines, comments) so they do not clear the arm before
      # the func that the attribute decorates is reached.
      if (pending_test) {
        if (line ~ /^[ \t]+(@Test[ \t]+)?((@[A-Za-z]+([ \t]*\([^)]*\))?[ \t]+)*)?((public|internal|private|fileprivate|static|final|mutating|override|nonisolated)[ \t]+)*func[ \t]+[A-Za-z0-9_]+[ \t]*\(/) {
          # fall through to the member-func handler below to emit + reset.
        } else {
          next
        }
      }

      # Member func (indented). Top-level funcs are never tests.
      if (line ~ /^[ \t]+(@Test[ \t]+)?((@[A-Za-z]+([ \t]*\([^)]*\))?[ \t]+)*)?((public|internal|private|fileprivate|static|final|mutating|override|nonisolated)[ \t]+)*func[ \t]+[A-Za-z0-9_]+[ \t]*\(/) {
        same_line_test = (line ~ /@Test([ \t]|$)/)
        fn = line
        sub(/^.*func[ \t]+/, "", fn)
        sub(/[ \t]*\(.*$/, "", fn)
        # Swift Testing iff decorated with @Test (same line or pending arm above);
        # a bare `func testXxx` with no @Test is XCTest.
        is_swift = (same_line_test || pending_test)
        is_test = (is_swift || fn ~ /^test/)
        if (is_test) {
          if (is_swift) {
            if (extract_params(line)) {
              emit(fn, 1, sig_from_params(PARAMS_OUT))
            } else if (container != "" && match_fn_or_container(fn, container)) {
              # Param list spans lines — signature unknowable from this line.
              # Fall back to the SUITE-level selector: a safe superset that
              # always matches, never a silent zero-match.
              print "-only-testing:" target "/" container
            }
          } else {
            emit(fn, 0, "")
          }
        }
        pending_test = 0
        next
      }

      # Any other non-blank line clears a dangling @Test arm (defensive).
      if (line !~ /^[ \t]*$/) pending_test = 0
    }
  ' "$file"
}

# Print all -only-testing flags across <test_dir>. $1=dir, $2=pattern.
discover_only_flags() {
  local test_dir="$1" pattern="${2:-}" target="${3:-BooksAndVocabTests}" f
  for f in "$test_dir"/*.swift; do
    [[ -f "$f" ]] || continue
    _discover_file "$f" "$pattern" "$target"
  done
}

# Print all -only-testing flags from one test file. $1=file, $2=pattern, $3=target.
discover_file_only_flags() {
  local file="$1" pattern="${2:-}" target="${3:-BooksAndVocabTests}"
  [[ -f "$file" ]] || return 1
  _discover_file "$file" "$pattern" "$target"
}
