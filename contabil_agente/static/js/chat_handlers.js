// Compatibility loader: ensure older HTML include `/static/js/chat_handlers.js` works
// by dynamically loading the real main script. This avoids 404s that cause the
// server to return HTML (which triggers MIME type errors).
(function(){
  try {
    var existing = document.querySelector('script[src="/static/js/main.js"]');
    if (!existing) {
      var s = document.createElement('script');
      s.src = '/static/js/main.js';
      s.defer = true;
      document.head.appendChild(s);
    }
  } catch (e) {
    console.error('chat_handlers loader failed', e);
  }
})();
