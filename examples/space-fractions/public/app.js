'use strict';

// Space Fractions frontend: single-window UI flow
// intro -> main menu -> question -> ending (requirement FR-5).

(function () {
  const screens = {
    intro: document.getElementById('screen-intro'),
    menu: document.getElementById('screen-menu'),
    question: document.getElementById('screen-question'),
    paused: document.getElementById('screen-paused'),
    ending: document.getElementById('screen-ending'),
    help: document.getElementById('screen-help'),
    admin: document.getElementById('screen-admin'),
  };

  let gameId = null;
  let currentOptions = [];
  let totalQuestions = 1;

  function show(name) {
    Object.values(screens).forEach((el) => el.classList.remove('is-active'));
    screens[name].classList.add('is-active');
  }

  function renderHelp(data) {
    document.getElementById('help-title').textContent = data.title || 'Help';
    const rules = document.getElementById('help-rules');
    const controls = document.getElementById('help-controls');
    rules.innerHTML = '';
    controls.innerHTML = '';
    (data.rules || []).forEach((r) => {
      const li = document.createElement('li');
      li.textContent = r;
      rules.appendChild(li);
    });
    (data.controls || []).forEach((c) => {
      const li = document.createElement('li');
      li.textContent = c;
      controls.appendChild(li);
    });
  }

  async function getHelp() {
    try {
      const res = await fetch('/help');
      renderHelp(await res.json());
      show('help');
    } catch (err) {
      alert('Could not load help: ' + err.message);
    }
  }

  function renderQuestion(question, score) {
    currentOptions = question.options || [];
    document.getElementById('prompt').textContent = question.prompt || '';
    document.getElementById('question-number').textContent =
      String((question.questionNumber) || 1);
    document.getElementById('question-total').textContent =
      String((question.totalQuestions) || totalQuestions);
    document.getElementById('live-score').textContent = String(score);
    document.getElementById('answer-feedback').textContent = '';
    document.getElementById('answer-feedback').className = 'feedback';

    const container = document.getElementById('options');
    container.innerHTML = '';
    (question.options || []).forEach((opt) => {
      const btn = document.createElement('button');
      btn.className = 'option';
      btn.textContent = opt;
      btn.addEventListener('click', () => submitAnswer(opt));
      container.appendChild(btn);
    });

    setPausedUI(false);
  }

  function setPausedUI(paused) {
    document.getElementById('live-state').textContent = paused ? 'PAUSED' : 'PLAYING';
    document.getElementById('btn-pause').disabled = paused;
    document.getElementById('btn-resume').disabled = !paused;
    document.getElementById('btn-quit').disabled = !paused;
    const opts = document.querySelectorAll('#options .option');
    opts.forEach((o) => { o.disabled = paused; });
  }

  async function startGame() {
    try {
      const res = await fetch('/play');
      const data = await res.json();
      if (!res.ok) throw new Error(readError(data));
      gameId = data.gameId;
      totalQuestions = data.totalQuestions || 1;
      renderQuestion(Object.assign({ questionNumber: 1 }, data.question), data.score || 0);
      show('question');
    } catch (err) {
      alert(err.message);
    }
  }

  function readError(data) {
    return (data && data.error && data.error.message) || 'Unexpected error';
  }

  // Compare two fraction/integer strings by value (e.g. "1/2" == "2/4").
  function sameValue(a, b) {
    const norm = (s) => {
      const t = String(s).trim();
      if (t.includes('/')) {
        const [n, d] = t.split('/');
        const num = Number(n);
        const den = Number(d);
        if (!den) return null;
        return num / den;
      }
      return Number(t);
    };
    const va = norm(a);
    const vb = norm(b);
    return va !== null && vb !== null && Math.abs(va - vb) < 1e-9;
  }

  async function submitAnswer(answer) {
    const feedback = document.getElementById('answer-feedback');
    feedback.className = 'feedback';
    try {
      const res = await fetch(`/games/${gameId}/answers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(readError(data));

      // Highlight the submitted vs correct option.
      const opts = document.querySelectorAll('#options .option');
      const idx = currentOptions.indexOf(answer);
      let correctIdx = -1;
      for (let i = 0; i < currentOptions.length; i += 1) {
        if (sameValue(currentOptions[i], data.correctAnswer)) {
          correctIdx = i;
          break;
        }
      }
      opts.forEach((o) => { o.disabled = true; });
      if (idx >= 0 && !data.correct) opts[idx].classList.add('wrong');
      if (correctIdx >= 0) opts[correctIdx].classList.add('correct');

      document.getElementById('live-score').textContent = String(data.score);
      feedback.textContent = data.correct
        ? 'Correct! ' + data.correctAnswer
        : 'Not quite. The answer was ' + data.correctAnswer;
      feedback.className = data.correct ? 'feedback ok' : 'feedback bad';

      if (data.nextQuestion) {
        // Advance after a short beat so the highlight is readable.
        window.setTimeout(() => {
          renderQuestion(
            Object.assign({ questionNumber: data.nextQuestion.questionNumber || totalQuestions },
              data.nextQuestion),
            data.score);
        }, 1200);
      } else {
        window.setTimeout(() => {
          showEnding(data.score, data.finalFeedback);
        }, 1200);
      }
    } catch (err) {
      feedback.textContent = err.message;
      feedback.className = 'feedback bad';
    }
  }

  async function showEnding(score, finalFeedback) {
    const res = await fetch(`/games/${gameId}/score`);
    const data = await res.json();
    const finalScore = data.score ?? score;
    const total = data.totalQuestions || totalQuestions;
    document.getElementById('final-score').textContent =
      `Final score: ${finalScore} / ${total}`;
    const fb = document.getElementById('final-feedback');
    const pct = total ? finalScore / total : 0;
    fb.className = 'feedback';
    if (pct === 1) {
      fb.textContent = '🌟 Outstanding, cadet! You\'re a fraction master!';
      fb.className = 'feedback ok';
      document.getElementById('ending-emoticon').textContent = '🏆';
    } else if (pct >= 0.6) {
      fb.textContent = '🚀 Great job! You\'re navigating the fraction galaxy well.';
      fb.className = 'feedback ok';
      document.getElementById('ending-emoticon').textContent = '🛰️';
    } else {
      fb.textContent = finalFeedback || '💫 Keep practicing, cadet. The stars are within reach!';
      fb.className = 'feedback bad';
      document.getElementById('ending-emoticon').textContent = '🛸';
    }
    show('ending');
  }

  async function transition(action) {
    try {
      const res = await fetch(`/games/${gameId}/${action}`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(readError(data));

      if (action === 'pause') {
        setPausedUI(true);
        show('paused');
      } else if (action === 'resume') {
        setPausedUI(false);
        show('question');
      } else if (action === 'quit') {
        showEnding();
      }
    } catch (err) {
      alert(err.message);
    }
  }

  async function showAdmin() {
    document.getElementById('admin-feedback').textContent = '';
    document.getElementById('admin-feedback').className = 'feedback';
    show('admin');
  }

  async function adminLoad() {
    const token = document.getElementById('admin-token').value;
    const feedback = document.getElementById('admin-feedback');
    feedback.className = 'feedback';
    try {
      const res = await fetch('/admin/questions', {
        headers: { 'x-admin-token': token },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(readError(data));
      const list = (data.questions || []).map((q) => ({
        prompt: q.prompt,
        options: q.options,
        correctAnswer: q.correctAnswer,
      }));
      document.getElementById('admin-questions').value =
        JSON.stringify(list, null, 2);
      feedback.textContent = 'Loaded current question bank.';
      feedback.className = 'feedback ok';
    } catch (err) {
      feedback.textContent = err.message;
      feedback.className = 'feedback bad';
    }
  }

  async function adminSave() {
    const token = document.getElementById('admin-token').value;
    const feedback = document.getElementById('admin-feedback');
    feedback.className = 'feedback';
    let questions;
    try {
      questions = JSON.parse(document.getElementById('admin-questions').value);
    } catch (err) {
      feedback.textContent = 'Invalid JSON: ' + err.message;
      feedback.className = 'feedback bad';
      return;
    }
    try {
      const res = await fetch('/admin/questions', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'x-admin-token': token,
        },
        body: JSON.stringify({ questions }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(readError(data));
      feedback.textContent = 'Question bank replaced (' + data.count + ' questions).';
      feedback.className = 'feedback ok';
    } catch (err) {
      feedback.textContent = err.message;
      feedback.className = 'feedback bad';
    }
  }

  // Wire up controls.
  document.getElementById('btn-start').addEventListener('click', () => show('menu'));
  document.getElementById('btn-skip').addEventListener('click', () => show('menu'));
  document.getElementById('btn-play').addEventListener('click', startGame);
  document.getElementById('btn-help').addEventListener('click', getHelp);
  document.getElementById('btn-help-back').addEventListener('click', () => show('menu'));
  document.getElementById('btn-admin').addEventListener('click', showAdmin);
  document.getElementById('btn-admin-back').addEventListener('click', () => show('menu'));
  document.getElementById('btn-admin-load').addEventListener('click', adminLoad);
  document.getElementById('btn-admin-save').addEventListener('click', adminSave);
  document.getElementById('btn-pause').addEventListener('click', () => transition('pause'));
  document.getElementById('btn-resume').addEventListener('click', () => transition('resume'));
  document.getElementById('btn-resume-full').addEventListener('click', () => transition('resume'));
  document.getElementById('btn-quit').addEventListener('click', () => transition('quit'));
  document.getElementById('btn-again').addEventListener('click', startGame);
  document.getElementById('btn-menu').addEventListener('click', () => show('menu'));
})();
