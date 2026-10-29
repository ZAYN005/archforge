'use strict';

// @req FR-1
// Returns a shallow copy of `options` in a shuffled order. `rng` is an optional
// random function returning a number in [0, 1) (defaults to Math.random).
function shuffleOptions(options, rng) {
  const random = rng || Math.random;
  const copy = options.slice();
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    const tmp = copy[i];
    copy[i] = copy[j];
    copy[j] = tmp;
  }
  return copy;
}

// @req FR-1
// Builds a player-safe payload for a question against a specific game's option
// ordering. Never returns the correct answer.
function presentQuestion(question, game) {
  const order = (game.optionOrders && game.optionOrders[question.id]) || null;
  let options;
  if (order && Array.isArray(order) && order.length === question.options.length) {
    options = order.map((i) => question.options[i]);
  } else {
    options = shuffleOptions(question.options);
  }
  return { prompt: question.prompt, options };
}

module.exports = { shuffleOptions, presentQuestion };
