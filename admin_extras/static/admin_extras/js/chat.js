// Simple admin chat client
(function () {
  const box = document.getElementById('chat-box');
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('chat-send');
  const cfgEl = document.getElementById('chat-config');
  let lastTs = null;
  let cfg = {messages_url: 'messages.json', send_url: 'send/'};

  try {
    if (cfgEl) cfg = JSON.parse(cfgEl.textContent || '{}') || cfg;
  } catch (e) {}

  function append(msg) {
    const el = document.createElement('div');
    el.className = 'mb-2';
    const time = new Date(msg.created_at).toLocaleString();
    el.textContent = `[${time}] ${msg.user}: ${msg.message}`;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
  }

  async function fetchMessages() {
    try {
      const url = lastTs ? (`${cfg.messages_url}?since=${encodeURIComponent(lastTs)}`) : cfg.messages_url;
      const res = await fetch(url);
      const data = await res.json();
      if (data.messages && data.messages.length) {
        data.messages.forEach(m => append(m));
        lastTs = data.messages[data.messages.length - 1].created_at;
      }
    } catch (e) { /* ignore */ }
  }

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  async function sendMessage() {
    const msg = input.value.trim();
    if (!msg) return;
    const form = new FormData();
    form.append('message', msg);
    try {
      await fetch(cfg.send_url, {method: 'POST', body: form, headers: {"X-CSRFToken": getCookie('csrftoken')}});
      input.value = '';
      lastTs = null; // fetch latest batch
      fetchMessages();
    } catch (e) {}
  }

  if (btn) btn.addEventListener('click', sendMessage);
  if (input) input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMessage(); });
  setInterval(fetchMessages, 5000);
  fetchMessages();
})();

