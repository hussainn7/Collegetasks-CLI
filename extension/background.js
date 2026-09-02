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
    runScanner(request.courses || [], request.token).catch(err => sendLog("[Scanner] Error: " + err.message));
    sendResponse({ status: 'scanning' });
  }
});

async function runScanner(courses, bearerToken) {
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
      const headers = {};
      if (bearerToken) {
        headers['Authorization'] = `Bearer ${bearerToken}`;
      }
      
      const response = await fetch(`https://gastate.view.usg.edu/d2l/api/le/1.43/${course.id}/news/`, { headers });
      
      if (response.ok) {
        const news = await response.json();
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
        sendLog(`[Scanner] API returned ${response.status} for ${course.name} news`);
      }

      // Deep scan modules for hidden assignments
      await deepScanCourseModules(course, bearerToken);
      
    } catch (e) {
      sendLog(`[Scanner] Error fetching course ${course.name}: ${e.message}`);
    }
  }

  // Fetch Notifications/Alerts
  try {
    sendLog("[Scanner] Fetching top notifications/alerts...");
    const headers = {};
    if (bearerToken) {
      headers['Authorization'] = `Bearer ${bearerToken}`;
    }
    
    const whoamiRes = await fetch("https://gastate.view.usg.edu/d2l/api/lp/1.43/users/whoami", { headers });
    if (whoamiRes.ok) {
      const user = await whoamiRes.json();
      const userId = user.Identifier;
      
      const alertRes = await fetch(`https://gastate.view.usg.edu/d2l/api/lp/1.43/alerts/user/${userId}?category=Update`, { headers });
      if (alertRes.ok) {
        const alerts = await alertRes.json();
        chrome.storage.local.set({ recentAlerts: alerts });
      } else {
        sendLog(`[Scanner] Failed to fetch alerts for user ${userId} (Status: ${alertRes.status})`);
      }
    } else {
      sendLog(`[Scanner] Failed to fetch whoami (Status: ${whoamiRes.status})`);
    }
  } catch (e) {
    sendLog(`[Scanner] Error fetching alerts: ${e.message}`);
  }

  // 3. Filter against "database" (chrome.storage.local) and ignore hidden courses
  chrome.storage.local.get(['processedAnnouncements', 'hiddenCourses', 'geminiKey', 'tgChatId'], async (data) => {
    const processed = new Set(data.processedAnnouncements || []);
    const hidden = new Set(data.hiddenCourses || []);
    
    const trulyNew = newAnnouncements.filter(a => !processed.has(a.Id) && !hidden.has(a.CourseId));

    if (trulyNew.length === 0) {
      sendLog("[Scanner] No new announcements found.");
      chrome.storage.local.set({ lastScanTime: Date.now() });
      return;
    }

    sendLog(`[Scanner] Found ${trulyNew.length} new announcements! Processing...`);

    // 4. Group by course
    const announcementsByCourse = {};
    for (const ann of trulyNew) {
      if (!announcementsByCourse[ann.Course]) {
        announcementsByCourse[ann.Course] = [];
      }
      announcementsByCourse[ann.Course].push(ann);
    }

    // 5. Summarize & Notify per course
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

    chrome.storage.local.set({ 
      processedAnnouncements: Array.from(processed),
      lastScanTime: Date.now()
    });
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

async function deepScanCourseModules(course, bearerToken) {
  sendLog(`[Scanner] Deep scanning modules for ${course.name}...`);
  try {
    const headers = {};
    if (bearerToken) {
      headers['Authorization'] = `Bearer ${bearerToken}`;
    }
    const response = await fetch(`https://gastate.view.usg.edu/d2l/api/le/1.43/${course.id}/content/toc`, { headers });
    if (!response.ok) return;
    
    const toc = await response.json();
    const hiddenDeadlines = [];
    
    // Recursive function to parse modules and topics
    function parseNodes(nodes) {
      if (!nodes) return;
      nodes.forEach(node => {
        sendLog(`[Debug] Traversing: ${node.Title} (Type: ${node.TypeIdentifier || 'Module'})`);
        
        // If it's a topic (Quiz, Dropbox, Discussion) with a DueDate or EndDate
        if (node.TopicType === 1 || node.TopicType === 3 || node.TypeIdentifier) {
          const dateStr = node.DueDate || node.EndDate;
          if (dateStr) {
            const dateObj = new Date(dateStr);
            const now = new Date();
            // Only care about future or recently past deadlines
            if (dateObj > now - 7 * 24 * 60 * 60 * 1000) {
              sendLog(`[Debug] -> Added deadline for: ${node.Title} (Due: ${dateStr})`);
              hiddenDeadlines.push({
                id: node.TopicId || Math.random(),
                title: node.Title,
                course: course.name,
                date: dateObj.toLocaleString(),
                type: node.TypeIdentifier || 'Module Item'
              });
            } else {
              sendLog(`[Debug] -> Skipped ${node.Title} (Date too old: ${dateStr})`);
            }
          }
        }
        
        // Traverse sub-modules
        if (node.Modules && node.Modules.length > 0) {
          parseNodes(node.Modules);
        }
        
        // Traverse topics
        if (node.Topics && node.Topics.length > 0) {
          parseNodes(node.Topics);
        }
      });
    }

    if (toc.Modules) {
      parseNodes(toc.Modules);
    }
    
    if (hiddenDeadlines.length > 0) {
      sendLog(`[Scanner] Found ${hiddenDeadlines.length} hidden module deadlines in ${course.name}`);
      chrome.storage.local.get({ deepScanDeadlines: [] }, (data) => {
        let existing = data.deepScanDeadlines || [];
        // merge and deduplicate
        hiddenDeadlines.forEach(hd => {
          if (!existing.find(e => e.id === hd.id)) {
            existing.push(hd);
          }
        });
        chrome.storage.local.set({ deepScanDeadlines: existing });
      });
    }

  } catch (e) {
    sendLog(`[Scanner] Deep scan error for ${course.name}: ${e.message}`);
  }
}

