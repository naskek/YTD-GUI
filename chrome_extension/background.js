const HOST_NAME = 'com.miniurlconverter.auth';
const RECONNECT_DELAY_MS = 2000;
let port = null;
let reconnectTimer = null;

function connectNative() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
    port.onMessage.addListener(handleNativeMessage);
    port.onDisconnect.addListener(() => {
      port = null;
      if (!reconnectTimer) {
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connectNative();
        }, RECONNECT_DELAY_MS);
      }
    });
    port.postMessage({ type: 'hello', version: chrome.runtime.getManifest().version });
  } catch (_) {
    port = null;
  }
}

async function cookiesForDomain(domain) {
  const normalized = String(domain || '').replace(/^\./, '');
  if (!normalized) return [];
  return await chrome.cookies.getAll({ domain: normalized });
}

async function handleNativeMessage(message) {
  if (!message || message.type !== 'getCookies' || !port) return;
  const requestId = String(message.requestId || '');
  const domains = Array.isArray(message.domains) && message.domains.length
    ? message.domains
    : ['.youtube.com', '.google.com'];
  try {
    const all = [];
    for (const domain of domains) {
      const items = await cookiesForDomain(domain);
      all.push(...items);
    }
    port.postMessage({ type: 'cookiesResponse', requestId, cookies: all });
  } catch (error) {
    port.postMessage({
      type: 'error',
      requestId,
      error: error && error.message ? error.message : String(error),
    });
  }
}

chrome.runtime.onStartup.addListener(connectNative);
chrome.runtime.onInstalled.addListener(connectNative);
connectNative();
