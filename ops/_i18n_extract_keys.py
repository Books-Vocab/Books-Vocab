#!/usr/bin/env -S uv run --python 3.13 python
# Extract i18n keys statically referenced from Swift sources.
#
# Outputs JSON to stdout:
#   {
#     "keys":               [...]   # union of all statically-resolvable keys
#     "plural_keys":        [...]   # keys passed via L10n.format(...) (plural candidates)
#     "dynamic_unresolved": [...]   # "file:line: <snippet>" for non-static call sites
#                                   # (excluding the AppLanguage/AppAppearanceMode enum
#                                   #  pattern, which is statically expanded)
#   }
#
# Patterns scanned (per non-stripped .swift, excluding *Preview*.swift / *Tests*.swift /
# *PreviewData* and stripping `#Preview {...}` / `private struct *Preview` bodies via
# _i18n_strip_previews.py):
#
#   1. "<key>".localized
#   2. L10n.string("<key>")
#   3. L10n.format("<key>", ...)
#   4. Enum `titleKey: String { switch self { case ...: return "<key>" ... } }`
#      AND `case ...: return L10n.string("<key>")` — keys collected into the static set.
#      Currently expands `AppLanguage` and `AppAppearanceMode`.
#
# Lines with `// i18n-allow` are skipped.
#
# Non-static call shapes (e.g. `L10n.string(someVar)` where `someVar` isn't a
# known enum's titleKey reference) are reported under dynamic_unresolved.

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IOS_SRC = ROOT / "ios" / "BooksAndVocab"
STRIP_PREVIEWS = ROOT / "ops" / "_i18n_strip_previews.py"

# Load the preview-stripper as a module (loaded from its absolute path so this
# works regardless of the caller's CWD / sys.path) and reuse its pure
# text->text strip_previews(), instead of spawning one python3 subprocess per
# Swift file — which is slow at repo scale and depends on bare `python3` on PATH.
_strip_spec = importlib.util.spec_from_file_location("_i18n_strip_previews", STRIP_PREVIEWS)
_strip_mod = importlib.util.module_from_spec(_strip_spec)
_strip_spec.loader.exec_module(_strip_mod)

EXCLUDE_SUBSTRINGS = ("Preview", "Tests", "PreviewData")

# "<key>".localized — capture the literal inside the quotes
RE_DOT_LOCALIZED = re.compile(r'"((?:[^"\\]|\\.)*)"\s*\.localized\b')
RE_L10N_STRING = re.compile(r'\bL10n\.string\(\s*"((?:[^"\\]|\\.)*)"\s*[,\)]')
RE_L10N_FORMAT = re.compile(r'\bL10n\.format\(\s*"((?:[^"\\]|\\.)*)"\s*[,\)]')

# Dynamic shapes — same prefix but no opening quote inside paren.
RE_L10N_STRING_DYNAMIC = re.compile(r'\bL10n\.string\(\s*(?!")')
RE_L10N_FORMAT_DYNAMIC = re.compile(r'\bL10n\.format\(\s*(?!")')
RE_VAR_DOT_LOCALIZED = re.compile(r'\b([A-Za-z_][\w.]*)\.localized\b')

ALLOW_MARK = re.compile(r'//\s*i18n-allow')

# Known enums whose `titleKey: String` we statically expand. We do not auto-
# discover enums to keep behavior deterministic — add new ones here when the
# call-site grep below stops being exhaustive.
KNOWN_TITLEKEY_TYPES = ("AppLanguage", "AppAppearanceMode")


def list_swift_files() -> list[Path]:
    out: list[Path] = []
    for path in IOS_SRC.rglob("*.swift"):
        name = path.name
        if any(s in name for s in EXCLUDE_SUBSTRINGS):
            continue
        out.append(path)
    return sorted(out)


def strip_previews(path: Path) -> str:
    # Reuse the existing preview-stripper so blank lines preserve line numbers.
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return path.read_text(encoding="utf-8", errors="replace")
    return _strip_mod.strip_previews(text)


def extract_titlekey_literals(text: str) -> list[str]:
    """Find `titleKey: String { ... }` blocks inside a known enum and pull all
    case-returned literals.

    Recognizes two shapes inside the switch:
        case .foo: return "raw"
        case .foo: return L10n.string("raw")
    """
    keys: list[str] = []
    # Find any of the known enum declarations.
    enum_re = re.compile(
        r"\benum\s+(" + "|".join(KNOWN_TITLEKEY_TYPES) + r")\b[^{]*\{",
        re.MULTILINE,
    )
    for enum_match in enum_re.finditer(text):
        # Brace-match the enum body.
        body_start = enum_match.end()  # right after `{`
        depth = 1
        i = body_start
        while i < len(text) and depth > 0:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        enum_body = text[body_start : i - 1]

        # Inside the enum, find the `titleKey: String { ... }` getter.
        # Tolerate `var titleKey: String {` with optional whitespace.
        tk_re = re.compile(r"\bvar\s+titleKey\s*:\s*String\s*\{")
        tk_match = tk_re.search(enum_body)
        if not tk_match:
            continue
        getter_start = tk_match.end()
        depth = 1
        j = getter_start
        while j < len(enum_body) and depth > 0:
            c = enum_body[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        getter_body = enum_body[getter_start : j - 1]

        # Collect every literal in the getter (covers both raw and L10n-wrapped).
        for lit in re.findall(r'"((?:[^"\\]|\\.)*)"', getter_body):
            keys.append(lit)
    return keys


def scan_file(path: Path) -> tuple[set[str], set[str], list[str]]:
    keys: set[str] = set()
    plural_keys: set[str] = set()
    dynamic: list[str] = []

    text = strip_previews(path)

    # Enum titleKey expansion is whole-file scope.
    for lit in extract_titlekey_literals(text):
        keys.add(lit)

    rel = path.relative_to(ROOT)
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARK.search(line):
            continue
        # Skip whole-line comments — they contain example/prose text that
        # would otherwise pollute dynamic_unresolved and (rarely) keys.
        if line.lstrip().startswith("//"):
            continue
        for m in RE_DOT_LOCALIZED.finditer(line):
            keys.add(m.group(1))
        for m in RE_L10N_STRING.finditer(line):
            keys.add(m.group(1))
        for m in RE_L10N_FORMAT.finditer(line):
            k = m.group(1)
            keys.add(k)
            plural_keys.add(k)

        # Dynamic shapes — anything that looks like L10n.string( / L10n.format(
        # but doesn't open with a quote.
        for rx in (RE_L10N_STRING_DYNAMIC, RE_L10N_FORMAT_DYNAMIC):
            if rx.search(line):
                # Suppress the AppLanguage/AppAppearanceMode pattern; their cases
                # are already enumerated via extract_titlekey_literals.
                if ".titleKey" in line:
                    continue
                dynamic.append(f"{rel}:{lineno}: {line.strip()}")

        # Variable.localized — flag unless it's a `.titleKey.localized` we handle.
        for m in RE_VAR_DOT_LOCALIZED.finditer(line):
            ident = m.group(1)
            if ident.endswith("titleKey"):
                continue
            dynamic.append(f"{rel}:{lineno}: {line.strip()}")
            break  # one report per line is enough

    return keys, plural_keys, dynamic


def main(argv: list[str]) -> int:
    all_keys: set[str] = set()
    plural_keys: set[str] = set()
    dynamic: list[str] = []

    for f in list_swift_files():
        k, p, d = scan_file(f)
        all_keys.update(k)
        plural_keys.update(p)
        dynamic.extend(d)

    out = {
        "keys": sorted(all_keys),
        "plural_keys": sorted(plural_keys),
        "dynamic_unresolved": sorted(set(dynamic)),
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
