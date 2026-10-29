'use strict';

const express = require('express');

const STATUS = {
  INVALID_ANSWER: 400,
  INVALID_QUESTIONS: 400,
  ADMIN_TOKEN_MISSING: 401,
  ADMIN_TOKEN_INVALID: 403,
  GAME_NOT_FOUND: 404,
  QUESTION_NOT_FOUND: 404,
  GAME_OVER: 409,
  NOT_PLAYING: 409,
  ILLEGAL_TRANSITION: 409,
  NO_QUESTIONS: 404,
};

// @req FR-1 FR-2
function createGameRouter({ gameService, store }) {
  const router = express.Router();

  // @req FR-1
  router.get('/play', (req, res) => {
    try {
      res.json(gameService.createGame(store));
    } catch (err) {
      respondError(res, err);
    }
  });

  // @req FR-1
  router.get('/games/:gameId/question', (req, res) => {
    handleQuestion(store, req, res, gameService.getCurrentQuestion);
  });

  // @req FR-1 FR-2
  router.post('/games/:gameId/answers', (req, res) => {
    try {
      res.json(gameService.submitAnswer(store, req.params.gameId, req.body && req.body.answer));
    } catch (err) {
      respondError(res, err);
    }
  });

  // @req FR-2
  router.get('/games/:gameId/score', (req, res) => {
    handleQuestion(store, req, res, gameService.getScore);
  });

  // @req FR-1
  router.post('/games/:gameId/pause', (req, res) => {
    handleQuestion(store, req, res, gameService.pauseGame);
  });

  // @req FR-1
  router.post('/games/:gameId/resume', (req, res) => {
    handleQuestion(store, req, res, gameService.resumeGame);
  });

  // @req FR-1
  router.post('/games/:gameId/quit', (req, res) => {
    handleQuestion(store, req, res, gameService.quitGame);
  });

  return router;
}

function respondError(res, err) {
  const code = err.code || 'INTERNAL_ERROR';
  res.status(STATUS[code] || 500).json({ error: { code, message: err.message } });
}

function handleQuestion(store, req, res, fn) {
  try {
    res.json(fn(store, req.params.gameId));
  } catch (err) {
    respondError(res, err);
  }
}

module.exports = { createGameRouter };
