// Minimal dependency-free reference server used ONLY to test the acceptance probe.
// Env SHUFFLE=0 disables option shuffling (to prove the probe catches unfair games).
'use strict';
const http = require('http');
const fs = require('fs');
const file = process.env.DATA_FILE;
const token = process.env.ADMIN_TOKEN || 'dev';
const seed = [1, 2, 3, 4, 5, 6].map((i) => ({ prompt: `seed ${i}`, options: [`${i}/9`, 'a', 'b', 'c'], correctAnswer: `${i}/9` }));
let db = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : { questions: seed, games: {}, next: 1 };
const save = () => fs.writeFileSync(file, JSON.stringify(db));
const shuffle = (a) => { a = a.slice(); if (process.env.SHUFFLE === '0') return a; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const send = (res, st, body) => { res.writeHead(st, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
const err = (res, st, code) => send(res, st, { error: { code, message: code } });
http.createServer((req, res) => {
  let raw = ''; req.on('data', (c) => (raw += c)); req.on('end', () => {
    const body = raw ? JSON.parse(raw) : {}; const u = req.url; let m;
    if (req.method === 'GET' && u === '/play') { const id = db.next++; db.games[id] = { id, state: 'Playing', i: 0, score: 0, qs: db.questions.map((q) => ({ ...q, options: shuffle(q.options) })) }; save(); return send(res, 200, { gameId: id }); }
    if (req.method === 'GET' && u === '/help') return send(res, 200, { help: 'x' });
    if (u.startsWith('/admin')) { if (!req.headers['x-admin-token']) return err(res, 401, 'NO_TOKEN'); if (req.headers['x-admin-token'] !== token) return err(res, 403, 'BAD_TOKEN');
      if (req.method === 'GET') return send(res, 200, { questions: db.questions });
      if (req.method === 'PUT') { db.questions = body.questions; save(); return send(res, 200, { count: db.questions.length }); } }
    if ((m = u.match(/^\/games\/(\d+)\/(\w+)$/))) { const g = db.games[m[1]]; if (!g) return err(res, 404, 'GAME_NOT_FOUND'); const a = m[2];
      const tr = { pause: ['Playing', 'Paused'], resume: ['Paused', 'Playing'], quit: ['Paused', 'GameOver'] };
      if (tr[a]) { if (g.state !== tr[a][0]) return err(res, 409, 'ILLEGAL_TRANSITION'); g.state = tr[a][1]; save(); return send(res, 200, { state: g.state }); }
      if (a === 'score') return send(res, 200, { score: g.score });
      if (g.state !== 'Playing') return err(res, 409, 'NOT_PLAYING');
      const q = g.qs[g.i]; if (!q) return err(res, 404, 'NO_QUESTIONS');
      if (a === 'question') return send(res, 200, { question: { prompt: q.prompt, options: q.options } });
      if (a === 'answers') { const ok = body.answer === q.correctAnswer || body.answer === q.options.find((o) => o === q.correctAnswer); g.score += ok ? 1 : 0; g.i++; const over = g.i >= g.qs.length; if (over) g.state = 'GameOver'; save(); return send(res, 200, { correct: ok, score: g.score, gameOver: over }); } }
    err(res, 404, 'NOT_FOUND');
  });
}).listen(Number(process.env.PORT) || 3000);
