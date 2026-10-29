'use strict';

// Local in-memory registry of anonymous players. Desktop play does not
// require authentication, so each normal game flow starts with a fresh local
// player identity that can be looked up by id for the current session.
let nextId = 1;
const players = new Map();

// @req FR-1
function createPlayer() {
  const id = nextId;
  nextId += 1;
  const user = { id, username: `player-${id}` };
  players.set(id, user);
  return user;
}

// @req FR-1
function getPlayer(id) {
  if (id == null) {
    return undefined;
  }
  return players.get(Number(id));
}

module.exports = {
  createPlayer,
  getPlayer,
};
