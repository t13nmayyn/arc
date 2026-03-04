# A.R.C — Autonomous Registration Companion

> Fill forms. Log in. Submit applications. Automatically.

A.R.C is a local AI agent that opens websites, reads forms, and fills them out on your behalf — using your saved profile and browser sessions.

---

## What it does

- Opens any URL in a real browser
- Reads form fields using DOM extraction
- Fills text, radio buttons, checkboxes, dropdowns, file uploads
- Uses saved browser sessions to skip logins (Google, Instagram, etc.)
- Records a video of everything the agent does
- Takes a screenshot at the end

---

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/YOUR_USERNAME/arc.git
cd arc
```

**2. Install dependencies**
```bash
pip install playwright groq python-dotenv
playwright install chromium
```

**3. Add your Groq API key**

Get a free key at https://console.groq.com

```bash
echo "GROQ_API=your_key_here" > .env
```

**4. Run**
```bash
python3 arc.py
```

---

## Usage

```
1  Run on a URL        — fill a form or log in automatically
2  Save a session      — log in once, reuse forever
3  View / edit profile — name, email, phone, credentials
q  Quit
```

**Example — fill a Google Form:**
```bash
python3 arc.py
# choose 2 → save your Google session once
# choose 1 → paste Google Form URL → done
```

---

## File structure

```
arc/
  arc.py           — CLI entry point
  agent.py         — AI planning loop
  browse.py        — browser automation (Playwright)
  save_session.py  — save browser sessions
  .env             — your API key (never commit this)
  sessions/        — saved login sessions (never commit)
  workspace/       — screenshots and recordings
```

---

## Tech stack

- [Playwright](https://playwright.dev/python/) — browser automation
- [Groq](https://console.groq.com) — LLaMA 3.3 70B for planning
- Python 3.10+

---

## Status

Early stage — works on Google Forms, actively improving.

---

*Built by Tanmay Narnaware*