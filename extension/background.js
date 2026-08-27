// Background Service Worker for iCollege Organizer

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'scan_announcements') {
    runScanner().catch(console.error);
    sendResponse({ status: 'scanning' });
  }
});

async function runScanner() {
  console.log("[Scanner] Starting background scan...");
  
  // 1. Fetch user's courses (Mocking API fetch for extension purposes)
  // Real endpoint: /d2l/api/lp/1.43/enrollments/myenrollments/
  const courses = [
    { id: 12345, name: 'CSC 1302' },
    { id: 67890, name: 'MATH 2211' }
  ];

  let newAnnouncements = [];

  // 2. Fetch announcements for each course
  for (const course of courses) {
    try {
      // Real endpoint: /d2l/api/le/1.43/${course.id}/news/
      // Mocking response
      const mockNews = [
        { Id: 101, Title: 'Welcome to Class', Body: 'Read the syllabus.', Course: course.name },
        { Id: 102, Title: 'Exam 1 Moved', Body: 'Exam 1 is now on Friday.', Course: course.name }
      ];
      newAnnouncements.push(...mockNews);
    } catch (e) {
      console.warn(`Failed to scan course ${course.id}`);
    }
  }

  // 3. Filter against "database" (chrome.storage.local)
  chrome.storage.local.get(['processedAnnouncements', 'geminiKey', 'tgToken', 'tgChatId'], async (data) => {
    const processed = new Set(data.processedAnnouncements || []);
    const trulyNew = newAnnouncements.filter(a => !processed.has(a.Id));

    if (trulyNew.length === 0) {
      console.log("[Scanner] No new announcements found.");
      return;
    }

    console.log(`[Scanner] Found ${trulyNew.length} new announcements!`);

    // 4. Summarize & Notify
    for (const ann of trulyNew) {
      let summary = ann.Body;
      
      // If Gemini Key is present, try to summarize
      if (data.geminiKey) {
        summary = await summarizeWithGemini(ann.Body, data.geminiKey);
      }
      
      // If Telegram is configured, send notification
      if (data.tgToken && data.tgChatId) {
        await sendTelegram(data.tgToken, data.tgChatId, `🚨 *New Announcement in ${ann.Course}*\\n\\n*${ann.Title}*\\n${summary}`);
      } else {
        console.log("Telegram not configured. Summary:", summary);
      }
      
      processed.add(ann.Id);
    }

    // Save back to database
    chrome.storage.local.set({ processedAnnouncements: Array.from(processed) });
    console.log("[Scanner] Scan complete.");
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
    return result.candidates[0].content.parts[0].text.trim();
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
