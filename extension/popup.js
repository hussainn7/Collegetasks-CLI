document.addEventListener('DOMContentLoaded', () => {
  // Load saved settings
  chrome.storage.local.get(['tgToken', 'tgChatId', 'geminiKey'], (result) => {
    if (result.tgToken) document.getElementById('tgToken').value = result.tgToken;
    if (result.tgChatId) document.getElementById('tgChatId').value = result.tgChatId;
    if (result.geminiKey) document.getElementById('geminiKey').value = result.geminiKey;
  });

  // Save settings
  document.getElementById('saveBtn').addEventListener('click', () => {
    const tgToken = document.getElementById('tgToken').value.trim();
    const tgChatId = document.getElementById('tgChatId').value.trim();
    const geminiKey = document.getElementById('geminiKey').value.trim();

    chrome.storage.local.set({
      tgToken: tgToken,
      tgChatId: tgChatId,
      geminiKey: geminiKey
    }, () => {
      const status = document.getElementById('status');
      status.textContent = 'Settings saved successfully! ✓';
      setTimeout(() => { status.textContent = ''; }, 2000);
    });
  });
});
