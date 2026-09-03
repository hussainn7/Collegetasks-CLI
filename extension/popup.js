document.addEventListener('DOMContentLoaded', () => {
  // Load saved settings
  chrome.storage.local.get(['tgChatId', 'geminiKey', 'globalDarkMode', 'lastScanTime'], (result) => {
    if (result.tgChatId) document.getElementById('tgChatId').value = result.tgChatId;
    if (result.geminiKey) document.getElementById('geminiKey').value = result.geminiKey;
    if (result.globalDarkMode !== undefined) {
      document.getElementById('globalDarkMode').checked = result.globalDarkMode;
    }
    if (result.lastScanTime) {
      const date = new Date(result.lastScanTime);
      document.getElementById('lastScanTime').textContent = date.toLocaleString();
    }
  });

  // Save settings
  document.getElementById('saveBtn').addEventListener('click', () => {
    const tgChatId = document.getElementById('tgChatId').value.trim();
    const geminiKey = document.getElementById('geminiKey').value.trim();
    const globalDarkMode = document.getElementById('globalDarkMode').checked;

    chrome.storage.local.set({
      tgChatId: tgChatId,
      geminiKey: geminiKey,
      globalDarkMode: globalDarkMode
    }, () => {
      const status = document.getElementById('status');
      status.textContent = 'Settings saved successfully! ✓';
      setTimeout(() => { status.textContent = ''; }, 2000);
      
      // Notify active tabs about dark mode change
      chrome.tabs.query({ url: "*://gastate.view.usg.edu/*" }, (tabs) => {
        tabs.forEach(tab => chrome.tabs.sendMessage(tab.id, { action: 'toggle_dark_mode', enabled: globalDarkMode }));
      });
    });
  });

  // Test Gemini key
  document.getElementById('testGeminiBtn').addEventListener('click', async () => {
    const key = document.getElementById('geminiKey').value.trim();
    const statusEl = document.getElementById('geminiStatus');
    if (!key) {
      statusEl.style.color = '#ef4444';
      statusEl.textContent = 'Enter a key first.';
      return;
    }
    statusEl.style.color = '#888';
    statusEl.textContent = 'Testing…';
    try {
      const res = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key=${key}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ contents: [{ parts: [{ text: 'Say "OK" only.' }] }] }),
        }
      );
      const json = await res.json();
      if (json.candidates && json.candidates.length > 0) {
        statusEl.style.color = '#10b981';
        statusEl.textContent = '✓ Key works!';
      } else if (json.error) {
        statusEl.style.color = '#ef4444';
        statusEl.textContent = '✗ ' + json.error.message;
      } else {
        statusEl.style.color = '#ef4444';
        statusEl.textContent = '✗ Unexpected response';
      }
    } catch (e) {
      statusEl.style.color = '#ef4444';
      statusEl.textContent = '✗ ' + e.message;
    }
  });

  // Clear DB
  document.getElementById('clearDbBtn').addEventListener('click', () => {
    chrome.storage.local.remove('processedAnnouncements', () => {
      const status = document.getElementById('status');
      status.textContent = 'Database cleared! ✓';
      setTimeout(() => { status.textContent = ''; }, 2000);
    });
  });
});
