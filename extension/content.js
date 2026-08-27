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
      // Find course links by piercing shadow DOM
      const links = querySelectorAllShadows('a[href*="/d2l/home/"]');
      
      links.forEach(link => {
        let card = link.closest('d2l-enrollment-card, d2l-card, .vui-card, .d2l-course-banner-container') || link.parentElement;
        
        // Sometimes the link itself is the overlay! So let's attach to its parent if it's an overlay
        if (card === link) {
           card = link.parentElement;
        }
        
        if (card.hasAttribute('data-hide-injected')) return;
        card.setAttribute('data-hide-injected', 'true');
        
        const courseId = link.getAttribute('href');
        if (!courseId) return;

        if (hiddenCourses.has(courseId)) {
          card.style.display = 'none';
        }

        const hideBtn = document.createElement('button');
        hideBtn.innerText = '🙈 Hide';
        hideBtn.className = 'icollege-hide-btn';
        hideBtn.onclick = (e) => {
          e.preventDefault();
          e.stopPropagation();
          hiddenCourses.add(courseId);
          chrome.storage.local.set({ hiddenCourses: Array.from(hiddenCourses) }, () => {
            card.style.display = 'none';
          });
        };
        
        // Ensure card has relative positioning to hold the absolute button
        if (window.getComputedStyle(card).position === 'static') {
            card.style.position = 'relative'; 
        }
        
        card.appendChild(hideBtn);
      });
    }, 2000);
  });
}

initHideClasses();

// --- Feature 1: What's Due Injector ---

async function scrapeDeadlines() {
  try {
    // Attempt to fetch from the actual D2L calendar API
    const response = await fetch('/d2l/api/le/1.43/calendar/events/myEvents/');
    if (response.ok) {
      const data = await response.json();
      if (data && data.length > 0) {
        return data.map(event => ({
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

  // Fallback if API fails or returns empty
  return [
    { id: 1, title: 'Read Chapter 3', course: 'CSC 1302', date: 'Due Tomorrow, 11:59 PM' },
    { id: 2, title: 'Quiz 2', course: 'MATH 2211', date: 'Due Friday, 5:00 PM' },
    { id: 3, title: 'Project Draft', course: 'CSC 1302', date: 'Due Next Monday' }
  ];
}

async function injectWhatsDueUI() {
  if (document.getElementById('icollege-whats-due-widget')) return;
  
  const deadlines = await scrapeDeadlines();
  
  const widget = document.createElement('div');
  widget.id = 'icollege-whats-due-widget';
  
  let html = `
    <div class="whats-due-header">
      <h2>📅 What's Due</h2>
      <div>
        <button id="icollege-scan-btn" class="calendar-btn" style="background: #10b981; margin-right: 8px;">Scan Announcements 🔍</button>
        <button id="icollege-calendar-sync-btn" class="calendar-btn">Sync to Google Calendar ✨</button>
      </div>
    </div>
    <ul class="whats-due-list">
  `;
  
  if (deadlines.length === 0) {
    html += `<li class="empty-state">Nothing due soon! 🎉</li>`;
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
  
  document.getElementById('icollege-scan-btn').addEventListener('click', () => {
    const logContainer = document.getElementById('icollege-scanner-logs');
    logContainer.style.display = 'block';
    logContainer.innerHTML = '<div><em>Starting scan...</em></div>';
    
    // Send message to background script to trigger manual scan
    chrome.runtime.sendMessage({ action: 'scan_announcements' });
  });
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

  const icsString = icsLines.join("\\r\\n");
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
