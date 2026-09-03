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
    processPhysicalScan(request.announcements || [], request.events || [])
      .then(() => sendLog("[Scanner] Background processing finished."))
      .catch(err => sendLog("[Scanner] Error: " + err.message));
    return true; // keep message channel open for async work
  }
});

async function processPhysicalScan(newAnnouncements, events) {
  sendLog("[Scanner] Background received data. Processing...");
  sendLog(`[Scanner] Received: ${newAnnouncements.length} announcements/notifications, ${events.length} course events.`);
  
  const data = await chrome.storage.local.get([
    'processedAnnouncements', 'hiddenCourses', 'geminiKey', 'tgChatId'
  ]);

  const processed = new Set(data.processedAnnouncements || []);
  const hidden = new Set(data.hiddenCourses || []);
  
  // Filter out already-processed announcements and hidden courses
  const trulyNew = newAnnouncements.filter(a => !processed.has(a.Id) && !hidden.has(`/d2l/home/${a.CourseId}`));
  
  // Build one consolidated text blob with ALL information
  let allScrapedText = "";

  if (trulyNew.length > 0) {
    sendLog(`[Scanner] ${trulyNew.length} new announcements/notifications to process.`);
    
    // Group by course for clarity
    const grouped = {};
    trulyNew.forEach(a => {
      if (!grouped[a.Course]) grouped[a.Course] = [];
      grouped[a.Course].push(a);
    });
    
    for (const [course, items] of Object.entries(grouped)) {
      allScrapedText += `\n=== ${course} ===\n`;
      items.forEach(a => {
        allScrapedText += `[${a.Title}] ${a.Body}\n\n`;
      });
    }
    
    // Mark them as processed
    trulyNew.forEach(a => processed.add(a.Id));
  } else {
    sendLog("[Scanner] No new announcements/notifications.");
  }

  // Add course events
  if (events && events.length > 0) {
    allScrapedText += `\n=== UPCOMING COURSE EVENTS ===\n`;
    events.forEach(e => {
      allScrapedText += `${e.text}\n\n`;
    });
  }

  // If we have any text at all, process it
  if (allScrapedText.trim().length > 0) {
    let finalMessage = allScrapedText;
    
    if (data.geminiKey) {
      sendLog("[Scanner] Sending all data to Gemini for To-Do list...");
      try {
        finalMessage = await summarizeWithGemini(allScrapedText, data.geminiKey);
        sendLog("[Scanner] Gemini To-Do list received.");
      } catch (e) {
        sendLog(`[Scanner] Gemini error: ${e.message}. Sending raw text.`);
      }
    } else {
      sendLog("[Scanner] No Gemini key set — sending raw text instead.");
    }
    
    if (data.tgChatId) {
      sendLog("[Scanner] Sending to Telegram...");
      try {
        // Telegram has a 4096 char limit — split if needed
        const chunks = splitMessage(finalMessage, 3800);
        for (let i = 0; i < chunks.length; i++) {
          const prefix = i === 0 ? "🚨 *iCollege Update*\n\n" : "";
          await sendTelegram(CONFIG.TELEGRAM_BOT_TOKEN, data.tgChatId, prefix + chunks[i]);
        }
        sendLog("[Scanner] ✅ Telegram notification sent!");
      } catch (e) {
        sendLog(`[Scanner] Telegram error: ${e.message}`);
      }
    } else {
      sendLog("[Scanner] ⚠️ No Telegram Chat ID set. Cannot send.");
    }
  } else {
    sendLog("[Scanner] Nothing new to report.");
  }

  await chrome.storage.local.set({ 
    processedAnnouncements: Array.from(processed),
    lastScanTime: Date.now()
  });
  
  sendLog("[Scanner] Done! 🎉");
}

function splitMessage(text, maxLen) {
  if (text.length <= maxLen) return [text];
  const chunks = [];
  let remaining = text;
  while (remaining.length > 0) {
    if (remaining.length <= maxLen) {
      chunks.push(remaining);
      break;
    }
    // Try to split at a newline
    let splitIdx = remaining.lastIndexOf('\n', maxLen);
    if (splitIdx < maxLen / 2) splitIdx = maxLen; // fallback
    chunks.push(remaining.substring(0, splitIdx));
    remaining = remaining.substring(splitIdx);
  }
  return chunks;
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
