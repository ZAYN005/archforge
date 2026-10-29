'use strict';

const ILLEGAL_TRANSITION = 'ILLEGAL_TRANSITION';

// Allowed: PLAYING -> PAUSED, PAUSED -> PLAYING, PLAYING -> GAME_OVER, PAUSED -> GAME_OVER.
const TRANSITIONS = {
  PLAYING: { pause: 'PAUSED', gameOver: 'GAME_OVER' },
  PAUSED: { resume: 'PLAYING', quit: 'GAME_OVER' },
  GAME_OVER: {},
};

// @req FR-1
function transition(state, event) {
  const targets = TRANSITIONS[state];
  if (!targets || !Object.prototype.hasOwnProperty.call(targets, event)) {
    const err = new Error(`${ILLEGAL_TRANSITION}: ${state} --${event}()--> ?`);
    err.code = ILLEGAL_TRANSITION;
    throw err;
  }
  return targets[event];
}

module.exports = { transition };
