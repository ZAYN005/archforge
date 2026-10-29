'use strict';

const {
  parseFraction,
  areEquivalent,
} = require('../src/domain/fraction');
const { transition } = require('../src/domain/gameStateMachine');

describe('fraction logic', () => {
  test('FR-1: parseFraction parses n/d strings into numerator and denominator', () => {
    expect(parseFraction('1/2')).toEqual({ numerator: 1, denominator: 2 });
    expect(parseFraction('2/4')).toEqual({ numerator: 2, denominator: 4 });
  });

  test('FR-1: parseFraction parses integer strings', () => {
    expect(parseFraction('3')).toEqual({ numerator: 3, denominator: 1 });
    expect(parseFraction('0')).toEqual({ numerator: 0, denominator: 1 });
  });

  test('FR-1: parseFraction rejects malformed input with INVALID_FRACTION', () => {
    for (const bad of ['', 'abc', '1/', '/2', 'a/b', '1/2/3', '1 / 2']) {
      expect(() => parseFraction(bad)).toThrow(/INVALID_FRACTION/);
    }
  });

  test('FR-1: parseFraction rejects a zero denominator', () => {
    expect(() => parseFraction('1/0')).toThrow(/INVALID_FRACTION/);
  });

  test('FR-1: areEquivalent compares fraction values, so 1/2 equals 2/4', () => {
    expect(areEquivalent('1/2', '2/4')).toBe(true);
    expect(areEquivalent('1/2', '1/2')).toBe(true);
    expect(areEquivalent('2', '6/3')).toBe(true);
  });

  test('FR-1: areEquivalent returns false for different values', () => {
    expect(areEquivalent('1/2', '1/3')).toBe(false);
    expect(areEquivalent('3/4', '2/4')).toBe(false);
    expect(areEquivalent('1', '2')).toBe(false);
  });
});

describe('game state machine', () => {
  test('FR-1: PLAYING --pause()--> PAUSED', () => {
    expect(transition('PLAYING', 'pause')).toBe('PAUSED');
  });

  test('FR-1: PAUSED --resume()--> PLAYING', () => {
    expect(transition('PAUSED', 'resume')).toBe('PLAYING');
  });

  test('FR-1: PLAYING --gameOver()--> GAME_OVER', () => {
    expect(transition('PLAYING', 'gameOver')).toBe('GAME_OVER');
  });

  test('FR-1: PAUSED --quit()--> GAME_OVER', () => {
    expect(transition('PAUSED', 'quit')).toBe('GAME_OVER');
  });

  test('FR-1: illegal transitions throw ILLEGAL_TRANSITION', () => {
    const illegal = [
      ['PLAYING', 'resume'],
      ['PLAYING', 'quit'],
      ['PAUSED', 'pause'],
      ['PAUSED', 'resumeDone'],
      ['GAME_OVER', 'pause'],
      ['GAME_OVER', 'resume'],
      ['GAME_OVER', 'quit'],
      ['GAME_OVER', 'gameOver'],
      ['PLAYING', 'bogus'],
      ['PAUSED', 'bogus'],
    ];
    for (const [state, event] of illegal) {
      expect(() => transition(state, event)).toThrow(/ILLEGAL_TRANSITION/);
    }
  });
});
