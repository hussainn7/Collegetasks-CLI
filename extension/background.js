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
    processPhysicalScan(request.announcements || [], request.deadlines || []).catch(err => sendLog("[Scanner] Error: " + err.message));
    sendResponse({ status: 'processing' });
  }
});

async function processPhysicalScan(newAnnouncements, hiddenDeadlines) {
  chrome.storage.local.get(['processedAnnouncements', 'hiddenCourses', 'geminiKey', 'tgChatId', 'deepScanDeadlines'], async (data) => {
    const processed = new Set(data.processedAnnouncements || []);
    const hidden = new Set(data.hiddenCourses || []);
    
    // Process Announcements
    const trulyNew = newAnnouncements.filter(a => !processed.has(a.Id) && !hidden.has(`/d2l/home/${a.CourseId}`));

    if (trulyNew.length > 0) {
      sendLog(`[Scanner] Found ${trulyNew.length} new announcements! Processing...`);

      const announcementsByCourse = {};
      for (const ann of trulyNew) {
        if (!announcementsByCourse[ann.Course]) {
          announcementsByCourse[ann.Course] = [];
        }
        announcementsByCourse[ann.Course].push(ann);
      }

      for (const [courseName, anns] of Object.entries(announcementsByCourse)) {
        let combinedText = anns.map(a => `Title: ${a.Title}\nBody: ${a.Body}`).join('\n\n---\n\n');
        let summary = combinedText;
        
        if (data.geminiKey) {
          sendLog(`[Scanner] Summarizing ${anns.length} announcements for ${courseName}...`);
          summary = await summarizeWithGemini(combinedText, data.geminiKey);
        }
        
        if (data.tgChatId) {
          sendLog(`[Scanner] Sending Telegram notification to ${data.tgChatId}...`);
          await sendTelegram(CONFIG.TELEGRAM_BOT_TOKEN, data.tgChatId, `🚨 *New Announcements in ${courseName}*\n\n${summary}`);
        } else {
          sendLog(`[Scanner] Telegram Chat ID not set! Summary: ${summary.substring(0,30)}...`);
        }
        
        anns.forEach(a => processed.add(a.Id));
      }
    } else {
       sendLog("[Scanner] No new announcements found.");
    }

    // Process Deadlines
    if (hiddenDeadlines.length > 0) {
      let existingDeadlines = data.deepScanDeadlines || [];
      hiddenDeadlines.forEach(hd => {
        // deduplicate by title and course
        if (!existingDeadlines.find(e => e.title === hd.title && e.course === hd.course)) {
          existingDeadlines.push(hd);
        }
      });
      chrome.storage.local.set({ deepScanDeadlines: existingDeadlines });
      sendLog(`[Scanner] Saved ${hiddenDeadlines.length} physical deadlines to storage.`);
    }

    chrome.storage.local.set({ 
      processedAnnouncements: Array.from(processed),
      lastScanTime: Date.now()
    });
    
    sendLog("[Scanner] Physical scan and sync complete! You are all caught up. 🎉");
  });
}

async function summarizeWithGemini(text, apiKey) {
  try {
    const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: "Summarize this announcement briefly: " + text }] }]
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
    return text; // Fallback to raw text
  }
}

async function sendTelegram(token, chatId, text) {
  try {
    await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: chatId,
        text: text,
        parse_mode: 'Markdown'
      })
    });
  } catch (e) {
    console.error("Telegram API error:", e);
  }


