import { CONFIG } from './config.js';

// Background Service Worker for iCollege Organizer

function sendLog(msg) {
  console.log(msg);
  chrome.tabs.query({active: true, currentWindow: true}, function(tabs) {
    if (tabs[0]) {
      chrome.tabs.sendMessage(tabs[0].id, { type: 'scanner_log', message: msg });
    }
  });
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'process_physical_scan') {
    processPhysicalScan(request.announcements || [], request.deadlines || [])
      .then(() => sendLog("[Scanner] Background processing finished."))
      .catch(err => sendLog("[Scanner] Error: " + err.message));
    return true; // keep message channel open for async work
  }
});

async function processPhysicalScan(newAnnouncements, hiddenDeadlines) {
  sendLog("[Scanner] Background received data. Processing...");
  
  // Use Promise form (no callback) so await actually works in MV3
  const data = await chrome.storage.local.get([
    'processedAnnouncements', 'hiddenCourses', 'geminiKey', 'tgChatId', 'deepScanDeadlines'
  ]);

  const processed = new Set(data.processedAnnouncements || []);
  const hidden = new Set(data.hiddenCourses || []);
  
  const trulyNew = newAnnouncements.filter(a => !processed.has(a.Id) && !hidden.has(`/d2l/home/${a.CourseId}`));
  
  let allScrapedText = "";

  if (trulyNew.length > 0) {
    sendLog(`[Scanner] Found ${trulyNew.length} new announcements!`);
    allScrapedText += "--- NEW ANNOUNCEMENTS ---\n";
    trulyNew.forEach(a => {
      allScrapedText += `Course: ${a.Course}\nText: ${a.Body}\n\n`;
      processed.add(a.Id);
    });
  } else {
    sendLog("[Scanner] No new announcements found.");
  }

  // Process Deadlines
  let existingDeadlines = data.deepScanDeadlines || [];
  let trulyNewDeadlines = [];
  if (hiddenDeadlines.length > 0) {
    hiddenDeadlines.forEach(hd => {
      if (!existingDeadlines.find(e => e.id === hd.id)) {
        existingDeadlines.push(hd);
        trulyNewDeadlines.push(hd);
      }
    });
    await chrome.storage.local.set({ deepScanDeadlines: existingDeadlines });
    sendLog(`[Scanner] Saved ${hiddenDeadlines.length} physical deadlines.`);
    
    if (trulyNewDeadlines.length > 0) {
      allScrapedText += "--- NEW UPCOMING DEADLINES ---\n";
      trulyNewDeadlines.forEach(d => {
        allScrapedText += `Course: ${d.course}\nTask: ${d.title}\nDue: ${d.date}\n\n`;
      });
    }
  }

  // If we have any new data, send a consolidated To-Do list
  if (allScrapedText.trim().length > 0) {
    let finalMessage = allScrapedText;
    
    if (data.geminiKey) {
      sendLog("[Scanner] Generating To-Do list with Gemini...");
      finalMessage = await summarizeWithGemini(allScrapedText, data.geminiKey);
      sendLog("[Scanner] Gemini response received.");
    } else {
      sendLog("[Scanner] No Gemini key set, sending raw text.");
    }
    
    if (data.tgChatId) {
      sendLog("[Scanner] Sending Telegram To-Do list...");
      await sendTelegram(CONFIG.TELEGRAM_BOT_TOKEN, data.tgChatId, `🚨 *New Updates from iCollege!*\n\n${finalMessage}`);
      sendLog("[Scanner] ✅ Telegram notification sent successfully!");
    } else {
      sendLog("[Scanner] ⚠️ Telegram Chat ID not set! Cannot send notification.");
    }
  } else {
    sendLog("[Scanner] Nothing new to report this scan.");
  }

  await chrome.storage.local.set({ 
    processedAnnouncements: Array.from(processed),
    lastScanTime: Date.now()
  });
  
  sendLog("[Scanner] Physical scan and sync complete! 🎉");
}

async function summarizeWithGemini(text, apiKey) {
  try {
    const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: "Extract all tasks, assignments, and important actionable information from the following text and create a concise, structured To-Do list. Format it clearly with bullet points and bold text for course names. Do not write a long paragraph. If there is nothing actionable, just summarize the updates briefly.\n\n" + text }] }]
      })
    });
    const result = await response.json();
    if (result.candidates && result.candidates.length > 0) {
      return result.candidates[0].content.parts[0].text.trim();
    } else {
      console.error("Gemini returned unexpected format:", result);
      return text;
    }
  } catch (e) {
    console.error("Gemini API error:", e);
    return text;
  }
}

async function sendTelegram(token, chatId, text) {
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: chatId,
        text: text,
        parse_mode: 'Markdown'
      })
    });
    const json = await res.json();
    if (!json.ok) {
      sendLog(`[Scanner] Telegram API error: ${JSON.stringify(json)}`);
    }
  } catch (e) {
    console.error("Telegram API error:", e);
    sendLog(`[Scanner] Telegram network error: ${e.message}`);
  }
}
