'use strict';
if (document.querySelector('[data-refresh="true"]')) {
  window.setTimeout(() => window.location.reload(), 10000);
}

const provider = document.querySelector('#provider');
if (provider) {
  const updateProvider = () => {
    const isCodex = provider.value === 'codex_cli';
    document.querySelector('#codex-settings').hidden = !isCodex;
    const api = document.querySelector('#api-settings');
    api.hidden = isCodex;
    api.disabled = isCodex;
  };
  provider.addEventListener('change', updateProvider);
  updateProvider();
}
