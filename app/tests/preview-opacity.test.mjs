import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPreviewOpacity } from '../src/visual/preview-opacity.js';

test('previous preview cannot flash after an empty recording, even if idle was skipped', () => {
  for (const skipIdle of [false, true]) {
    const frame = createPreviewOpacity();
    assert.equal(frame('preview', 1, 0), 1);
    assert.equal(frame('inserting', 1, 16), 0);
    assert.equal(frame('closing', 1, 32), 0);
    if (!skipIdle) frame('idle', 0, 1200);
    frame('arming', 0, 1300);
    frame('recording', 0, 1400);
    frame('processing', 0, 1500);
    for (let now = 1600; now <= 2800; now += 16) {
      assert.equal(frame('closing', 0, now), 0);
    }
  }
});

test('cancel from arming, recording or processing never reveals a card', () => {
  for (const phase of ['arming', 'recording', 'processing']) {
    const frame = createPreviewOpacity();
    frame('preview', 1, 0);
    frame(phase, .5, 100);
    assert.equal(frame('closing', .5, 116), 0);
    assert.equal(frame('closing', .5, 176), 0);
  }
});

test('closing a real preview fades continuously from its last opacity', () => {
  for (const phase of ['preview', 'error']) {
    for (const progress of [.65, .8, 1]) {
      const frame = createPreviewOpacity();
      const shown = frame(phase, progress, 0);
      assert.equal(frame('closing', progress, 16), shown);
      assert.equal(frame('closing', progress, 76), shown / 2);
      assert.equal(frame('closing', progress, 136), 0);
    }
  }
});

test('a new recording interrupts a closing preview without retaining its opacity', () => {
  const frame = createPreviewOpacity();
  frame('preview', 1, 0);
  frame('closing', 1, 16);
  assert.equal(frame('recording', 0, 32), 0);
  assert.equal(frame('closing', 0, 48), 0);
});
