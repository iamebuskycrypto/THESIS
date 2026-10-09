const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const script = fs.readFileSync('public/workspace-navigation.js', 'utf8');

function browser(hash) {
  const listeners = {}, dialogListeners = {}, visited = [], history = [];
  const dialog = {
    open: false,
    showModal() { this.open = true; },
    close() { this.open = false; dialogListeners.close?.(); },
    addEventListener(name, fn) { dialogListeners[name] = fn; }
  };
  const context = vm.createContext({
    go: tab => visited.push(tab),
    location: {hash},
    history: {
      pushState(_a, _b, value) { history.push(value); context.location.hash = value; },
      replaceState(_a, _b, value) { context.location.hash = value; }
    },
    window: {addEventListener: (name, fn) => { listeners[name] = fn; }},
    document: {
      querySelectorAll: () => [],
      getElementById: id => id === 'judge-video' ? dialog : {addEventListener() {}}
    }
  });
  vm.runInContext(script, context);
  return {context, visited, listeners, dialog, history};
}

test('every workspace link opens its requested section, not the default review', () => {
  const html = fs.readFileSync('public/index.html', 'utf8');
  for (const tab of ['overview', 'research', 'journal', 'demo', 'setup']) {
    assert.ok(html.includes(`demo.html#${tab}`));
    const b = browser('#' + tab);
    assert.equal(b.visited.at(-1), tab);
    assert.equal(b.history.length, 0, 'initial load does not pollute Back history');
  }
});

test('switching sections, Back and citation anchors preserve the correct view', () => {
  const b = browser('#journal');
  b.context.go('demo');
  assert.equal(b.context.location.hash, '#demo');
  b.context.location.hash = '#journal';
  b.listeners.popstate();
  assert.equal(b.visited.at(-1), 'journal');
  b.context.go('research');
  b.context.location.hash = '#evidence-article_001';
  b.listeners.hashchange();
  assert.equal(b.visited.at(-1), 'research');
});

test('walkthrough deep link opens the video and returns to the workspace on close', () => {
  const b = browser('#walkthrough');
  assert.equal(b.dialog.open, true);
  assert.equal(b.visited.at(-1), 'overview');
  b.dialog.close();
  assert.equal(b.context.location.hash, '#overview');
  b.context.location.hash = '#walkthrough';
  b.listeners.hashchange();
  b.context.location.hash = '#journal';
  b.listeners.popstate();
  assert.equal(b.dialog.open, false);
  assert.equal(b.visited.at(-1), 'journal');
});
