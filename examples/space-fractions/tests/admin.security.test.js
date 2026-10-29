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

describe('admin security (ASR-2)', () => {
  test('ASR-2: GET /admin/questions without token returns 401 ADMIN_TOKEN_MISSING', async () => {
    const { app } = makeApp();
    const res = await request(app).get('/admin/questions').expect(401);
    expect(res.body).toEqual({
      error: { code: 'ADMIN_TOKEN_MISSING', message: expect.any(String) },
    });
  });

  test('ASR-2: PUT /admin/questions without token returns 401 ADMIN_TOKEN_MISSING', async () => {
    const { app } = makeApp();
    const res = await request(app)
      .put('/admin/questions')
      .send({ questions: [] })
      .expect(401);
    expect(res.body.error.code).toBe('ADMIN_TOKEN_MISSING');
  });

  test('ASR-2: GET /admin/questions with wrong token returns 403 ADMIN_TOKEN_INVALID', async () => {
    const { app } = makeApp();
    const res = await request(app)
      .get('/admin/questions')
      .set('x-admin-token', 'wrong-token')
      .expect(403);
    expect(res.body.error.code).toBe('ADMIN_TOKEN_INVALID');
  });

  test('ASR-2: PUT /admin/questions with wrong token returns 403 ADMIN_TOKEN_INVALID', async () => {
    const { app } = makeApp();
    const res = await request(app)
      .put('/admin/questions')
      .set('x-admin-token', 'wrong-token')
      .send({ questions: [] })
      .expect(403);
    expect(res.body.error.code).toBe('ADMIN_TOKEN_INVALID');
  });

  test('ASR-2/FR-3: GET /admin/questions with valid token returns 200 with the question bank', async () => {
    const { app } = makeApp();
    const res = await request(app)
      .get('/admin/questions')
      .set('x-admin-token', ADMIN_TOKEN)
      .expect(200);
    expect(res.body).toHaveProperty('questions');
    expect(Array.isArray(res.body.questions)).toBe(true);
    for (const q of res.body.questions) {
      expect(q).toEqual({
        id: expect.any(Number),
        prompt: expect.any(String),
        options: expect.any(Array),
        correctAnswer: expect.any(String),
      });
    }
  });

  test('ASR-2/FR-3: PUT /admin/questions with valid token returns 200 with count', async () => {
    const { app } = makeApp();
    const res = await request(app)
      .put('/admin/questions')
      .set('x-admin-token', ADMIN_TOKEN)
      .send({
        questions: [
          {
            prompt: '1/4 + 1/4 = ?',
            options: ['1/2', '1/4', '1/8', '1/3'],
            correctAnswer: '1/2',
          },
        ],
      })
      .expect(200);
    expect(res.body).toEqual({ count: 1 });
  });
});
