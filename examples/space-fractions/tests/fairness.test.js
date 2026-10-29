'use strict';

const request = require('supertest');
const { createApp } = require('../src/app');
const { createMemoryStore } = require('../src/store/memoryStore');
const { seedQuestions } = require('../src/domain/seedQuestions');
const { areEquivalent } = require('../src/domain/fraction');

const ADMIN_TOKEN = 'test-token';

describe('fair play (FR-1)', () => {
  test('FR-1: correct answer position is not identical across questions (options are shuffled)', async () => {
    const store = createMemoryStore();
    const app = createApp({ store, adminToken: ADMIN_TOKEN });

    // start a fresh game on the seed bank
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;
    const total = play.body.totalQuestions;
    expect(total).toBe(seedQuestions.length);

    // build a lookup of correct answer -> seed question by prompt
    const byPrompt = new Map(seedQuestions.map((q) => [q.prompt, q]));

    const positions = [];
    for (let i = 0; i < total; i += 1) {
      const q = await request(app).get(`/games/${gameId}/question`).expect(200);
      const seed = byPrompt.get(q.body.prompt);
      expect(seed).toBeDefined();

      // find the index whose value equals the seed correctAnswer
      let correctIndex = -1;
      q.body.options.forEach((opt, idx) => {
        if (areEquivalent(opt, seed.correctAnswer)) correctIndex = idx;
      });
      expect(correctIndex).toBeGreaterThanOrEqual(0);
      positions.push(correctIndex);

      // advance to the next question with a deterministically valid answer
      await request(app)
        .post(`/games/${gameId}/answers`)
        .send({ answer: q.body.options[0] })
        .expect(200);
    }

    // fair play: the correct answer must NOT sit in the same position every time
    const unique = new Set(positions);
    expect(unique.size).toBeGreaterThan(1);
  });

  test('FR-1: the API never reveals correctAnswer before submission', async () => {
    const store = createMemoryStore();
    const app = createApp({ store, adminToken: ADMIN_TOKEN });

    const play = await request(app).get('/play').expect(200);
    expect(play.body).not.toHaveProperty('correctAnswer');
    expect(play.body.question).not.toHaveProperty('correctAnswer');

    const q = await request(app)
      .get(`/games/${play.body.gameId}/question`)
      .expect(200);
    expect(q.body).not.toHaveProperty('correctAnswer');
    q.body.options.forEach((opt) => {
      expect(typeof opt).toBe('string');
    });
  });
});
