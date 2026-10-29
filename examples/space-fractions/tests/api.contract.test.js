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

describe('API contract: one test per endpoint', () => {
  test('FR-1: GET /play returns 200 and a new playable game payload', async () => {
    const { app } = makeApp();
    const res = await request(app).get('/play').expect(200);
    expect(res.body).toEqual({
      gameId: expect.any(Number),
      state: 'PLAYING',
      score: 0,
      totalQuestions: expect.any(Number),
      question: {
        prompt: expect.any(String),
        options: expect.any(Array),
      },
    });
    expect(res.body.question.options).toHaveLength(4);
    // correctness must never leak
    expect(res.body.question).not.toHaveProperty('correctAnswer');
  });

  test('FR-1: GET /games/:id/question returns 200 with prompt and 4 options', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    const res = await request(app)
      .get(`/games/${gameId}/question`)
      .expect(200);
    expect(res.body).toEqual({
      prompt: expect.any(String),
      options: expect.any(Array),
      questionNumber: expect.any(Number),
      totalQuestions: expect.any(Number),
    });
    expect(res.body.options).toHaveLength(4);
    expect(res.body).not.toHaveProperty('correctAnswer');
  });

  test('FR-1: GET /games/:id/question returns 404 GAME_NOT_FOUND for unknown id', async () => {
    const { app } = makeApp();
    const res = await request(app).get('/games/999999/question').expect(404);
    expect(res.body).toEqual({
      error: { code: 'GAME_NOT_FOUND', message: expect.any(String) },
    });
  });

  test('FR-1/FR-2: POST /games/:id/answers returns 200 with feedback and score', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    const res = await request(app)
      .post(`/games/${gameId}/answers`)
      .send({ answer: '1/2' })
      .expect(200);
    expect(res.body).toEqual({
      correct: expect.any(Boolean),
      submittedAnswer: '1/2',
      correctAnswer: expect.any(String),
      score: expect.any(Number),
      totalQuestions: expect.any(Number),
      state: expect.stringMatching(/^(PLAYING|GAME_OVER)$/),
      nextQuestion: null,
      finalFeedback: null,
    });
  });

  test('FR-1: POST /games/:id/answers returns 400 INVALID_ANSWER for missing/bad answer', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    const missing = await request(app)
      .post(`/games/${gameId}/answers`)
      .send({})
      .expect(400);
    expect(missing.body.error.code).toBe('INVALID_ANSWER');

    // start a fresh game for the malformed answer case
    const play2 = await request(app).get('/play').expect(200);
    const bad = await request(app)
      .post(`/games/${play2.body.gameId}/answers`)
      .send({ answer: 'not-a-fraction' })
      .expect(400);
    expect(bad.body.error.code).toBe('INVALID_ANSWER');
  });

  test('FR-1: POST /games/:id/answers returns 404 GAME_NOT_FOUND for unknown id', async () => {
    const { app } = makeApp();
    const res = await request(app)
      .post('/games/999999/answers')
      .send({ answer: '1/2' })
      .expect(404);
    expect(res.body.error.code).toBe('GAME_NOT_FOUND');
  });

  test('FR-1: POST /games/:id/answers returns 409 NOT_PLAYING when paused', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    await request(app).post(`/games/${gameId}/pause`).expect(200);
    const res = await request(app)
      .post(`/games/${gameId}/answers`)
      .send({ answer: '1/2' })
      .expect(409);
    expect(res.body.error.code).toBe('NOT_PLAYING');
  });

  test('FR-1: POST /games/:id/answers on a finished game returns 409 GAME_OVER', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;
    const total = play.body.totalQuestions;

    // answer through the whole bank with a value that exists as an option
    for (let i = 0; i < total; i += 1) {
      const q = await request(app).get(`/games/${gameId}/question`).expect(200);
      await request(app)
        .post(`/games/${gameId}/answers`)
        .send({ answer: q.body.options[0] })
        .expect(200);
    }

    const res = await request(app)
      .post(`/games/${gameId}/answers`)
      .send({ answer: '1/2' })
      .expect(409);
    expect(res.body.error.code).toBe('GAME_OVER');
  });

  test('FR-2: GET /games/:id/score returns 200 with score, percent and state', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    const res = await request(app).get(`/games/${gameId}/score`).expect(200);
    expect(res.body).toEqual({
      gameId,
      score: 0,
      totalQuestions: expect.any(Number),
      percent: 0,
      state: expect.stringMatching(/^(PLAYING|PAUSED|GAME_OVER)$/),
    });
  });

  test('FR-2: GET /games/:id/score returns 404 GAME_NOT_FOUND for unknown id', async () => {
    const { app } = makeApp();
    const res = await request(app).get('/games/999999/score').expect(404);
    expect(res.body.error.code).toBe('GAME_NOT_FOUND');
  });

  test('FR-1: POST /games/:id/pause returns 200 with state PAUSED', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    const res = await request(app).post(`/games/${gameId}/pause`).expect(200);
    expect(res.body).toEqual({ gameId, state: 'PAUSED' });
  });

  test('FR-1: POST /games/:id/pause on a paused game returns 409 ILLEGAL_TRANSITION', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    await request(app).post(`/games/${gameId}/pause`).expect(200);
    const res = await request(app).post(`/games/${gameId}/pause`).expect(409);
    expect(res.body.error.code).toBe('ILLEGAL_TRANSITION');
  });

  test('FR-1: POST /games/:id/pause returns 404 for unknown id', async () => {
    const { app } = makeApp();
    const res = await request(app).post('/games/999999/pause').expect(404);
    expect(res.body.error.code).toBe('GAME_NOT_FOUND');
  });

  test('FR-1: POST /games/:id/resume returns 200 with state PLAYING', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    await request(app).post(`/games/${gameId}/pause`).expect(200);
    const res = await request(app).post(`/games/${gameId}/resume`).expect(200);
    expect(res.body).toEqual({ gameId, state: 'PLAYING' });
  });

  test('FR-1: POST /games/:id/resume on a playing game returns 409 ILLEGAL_TRANSITION', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    const res = await request(app).post(`/games/${gameId}/resume`).expect(409);
    expect(res.body.error.code).toBe('ILLEGAL_TRANSITION');
  });

  test('FR-1: POST /games/:id/quit on a paused game returns 200 with GAME_OVER', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    await request(app).post(`/games/${gameId}/pause`).expect(200);
    const res = await request(app).post(`/games/${gameId}/quit`).expect(200);
    expect(res.body).toEqual({ gameId, state: 'GAME_OVER' });
  });

  test('FR-1: POST /games/:id/quit on a playing game returns 409 ILLEGAL_TRANSITION', async () => {
    const { app } = makeApp();
    const play = await request(app).get('/play').expect(200);
    const gameId = play.body.gameId;

    const res = await request(app).post(`/games/${gameId}/quit`).expect(409);
    expect(res.body.error.code).toBe('ILLEGAL_TRANSITION');
  });

  test('FR-4: GET /help returns 200 with title, rules and controls', async () => {
    const { app } = makeApp();
    const res = await request(app).get('/help').expect(200);
    expect(res.body).toEqual({
      title: expect.any(String),
      rules: expect.any(Array),
      controls: expect.any(Array),
    });
  });
});
