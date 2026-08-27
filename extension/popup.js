document.addEventListener('DOMContentLoaded', () => {
  // Load saved settings
  chrome.storage.local.get(['tgChatId', 'geminiKey', 'globalDarkMode'], (result) => {
    if (result.tgChatId) document.getElementById('tgChatId').value = result.tgChatId;
    if (result.geminiKey) document.getElementById('geminiKey').value = result.geminiKey;
    if (result.globalDarkMode !== undefined) {
      document.getElementById('globalDarkMode').checked = result.globalDarkMode;
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

  // Clear DB
  document.getElementById('clearDbBtn').addEventListener('click', () => {
    chrome.storage.local.remove('processedAnnouncements', () => {
      const status = document.getElementById('status');
      status.textContent = 'Database cleared! ✓';
      setTimeout(() => { status.textContent = ''; }, 2000);
    });
  });
});
