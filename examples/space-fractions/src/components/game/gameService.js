'use strict';

const { parseFraction, areEquivalent } = require('../../domain/fraction');
const { transition } = require('../../domain/gameStateMachine');
const { shuffleOptions, presentQuestion } = require('../../domain/questionPresenter');

const GAME_NOT_FOUND = 'GAME_NOT_FOUND';
const NO_QUESTIONS = 'NO_QUESTIONS';
const GAME_OVER = 'GAME_OVER';
const NOT_PLAYING = 'NOT_PLAYING';
const INVALID_ANSWER = 'INVALID_ANSWER';

function httpError(code, message) {
  const err = new Error(message);
  err.code = code;
  return err;
}

function requireGame(store, gameId) {
  if (gameId == null || Number.isNaN(Number(gameId))) {
    throw httpError(GAME_NOT_FOUND, 'Game not found');
  }
  const game = store.getGame(Number(gameId));
  if (!game) {
    throw httpError(GAME_NOT_FOUND, 'Game not found');
  }
  return game;
}

function buildOptionOrders(questions, rng) {
  const orders = {};
  questions.forEach((q) => {
    orders[q.id] = shuffleOptions(
      q.options.map((_, i) => i),
      rng,
    );
  });
  return orders;
}

// @req FR-1
function createGame(store) {
  const questions = store.listQuestions();
  if (!questions.length) {
    throw httpError(NO_QUESTIONS, 'The question bank is empty');
  }

  const game = store.createGame();

  const order = questions.map((q) => q.id);
  // Shuffle the order of questions for this game.
  const rng = Math.random;
  for (let i = order.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rng() * (i + 1));
    const tmp = order[i];
    order[i] = order[j];
    order[j] = tmp;
  }

  game.questionOrder = order;
  game.optionOrders = buildOptionOrders(questions, rng);
  store.saveGame(game);

  const first = questions.find((q) => q.id === order[0]);

  return {
    gameId: game.id,
    state: game.state,
    score: game.score,
    totalQuestions: questions.length,
    question: presentQuestion(first, game),
  };
}

function findCurrentQuestion(game) {
  // questionOrder holds question ids; resolve them against the bank lazily.
  return { questions: game.questionOrder, index: game.currentQuestionIndex };
}

// @req FR-1
function getCurrentQuestion(store, gameId) {
  const game = requireGame(store, gameId);
  if (game.state === 'GAME_OVER') {
    throw httpError(GAME_OVER, 'The game has already ended');
  }

  const questions = store.listQuestions();
  const byId = new Map(questions.map((q) => [q.id, q]));

  const order = game.questionOrder;
  const idx = game.currentQuestionIndex;
  if (idx >= order.length) {
    throw httpError(GAME_OVER, 'The game has already ended');
  }

  const question = byId.get(order[idx]);
  return {
    prompt: question.prompt,
    options: presentQuestion(question, game).options,
    questionNumber: idx + 1,
    totalQuestions: order.length,
  };
}

// @req FR-1 FR-2
function submitAnswer(store, gameId, answerText) {
  const game = requireGame(store, gameId);

  if (game.state === 'GAME_OVER') {
    throw httpError(GAME_OVER, 'The game has already ended');
  }
  if (game.state !== 'PLAYING') {
    throw httpError(NOT_PLAYING, 'The game is paused; resume before answering');
  }

  if (typeof answerText !== 'string') {
    throw httpError(INVALID_ANSWER, 'Answer is required');
  }
  let parsed;
  try {
    parsed = parseFraction(answerText);
  } catch (err) {
    throw httpError(INVALID_ANSWER, 'Answer must be a valid fraction or integer');
  }

  const questions = store.listQuestions();
  const byId = new Map(questions.map((q) => [q.id, q]));

  const order = game.questionOrder;
  const idx = game.currentQuestionIndex;
  const question = byId.get(order[idx]);

  const correct = areEquivalent(answerText, question.correctAnswer);
  if (correct) {
    game.score += 1;
  }
  game.history.push({
    questionId: question.id,
    submittedAnswer: answerText,
    correct,
    correctAnswer: question.correctAnswer,
  });
  game.currentQuestionIndex += 1;

  const finished = game.currentQuestionIndex >= order.length;
  if (finished) {
    game.state = transition(game.state, 'gameOver');
  }
  store.saveGame(game);

  let nextQuestion = null;
  let finalFeedback = null;
  if (!finished) {
    const next = byId.get(order[game.currentQuestionIndex]);
    nextQuestion = presentQuestion(next, game);
  } else {
    const percent = order.length ? Math.round((game.score / order.length) * 100) : 0;
    finalFeedback = `Game over! You answered ${game.score} of ${order.length} questions correctly (${percent}%).`;
  }

  return {
    correct,
    submittedAnswer: answerText,
    correctAnswer: question.correctAnswer,
    score: game.score,
    totalQuestions: order.length,
    state: game.state,
    nextQuestion,
    finalFeedback,
  };
}

// @req FR-2
function getScore(store, gameId) {
  const game = requireGame(store, gameId);
  const total = game.questionOrder.length;
  const percent = total ? Math.round((game.score / total) * 100) : 0;
  return {
    gameId: game.id,
    score: game.score,
    totalQuestions: total,
    percent,
    state: game.state,
  };
}

// @req FR-1
function pauseGame(store, gameId) {
  const game = requireGame(store, gameId);
  game.state = transition(game.state, 'pause');
  store.saveGame(game);
  return { gameId: game.id, state: game.state };
}

// @req FR-1
function resumeGame(store, gameId) {
  const game = requireGame(store, gameId);
  game.state = transition(game.state, 'resume');
  store.saveGame(game);
  return { gameId: game.id, state: game.state };
}

// @req FR-1
function quitGame(store, gameId) {
  const game = requireGame(store, gameId);
  game.state = transition(game.state, 'quit');
  store.saveGame(game);
  return { gameId: game.id, state: game.state };
}

module.exports = {
  createGame,
  getCurrentQuestion,
  submitAnswer,
  getScore,
  pauseGame,
  resumeGame,
  quitGame,
};
