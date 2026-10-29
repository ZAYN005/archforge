'use strict';

const path = require('path');
const express = require('express');
const { createFileStore } = require('./store/fileStore');
const { createGameRouter } = require('./components/game/gameRoutes');
const { createAdminRouter } = require('./components/admin/adminRoutes');
const gameService = require('./components/game/gameService');
const questionService = require('./components/question/questionService');

// @req NFR-1 FR-4 ASR-2
function createApp(options) {
  const opts = options || {};
  const store = opts.store || createFileStore(process.env.DATA_FILE || 'data/store.json');
  const adminToken = opts.adminToken || process.env.ADMIN_TOKEN || 'dev-admin-token';

  const app = express();
  app.use(express.json());
  app.use(express.static(path.join(__dirname, '..', 'public')));

  // @req FR-4
  app.get('/help', (req, res) => {
    res.json({
      title: 'Space Fractions Help',
      rules: [
        'Solve each fraction question by selecting the correct answer.',
        'Each question has exactly one correct answer.',
        'Your score is the number of correct answers.',
        'You can pause, resume, or quit during a game.',
      ],
      controls: [
        'Click an option to submit your answer.',
        'Use Pause to take a break and Resume to continue.',
        'Use Quit to end the game early.',
        'Use Main Menu to return to the start screen.',
      ],
    });
  });

  app.use(
    createGameRouter({ gameService, store }),
    createAdminRouter({ questionService, adminToken, store }),
  );

  return app;
}

module.exports = { createApp };
