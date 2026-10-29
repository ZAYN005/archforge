'use strict';
const assert = require('assert');
const { createMemoryStore } = require('../../store/memoryStore');
const gs = require('./gameService');

const s = createMemoryStore();
const game = gs.createGame(s);
assert.equal(game.state, 'PLAYING');
assert.equal(game.score, 0);
assert.equal(game.totalQuestions, 8);
assert.equal(game.question.options.length, 4);
assert.ok(!('correctAnswer' in game.question));
assert.ok(!('correctAnswer' in game));

const id = game.gameId;
const q = gs.getCurrentQuestion(s, id);
assert.equal(q.options.length, 4);
assert.ok(!('correctAnswer' in q));
assert.equal(q.questionNumber, 1);
assert.equal(q.totalQuestions, 8);

// answer all questions
let score = 0;
for (let i = 0; i < 8; i += 1) {
  const cur = gs.getCurrentQuestion(s, id);
  const ans = gs.submitAnswer(s, id, cur.options[0]);
  if (ans.correct) score += 1;
  if (i < 7) {
    assert.equal(ans.state, 'PLAYING');
    assert.ok(ans.nextQuestion);
    assert.equal(ans.finalFeedback, null);
  } else {
    assert.equal(ans.state, 'GAME_OVER');
    assert.equal(ans.nextQuestion, null);
    assert.equal(typeof ans.finalFeedback, 'string');
  }
}

const sc = gs.getScore(s, id);
assert.equal(sc.score, score);
assert.equal(sc.percent, Math.round((score / 8) * 100));
assert.equal(sc.state, 'GAME_OVER');

// pause/resume flow
const g2 = gs.createGame(s);
assert.deepEqual(gs.pauseGame(s, g2.gameId), { gameId: g2.gameId, state: 'PAUSED' });
assert.deepEqual(gs.resumeGame(s, g2.gameId), { gameId: g2.gameId, state: 'PLAYING' });
gs.pauseGame(s, g2.gameId);
assert.deepEqual(gs.quitGame(s, g2.gameId), { gameId: g2.gameId, state: 'GAME_OVER' });

// illegal transitions
assert.throws(() => gs.pauseGame(s, g2.gameId), (e) => e.code === 'ILLEGAL_TRANSITION');
assert.throws(() => gs.resumeGame(s, g2.gameId), (e) => e.code === 'ILLEGAL_TRANSITION');

// invalid answer
const g3 = gs.createGame(s);
assert.throws(() => gs.submitAnswer(s, g3.gameId, 'bogus'), (e) => e.code === 'INVALID_ANSWER');

// not playing when paused
gs.pauseGame(s, g3.gameId);
assert.throws(() => gs.submitAnswer(s, g3.gameId, '1/2'), (e) => e.code === 'NOT_PLAYING');

// unknown id
assert.throws(() => gs.getCurrentQuestion(s, 999999), (e) => e.code === 'GAME_NOT_FOUND');

console.log('all game service assertions passed; final verified score =', score);
