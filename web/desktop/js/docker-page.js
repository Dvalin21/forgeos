// Docker page — event delegation (CSP-compliant, replaces inline onclick handlers)
(function() {
  'use strict';

  document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var action = btn.dataset.action;
    var container = btn.dataset.container;

    if (action === 'open-terminal') {
      var termName = document.getElementById('terminal-container-name');
      if (termName) termName.textContent = container;
      var modal = document.getElementById('terminal-modal');
      if (modal) modal.classList.remove('hidden');
      var terminal = document.getElementById('terminal-component');
      if (terminal) terminal.setAttribute('container', container);

    } else if (action === 'close-terminal') {
      var modal = document.getElementById('terminal-modal');
      if (modal) modal.classList.add('hidden');

    } else if (action === 'update-container') {
      if (confirm('Update container ' + container + ' via docker-compose?')) {
        alert('Running: docker-compose pull && docker-compose up -d\n\n(Integration with Docker API pending)');
      }

    } else if (action === 'stop-container') {
      if (confirm('Stop container ' + container + '?')) {
        alert('Running: docker stop ' + container + '\n\n(Integration with Docker API pending)');
        var card = document.querySelector('[data-container="' + container + '"]');
        if (card) {
          var badge = card.querySelector('.status-badge');
          if (badge) { badge.className = 'status-badge status-stopped'; badge.textContent = 'Stopped'; }
        }
      }

    } else if (action === 'down-container') {
      if (confirm('Stop and remove container ' + container + '? (docker down)')) {
        alert('Running: docker stop ' + container + ' && docker rm ' + container + '\n\n(Integration with Docker API pending)');
      }

    } else if (action === 'toggle-dropdown') {
      var menu = btn.nextElementSibling;
      if (menu) menu.classList.toggle('hidden');
      var outer = btn;
      document.addEventListener('click', function closeMenu(ev) {
        if (!outer.contains(ev.target) && !menu.contains(ev.target)) {
          menu.classList.add('hidden');
          document.removeEventListener('click', closeMenu);
        }
      });
    }
  });

  // Filter functionality (uses data-filter, not onclick)
  document.querySelectorAll('.filters .btn[data-filter]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.filters .btn').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      console.log('Filter:', btn.dataset.filter);
    });
  });

})();
