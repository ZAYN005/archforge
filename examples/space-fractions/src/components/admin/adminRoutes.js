'use strict';

const express = require('express');

const STATUS = {
  INVALID_QUESTIONS: 400,
  ADMIN_TOKEN_MISSING: 401,
  ADMIN_TOKEN_INVALID: 403,
};

function respondError(res, err) {
  const code = err.code || err.message || 'INTERNAL_ERROR';
  res.status(STATUS[code] || 500).json({ error: { code, message: err.message } });
}

// @req FR-3 ASR-2
function createAdminRouter({ questionService, adminToken, store }) {
  const router = express.Router();

  // @req ASR-2
  router.use((req, res, next) => {
    const provided = req.get('x-admin-token');
    if (!provided) {
      res.status(401).json({
        error: {
          code: 'ADMIN_TOKEN_MISSING',
          message: 'Administrator token is required.',
        },
      });
      return;
    }
    if (provided !== adminToken) {
      res.status(403).json({
        error: {
          code: 'ADMIN_TOKEN_INVALID',
          message: 'Administrator token is invalid.',
        },
      });
      return;
    }
    next();
  });

  // @req FR-3
  router.get('/admin/questions', (req, res) => {
    try {
      const questions = store
        ? questionService.listQuestions(store)
        : questionService.listQuestions();
      res.json({ questions });
    } catch (err) {
      respondError(res, err);
    }
  });

  // @req FR-3
  router.put('/admin/questions', (req, res) => {
    try {
      const questions = req.body && req.body.questions;
      const result = store
        ? questionService.replaceQuestions(store, questions)
        : questionService.replaceQuestions(questions);
      res.json(result);
    } catch (err) {
      respondError(res, err);
    }
  });

  return router;
}

module.exports = { createAdminRouter };
