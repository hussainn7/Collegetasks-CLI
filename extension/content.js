// iCollege Extension Content Script
console.log("iCollege Organizer extension loaded.");

// --- Feature 2: Hide Trash Classes ---

function initHideClasses() {
  chrome.storage.local.get({ hiddenCourses: [] }, (data) => {
    const hiddenCourses = new Set(data.hiddenCourses);
    
    // Periodically check for course cards because D2L loads them dynamically
    setInterval(() => {
      // D2L typically uses a custom web component for course cards
      const cards = document.querySelectorAll('d2l-enrollment-card');
      
      cards.forEach(card => {
        // Avoid adding the button twice
        if (card.hasAttribute('data-hide-injected')) return;
        card.setAttribute('data-hide-injected', 'true');
        
        // Extract a unique identifier for the course. 
        // In D2L, this could be the href of the main link.
        const link = card.shadowRoot?.querySelector('a') || card.querySelector('a');
        const courseId = link ? link.getAttribute('href') : card.getAttribute('text');
        
        if (!courseId) return;

        if (hiddenCourses.has(courseId)) {
          card.style.display = 'none';
        }

        // Create the Hide Button
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
        
        // Try to inject it into a header area inside the card
        // We just append to the card itself (using absolute positioning in CSS)
        card.style.position = 'relative'; // Ensure button positions correctly
        card.appendChild(hideBtn);
      });
    }, 2000);
  });
}

initHideClasses();

// --- Feature 1: What's Due Injector ---

function scrapeDeadlines() {
  // In a real D2L page, this would traverse widgets looking for calendar events
  // or use the D2L API: fetch('/d2l/api/le/1.43/12345/calendar/events/')
  // For the extension, we'll try to parse any visible dates/events.
  
  const deadlines = [];
  
  // D2L often has an 'Updates' or 'Calendar' widget.
  // We'll simulate finding tasks for demonstration, but add standard selectors
  const taskElements = document.querySelectorAll('.d2l-datalist-item, .d2l-textblock');
  
  // If no tasks found, return a placeholder for the demo
  if (taskElements.length === 0) {
    return [
      { id: 1, title: 'Read Chapter 3', course: 'CSC 1302', date: 'Due Tomorrow, 11:59 PM' },
      { id: 2, title: 'Quiz 2', course: 'MATH 2211', date: 'Due Friday, 5:00 PM' },
      { id: 3, title: 'Project Draft', course: 'CSC 1302', date: 'Due Next Monday' }
    ];
  }
  
  return deadlines;
}

function injectWhatsDueUI() {
  if (document.getElementById('icollege-whats-due-widget')) return;
  
  const deadlines = scrapeDeadlines();
  
  const widget = document.createElement('div');
  widget.id = 'icollege-whats-due-widget';
  
  let html = `
    <div class="whats-due-header">
      <h2>📅 What's Due</h2>
      <button id="icollege-calendar-sync-btn" class="calendar-btn">Sync to Google Calendar ✨</button>
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
  widget.innerHTML = html;
  
  // Try to insert it above the main content area in D2L
  const mainContent = document.querySelector('.d2l-page-main') || document.body;
  if (mainContent === document.body) {
    // If we can't find the main container, float it in the corner
    widget.classList.add('floating-widget');
  }
  
  mainContent.prepend(widget);
}

// Run the injector after a short delay to let D2L load
setTimeout(injectWhatsDueUI, 3000);
