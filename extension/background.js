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
  if (request.action === 'scan_announcements') {
    runScanner(request.courses || []).catch(err => sendLog("[Scanner] Error: " + err.message));
    sendResponse({ status: 'scanning' });
  }
});

async function runScanner(courses) {
  sendLog("[Scanner] Starting background scan...");
  
  if (!courses || courses.length === 0) {
    sendLog("[Scanner] No courses found to scan.");
    return;
  }

  let newAnnouncements = [];

  // 2. Fetch announcements for each course using real API
  for (const course of courses) {
    try {
      sendLog(`[Scanner] Checking course: ${course.name}...`);
      const response = await fetch(`https://gastate.view.usg.edu/d2l/api/le/1.43/${course.id}/news/`);
      
      if (response.ok) {
        const news = await response.json();
        // The D2L API typically returns an array of News objects
        if (Array.isArray(news)) {
          news.forEach(item => {
            newAnnouncements.push({
              Id: item.Id || Math.random(),
              Title: item.Title || 'Announcement',
              Body: (item.Body && (item.Body.Text || item.Body.Html)) || 'No content.',
              Course: course.name,
              CourseId: `/d2l/home/${course.id}`
            });
          });
        }
      } else {
        sendLog(`[Scanner] API returned ${response.status} for ${course.name}`);
      }
    } catch (e) {
      sendLog(`[Scanner] Error fetching course ${course.name}: ${e.message}`);
    }
  }

  // 3. Filter against "database" (chrome.storage.local) and ignore hidden/muted courses
  chrome.storage.local.get(['processedAnnouncements', 'hiddenCourses', 'mutedCourses', 'geminiKey', 'tgChatId'], async (data) => {
    const processed = new Set(data.processedAnnouncements || []);
    const hidden = new Set(data.hiddenCourses || []);
    const muted = new Set(data.mutedCourses || []);
    
    const trulyNew = newAnnouncements.filter(a => !processed.has(a.Id) && !hidden.has(a.CourseId) && !muted.has(a.CourseId));

    if (trulyNew.length === 0) {
      sendLog("[Scanner] No new announcements found.");
      return;
    }

    sendLog(`[Scanner] Found ${trulyNew.length} new announcements! Processing...`);

    // 4. Summarize & Notify
    for (const ann of trulyNew) {
      let summary = ann.Body;
      
      if (data.geminiKey) {
        sendLog(`[Scanner] Summarizing announcement for ${ann.Course} using Gemini...`);
        summary = await summarizeWithGemini(ann.Body, data.geminiKey);
      }
      
      if (data.tgChatId) {
        sendLog(`[Scanner] Sending Telegram notification to ${data.tgChatId}...`);
        await sendTelegram(CONFIG.TELEGRAM_BOT_TOKEN, data.tgChatId, `🚨 *New Announcement in ${ann.Course}*\n\n*${ann.Title}*\n${summary}`);
      } else {
        sendLog(`[Scanner] Telegram Chat ID not set! Summary: ${summary.substring(0,30)}...`);
      }
      
      processed.add(ann.Id);
    }

    chrome.storage.local.set({ processedAnnouncements: Array.from(processed) });
    sendLog("[Scanner] Scan complete! You are all caught up. 🎉");
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
}
