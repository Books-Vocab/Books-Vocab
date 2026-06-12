/**
 * Unit tests for background.js effect orchestration.
 *
 * These run the MV3 service worker module under Node with mocked chrome APIs.
 * Pure outbox transitions stay covered in shared/vocab-outbox.test.js; this
 * file pins the impure glue: retry alarms and notebook-scoped enrich polling.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

function makeChromeMock(initial = {}) {
  const store = { ...initial };
  const alarmListeners = [];
  const createdAlarms = [];
  return {
    _store: store,
    _createdAlarms: createdAlarms,
    runtime: {
      onMessage: { addListener() {} },
      onMessageExternal: { addListener() {} },
      sendMessage: () => Promise.resolve(),
    },
    sidePanel: { setPanelBehavior: () => Promise.resolve() },
    storage: {
      local: {
        async get(key) {
          if (key == null) return { ...store };
          if (Array.isArray(key)) {
            return Object.fromEntries(key.map((k) => [k, store[k]]));
          }
          if (typeof key === 'object') {
            return Object.fromEntries(Object.keys(key).map((k) => [k, store[k] ?? key[k]]));
          }
          return { [key]: store[key] };
        },
        async set(values) {
          Object.assign(store, values);
        },
        async remove(key) {
          for (const k of Array.isArray(key) ? key : [key]) delete store[k];
        },
      },
    },
    alarms: {
      create(name, info) {
        createdAlarms.push({ name, info });
      },
      clear: () => Promise.resolve(),
      onAlarm: {
        addListener(fn) {
          alarmListeners.push(fn);
        },
      },
      _emit(name) {
        for (const fn of alarmListeners) fn({ name });
      },
    },
  };
}

async function importBackground({ chrome, fetchImpl }) {
  globalThis.chrome = chrome;
  globalThis.fetch = fetchImpl;
  await import(`./shared/pure.js?test=${Date.now()}-${Math.random()}`);
  const mod = await import(`./background.js?test=${Date.now()}-${Math.random()}`);
  await Promise.resolve();
  return mod.__test__;
}

async function waitFor(predicate, label) {
  const deadline = Date.now() + 1000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.fail(`timed out waiting for ${label}`);
}

test('failed notebook add flush marks failed, schedules alarm, then manual retry flushes', async () => {
  const chrome = makeChromeMock();
  const calls = [];
  let mode = 'fail';
  const api = await importBackground({
    chrome,
    fetchImpl: async (url, opts) => {
      calls.push({ url: String(url), opts });
      if (String(url).includes('/api/pipeline')) {
        return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (mode === 'fail') return new Response('server down', { status: 503 });
      return new Response(JSON.stringify({ cardIds: { lascivious: 'card-1' } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    },
  });

  const ack = await api.handleMessage({
    type: 'addVocab',
    entries: [{ word: 'lascivious', translation: '好色的', context: 'ctx', source: { type: 'web' } }],
    notebookId: 'nb-reading',
  });
  assert.deepEqual(ack, { ok: true, optimistic: true, queued: 1 });

  await waitFor(
    () => chrome._createdAlarms.some((a) => a.name === 'kg-outbox-retry'),
    'outbox retry alarm',
  );

  assert.equal(calls.some((c) => c.url.includes('/api/vocab?notebook_id=nb-reading')), true);
  assert.equal(chrome._store.vocab_outbox.length, 1);
  assert.equal(chrome._store.vocab_outbox[0].status, 'failed');
  assert.equal(chrome._store.vocab_outbox[0].notebookId, 'nb-reading');
  assert.equal(chrome._createdAlarms.some((a) => a.name === 'kg-outbox-retry'), true);

  mode = 'success';
  const retry = await api.handleMessage({ type: 'retryOutbox' });
  assert.deepEqual(retry, { ok: true });
  assert.equal(chrome._store.vocab_outbox.length, 0);
  assert.equal(calls.some((c) => c.url.includes('/api/pipeline?notebook_id=nb-reading')), true);
});

test('enrich poll re-pulls every triggered notebook with notebook_id', async () => {
  const chrome = makeChromeMock();
  const calls = [];
  const api = await importBackground({
    chrome,
    fetchImpl: async (url, opts) => {
      calls.push({ url: String(url), opts });
      if (String(url).includes('/api/pipeline')) {
        return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response('[]', {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'X-Pipeline-Pending': 'false' },
      });
    },
  });

  await api.triggerEnrichPolling('nb-a');
  await api.triggerEnrichPolling('nb-b');
  await api.handleEnrichPoll();

  const vocabCalls = calls.map((c) => c.url).filter((u) => u.includes('/api/vocab?'));
  assert.equal(vocabCalls.some((u) => u.includes('notebook_id=nb-a')), true);
  assert.equal(vocabCalls.some((u) => u.includes('notebook_id=nb-b')), true);
  assert.equal(chrome._store.enrich_poll_state, undefined);
});
