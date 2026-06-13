#!/usr/bin/env node
// ============================================================
// Parity-isolation static lint for responsive CSS.
//
// WHY: The parity capture path (?surface=X without ?shell=1) renders
// PhoneFrame -> SurfaceView in a fixed 393x852 .phone-frame and screenshots
// ONLY the [data-harness="phone-frame"] subtree. Responsive layout CSS is
// web-only chrome that must ONLY ever apply under .kg-responsive-shell (mounted
// solely by ResponsiveShell on the shell path at tablet+). If a future fan-out
// stream lands a responsive rule that reaches the parity DOM (.phone-frame or a
// bare *-surface root), all 290 parity cases silently regress.
//
// This check scans src/ ** / *.css and FAILS (exit 1) on the real leak patterns:
//   A) Any selector containing `.phone-frame` inside a responsive context
//      (@media min-width>=768, or @container).
//   B) Any rule inside a responsive context (@media min-width>=768, or
//      @container) whose selector list has NO `.kg-responsive-shell` ancestor.
//   C) Any rule referencing a web-only responsive layout var that targets a
//      parity-DOM root (.phone-frame / [data-harness=phone-frame] / *-surface)
//      WITHOUT a `.kg-responsive-shell` ancestor.
//
// Conservative by design: prefers-reduced-motion, max-width-only and
// min-width<768 media blocks are NOT responsive contexts, so the correctly
// scoped foundation (responsive.css) and the component-crop / scenario
// .phone-frame[...] rules in surface CSS are all CLEAN.
//
// No deps beyond Node builtins. Run: node tools/check-responsive-isolation.mjs
// ============================================================

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const WEB_ROOT = join(__dirname, '..');
const SRC_ROOT = join(WEB_ROOT, 'src');

const RESPONSIVE_SHELL_TOKEN = '.kg-responsive-shell';
// Web-only responsive layout custom properties (declared in responsive.css,
// scoped to .kg-responsive-shell). Referencing one outside that scope on a
// parity root is a leak.
const RESPONSIVE_LAYOUT_VARS = [
  '--shell-sidenav-w',
  '--shell-rail-w',
  '--pane-list-w',
  '--reader-measure',
  '--content-max-w',
];
// Minimum viewport at which a min-width media query is treated as "responsive"
// (the tablet breakpoint). Anything below this targets the phone capture width
// and is intentionally not a responsive context.
const RESPONSIVE_MIN_WIDTH_PX = 768;

// ---------------------------------------------------------------------------
// File discovery
// ---------------------------------------------------------------------------

/** @returns {string[]} absolute paths to every *.css under SRC_ROOT */
function findCssFiles(dir) {
  /** @type {string[]} */
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      out.push(...findCssFiles(full));
    } else if (entry.endsWith('.css')) {
      out.push(full);
    }
  }
  return out.sort();
}

// ---------------------------------------------------------------------------
// CSS scanning (block-aware, comment-stripping, brace-depth tokenizer)
//
// We don't need a full CSS parser. We walk the source char-by-char, tracking:
//   - byte offset -> line number (for reporting)
//   - the stack of currently-open at-rule preludes (for @media / @container)
//   - rule preludes (selector lists) immediately before a `{`
// and emit one "rule" record per declaration block whose prelude is a selector
// (i.e. not itself an at-rule). Each record carries the chain of enclosing
// at-rule preludes so we can decide if it is in a responsive context.
// ---------------------------------------------------------------------------

/**
 * @param {string} css raw file text
 * @returns {{selector:string, body:string, line:number, atChain:string[]}[]}
 */
function extractRules(css) {
  // Strip comments but preserve newlines so line numbers stay accurate.
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, (m) =>
    m.replace(/[^\n]/g, ' '),
  );

  /** @type {{selector:string, body:string, line:number, atChain:string[]}[]} */
  const rules = [];
  // Stack of open at-rule preludes (e.g. "@media (min-width: 768px)").
  /** @type {string[]} */
  const atChain = [];
  let prelude = '';
  let preludeStartIdx = -1;
  let i = 0;
  const len = stripped.length;

  const lineAt = (idx) => {
    let line = 1;
    for (let k = 0; k < idx && k < len; k++) {
      if (stripped[k] === '\n') line++;
    }
    return line;
  };

  while (i < len) {
    const ch = stripped[i];
    if (ch === '{') {
      const pre = prelude.trim();
      const startIdx = preludeStartIdx;
      prelude = '';
      preludeStartIdx = -1;
      if (pre.startsWith('@')) {
        // At-rule with a block (e.g. @media / @container / @supports).
        atChain.push(pre);
        i++;
        // Mark depth so the matching `}` pops the chain. We track with a sentinel.
        atChain[atChain.length - 1] = pre; // (kept explicit for readability)
        continue;
      }
      // Selector rule: capture its body up to the matching `}`.
      let depth = 1;
      let j = i + 1;
      for (; j < len && depth > 0; j++) {
        if (stripped[j] === '{') depth++;
        else if (stripped[j] === '}') depth--;
      }
      const body = stripped.slice(i + 1, j - 1);
      rules.push({
        selector: pre,
        body,
        line: lineAt(startIdx >= 0 ? startIdx : i),
        atChain: [...atChain],
      });
      i = j;
      continue;
    }
    if (ch === '}') {
      // Close of an at-rule block.
      if (atChain.length > 0) atChain.pop();
      prelude = '';
      preludeStartIdx = -1;
      i++;
      continue;
    }
    if (ch === ';') {
      // A statement-level at-rule (e.g. @import) or stray declaration; reset.
      prelude = '';
      preludeStartIdx = -1;
      i++;
      continue;
    }
    if (prelude === '' && !/\s/.test(ch)) preludeStartIdx = i;
    prelude += ch;
    i++;
  }
  return rules;
}

// ---------------------------------------------------------------------------
// Predicates
// ---------------------------------------------------------------------------

/** Largest min-width (px) declared anywhere in an at-rule prelude, or 0. */
function maxMinWidthPx(prelude) {
  let max = 0;
  const re = /min-width\s*:\s*([\d.]+)px/gi;
  let m;
  while ((m = re.exec(prelude))) {
    const v = parseFloat(m[1]);
    if (!Number.isNaN(v) && v > max) max = v;
  }
  return max;
}

/** True if the at-rule chain establishes a responsive context. */
function isResponsiveAtChain(atChain) {
  return atChain.some((a) => {
    if (/^@container\b/i.test(a)) return true;
    if (/^@media\b/i.test(a)) {
      return maxMinWidthPx(a) >= RESPONSIVE_MIN_WIDTH_PX;
    }
    return false;
  });
}

/** True if any selector in the comma list is under a .kg-responsive-shell ancestor. */
function allSelectorsScoped(selector) {
  return splitSelectorList(selector).every((s) =>
    s.includes(RESPONSIVE_SHELL_TOKEN),
  );
}

/** Selectors (in the comma list) that lack a .kg-responsive-shell ancestor. */
function unscopedSelectors(selector) {
  return splitSelectorList(selector).filter(
    (s) => !s.includes(RESPONSIVE_SHELL_TOKEN),
  );
}

/** Split a selector list on top-level commas (ignore commas inside :not(...) etc). */
function splitSelectorList(selector) {
  const out = [];
  let depth = 0;
  let cur = '';
  for (const ch of selector) {
    if (ch === '(' || ch === '[') depth++;
    else if (ch === ')' || ch === ']') depth--;
    if (ch === ',' && depth === 0) {
      out.push(cur.trim());
      cur = '';
    } else {
      cur += ch;
    }
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

/** True if a single selector targets a parity-DOM root marker. */
function targetsParityRoot(sel) {
  if (sel.includes('.phone-frame')) return true;
  if (/\[data-harness\s*[~=]?\s*=?\s*["']?phone-frame/i.test(sel)) return true;
  // Bare per-surface root classes: the `*-surface` family rendered by SurfaceView.
  if (/\.[a-z][a-z0-9-]*-surface\b/i.test(sel)) return true;
  return false;
}

/** True if a rule references a web-only responsive layout var. */
function referencesResponsiveVar(selector, body) {
  const hay = selector + ' ' + body;
  return RESPONSIVE_LAYOUT_VARS.some((v) => hay.includes(v));
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main() {
  const files = findCssFiles(SRC_ROOT);
  /** @type {{file:string, line:number, rule:string, reason:string}[]} */
  const violations = [];

  for (const file of files) {
    const rel = relative(WEB_ROOT, file);
    const css = readFileSync(file, 'utf8');
    const rules = extractRules(css);

    for (const r of rules) {
      const responsiveCtx = isResponsiveAtChain(r.atChain);
      const ruleHead = r.selector.replace(/\s+/g, ' ').trim();

      // (A) .phone-frame inside a responsive context — always a leak.
      if (responsiveCtx && r.selector.includes('.phone-frame')) {
        violations.push({
          file: rel,
          line: r.line,
          rule: ruleHead,
          reason:
            'selector targets .phone-frame inside a responsive context (min-width>=768 / @container)',
        });
        continue;
      }

      // (B) Any rule in a responsive context lacking a .kg-responsive-shell ancestor.
      if (responsiveCtx && !allSelectorsScoped(r.selector)) {
        const leaked = unscopedSelectors(r.selector).join(', ') || ruleHead;
        violations.push({
          file: rel,
          line: r.line,
          rule: leaked,
          reason:
            'responsive rule (min-width>=768 / @container) is not scoped under .kg-responsive-shell',
        });
        continue;
      }

      // (C) References a responsive layout var, targets a parity root, unscoped.
      if (referencesResponsiveVar(r.selector, r.body)) {
        const offending = splitSelectorList(r.selector).filter(
          (s) => !s.includes(RESPONSIVE_SHELL_TOKEN) && targetsParityRoot(s),
        );
        if (offending.length > 0) {
          violations.push({
            file: rel,
            line: r.line,
            rule: offending.join(', '),
            reason:
              'rule references a web-only responsive layout var and targets a parity-DOM root (.phone-frame / *-surface) outside .kg-responsive-shell',
          });
        }
      }
    }
  }

  if (violations.length > 0) {
    console.error('parity-isolation: RESPONSIVE CSS LEAK(S) DETECTED\n');
    for (const v of violations) {
      console.error(`  ${v.file}:${v.line}`);
      console.error(`    rule:   ${v.rule}`);
      console.error(`    reason: ${v.reason}\n`);
    }
    console.error(
      `parity-isolation: ${violations.length} violation(s). ` +
        'Responsive layout CSS must live under .kg-responsive-shell and never ' +
        'touch .phone-frame or a bare *-surface root.',
    );
    process.exit(1);
  }

  console.log(
    `parity-isolation: CLEAN — scanned ${files.length} CSS file(s), no responsive leak into parity DOM.`,
  );
  process.exit(0);
}

main();
