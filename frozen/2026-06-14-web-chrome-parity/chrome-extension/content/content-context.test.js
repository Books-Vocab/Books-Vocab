'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const contentSrc = fs.readFileSync(path.join(__dirname, 'content.js'), 'utf8');

function extractFn(name) {
  const start = contentSrc.indexOf('function ' + name);
  assert.notEqual(start, -1, `${name} not found`);
  let depth = 0;
  let seen = false;
  for (let i = start; i < contentSrc.length; i++) {
    if (contentSrc[i] === '{') {
      depth += 1;
      seen = true;
    } else if (contentSrc[i] === '}') {
      depth -= 1;
      if (seen && depth === 0) return contentSrc.slice(start, i + 1);
    }
  }
  throw new Error(`${name} body not closed`);
}

function runFn(name, chrome) {
  return vm.runInNewContext(
    `"use strict"; ${extractFn(name)}; ${name}();`,
    { chrome, globalThis: { chrome } }
  );
}

function runFns(names, expression, context) {
  const source = names.map(extractFn).join('\n');
  return vm.runInNewContext(`"use strict"; ${source}; ${expression}`, context);
}

test('extensionContextValid treats invalidated runtime.id access as unavailable', () => {
  const chrome = {
    runtime: {
      get id() {
        throw new Error('Extension context invalidated.');
      },
    },
  };

  assert.equal(runFn('extensionContextValid', chrome), false);
});

test('runtimeLastError tolerates invalidated runtime access', () => {
  const chrome = {
    runtime: {
      get lastError() {
        throw new Error('Extension context invalidated.');
      },
    },
  };

  assert.equal(runFn('runtimeLastError', chrome).message, 'Extension context invalidated.');
});

test('i18nMessage tolerates invalidated getMessage access used by popup head', () => {
  const chrome = {
    runtime: { id: 'kg-test' },
    i18n: {
      get getMessage() {
        throw new Error('Extension context invalidated.');
      },
    },
  };

  const value = runFns(
    ['i18nMessage'],
    "i18nMessage('popupSpeakAria')",
    { chrome, globalThis: { chrome } }
  );
  assert.equal(value, '');
});
