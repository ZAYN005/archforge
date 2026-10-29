'use strict';

const { parseFraction } = require('../../domain/fraction');

const INVALID_QUESTIONS = 'INVALID_QUESTIONS';

// @req FR-3
function validateQuestions(questions) {
  if (!Array.isArray(questions)) {
    throw new Error(INVALID_QUESTIONS);
  }

  for (const q of questions) {
    if (!q || typeof q !== 'object') {
      throw new Error(INVALID_QUESTIONS);
    }
    if (typeof q.prompt !== 'string' || q.prompt.trim() === '') {
      throw new Error(INVALID_QUESTIONS);
    }
    if (!Array.isArray(q.options) || q.options.length === 0) {
      throw new Error(INVALID_QUESTIONS);
    }
    for (const option of q.options) {
      try {
        parseFraction(option);
      } catch (err) {
        throw new Error(INVALID_QUESTIONS);
      }
    }
    try {
      parseFraction(q.correctAnswer);
    } catch (err) {
      throw new Error(INVALID_QUESTIONS);
    }
  }
}

// @req FR-3
function listQuestions(store) {
  return store.listQuestions();
}

// @req FR-3
function replaceQuestions(store, questions) {
  validateQuestions(questions);
  const replaced = store.replaceQuestions(questions);
  return { count: replaced.length };
}

module.exports = {
  validateQuestions,
  listQuestions,
  replaceQuestions,
};
