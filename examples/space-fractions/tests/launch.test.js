'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const request = require('supertest');
const { createApp } = require('../src/app');
const { createFileStore } = require('../src/store/fileStore');
const { start } = require('../src/server');

describe('first launch experience', () => {
  test('FR-1/FR-5: a brand-new file store is immediately playable with 4 options per question', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'space-fractions-'));
    const filePath = path.join(dir, 'store.json');

    // no seeding by the test: the file must NOT exist before the app creates the store
    expect(fs.existsSync(filePath)).toBe(false);

    const store = createFileStore(filePath);
    const app = createApp({ store, adminToken: 'test-token' });

    const play = await request(app).get('/play').expect(200);
    expect(play.body.totalQuestions).toBeGreaterThan(0);

    const q = await request(app)
      .get(`/games/${play.body.gameId}/question`)
      .expect(200);
    expect(q.body.options).toHaveLength(4);
    expect(q.body.prompt).toEqual(expect.any(String));
  });

  test('FR-5: start(0) binds a real port and serves the HTML UI at /', async () => {
    const { server, port } = await start(0);
    expect(port).not.toBe(0);
    expect(port).toBeGreaterThan(0);

    try {
      const res = await request(server).get('/').expect(200);
      expect(res.headers['content-type']).toMatch(/text\/html/);
      expect(res.text).toMatch(/<html/i);
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
  });
});
