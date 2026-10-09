/* Stable links to the existing workspace without changing saved evidence. */
(function () {
  'use strict';
  const tabs = new Set(['overview', 'inputs', 'research', 'journal', 'demo', 'setup']);
  const showTab = go;
  const dialog = document.getElementById('judge-video');
  let currentTab = 'overview';

  function display(tab) {
    currentTab = tab;
    showTab(tab);
    document.querySelectorAll('[data-tab]').forEach(button => {
      if (button.dataset.tab === tab) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
  }

  go = function (tab) {
    if (!tabs.has(tab)) return;
    display(tab);
    if (location.hash !== '#' + tab) history.pushState(null, '', '#' + tab);
  };

  function followRoute(initial = false) {
    const route = location.hash.slice(1);
    if (route === 'walkthrough') {
      if (initial) display('overview');
      if (!dialog.open) dialog.showModal();
    } else if (tabs.has(route) || !route) {
      if (dialog.open) dialog.close();
      display(route || 'overview');
    }
    // Evidence/citation anchors are left to the browser, without changing tabs.
  }

  document.getElementById('watch-video').addEventListener('click', function () {
    if (location.hash !== '#walkthrough') history.pushState(null, '', '#walkthrough');
  });
  dialog.addEventListener('close', function () {
    if (location.hash === '#walkthrough') history.replaceState(null, '', '#' + currentTab);
  });
  window.addEventListener('hashchange', () => followRoute());
  window.addEventListener('popstate', () => followRoute());
  followRoute(true);
})();
