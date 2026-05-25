(function () {
  var sidebar   = document.getElementById('aq-sidebar');
  var overlay   = document.getElementById('aq-overlay');
  var hamburger = document.getElementById('aq-hamburger');
  function openSB()  { sidebar && sidebar.classList.add('is-open'); overlay && overlay.classList.add('is-open'); hamburger && hamburger.classList.add('is-open'); }
  function closeSB() { sidebar && sidebar.classList.remove('is-open'); overlay && overlay.classList.remove('is-open'); hamburger && hamburger.classList.remove('is-open'); }
  if (hamburger) hamburger.addEventListener('click', function () { sidebar && sidebar.classList.contains('is-open') ? closeSB() : openSB(); });
  if (overlay)   overlay.addEventListener('click', closeSB);
  document.querySelectorAll('.aq-nav a.aq-nav-item').forEach(function (a) { a.addEventListener('click', closeSB); });

  // Accordion toggle for grouped nav items (e.g. カレンダー)
  document.querySelectorAll('#aq-nav .aq-nav-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var group = btn.closest('.aq-nav-group');
      if (!group) return;
      var open = group.classList.toggle('is-open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  });

  // Highlight active sidebar item by data-page set on body, expand parent group if needed
  var page = document.body.getAttribute('data-page') || 'home';
  document.querySelectorAll('#aq-nav a.aq-nav-item').forEach(function (a) {
    if (a.getAttribute('data-nav') === page) {
      a.classList.add('is-active');
      var group = a.closest('.aq-nav-group');
      if (group) {
        group.classList.add('is-open');
        var toggle = group.querySelector('.aq-nav-toggle');
        if (toggle) toggle.setAttribute('aria-expanded', 'true');
      }
    }
  });
})();
