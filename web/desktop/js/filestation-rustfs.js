// File Station (RustFS) page — CSP-compliant event delegation
(function() {
  'use strict';

  var RUSTFS_API = 'http://localhost:9000';
  var CURRENT_BUCKET = 'forgeos-main';

  // ── Event delegation (replaces all inline onclick/onchange/ondrop) ──
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var action = btn.dataset.action;

    if (action === 'toggle-settings') {
      showSettings();
    } else if (action === 'trigger-file-input') {
      var input = document.getElementById('file-input');
      if (input) input.click();
    } else if (action === 'navigate') {
      navigateTo(btn.dataset.path || '');
    } else if (action === 'open-file') {
      openFile(btn.dataset.filename || '');
    } else if (action === 'open-folder') {
      openFolder(btn.dataset.filename || '');
    }
  });

  // File input change listener (replaces inline onchange)
  document.addEventListener('change', function(e) {
    if (e.target.id === 'file-input') {
      handleFileUpload(e.target.files);
    }
  });

  // Drag/drop listeners (replaces inline ondrop/ondragover/ondragleave)
  (function() {
    var area = document.getElementById('upload-area');
    if (!area) return;
    area.addEventListener('dragover', function(e) {
      e.preventDefault();
      area.classList.add('dragover');
    });
    area.addEventListener('dragleave', function(e) {
      area.classList.remove('dragover');
    });
    area.addEventListener('drop', function(e) {
      e.preventDefault();
      area.classList.remove('dragover');
      handleFileUpload(e.dataTransfer.files);
    });
  })();

  // File navigation
  function navigateTo(path) {
    console.log('Navigate to:', path);
    // In production, this would call RustFS S3 API
    // GET /{bucket}/{prefix}
  }

  function openFile(fileName) {
    console.log('Open file:', fileName);
    // In production: window.open(RUSTFS_API + '/' + CURRENT_BUCKET + '/' + fileName);
  }

  function openFolder(folderName) {
    console.log('Open folder:', folderName);
    // In production: navigateTo(CURRENT_BUCKET + '/' + folderName);
  }

  // File upload
  function handleFileUpload(files) {
    if (!files || files.length === 0) return;
    console.log('Uploading', files.length, 'files to RustFS...');
    // In production, this would use S3 multipart upload API
    alert('Upload functionality will connect to RustFS S3 API in production');
  }

  // Settings toggle
  function showSettings() {
    var panel = document.getElementById('settings-panel');
    if (panel) panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  }

  // Load files from RustFS API (when backend is ready)
  window.loadFiles = function(bucket, prefix) {
    return $loadFiles(bucket, prefix);
  };
  async function $loadFiles(bucket, prefix) {
    prefix = prefix || '';
    try {
      var response = await fetch(RUSTFS_API + '/' + bucket + '?prefix=' + prefix, {
        headers: {
          'Authorization': 'Bearer ' + (localStorage.getItem('forgeos_token') || '')
        }
      });
      var text = await response.text();
      var parser = new DOMParser();
      var data = parser.parseFromString(text, 'text/xml');
      console.log('Files loaded:', data);
    } catch (error) {
      console.error('Error loading files:', error);
    }
  }

  // Initialize
  // $loadFiles(CURRENT_BUCKET);

})();
