'use strict';

const request = require('supertest');
const { createApp } = require('../src/app');
const { createMemoryStore } = require('../src/store/memoryStore');

const ADMIN_TOKEN = 'test-token';

describe('performance (NFR-1)', () => {
  test('NFR-1: 100 sequential GET /games/:id/question calls finish in under 2000 ms', async () => {
    const store = createMemoryStore();
    const app = createApp({ store, adminToken: ADMIN_TOKEN });

    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    const start = Date.now();
    for (let i = 0; i < 100; i += 1) {
      await request(app).get(`/games/${gameId}/question`).expect(200);
    }
    const elapsed = Date.now() - start;

    expect(elapsed).toBeLessThan(2000);
  });
});
