'use strict';

const { seedQuestions } = require('../domain/seedQuestions');

function cloneQuestions(questions) {
  return questions.map((q) => ({
    id: q.id,
    prompt: q.prompt,
    options: q.options.slice(),
    correctAnswer: q.correctAnswer,
  }));
}

function cloneGame(game) {
  return {
    id: game.id,
    score: game.score,
    state: game.state,
    questionOrder: game.questionOrder.slice(),
    currentQuestionIndex: game.currentQuestionIndex,
    optionOrders: Object.assign({}, game.optionOrders),
    history: game.history.map((h) => Object.assign({}, h)),
  };
}

// @req ASR-1 FR-1
function createMemoryStore(options) {
  const opts = options || {};
  const questions = opts.empty ? [] : cloneQuestions(seedQuestions);
  const games = new Map();
  let nextGameId = 1;
  let nextQuestionId = questions.reduce((max, q) => Math.max(max, q.id), 0) + 1;

  return {
    listQuestions() {
      return cloneQuestions(questions);
    },

    replaceQuestions(newQuestions) {
      const list = newQuestions.map((q, i) => ({
        id: q.id != null ? q.id : nextQuestionId + i,
        prompt: q.prompt,
        options: q.options.slice(),
        correctAnswer: q.correctAnswer,
      }));
      questions.length = 0;
      list.forEach((q) => questions.push(q));
      nextQuestionId = questions.reduce((max, q) => Math.max(max, q.id), 0) + 1;
      return cloneQuestions(questions);
    },

    createGame() {
      const game = {
        id: nextGameId,
        score: 0,
        state: 'PLAYING',
        questionOrder: [],
        currentQuestionIndex: 0,
        optionOrders: {},
        history: [],
      };
      nextGameId += 1;
      games.set(game.id, cloneGame(game));
      return cloneGame(game);
    },

    getGame(id) {
      const game = games.get(id);
      return game ? cloneGame(game) : undefined;
    },

    saveGame(game) {
      if (game && game.id != null) {
        games.set(game.id, cloneGame(game));
      }
      return game ? cloneGame(game) : undefined;
    },
  };
}

module.exports = { createMemoryStore };
