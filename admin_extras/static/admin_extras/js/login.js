// Toggle password visibility on admin login
(function () {
  function init() {
    const btn = document.getElementById('toggle-pass');
    const input = document.getElementById('id_password');
    if (!btn || !input) return;
    btn.addEventListener('click', function () {
      const type = input.getAttribute('type') === 'password' ? 'text' : 'password';
      input.setAttribute('type', type);
    });
  }
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();

