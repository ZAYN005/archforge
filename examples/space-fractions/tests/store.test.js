'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { createFileStore } = require('../src/store/fileStore');
const { seedQuestions } = require('../src/domain/seedQuestions');

function tempFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'space-fractions-'));
  return path.join(dir, 'store.json');
}

describe('file store durability (ASR-1)', () => {
  test('ASR-1: a new file store seeds the seed questions', () => {
    const filePath = tempFile();
    const store = createFileStore(filePath);
    const questions = store.listQuestions();
    expect(questions).toHaveLength(seedQuestions.length);
  });

  test('ASR-1: data written to a file store survives re-creation on the same file', () => {
    const filePath = tempFile();

    const store1 = createFileStore(filePath);
    store1.replaceQuestions([
      {
        id: 100,
        prompt: '1/8 + 1/8 = ?',
        options: ['1/4', '1/8', '1/16', '1/2'],
        correctAnswer: '1/4',
      },
    ]);

    // simulate a process restart: create a brand-new store on the same file
    const store2 = createFileStore(filePath);
    const questions = store2.listQuestions();
    expect(questions).toHaveLength(1);
    expect(questions[0]).toMatchObject({
      id: 100,
      prompt: '1/8 + 1/8 = ?',
      correctAnswer: '1/4',
    });
  });

  test('ASR-1: a game persisted via the file store is readable after re-creation', () => {
    const filePath = tempFile();

    const store1 = createFileStore(filePath);
    const game = store1.createGame();
    const gameId = game.id;

    const store2 = createFileStore(filePath);
    const loaded = store2.getGame(gameId);
    expect(loaded).toBeDefined();
    expect(loaded.id).toBe(gameId);
  });
});
