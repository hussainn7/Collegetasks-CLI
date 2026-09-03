import { CONFIG } from './config.js';

const PRIORITY = { HIGH: "🔴", MEDIUM: "🟡", LOW: "🟢" };
const CATEGORY = {
  ASSIGNMENT: "📝", EXAM: "📋", READING: "📖",
  MEETING: "🤝", SCHEDULE_CHANGE: "📅", LAB: "🔬",
  PROJECT: "🏗️", OTHER: "📌",
};

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
    return true;
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

  const trulyNew = newAnnouncements.filter(a => !processed.has(a.Id) && !hidden.has(`/d2l/home/${a.CourseId}`));

  if (trulyNew.length === 0 && (!events || events.length === 0)) {
    sendLog("[Scanner] Nothing new to report.");
    await chrome.storage.local.set({ lastScanTime: Date.now() });
    sendLog("[Scanner] Done! 🎉");
    return;
  }

  if (trulyNew.length > 0) {
    sendLog(`[Scanner] ${trulyNew.length} new announcements/notifications to process.`);
    trulyNew.forEach(a => processed.add(a.Id));
  } else {
    sendLog("[Scanner] No new announcements/notifications.");
  }

  const scrapedText = buildScrapedText(trulyNew, events);
  let tasks = fallbackTasks(trulyNew, events);

  if (data.geminiKey && scrapedText.trim()) {
    sendLog("[Scanner] Sending data to Gemini for task extraction...");
    try {
      const extracted = await extractTasksWithGemini(scrapedText, data.geminiKey);
      if (extracted.length > 0) {
        tasks = extracted;
        sendLog(`[Scanner] Gemini extracted ${tasks.length} task(s).`);
      } else {
        sendLog("[Scanner] Gemini found no tasks — using local format.");
      }
    } catch (e) {
      sendLog(`[Scanner] Gemini error: ${e.message}. Using local format.`);
    }
  } else if (!data.geminiKey) {
    sendLog("[Scanner] No Gemini key — formatting locally.");
  }

  if (data.tgChatId && tasks.length > 0) {
    sendLog("[Scanner] Sending to Telegram...");
    try {
      const message = formatTaskMessage(tasks);
      const chunks = splitMessage(message, 3800);
      for (const chunk of chunks) {
        await sendTelegram(CONFIG.TELEGRAM_BOT_TOKEN, data.tgChatId, chunk);
      }
      sendLog("[Scanner] ✅ Telegram notification sent!");
    } catch (e) {
      sendLog(`[Scanner] Telegram error: ${e.message}`);
    }
  } else if (!data.tgChatId) {
    sendLog("[Scanner] ⚠️ No Telegram Chat ID set. Cannot send.");
  }

  await chrome.storage.local.set({
    processedAnnouncements: Array.from(processed),
    lastScanTime: Date.now()
  });

  sendLog("[Scanner] Done! 🎉");
}

function buildScrapedText(announcements, events) {
  let text = "";
  const grouped = {};
  announcements.forEach(a => {
    if (!grouped[a.Course]) grouped[a.Course] = [];
    grouped[a.Course].push(a);
  });
  for (const [course, items] of Object.entries(grouped)) {
    text += `\n=== ${course} ===\n`;
    items.forEach(a => { text += `[${a.Title}] ${a.Body}\n\n`; });
  }
  if (events && events.length > 0) {
    text += `\n=== UPCOMING COURSE EVENTS ===\n`;
    events.forEach(e => { text += `${e.text}\n\n`; });
  }
  return text;
}

function fallbackTasks(announcements, events) {
  const tasks = [];
  announcements.forEach(a => {
    tasks.push({
      course: a.Course || "General",
      task: oneLine(a.Body || a.Title),
      deadline: extractDeadline(a.Body || ""),
      priority: "MEDIUM",
      category: "OTHER",
    });
  });
  (events || []).forEach(e => {
    tasks.push({
      course: "Upcoming",
      task: oneLine(e.text),
      deadline: extractDeadline(e.text || ""),
      priority: "MEDIUM",
      category: "OTHER",
    });
  });
  return tasks;
}

function oneLine(text) {
  const line = (text || "").split("\n").map(l => l.trim()).find(l => l.length > 3) || "Update";
  const cleaned = line.replace(/\s+/g, " ").trim();
  return cleaned.length > 90 ? cleaned.slice(0, 87) + "…" : cleaned;
}

function extractDeadline(text) {
  const m = (text || "").match(/\b(?:due|deadline|by)\b[:\s]+(.{3,40}?)(?:\.|$)/i);
  return m ? m[1].trim() : "";
}

function formatTaskMessage(tasks) {
  const lines = ["📋 <b>iCollege Tasks</b>", ""];
  let current = null;

  for (const t of tasks) {
    const course = t.course || "General";
    if (course !== current) {
      current = course;
      lines.push("━━━━━━━━━━━━━━━━━━━━");
      lines.push(`📚 <b>${escapeHtml(course)}</b>`);
      lines.push("");
    }

    const p = PRIORITY[t.priority] || "⚪";
    const c = CATEGORY[t.category] || "📌";
    lines.push(`${p}${c} <b>${escapeHtml(t.task)}</b>`);

    const due = t.deadline ? escapeHtml(t.deadline) : "No deadline";
    const pri = escapeHtml(t.priority || "MEDIUM");
    lines.push(`      📅 ${due} · ${pri}`);
    lines.push("");
  }

  return lines.join("\n");
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
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
    let splitIdx = remaining.lastIndexOf("\n", maxLen);
    if (splitIdx < maxLen / 2) splitIdx = maxLen;
    chunks.push(remaining.substring(0, splitIdx));
    remaining = remaining.substring(splitIdx);
  }
  return chunks;
}

async function extractTasksWithGemini(text, apiKey) {
  const prompt = `You extract student tasks from iCollege (D2L) announcements and events.

Return ONLY valid JSON, no markdown:
{"tasks":[{"course":"","task":"","deadline":"","priority":"HIGH|MEDIUM|LOW","category":"ASSIGNMENT|EXAM|READING|MEETING|SCHEDULE_CHANGE|LAB|PROJECT|OTHER"}]}

Rules:
- task is one short line: what the student must do
- deadline is the due date if mentioned, else empty string
- HIGH = exams / major work / due within 3 days
- skip purely informational noise
- if nothing actionable: {"tasks":[]}

Text:
${text}`;

  const response = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key=${apiKey}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.2 },
      }),
    }
  );
  const result = await response.json();
  if (!result.candidates || !result.candidates.length) {
    throw new Error(result.error?.message || "Gemini returned no candidates");
  }

  const raw = result.candidates[0].content.parts[0].text.trim();
  const parsed = parseJson(raw);
  if (!parsed || !Array.isArray(parsed.tasks)) return [];

  return parsed.tasks
    .filter(t => t && t.task)
    .map(t => ({
      course: t.course || "General",
      task: String(t.task).trim(),
      deadline: String(t.deadline || "").trim(),
      priority: String(t.priority || "MEDIUM").toUpperCase(),
      category: String(t.category || "OTHER").toUpperCase(),
    }));
}

function parseJson(text) {
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const candidate = fence ? fence[1] : text;
  try {
    return JSON.parse(candidate);
  } catch (_) {
    const brace = candidate.match(/\{[\s\S]*\}/);
    if (brace) {
      try { return JSON.parse(brace[0]); } catch (__) {}
    }
  }
  return null;
}

async function sendTelegram(token, chatId, text) {
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text: text,
        parse_mode: "HTML",
        disable_web_page_preview: true,
      }),
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
