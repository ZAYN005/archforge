'use strict';

// @req FR-1
const seedQuestions = [
  { id: 1, prompt: '1/2 + 1/4 = ?', options: ['3/4', '1/6', '1/8', '1/3'], correctAnswer: '3/4' },
  { id: 2, prompt: '3/5 - 1/10 = ?', options: ['1/2', '2/5', '1/5', '4/15'], correctAnswer: '1/2' },
  { id: 3, prompt: '1/3 × 2/5 = ?', options: ['2/15', '3/15', '5/6', '2/8'], correctAnswer: '2/15' },
  { id: 4, prompt: '3/4 ÷ 1/2 = ?', options: ['3/2', '3/8', '2/3', '4/3'], correctAnswer: '3/2' },
  { id: 5, prompt: 'Which fraction equals 2/4?', options: ['1/2', '2/3', '3/4', '2/5'], correctAnswer: '1/2' },
  { id: 6, prompt: '5/6 + 1/3 = ?', options: ['7/6', '6/9', '4/6', '5/9'], correctAnswer: '7/6' },
  { id: 7, prompt: 'Which is largest?', options: ['1/2', '2/5', '3/8', '5/12'], correctAnswer: '1/2' },
  { id: 8, prompt: '2/3 - 1/4 = ?', options: ['5/12', '3/7', '1/12', '1/4'], correctAnswer: '5/12' },
];

module.exports = { seedQuestions };
