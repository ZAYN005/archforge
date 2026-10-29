'use strict';

const INVALID_FRACTION = 'INVALID_FRACTION';

// @req FR-1
function parseFraction(value) {
  if (typeof value !== 'string') {
    throw new Error(INVALID_FRACTION);
  }

  const text = value.trim();
  if (text === '') {
    throw new Error(INVALID_FRACTION);
  }

  // Integer form: optional leading sign, one or more digits only.
  if (/^-?\d+$/.test(text)) {
    return { numerator: Number(text), denominator: 1 };
  }

  // Fraction form: exactly one '/' separating two integer parts (signs on numerator).
  const parts = text.split('/');
  if (parts.length !== 2) {
    throw new Error(INVALID_FRACTION);
  }

  const [numPart, denPart] = parts;
  if (!/^-?\d+$/.test(numPart) || !/^\d+$/.test(denPart)) {
    throw new Error(INVALID_FRACTION);
  }

  const numerator = Number(numPart);
  const denominator = Number(denPart);
  if (denominator === 0) {
    throw new Error(INVALID_FRACTION);
  }

  return { numerator, denominator };
}

// @req FR-1
function areEquivalent(a, b) {
  const left = parseFraction(a);
  const right = parseFraction(b);
  return left.numerator * right.denominator === right.numerator * left.denominator;
}

module.exports = {
  parseFraction,
  areEquivalent,
};
