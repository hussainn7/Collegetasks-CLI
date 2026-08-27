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
