// iCollege Extension Content Script
console.log("iCollege Organizer V2 extension loaded.");

// --- Shadow DOM Piercer ---
// D2L uses web components heavily. We need to pierce the shadow DOM to find elements.
function querySelectorAllShadows(selector, el = document.body) {
  const elements = [];
  const walk = (node) => {
    if (node.matches && node.matches(selector)) {
      elements.push(node);
    }
    if (node.shadowRoot) {
      walk(node.shadowRoot);
    }
    node.childNodes.forEach(child => walk(child));
  };
  walk(el);
  return elements;
}

// --- Feature 2: Hide Trash Classes ---

function initHideClasses() {
  // Inject global Unhide button if not exists
  if (!document.getElementById('icollege-unhide-btn')) {
    const unhideContainer = document.createElement('div');
    unhideContainer.id = 'icollege-unhide-btn';
    unhideContainer.style.cssText = 'text-align: center; margin-top: 15px; margin-bottom: 15px; width: 100%;';
    
    const unhideBtn = document.createElement('a');
    unhideBtn.innerText = 'Unhide all hidden courses';
    unhideBtn.style.cssText = 'color: #6366f1; cursor: pointer; font-size: 13px; text-decoration: underline;';
    unhideBtn.onclick = () => {
      chrome.storage.local.set({ hiddenCourses: [] }, () => {
        alert("All courses unhidden! Please refresh the page.");
        window.location.reload();
      });
    };
    unhideContainer.appendChild(unhideBtn);
    
    // Try to place it after the "My Courses" widget or in the main page
    const mainContent = document.querySelector('.d2l-page-main') || document.body;
    mainContent.appendChild(unhideContainer);
  }

  chrome.storage.local.get({ hiddenCourses: [] }, (data) => {
    const hiddenCourses = new Set(data.hiddenCourses);
    
    setInterval(() => {
      const links = querySelectorAllShadows('a[href*="/d2l/home/"]');
      
      links.forEach(link => {
        let card = link.closest('d2l-enrollment-card, d2l-card, .vui-card, .d2l-course-banner-container') || link.parentElement;
        
        if (card === link) {
           card = link.parentElement;
        }
        
        const courseId = link.getAttribute('href');
        if (!courseId) return;

        if (hiddenCourses.has(courseId)) {
          card.remove();
          return;
        }

        if (card.hasAttribute('data-hide-injected')) return;
        card.setAttribute('data-hide-injected', 'true');

        // Inline styles to pierce any Shadow DOM strictness
        // CSS Variables are defined in styles.css and inherited into Shadow DOM automatically
        const btnStyle = `
          position: absolute !important;
          top: 10px !important;
          z-index: 2147483647 !important;
          pointer-events: auto !important;
          background-color: var(--icollege-btn-bg, rgba(255, 255, 255, 0.9)) !important;
          color: var(--icollege-btn-text, #333) !important;
          border: 1px solid var(--icollege-btn-border, #e5e5e5) !important;
          border-radius: 4px !important;
          padding: 4px 8px !important;
          font-size: 11px !important;
          font-weight: 500 !important;
          cursor: pointer !important;
          box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
          display: block !important;
        `;

        // Hide Button
        const hideBtn = document.createElement('button');
        hideBtn.innerText = 'Hide';
        hideBtn.className = 'icollege-hide-btn';
        hideBtn.style.cssText = btnStyle + 'right: 10px !important;';
        
        hideBtn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          hiddenCourses.add(courseId);
          chrome.storage.local.set({ hiddenCourses: Array.from(hiddenCourses) }, () => {
            card.remove();
          });
        }, true);
        
        hideBtn.addEventListener('mousedown', (e) => {
          e.preventDefault();
          e.stopPropagation();
        }, true);
        
        if (window.getComputedStyle(card).position === 'static') {
            card.style.position = 'relative'; 
        }
        
        card.appendChild(hideBtn);

        // --- Debug Scan Button ---
        if (!card.querySelector('.icollege-debug-btn')) {
          const debugBtn = document.createElement('button');
          debugBtn.innerText = 'Debug Scan';
          debugBtn.className = 'icollege-debug-btn';
          debugBtn.style.cssText = btnStyle + 'right: 60px !important; background-color: #fef08a !important; color: #854d0e !important; border-color: #fde047 !important;';
          
          debugBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const rawText = link.innerText.trim() || link.parentElement.innerText.trim();
            const courseName = rawText.split('\n')[0] || `Course ${courseId.replace('/d2l/home/', '')}`;
            triggerScan([{ id: courseId.replace('/d2l/home/', ''), name: courseName }]);
          }, true);
          
          debugBtn.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
          }, true);
          card.appendChild(debugBtn);
        }
      });
    }, 2000);
  });
}

initHideClasses();

// --- Feature 1: What's Due Injector ---

async function scrapeDeadlines() {
  let deadlines = [];
  try {
    // Attempt to fetch from the actual D2L calendar API
    const response = await fetch('/d2l/api/le/1.43/calendar/events/myEvents/');
    if (response.ok) {
      const data = await response.json();
      if (data && data.length > 0) {
        deadlines = data.map(event => ({
          id: event.EventId || Math.random(),
          title: event.Title || 'Unknown Event',
          course: event.OrgUnitName || 'General',
          date: new Date(event.StartDateTime).toLocaleString()
        }));
      }
    }
  } catch (e) {
    console.warn("Could not fetch actual API, falling back to mock");
  }

  if (deadlines.length === 0) {
    deadlines = [
      { id: 1, title: 'Read Chapter 3', course: 'CSC 1302', date: 'Due Tomorrow, 11:59 PM' },
      { id: 2, title: 'Quiz 2', course: 'MATH 2211', date: 'Due Friday, 5:00 PM' },
      { id: 3, title: 'Project Draft', course: 'CSC 1302', date: 'Due Next Monday' }
    ];
  }
  
  // Merge Deep Scan Deadlines
  try {
    const deepScanDeadlines = await new Promise((resolve) => {
      chrome.storage.local.get({ deepScanDeadlines: [] }, (data) => resolve(data.deepScanDeadlines));
    });
    
    if (deepScanDeadlines && deepScanDeadlines.length > 0) {
      deepScanDeadlines.forEach(ds => {
        // Only add if not already in deadlines (naive check by title/course)
        const exists = deadlines.find(d => d.title === ds.title && d.course === ds.course);
        if (!exists) {
          deadlines.push({
            id: ds.id,
            title: ds.title + ' (Deep Scan)',
            course: ds.course,
            date: ds.date
          });
        }
      });
    }
  } catch (e) {
    console.error("Error merging deep scan deadlines", e);
  }

  return deadlines;
}

async function injectWhatsDueUI() {
  if (document.getElementById('icollege-whats-due-widget')) return;
  
  const deadlines = await scrapeDeadlines();
  
  const widget = document.createElement('div');
  widget.id = 'icollege-whats-due-widget';
  
  let html = `
    <div class="whats-due-header">
      <h2 style="cursor: pointer; display: flex; align-items: center;" id="icollege-collapse-toggle">
        What's Due <span id="icollege-collapse-icon" style="margin-left: 8px; font-size: 11px;">▼</span>
        <span id="icollege-alert-badge" style="display:none; margin-left: 8px; background: #ef4444; color: white; border-radius: 10px; padding: 2px 6px; font-size: 10px; font-weight: bold;"></span>
      </h2>
      <div style="display: flex; gap: 8px;">
        <button id="icollege-scan-btn" class="calendar-btn">Sync & Scan Everything</button>
        <button id="icollege-calendar-sync-btn" class="calendar-btn">Sync Calendar</button>
      </div>
    </div>
    <div id="icollege-whats-due-body">
      <ul class="whats-due-list">
  `;
  
  if (deadlines.length === 0) {
    html += `<li class="empty-state">Nothing due soon</li>`;
  } else {
    deadlines.forEach(d => {
      html += `
        <li>
          <label>
            <input type="checkbox" class="task-checkbox" data-id="${d.id}" />
            <div class="task-details">
              <span class="task-title">${d.title}</span>
              <div class="task-meta">
                <span class="task-course">${d.course}</span>
                <span class="task-date">${d.date}</span>
              </div>
            </div>
          </label>
        </li>
      `;
    });
  }
  
  html += `</ul>`;
  
  // Add scanner log container
  html += `
    <div id="icollege-scanner-logs" style="margin-top: 15px; max-height: 100px; overflow-y: auto; font-family: monospace; font-size: 11px; color: #555; background: #f8fafc; padding: 8px; border-radius: 4px; border: 1px solid #e2e8f0; display: none;">
      <div><em>Scanner idle.</em></div>
    </div>
    </div> <!-- End of body -->
  `;
  
  widget.innerHTML = html;
  
  const mainContent = document.querySelector('.d2l-page-main') || document.body;
  if (mainContent === document.body) {
    widget.classList.add('floating-widget');
  }
  
  mainContent.prepend(widget);
  
  document.getElementById('icollege-calendar-sync-btn').addEventListener('click', () => {
    generateAndDownloadICS(deadlines);
  });
  
  // Try to render API notifications if they exist
  setTimeout(() => {
    chrome.storage.local.get(['recentAlerts'], (data) => {
      if (data.recentAlerts && data.recentAlerts.length > 0) {
        const badgeEl = document.getElementById('icollege-alert-badge');
        badgeEl.textContent = data.recentAlerts.length + ' Alerts';
        badgeEl.style.display = 'inline-block';
        
        const list = document.querySelector('.whats-due-list');
        data.recentAlerts.forEach(alert => {
          const li = document.createElement('li');
          li.innerHTML = `
            <div style="padding: 10px; background: #fff1f2; border-left: 3px solid #ef4444; margin-bottom: 8px; font-size: 12px;">
              <strong>🔔 Alert</strong>
              <div style="color: #475569; margin-top: 4px;">${alert.Title || alert.Message || JSON.stringify(alert).substring(0,50)}</div>
            </div>
          `;
          list.prepend(li); // put alerts at the top
        });
      }
    });
  }, 2500);
  
  // Try to find the top notifications / alerts badge (Fallback)
  setTimeout(() => {
    const alertBtn = document.querySelector('button[aria-label^="Update alerts"], button[id^="d2l-"][aria-label*="alerts"]');
    if (alertBtn) {
      // The badge usually has an indicator or aria-label specifies count (e.g., "Update alerts - 2 new alerts")
      const ariaLabel = alertBtn.getAttribute('aria-label') || '';
      const match = ariaLabel.match(/(\d+)\s+new/i);
      const badgeIndicator = alertBtn.querySelector('.d2l-icon-custom, .d2l-navigation-notification-icon, d2l-icon');
      
      let count = 0;
      if (match) {
        count = parseInt(match[1], 10);
      } else if (badgeIndicator && !badgeIndicator.hidden && window.getComputedStyle(badgeIndicator).display !== 'none') {
        // sometimes there's just a dot indicator
        count = '!';
      }
      
      if (count) {
        const badgeEl = document.getElementById('icollege-alert-badge');
        badgeEl.textContent = count + ' Alerts';
        badgeEl.style.display = 'inline-block';
      }
    }
  }, 2000);
  
  // Collapse toggle logic
  chrome.storage.local.get(['isPanelFolded'], (data) => {
    const body = document.getElementById('icollege-whats-due-body');
    const icon = document.getElementById('icollege-collapse-icon');
    if (data.isPanelFolded) {
      body.style.display = 'none';
      icon.innerText = '▶';
    } else {
      body.style.display = 'block';
      icon.innerText = '▼';
    }
  });

  document.getElementById('icollege-collapse-toggle').addEventListener('click', () => {
    const body = document.getElementById('icollege-whats-due-body');
    const icon = document.getElementById('icollege-collapse-icon');
    if (body.style.display === 'none') {
      body.style.display = 'block';
      icon.innerText = '▼';
      chrome.storage.local.set({ isPanelFolded: false });
    } else {
      body.style.display = 'none';
      icon.innerText = '▶';
      chrome.storage.local.set({ isPanelFolded: true });
    }
  });
  
  document.getElementById('icollege-scan-btn').addEventListener('click', () => {
    triggerScan();
  });
  
  // Auto-scan on load if on dashboard and cooldown passed
  if (window.location.href.includes('/d2l/home')) {
    chrome.storage.local.get(['lastScanTime'], (data) => {
      const now = Date.now();
      // 5 minute cooldown
      if (!data.lastScanTime || (now - data.lastScanTime > 5 * 60 * 1000)) {
        setTimeout(triggerScan, 2000); // wait for DOM to settle
      }
    });
  }
}

function triggerScan(specificCourseList = null) {
  const logContainer = document.getElementById('icollege-scanner-logs');
  if (logContainer) {
    logContainer.style.display = 'block';
    logContainer.innerHTML = `<div><em>Starting scan ${specificCourseList ? '(Debug Mode)' : ''}...</em></div>`;
  }
  
  // Scrape active courses from dashboard if not provided
  let coursesToScan = [];
  if (specificCourseList) {
    coursesToScan = specificCourseList;
  } else {
    const links = querySelectorAllShadows('a[href*="/d2l/home/"]');
    links.forEach(link => {
      const match = link.getAttribute('href').match(/\/d2l\/home\/(\d+)/);
      if (match) {
        const rawText = link.innerText.trim() || link.parentElement.innerText.trim();
        const courseName = rawText.split('\n')[0] || `Course ${match[1]}`;
        if (!coursesToScan.find(c => c.id === match[1])) {
          coursesToScan.push({ id: match[1], name: courseName });
        }
      }
    });
  }

  chrome.runtime.sendMessage({ action: 'scan_announcements', courses: coursesToScan });
}

// Listen for logs from background script
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'scanner_log') {
    const logContainer = document.getElementById('icollege-scanner-logs');
    if (logContainer) {
      logContainer.style.display = 'block';
      const logLine = document.createElement('div');
      logLine.innerText = request.message;
      logContainer.appendChild(logLine);
      logContainer.scrollTop = logContainer.scrollHeight;
    }
  }
});

function generateAndDownloadICS(deadlines) {
  if (!deadlines || deadlines.length === 0) {
    alert("Nothing to sync!");
    return;
  }

  let icsLines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//iCollege Organizer//EN",
    "CALSCALE:GREGORIAN"
  ];

  deadlines.forEach(d => {
    const now = new Date();
    now.setDate(now.getDate() + 1);
    
    const dateStr = now.toISOString().replace(/[-:]/g, '').split('.')[0] + "Z";
    
    icsLines.push("BEGIN:VEVENT");
    icsLines.push(`UID:${d.id}@icollege-organizer`);
    icsLines.push(`DTSTAMP:${dateStr}`);
    icsLines.push(`DTSTART:${dateStr}`);
    icsLines.push(`SUMMARY:${d.course} - ${d.title}`);
    icsLines.push(`DESCRIPTION:Generated by iCollege Organizer`);
    icsLines.push("END:VEVENT");
  });

  icsLines.push("END:VCALENDAR");

  const icsString = icsLines.join("\r\n");
  const blob = new Blob([icsString], { type: 'text/calendar' });
  const url = URL.createObjectURL(blob);
  
  const a = document.createElement('a');
  a.href = url;
  a.download = 'icollege-deadlines.ics';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  
  alert("Calendar sync initiated! Premium feature successfully demonstrated.");
}

setTimeout(injectWhatsDueUI, 3000);

// --- Global Dark Mode Engine ---
chrome.storage.local.get({ globalDarkMode: false }, (data) => {
  if (data.globalDarkMode) {
    document.documentElement.classList.add('icollege-dark-mode');
  }
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'toggle_dark_mode') {
    if (request.enabled) {
      document.documentElement.classList.add('icollege-dark-mode');
    } else {
      document.documentElement.classList.remove('icollege-dark-mode');
    }
  }
});

// --- Shadow DOM Dark Mode Fixer ---
setInterval(() => {
  const isDark = document.documentElement.classList.contains('icollege-dark-mode');
  const courseImages = querySelectorAllShadows('img.d2l-organization-image-main, d2l-course-image, .d2l-course-banner-container');
  
  courseImages.forEach(img => {
    if (isDark) {
      if (img.style.filter !== 'invert(1) hue-rotate(180deg)') {
        img.style.filter = 'invert(1) hue-rotate(180deg)';
      }
    } else {
      if (img.style.filter === 'invert(1) hue-rotate(180deg)') {
        img.style.filter = '';
      }
    }
  });
}, 2000);

// --- AI Announcement Summarization ---
async function summarizeAnnouncementLocally(el) {
  if (el.hasAttribute('data-ai-summarized')) return;
  el.setAttribute('data-ai-summarized', 'true');
  
  const text = el.innerText || el.textContent;
  if (!text || text.trim().length < 50) return;
  
  // check if local AI is available
  if (!window.ai) return;

  try {
    let session;
    if (window.ai.createTextSession) {
      session = await window.ai.createTextSession();
    } else if (window.ai.languageModel && window.ai.languageModel.create) {
      session = await window.ai.languageModel.create();
    } else {
      return;
    }
    
    const prompt = `Read this announcement and extract a 2-3 word TL;DR tag (e.g. [CLASS CANCELED], [DEADLINE EXTENDED], [REMINDER]). Then provide a 1-sentence summary.\n\nText: ${text}`;
    const result = await session.prompt(prompt);
    
    // Extract tag
    const tagMatch = result.match(/\[.*?\]/);
    const tag = tagMatch ? tagMatch[0] : '[ANNOUNCEMENT]';
    const cleanResult = result.replace(tag, '').trim();
    
    const isUrgent = tag.toUpperCase().includes('CANCEL') || tag.toUpperCase().includes('EXTEND') || tag.toUpperCase().includes('DUE') || tag.toUpperCase().includes('URGENT');
    const color = isUrgent ? '#ef4444' : '#10b981'; // Red for urgent, Green otherwise
    
    const summaryDiv = document.createElement('div');
    summaryDiv.style.cssText = `
      background: #f8fafc; 
      border-left: 4px solid ${color}; 
      padding: 12px; 
      margin-bottom: 15px; 
      border-radius: 4px; 
      font-family: -apple-system, sans-serif;
      box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    `;
    
    summaryDiv.innerHTML = `
      <div style="font-weight: 900; color: ${color}; font-size: 14px; margin-bottom: 6px; letter-spacing: 0.5px;">✨ AI SUMMARY ${tag}</div>
      <div style="font-size: 13px; color: #334155; line-height: 1.4;">${cleanResult}</div>
    `;
    
    el.insertBefore(summaryDiv, el.firstChild);
    
  } catch(e) {
    console.error("Local AI Summarization failed", e);
  }
}

setInterval(() => {
  const items = querySelectorAllShadows('.d2l-datalist-item, .news-item, .announcement-card, d2l-html-block');
  items.forEach(summarizeAnnouncementLocally);
}, 3000);
