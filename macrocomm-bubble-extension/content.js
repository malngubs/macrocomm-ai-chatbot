// Injects the Macrocomm web widget into every page
(function inject() {
  const API = 'http://localhost:8000'; // or your public API domain
  if (document.getElementById('mc-ext-widget')) return;
  const s = document.createElement('script');
  s.id = 'mc-ext-widget';
  s.src = `${API}/static/macrocomm-widget.js?v=2`;  // cache-bust
  s.setAttribute('data-api', API);
  s.defer = true;
  (document.head || document.documentElement).appendChild(s);
})();

