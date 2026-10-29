'use strict';

const fs = require('fs');
const path = require('path');
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
function createFileStore(filePath) {
  let data;

  if (fs.existsSync(filePath)) {
    const raw = fs.readFileSync(filePath, 'utf8');
    data = raw.trim() === '' ? {} : JSON.parse(raw);
  } else {
    data = {};
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
  }

  const questions = (data.questions || []).map((q) => ({
    id: q.id,
    prompt: q.prompt,
    options: Array.isArray(q.options) ? q.options : [],
    correctAnswer: q.correctAnswer,
  }));

  const games = new Map();
  const gameList = data.games || [];
  gameList.forEach((g) => {
    games.set(g.id, {
      id: g.id,
      score: g.score,
      state: g.state,
      questionOrder: Array.isArray(g.questionOrder) ? g.questionOrder : [],
      currentQuestionIndex: g.currentQuestionIndex,
      optionOrders: g.optionOrders || {},
      history: Array.isArray(g.history) ? g.history : [],
    });
  });

  let nextGameId = data.nextGameId || (gameList.reduce((max, g) => Math.max(max, g.id), 0) + 1);
  let nextQuestionId = data.nextQuestionId
    || (questions.reduce((max, q) => Math.max(max, q.id), 0) + 1);

  // Seed a brand-new file (never existed) with the seed question bank.
  if (!data.seeded && questions.length === 0) {
    seedQuestions.forEach((q) => questions.push({
      id: q.id,
      prompt: q.prompt,
      options: q.options.slice(),
      correctAnswer: q.correctAnswer,
    }));
    nextQuestionId = questions.reduce((max, q) => Math.max(max, q.id), 0) + 1;
  }

  function persist() {
    const payload = {
      seeded: true,
      nextGameId,
      nextQuestionId,
      questions,
      games: Array.from(games.values()),
    };
    const tmpPath = `${filePath}.tmp`;
    fs.writeFileSync(tmpPath, JSON.stringify(payload, null, 2));
    fs.renameSync(tmpPath, filePath);
  }

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
      persist();
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
      persist();
      return cloneGame(game);
    },

    getGame(id) {
      const game = games.get(id);
      return game ? cloneGame(game) : undefined;
    },

    saveGame(game) {
      if (game && game.id != null) {
        games.set(game.id, cloneGame(game));
        persist();
      }
      return game ? cloneGame(game) : undefined;
    },
  };
}

module.exports = { createFileStore };
