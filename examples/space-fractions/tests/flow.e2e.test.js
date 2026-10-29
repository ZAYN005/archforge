'use strict';

const request = require('supertest');
const { createApp } = require('../src/app');
const { createMemoryStore } = require('../src/store/memoryStore');

const ADMIN_TOKEN = 'test-token';

function makeApp() {
  const store = createMemoryStore();
  const app = createApp({ store, adminToken: ADMIN_TOKEN });
  return { app, store };
}

describe('full game flow via the API', () => {
  test('FR-1/FR-2/FR-5: start -> answer all questions -> score -> game over', async () => {
    const { app } = makeApp();

    // 1. start the game
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;
    const total = play.body.totalQuestions;
    expect(play.body.state).toBe('PLAYING');
    expect(play.body.score).toBe(0);
    expect(total).toBeGreaterThan(0);

    // 2. answer every question in the bank
    let correctCount = 0;
    for (let i = 0; i < total; i += 1) {
      const q = await request(app).get(`/games/${gameId}/question`).expect(200);
      expect(q.body.options).toHaveLength(4);
      expect(q.body.questionNumber).toBe(i + 1);

      // submit the first option for every question (deterministic; some correct)
      const ans = await request(app)
        .post(`/games/${gameId}/answers`)
        .send({ answer: q.body.options[0] })
        .expect(200);

      if (ans.body.correct) correctCount += 1;

      if (i < total - 1) {
        expect(ans.body.state).toBe('PLAYING');
        expect(ans.body.nextQuestion).toEqual({
          prompt: expect.any(String),
          options: expect.any(Array),
        });
        expect(ans.body.finalFeedback).toBeNull();
      } else {
        expect(ans.body.state).toBe('GAME_OVER');
        expect(ans.body.nextQuestion).toBeNull();
        expect(ans.body.finalFeedback).toEqual(expect.any(String));
      }
    }

    // 3. score endpoint reflects the final run
    const score = await request(app).get(`/games/${gameId}/score`).expect(200);
    expect(score.body).toEqual({
      gameId,
      score: correctCount,
      totalQuestions: total,
      percent: Math.round((correctCount / total) * 100),
      state: 'GAME_OVER',
    });

    // 4. game is over: further questions are rejected
    const after = await request(app)
      .get(`/games/${gameId}/question`)
      .expect(409);
    expect(after.body.error.code).toBe('GAME_OVER');
  });

  test('FR-1/FR-2: pausing and resuming mid-game preserves progress', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    // answer the first question
    const q = await request(app).get(`/games/${gameId}/question`).expect(200);
    const ans = await request(app)
      .post(`/games/${gameId}/answers`)
      .send({ answer: q.body.options[0] })
      .expect(200);

    // pause, verify state
    await request(app).post(`/games/${gameId}/pause`).expect(200);
    const scoreMid = await request(app).get(`/games/${gameId}/score`).expect(200);
    expect(scoreMid.body.state).toBe('PAUSED');

    // resume, verify we can continue
    await request(app).post(`/games/${gameId}/resume`).expect(200);
    const q2 = await request(app).get(`/games/${gameId}/question`).expect(200);
    expect(q2.body.questionNumber).toBe(2);

    const scoreResumed = await request(app)
      .get(`/games/${gameId}/score`)
      .expect(200);
    expect(scoreResumed.body.score).toBe(ans.body.score);
  });
});
