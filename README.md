# 🎯 Live Class Audit System

An AI-powered, automated auditing system for live online classes (Zoom). It ingests a session's VTT transcript and Zoom chat export, fetches the planned syllabus from a Google Sheet, and produces a structured, multi-parameter quality report — all through a polished Streamlit UI.

---

## 📋 Table of Contents

- [What it Does](#what-it-does)
- [Architecture Overview](#architecture-overview)
- [Audit Parameters](#audit-parameters)
- [Scoring Engine](#scoring-engine)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [Running the App](#running-the-app)
- [How to Use](#how-to-use)
- [Curriculum Integration](#curriculum-integration)

---

## What it Does

Given a Zoom session's `.vtt` transcript file and a `.txt` chat export, the system:

1. **Parses** the VTT and chat into structured speaker turns and messages.
2. **Detects doubt windows** — pre-computes a 5-minute response window for every student chat message to determine if the instructor responded.
3. **Fetches the session syllabus** from a Google Sheet using the session name (with fuzzy matching).
4. **Sends everything to an LLM** (GPT-4.1 mini or Gemini) with a detailed audit prompt.
5. **Computes scores deterministically** from the LLM's qualitative flags (`pass` / `warn` / `flagged`) — the LLM never generates numbers.
6. **Renders a rich visual report** in Streamlit with per-parameter scores, evidence timelines, missed doubts, and escalation verdicts.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Streamlit UI (app.py)                    │
│  Sidebar: upload files / session details / model selection      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │         parser.py               │
          │  • parse_vtt()  → speaker turns │
          │  • parse_chat() → chat messages │
          │  • compute_doubt_windows()      │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │       curriculum.py             │
          │  • Connects to Google Sheets    │
          │  • Fuzzy-matches session name   │
          │  • Returns topic list           │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │         analyzer.py             │
          │  • Builds full LLM prompt       │
          │  • Calls OpenAI or Gemini API   │
          │  • _compute_scores() — scoring  │
          │    engine runs post-LLM         │
          │  • Writes audit to chat.log     │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │      render_report() in app.py  │
          │  • Renders HTML report cards    │
          │  • Score bars, badges, evidence │
          └─────────────────────────────────┘
```

---

## Audit Parameters

The system evaluates 5 top-level parameters, each with sub-checks:

### 1. 🔵 Instructor Behaviour
| Sub-check | What it detects |
|---|---|
| Abusive Language | Rude, insulting, or demeaning language toward students |
| Vague Conversation | Off-topic talk (self-promotion, unrelated anecdotes) |
| Long Break | Break > 10 min (warn) or > 15 min (flag) |
| Idle | No teaching for > 5 minutes at session start |
| Forcing Ratings | Any attempt to influence student ratings |
| Stretching Session | Unnecessary repetition without adding new information |

### 2. 💬 Engagement
| Sub-check | What it detects |
|---|---|
| Doubts Engagement | Ratio of student questions addressed vs missed |
| In-class Engagement | Instructor-student interaction quality |
| Class Elongation | Whether session extended purely due to picking up doubts |

### 3. 📚 Content Evaluation
| Sub-check | What it detects |
|---|---|
| Teaching Methodology | Clarity, structure (concept → example → explanation), use of examples |
| Content Coverage | Topics covered vs planned syllabus; skipped topics flagged |

### 4. ⚙️ Session Quality
| Sub-check | What it detects |
|---|---|
| Camera ON/OFF | Any student mention of camera being off |
| Audio/Video Quality | Voice breaking, inaudible audio, network issues |
| Screen Sharing Internal Document | Internal company documents shared during teaching |

### 5. ⭐ Escalation Evaluation
- Validates post-session low-rating student feedback against the transcript/chat evidence.

---

## Scoring Engine

Scores are computed **deterministically in code** after the LLM produces qualitative flags — the LLM never outputs numbers.

| Parameter | Scoring Logic |
|---|---|
| Instructor Behaviour | 10 points split equally across 6 sub-checks. `pass` = full pts, `warn` = half pts, `flagged` = 0 |
| Engagement | Same as above, split across 3 sub-checks |
| Content Evaluation | 5 pts for Teaching Methodology + 5 pts for Content Coverage; `pass`=full, `warn`=half |
| Session Quality | 10 pts split across 3 quality checks; `pass`=full, `unverifiable`/`needs_video`=half |
| Escalation | Starts at 10; each valid complaint deducts `10 / total_claims` |
| **Overall Score** | Average of all 5 parameter scores, rounded to 1 decimal |

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | [Streamlit](https://streamlit.io/) |
| LLM (primary) | OpenAI GPT-4.1 mini |
| LLM (alternative) | Google Gemini (2.0 Flash / 2.5 Flash / 1.5 Pro) |
| Curriculum data | Google Sheets via `gspread` |
| Fuzzy matching | `rapidfuzz` |
| Transcript parsing | Custom VTT parser (`parser.py`) |
| Cost tracking | Built-in token counting with INR conversion |

---

## Project Structure

```
Live Class Audit/
├── app.py                   # Streamlit UI + report renderer
├── analyzer.py              # LLM orchestration + scoring engine
├── parser.py                # VTT & chat parsers, doubt window logic
├── curriculum.py            # Google Sheets curriculum loader
├── run_audit.py             # (Optional) CLI runner
├── requirements.txt         # Python dependencies
├── Recording.transcript.vtt # Demo transcript file
├── Chat.txt                 # Demo chat export file
├── chat.log                 # Full prompt + result log for every audit run
├── .env                     # API keys (not committed)
├── service_account.json     # GCP service account (not committed)
└── .gitignore
```

---

## Setup & Installation

### Prerequisites
- Python 3.10+
- A Google Cloud service account with access to the curriculum Google Sheet
- An OpenAI API key and/or a Google Gemini API key

### 1. Clone the repo

```bash
git clone https://github.com/programteam-cn/PoC_Live_Class_Audit_System.git
cd PoC_Live_Class_Audit_System
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate   # macOS / Linux
venv\Scripts\activate      # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
pip install gspread rapidfuzz pandas
```

> **Note:** `gspread`, `rapidfuzz`, and `pandas` are used by `curriculum.py` and may not be listed in `requirements.txt` yet. Install them separately as shown above.

---

## Configuration

### `.env` file

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AI...
```

### `service_account.json`

Place your Google Cloud service account JSON file in the project root as `service_account.json`. This file is used by `curriculum.py` to authenticate with Google Sheets.

> ⚠️ **Never commit this file.** It is listed in `.gitignore`.

To create a service account:
1. Go to [Google Cloud Console](https://console.cloud.google.com/) → IAM & Admin → Service Accounts.
2. Create a new service account and download the JSON key.
3. Share the curriculum Google Sheet with the service account email (as a Viewer).

---

## Running the App

```bash
streamlit run app.py
```

The app will open at `http://localhost:8501`.

---

## How to Use

1. **Upload files** (or use demo files): In the sidebar, upload a `.vtt` transcript and a `.txt` Zoom chat export, or check **"Use demo session files"** to use the bundled `Recording.transcript.vtt` and `Chat.txt`.

2. **Fill in session details**: Enter the session title, date, time, duration, instructor name, and number of learners.

3. **Select a model**: Choose between GPT-4.1 mini, Gemini 3.1 Flash, or Gemini 3.1 Pro.

4. **Enter the session name**: This is used to fuzzy-match against the curriculum Google Sheet to auto-fetch the planned syllabus. Leave blank to let the LLM determine topics from the transcript itself.

5. **Add escalation feedback** *(optional)*: Paste any low-rating student feedback from the post-session survey. The LLM will validate each claim against the transcript.

6. **Click 🚀 Run Audit**: The system will parse, analyze, and render the full report in seconds.

7. **Download the JSON report**: Click "⬇ Download JSON Report" to save the full structured audit output.

---

## Curriculum Integration

`curriculum.py` connects to a Google Sheet structured as follows:

| Week # | Session # | Session Name | Topics/Objectives of the Class | ... |
|---|---|---|---|---|
| 1 | 1 | Excel Basics | Filtering, Sorting | ... |

- Each worksheet tab represents a **module**.
- Session Name is fuzzy-matched (≥ 82% similarity threshold via `rapidfuzz`) so minor naming inconsistencies are handled gracefully.
- Assessment rows (containing "assess") are automatically excluded from the syllabus.

### Test the curriculum lookup standalone

```bash
python curriculum.py
# Enter session name: Excel Basics
```

---

## Cost Tracking

Every audit logs its token usage and cost:

| Model | Input | Output |
|---|---|---|
| GPT-4.1 mini | $0.40 / 1M tokens | $1.60 / 1M tokens |
| Gemini 2.0 Flash | $0.10 / 1M tokens | $0.40 / 1M tokens |

Costs are displayed in both USD and INR (₹) in the UI after each audit run. A typical 2-hour session audit costs under **₹2**.

---

## Audit Log

Every audit run appends a full log entry to `chat.log` including:
- Timestamp and model used
- The complete rendered prompt sent to the LLM
- The full JSON result returned

This is useful for debugging, prompt iteration, and audit traceability.

---

*Built for Coding Ninjas · PoC — Live Class Audit System*
