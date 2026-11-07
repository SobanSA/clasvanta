/* Clasvanta v2.8.3 installation UX: Chrome/Edge + iOS Safari. */
(() => {
  'use strict';
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js', {scope: '/'})
        .catch(e => console.warn('Service worker registration unavailable:', e));
    });
  }
  let promptEvent = null, button = null;
  const installed = () => window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  const ios = () => /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const iosSafari = () => ios() && /WebKit/i.test(navigator.userAgent) && !/CriOS|FxiOS|EdgiOS|OPiOS/i.test(navigator.userAgent);
  const updateVisibility = () => { if (button) button.hidden = installed() || !(promptEvent || iosSafari()); };
  function showGuide() {
    const old = document.getElementById('clasvantaIosInstallGuide');
    if (old) { old.remove(); return; }
    const guide = document.createElement('div');
    guide.id = 'clasvantaIosInstallGuide';
    guide.className = 'pwa-ios-guide';
    guide.setAttribute('role', 'dialog');
    guide.setAttribute('aria-label', 'Install app');
    const instruction = document.createElement('p');
    instruction.textContent = 'To install on iPhone or iPad, tap Share in Safari, then choose “Add to Home Screen”.';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'pwa-close-guide';
    close.textContent = 'Close';
    close.addEventListener('click', () => guide.remove());
    guide.append(instruction, close);
    document.body.append(guide);
    close.focus();
  }
  async function install() {
    if (promptEvent) {
      const p = promptEvent;
      promptEvent = null;
      updateVisibility();
      try { await p.prompt(); await p.userChoice; } catch (e) { console.warn('Install not completed:', e); }
    } else if (iosSafari()) showGuide();
  }
  function mount() {
    if (button || document.getElementById('clasvantaPwaInstall')) return;
    button = document.createElement('button');
    button.id = 'clasvantaPwaInstall';
    button.className = 'pwa-install-button';
    button.type = 'button';
    button.textContent = 'Install app';
    button.hidden = true;
    button.addEventListener('click', install);
    const header = document.querySelector('.top-right');
    if (header) header.insertBefore(button, header.firstChild);
    else { button.classList.add('pwa-install-floating'); document.body.append(button); }
    updateVisibility();
  }
  window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); promptEvent = e; updateVisibility(); });
  window.addEventListener('appinstalled', () => { promptEvent = null; document.getElementById('clasvantaIosInstallGuide')?.remove(); updateVisibility(); });
  window.addEventListener('DOMContentLoaded', mount);
  if (document.readyState !== 'loading') mount();
})();
