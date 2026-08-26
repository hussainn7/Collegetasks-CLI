"""Prompt templates for LLM-based announcement summarization."""

# System prompt that establishes the LLM's role and output format
SYSTEM_PROMPT = """\
You are an expert academic assistant for a university student. Your job is to
analyze course announcements from Georgia State University's iCollege (D2L
Brightspace) and extract actionable information.

You must be thorough — students depend on you to never miss a deadline or
important update. When in doubt, flag it as an action item.
"""

# Per-batch summarization prompt
SUMMARIZE_PROMPT = """\
Analyze the following course announcements and produce a structured summary.

**Course:** {course_name}
**Current Date:** {current_date}

---
### Announcements:

{announcements_text}

---

### Instructions:

1. **Summary**: Write a concise 2-3 sentence overview of what's new in this course.

2. **Action Items**: Extract EVERY specific task, deadline, or change the student
   must act on. For each item include:
   - `task`: Clear description of what needs to be done
   - `deadline`: Due date/time in ISO 8601 if mentioned, otherwise "No deadline specified"
   - `priority`: HIGH (exams, major assignments, deadlines within 3 days), MEDIUM (regular
     homework, readings), or LOW (FYI, optional activities)
   - `category`: One of: ASSIGNMENT, EXAM, READING, MEETING, SCHEDULE_CHANGE, LAB, PROJECT, OTHER

3. Pay special attention to:
   - Upcoming deadlines and due dates
   - Changes to class schedule or location
   - Exam/quiz announcements
   - Assignment submissions and requirements
   - Lab session details and modifications
   - Office hours changes
   - Syllabus updates or policy changes

Respond in valid JSON with this exact structure:
```json
{{
  "course_name": "{course_name}",
  "summary": "...",
  "action_items": [
    {{
      "task": "...",
      "deadline": "...",
      "priority": "HIGH|MEDIUM|LOW",
      "category": "..."
    }}
  ],
  "raw_announcement_count": {announcement_count}
}}
```

If there are no action items, return an empty `action_items` array.
"""


def build_summarization_prompt(
    course_name: str,
    announcements_text: str,
    announcement_count: int,
    current_date: str,
) -> str:
    """Build the full summarization prompt with course context."""
    return SUMMARIZE_PROMPT.format(
        course_name=course_name,
        current_date=current_date,
        announcements_text=announcements_text,
        announcement_count=announcement_count,
    )
