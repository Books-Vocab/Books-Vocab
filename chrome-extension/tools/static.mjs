/**
 * Chrome static integrity check (Layer 1 of ops/chrome_verify.sh).
 *
 * Fast (no browser): catches the load-blocking errors before the render smoke
 * test even starts, and pinpoints them precisely (the smoke test only says "a
 * surface is broken"). Also covers surfaces the smoke test can't open — the
 * content script and the service worker.
 *
 * Hard failures (exit 1):
 *   - manifest.json invalid JSON, or referencing a file that does not exist
 *     (service_worker, content_scripts, side_panel, options_ui, icons,
 *     web_accessible_resources, default_locale messages)
 *   - any .js with a syntax error (ESM files checked in module mode)
 *   - any <link href> / <script src> in an HTML page pointing at a missing file
 *   - messages.json invalid JSON
 *
 * Warnings (reported, non-fatal): a data-i18n / getMessage / t() key with no
 * entry in messages.json (chrome.i18n returns '' → blank UI, not a crash).
 *
 * Usage:  node tools/static.mjs
 */

import { execFileSync } from 'node:child_process';
import { readFileSync, existsSync, readdirSync, writeFileSync, unlinkSync } from 'node:fs';
import { join, resolve, dirname, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const EXT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const fails = [];
const warns = [];
const fail = (m) => fails.push(m);
const warn = (m) => warns.push(m);
const rel = (p) => relative(EXT, p);

const read = (p) => readFileSync(p, 'utf8');
const abs = (p) => join(EXT, p);

// All .js / .html under the extension, excluding tooling + deps.
function walk() {
  const out = { js: [], html: [] };
  for (const name of readdirSync(EXT, { recursive: true })) {
    const p = String(name);
    if (p.includes('node_modules') || p.startsWith('tools/')) continue;
    if (p.endsWith('.js')) out.js.push(join(EXT, p));
    else if (p.endsWith('.html')) out.html.push(join(EXT, p));
  }
  return out;
}

// -------------------------------------------------------------------------
// 1. manifest.json — valid JSON + every referenced path exists
// -------------------------------------------------------------------------
function checkManifest() {
  const mpath = abs('manifest.json');
  if (!existsSync(mpath)) return fail('manifest.json missing');
  let m;
  try {
    m = JSON.parse(read(mpath));
  } catch (e) {
    return fail(`manifest.json invalid JSON: ${e.message}`);
  }

  const must = (p, label) => {
    if (!p) return;
    if (!existsSync(abs(p))) fail(`manifest ${label} → missing file: ${p}`);
  };

  must(m.background?.service_worker, 'background.service_worker');
  must(m.side_panel?.default_path, 'side_panel.default_path');
  must(m.options_ui?.page, 'options_ui.page');
  must(m.action?.default_popup, 'action.default_popup');
  for (const [size, p] of Object.entries(m.icons || {})) must(p, `icons[${size}]`);
  for (const [i, cs] of (m.content_scripts || []).entries()) {
    for (const j of cs.js || []) must(j, `content_scripts[${i}].js`);
    for (const c of cs.css || []) must(c, `content_scripts[${i}].css`);
  }
  for (const [i, war] of (m.web_accessible_resources || []).entries()) {
    for (const r of war.resources || []) {
      // glob entries (foo/*) — check the directory; literal entries — the file.
      if (r.includes('*')) {
        const d = abs(r.replace(/\/?\*+.*$/, ''));
        if (!existsSync(d)) fail(`web_accessible_resources[${i}] glob → missing dir: ${r}`);
      } else {
        must(r, `web_accessible_resources[${i}]`);
      }
    }
  }
  const locale = m.default_locale;
  if (locale && !existsSync(abs(`_locales/${locale}/messages.json`))) {
    fail(`default_locale '${locale}' → missing _locales/${locale}/messages.json`);
  }
  return m;
}

// -------------------------------------------------------------------------
// 2. JS syntax — node --check (ESM files checked in module mode)
// -------------------------------------------------------------------------
function checkJsSyntax(files) {
  for (const f of files) {
    const src = read(f);
    const isESM = /^\s*(import|export)\s/m.test(src);
    try {
      if (!isESM) {
        execFileSync(process.execPath, ['--check', f], { stdio: 'pipe' });
      } else {
        // node --check infers CommonJS for a .js with no package.json type, so
        // copy ESM sources to a .mjs sibling for the check.
        const tmp = f.replace(/\.js$/, '.__syntaxcheck__.mjs');
        writeFileSync(tmp, src);
        try {
          execFileSync(process.execPath, ['--check', tmp], { stdio: 'pipe' });
        } finally {
          unlinkSync(tmp);
        }
      }
    } catch (e) {
      const msg = (e.stderr ? e.stderr.toString() : e.message).split('\n').find((l) => l.includes('Error')) || e.message;
      fail(`syntax error in ${rel(f)}: ${msg.trim()}`);
    }
  }
}

// -------------------------------------------------------------------------
// 3. HTML asset references — every <link href> / <script src> exists
// -------------------------------------------------------------------------
function checkHtmlAssets(files) {
  const refRe = /(?:href|src)\s*=\s*"([^"]+)"/g;
  for (const f of files) {
    const src = read(f);
    let m;
    while ((m = refRe.exec(src))) {
      const ref = m[1];
      if (/^(https?:|data:|#|mailto:|chrome:)/.test(ref)) continue;
      const target = resolve(dirname(f), ref.split(/[?#]/)[0]);
      if (!existsSync(target)) fail(`${rel(f)} → missing asset: ${ref}`);
    }
  }
}

// -------------------------------------------------------------------------
// 4. i18n — every used key exists in the default-locale messages.json
// -------------------------------------------------------------------------
function checkI18n(manifest, html, js) {
  const locale = manifest?.default_locale;
  if (!locale) return;
  const mpath = abs(`_locales/${locale}/messages.json`);
  if (!existsSync(mpath)) return; // already failed in checkManifest
  let messages;
  try {
    messages = JSON.parse(read(mpath));
  } catch (e) {
    return fail(`_locales/${locale}/messages.json invalid JSON: ${e.message}`);
  }
  const defined = new Set(Object.keys(messages));
  const used = new Map(); // key → first file that used it

  const note = (key, file) => { if (key && !used.has(key)) used.set(key, rel(file)); };

  for (const f of html) {
    const src = read(f);
    let m;
    const di = /data-i18n\s*=\s*"([^"]+)"/g;
    while ((m = di.exec(src))) note(m[1], f);
    const da = /data-i18n-attr\s*=\s*"([^"]+)"/g;
    while ((m = da.exec(src))) {
      for (const pair of m[1].split(';')) {
        const key = pair.split(':')[1]?.trim();
        if (key) note(key, f);
      }
    }
  }
  for (const f of js) {
    const src = read(f);
    let m;
    const g = /getMessage\(\s*['"]([A-Za-z][\w]*)['"]/g;
    while ((m = g.exec(src))) note(m[1], f);
    // content.js / sidepanel/app.js / options/options.js each alias
    // chrome.i18n.getMessage to a short `t()` accessor and call t('literalKey')
    // dozens of times. Mine those literal keys too, gated on the alias being
    // present so unrelated `t(` calls in other files aren't taken for i18n keys.
    // (False positives are harmless anyway — only keys MISSING from messages.json
    // warn; an over-matched key that exists is silent.)
    if (/chrome\.i18n\.getMessage/.test(src)) {
      const tc = /\bt\(\s*['"]([A-Za-z][\w]*)['"]/g;
      while ((m = tc.exec(src))) note(m[1], f);
    }
  }

  for (const [key, file] of used) {
    if (!defined.has(key)) warn(`i18n key '${key}' used in ${file} but not in _locales/${locale}/messages.json (renders blank)`);
  }
}

// -------------------------------------------------------------------------

const { js, html } = walk();
const manifest = checkManifest();
checkJsSyntax(js);
checkHtmlAssets(html);
checkI18n(manifest, html, js);

for (const w of warns) console.error(`⚠ ${w}`);
if (fails.length) {
  for (const f of fails) console.error(`✗ ${f}`);
  console.error(`\nSTATIC FAILED — ${fails.length} error(s).`);
  process.exit(1);
}
console.error(`✓ static checks passed (${js.length} js, ${html.length} html${warns.length ? `, ${warns.length} warning(s)` : ''})`);
