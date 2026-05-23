(function () {
  var sidebar   = document.getElementById('aq-sidebar');
  var overlay   = document.getElementById('aq-overlay');
  var hamburger = document.getElementById('aq-hamburger');
  function openSB()  { sidebar && sidebar.classList.add('is-open'); overlay && overlay.classList.add('is-open'); hamburger && hamburger.classList.add('is-open'); }
  function closeSB() { sidebar && sidebar.classList.remove('is-open'); overlay && overlay.classList.remove('is-open'); hamburger && hamburger.classList.remove('is-open'); }
  if (hamburger) hamburger.addEventListener('click', function () { sidebar && sidebar.classList.contains('is-open') ? closeSB() : openSB(); });
  if (overlay)   overlay.addEventListener('click', closeSB);
  document.querySelectorAll('.aq-nav a.aq-nav-item').forEach(function (a) { a.addEventListener('click', closeSB); });

  // Highlight active sidebar item by data-page set on body
  var page = document.body.getAttribute('data-page') || 'home';
  document.querySelectorAll('#aq-nav a.aq-nav-item').forEach(function (a) {
    if (a.getAttribute('data-nav') === page) a.classList.add('is-active');
  });
})();
