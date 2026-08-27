document.addEventListener('DOMContentLoaded', () => {
  // Load saved settings
  chrome.storage.local.get(['tgChatId', 'geminiKey'], (result) => {
    if (result.tgChatId) document.getElementById('tgChatId').value = result.tgChatId;
    if (result.geminiKey) document.getElementById('geminiKey').value = result.geminiKey;
  });

  // Save settings
  document.getElementById('saveBtn').addEventListener('click', () => {
    const tgChatId = document.getElementById('tgChatId').value.trim();
    const geminiKey = document.getElementById('geminiKey').value.trim();

    chrome.storage.local.set({
      tgChatId: tgChatId,
      geminiKey: geminiKey
    }, () => {
      const status = document.getElementById('status');
      status.textContent = 'Settings saved successfully! ✓';
      setTimeout(() => { status.textContent = ''; }, 2000);
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
