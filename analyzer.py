import os
import json
from datetime import datetime, timezone
from pathlib import Path
from openai import OpenAI
from google import genai
from dotenv import load_dotenv
from parser import format_turns_for_prompt, format_chat_for_prompt, compute_doubt_windows
from curriculum import CurriculumService

import streamlit as st

load_dotenv()

# Lazy curriculum — initialized on first use so missing service_account.json
# at import time doesn't crash the app on deployment.
_curriculum_cache: dict = {}

def _get_curriculum(credentials_dict: dict = None) -> CurriculumService:
    """Return a CurriculumService, re-using a cached instance unless credentials changed."""
    cache_key = id(credentials_dict) if credentials_dict else "default"
    if cache_key not in _curriculum_cache:
        _curriculum_cache[cache_key] = CurriculumService(credentials_dict=credentials_dict)
    return _curriculum_cache[cache_key]


def _resolve_key(env_var: str, ui_key: str = "") -> str:
    """Return API key using priority: UI input → st.secrets → .env / os.getenv."""
    if ui_key and ui_key.strip():
        return ui_key.strip()
    try:
        secret = st.secrets.get(env_var, "")
        if secret:
            return secret
    except Exception:
        pass
    return os.getenv(env_var, "")

# ── Chat log path (same directory as this file) ───────────────────────────────
_LOG_PATH = Path(__file__).parent / "chat.log"
_SEP = "=" * 120

def _write_chat_log(prompt: str, result: dict, model_name: str = "unknown") -> None:
    """Append a timestamped block with the full prompt and JSON result to chat.log."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with _LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"{_SEP}\n")
        fh.write(f"TIMESTAMP : {ts}\n")
        fh.write(f"MODEL     : {model_name}\n")
        fh.write(f"{_SEP}\n")
        fh.write("[PROMPT — full rendered text sent to LLM]\n")
        fh.write(f"{_SEP}\n")
        fh.write(prompt.strip())
        fh.write(f"\n{_SEP}\n")
        fh.write("[RESULT — parsed JSON response from LLM]\n")
        fh.write(f"{_SEP}\n")
        fh.write(json.dumps(result, indent=2, ensure_ascii=False))
        fh.write(f"\n{_SEP}\n\n")

# Supported model identifiers
_OPENAI_MODELS = {"gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"}
_GEMINI_MODELS = {"gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"}

def _compute_scores(result: dict) -> dict:
    params = result.get('parameters', {})
    
    overall_sum = 0.0
    overall_count = 5.0
    
    # 1. Instructor Behaviour
    ib = params.get('instructor_behaviour', {})
    sub_checks = ib.get('sub_checks', {})
    total_ib = len(sub_checks)
    ib_score = 0.0
    ib_flags = 0
    if total_ib > 0:
        pts = 10.0 / total_ib
        for k, v in sub_checks.items():
            st = v.get('status', '').lower()
            if st == 'pass':
                ib_score += pts
            elif st == 'warn':
                ib_score += pts / 2.0
            elif st == 'fail':
                ib_flags += 1
    ib['score'] = round(ib_score, 1)
    ib['flag_count'] = ib_flags
    overall_sum += ib['score']
    
    # 2. Engagement
    eng = params.get('engagement', {})
    sub_checks = eng.get('sub_checks', {})
    total_eng = len(sub_checks)
    eng_score = 0.0
    eng_flags = 0
    if total_eng > 0:
        pts = 10.0 / total_eng
        for k, v in sub_checks.items():
            st = v.get('status', '').lower()
            if st == 'pass':
                eng_score += pts
            elif st == 'warn':
                eng_score += pts / 2.0
            elif st == 'fail':
                eng_flags += 1
    eng['score'] = round(eng_score, 1)
    eng['flag_count'] = eng_flags
    overall_sum += eng['score']
    
    # 3. Content Evaluation
    ce = params.get('content_evaluation', {})
    tm = ce.get('teaching_methodology', {})
    cc = ce.get('content_coverage', {})
    
    ce_score = 0.0
    # Two parts, 5 points each
    for part in [tm, cc]:
        st = part.get('status', '').lower()
        if st == 'pass':
            ce_score += 5.0
        elif st == 'warn':
            ce_score += 2.5
    ce['score'] = round(ce_score, 1)
    overall_sum += ce['score']
    
    # 4. Session Quality
    sq = params.get('session_quality', {})
    # camera, audio_video, screen_sharing
    _SQ_KEYS = ['camera', 'audio_video', 'screen_sharing']
    sq_total = sum(1 for k in _SQ_KEYS if k in sq)
    sq_score = 0.0
    if sq_total > 0:
        pts = 10.0 / sq_total
        for k in _SQ_KEYS:
            v = sq.get(k, {})
            if not v:
                continue
            st = v.get('status', '').lower()
            if st in ['pass', 'no_input']:
                sq_score += pts
            elif st in ['warn', 'unverifiable', 'needs_video']:
              sq_score += pts / 2.0
    sq['score'] = round(sq_score, 1)
    overall_sum += sq['score']
    
    # 5. Escalation Evaluation
    esc_wrapper = params.get('escalation', {})
    esc = esc_wrapper.get('low_rating', {})
    claims = esc.get('claims', [])
    esc_score = 10.0
    if claims:
        valid_count = sum(1 for c in claims if c.get('verdict', '').lower() == 'valid')
        total_claims = len(claims)
        esc_score = 10.0 - (valid_count * (10.0 / total_claims))
    esc_wrapper['score'] = round(esc_score, 1)
    overall_sum += esc_wrapper['score']
    
    result['overall_score'] = round(overall_sum / overall_count, 1)
    return result

def analyze_session(turns, chat_messages, session_name, escalation_feedback="", model: str = "gpt-4.1-mini", api_key: str = "", credentials_dict: dict = None):
    transcript_text  = format_turns_for_prompt(turns)
    chat_text        = format_chat_for_prompt(chat_messages)
    doubt_windows    = compute_doubt_windows(chat_messages, turns)
    # Only send unresponded messages to the LLM — responded ones are already addressed.
    # Compact JSON (no indent) eliminates whitespace tokens with zero semantic value.
    unresponded   = [d for d in doubt_windows if not d['instructor_responded']]
    doubt_context = json.dumps(unresponded, separators=(',', ':'))
    syllabus = _get_curriculum(credentials_dict).get_syllabus(session_name)

    SYSTEM_PROMPT = f"""

You will be tasked to audit a online learning session conducted on zoom.

Your thinking should be thorough and so it's fine if it's very long. You can think step by step before and after each action you decide to take.

You already have everything you need to solve this problem in the prompt itself. I want you to fully solve this autonomously before coming back to me.

Only terminate your turn when you are sure that the audit is completed. Go through the context step by step, and make sure to verify that your results are correct.

# Workflow

## High-Level Problem Solving Strategy

1. Think step by step and then carefully analyze the transcript and chat.
2. Identify all relevant events (flags, doubts, coverage) based on different Evaluation Rules.
3. Compute status (pass/warn/fail) strictly using your analysis and rules provided.
4. ONLY THEN generate final JSON.

Refer to the detailed sections below for more information on each step.

## 1. Instructor Behaviour Evaluation Rules

### Abusive Language:
- Any rude, insulting, sarcastic, or demeaning language toward students.

### Vague Conversation:
- A conversation is vague if it's unrelated to the session or tools being taught and was never initiated by the student.
Examples:
  - Self Promotion: Instructor promoting their own course, YouTube channel, or personal website → fail
  - Personal anecdotes: Instructor sharing personal anecdotes with no connection to the lesson → warn
CRITICAL: Even if semantic analysis shows low probability, you must still use your own judgement to determine if the conversation is vague or not.

### Stretching Session:
- Repeating same concept unnecessarily (>2 times without new information)
- OR delaying progression without adding value for extra money
- Do NOT flag recap or clarification.

### On time Start:
- session start within 10 mins of scheduled time (pass)
- session start >10 mins of scheduled time (warn)
- Time from session start to first actual teaching concept.
- Ignore greetings/introduction.

### Long Break:
- We need to identify the total instructor break duration and check if it is within acceptable limits.
- If break duration is:
  - Within 10 minutes (pass)
  - Greater than 10 and less than or equal to 15 minutes (warn)
  - Greater than 15 minutes (fail)

### Forcing Ratings:
- Any attempt to influence students to give high ratings.

---------

## 2. Engagement Evaluation Rules:

### a. Doubts Engagement
A message is a genuine doubt ONLY IF:
- It asks about the topic being taught
- OR asks for explanation/repetition/clarification
- OR asks "how/why" related to content

NOT A Doubt:
- reactions, emoji, confirmations ("clear", "yes sir")
- technical issues ("network issue", "screen stuck")
- peer-to-peer messages
- greetings or casual chat

A doubt is considered MISSED ONLY IF:
1. It exists in doubt_windows
2. It doesn't lie under NOT A Doubt category
3. AND no conceptually relevant explanation appears later in instructor turns

CRITICAL FOR PARKED DOUBTS: 
- If an instructor acknowledges a doubt and promises to answer it later (e.g., "I will answer this at the end of the class"), this acknowledgment is NOT a conceptually relevant explanation. 
- You MUST cross-reference the rest of the transcript. If the session ends without the instructor actually providing the promised explanation, the doubt MUST be flagged as MISSED.

Note: ALWAYS anlayze the full transcript & chat before making any decision regarding any doubt being missed (instructors may conduct doubt session at the end of the session).

### b. In-class Engagement:
- Analysing the chat and transcript, answer the following:
  - Did the instructor actively ask questions to students during the session.
  - Are the students actively responding to the instructor.
  - Is there a lack of engagement from the instructor.
- Factors like boredom, zero student-instructor interaction and low class engagement are the reason for deduction here. 

### c. Class Elongation:
- Verify if the session got elongated due to the instructor picking up more doubts

---------

## 3. Content Evaluation Rules

### a. Teaching Methodology

Evaluate teaching methodology on these 5 factors ONLY:

i. Agenda and Recap
- Does the instructor provide a brief agenda or recap of the previous session early in the class (usually in the first 20 minutes)?

ii. Clarity
- Concepts explained step-by-step with simple and easy to understand examples.
- No skipping reasoning

iii. Structure
- Follows: Concept → Example → Explanation → Doubt Clarification → Next Class Expectations
- No random topic jumps

iv. Examples
- Uses relevant examples to explain concepts (if applicable to the topic)
- Not just demo or theory

v. Session Summary or Next Class Expectations
- Check if instructor has given either a session summary or next class expectations in the final 20 minutes of the session (even if doubt-clearing happens afterwards).

Note: If any of the teaching methodology factors are missing (i.e. there is no evidence of it in the transcript and chat), then its clearly a gap.

### b. Content Coverage
- If syllabus is not provided, then determine which topics were covered in the session and list them down.
- If syllabus is provided, carefully analyse the transcript with respect to the syllabus and determine if the instructor has covered all the topics.
 - If a topic was not covered or skipped or postponed, then flag it warn or fail based on number of topics not covered.
- CRITICAL FOR POSTPONED TOPICS: If the instructor explicitly postpones a syllabus topic to a future session (e.g., "We will cover AI tools in the next class due to lack of time"), that topic MUST be placed in `topics_skipped` and the coverage status MUST be flagged as `warn` or `fail`. Mentioning a topic for the future does NOT count as covering it in the current session.

--------- 

## 4. Session Quality Evaluation Rules

### a. Camera ON/OFF
- Reading the transcript and chat try to identify if the instructor has turned on their camera. 
- Flag warn with your reasoning if there is ANY mention of the camera being OFF by students (e.g., "camera is OFF", "turn ON camera"), even if it was just for a short duration.

### b. Audio/Video Quality
- Any audio, video, or connectivity issue explicitly reported by students related to the instructor.
- Flag warn with your reasoning if there is ANY mention of instructor voice breaking, instructor not audible, or instructor related network issues, even if it didn't ruin the entire class.
- E.g: "sir your voice is not good", "sir your voice broke", "sir you are not audible".
- DO NOT flag if the complaint is about the student's own network ("my network is not stable", "my internet is slow").

### c. Screen Sharing Internal Document
- By analysing the transcript and chat try to identify if any kind of internal document is being utilized by the instructor for the teaching purpose. 
- Note: There could be cases where instructor might utilize their personal notes for teaching purpose, such cases dont fall under this category.  
- Do NOT consider Dataset, PPT or whiteboards or external websites.  
- If detected then warn with your reasoning.

---------

## 5. Escalation Evaluation Rules

### Low Rating Subjective Feedback

- These are the real feedbacks provided by the students after the session got ended.
- Each feedback is separated by user id.
- Validate them based on the analysis gathered from steps above, if a feedback is valid then flag it with reasoning.
- Note: In case where the gathered analysis is insufficient or lacking, only then re-iterate through the provided context.

---------

## 6. Final Verification
- Go through each detailed sections again and verify each evaluation rule category against the transcript & chat. (This will take time but believe me this is necessary and well within our context range)
 - If something seems wrong, correct it and continue.
- Review each sub_check and if status is fail, warn or pass, double check if the evidence attribute is present for it.
 - In case its missing re-evaluate and add the appropriate evidence to the proper sub_check.
- Only once you are done with the review process and extremely confident with your audit, then only proceed to generate the final JSON.

---------

# Evidence Verification
- Make sure each status with fail or warn issue has timestamp-based evidence (use the timestamp of the speaker block if the exact sentence doesn't have one). Do not hallucinate timestamps.
- If no issue → use "None detected"

---------
# Output Schema

{{
  "parameters": {{
    "instructor_behaviour": {{
      "summary": "<2-3 sentences>",
      "sub_checks": {{
        "abusive_language": {{
          "status": "pass|fail|warn",
           "detail": "<quote or 'None detected'>"
        }},
        "vague_conversation": {{
          "status": "pass|fail|warn",
           "detail": "<finding or 'None detected'>"
        }},
        "long_break": {{
          "status": "pass|fail|warn",
           "detail": "<timestamp/duration or 'None detected'>"
        }},
        "on_time_start": {{
          "status": "pass|fail|warn",
           "detail": "<timestamp or 'None detected'>"
        }},
        "forcing_ratings": {{
          "status": "pass|fail|warn",
           "detail": "<quote or 'None detected'>"
        }},
        "stretching_session": {{
          "status": "pass|fail|warn",
           "detail": "<finding or 'None detected'>"
        }}
      }},
      "evidence": [
        {{"source": "transcript|chat", "timestamp": "HH:MM:SS", "detail": "<what this shows>"}}
      ]
    }},
    "engagement": {{
      "summary": "<2-3 sentences>",
      "sub_checks": {{
        "doubts_engagement": {{
          "detail": "<quote or 'None detected'>",
          "status": "pass|fail|warn",
          "missed_doubts": [
            {{
              "question": "<their message text>",
              "timestamp": "HH:MM:SS",
              "source": "chat|transcript",
              "reason": "<why genuinely missed>"
            }}
          ]
        }},
        "in_class_engagement": {{
          "status": "pass|fail|warn",
          "detail": "<finding or 'None detected'>"
        }},
        "class_elongation": {{
          "status": "pass|fail|warn",
          "detail": "<finding or 'None detected'>"
        }}
      }},
      "evidence": [
        {{"source": "transcript|chat", "timestamp": "HH:MM:SS", "detail": "<what this shows>"}}
      ]
    }},
    "content_evaluation": {{
      "teaching_methodology": {{
        "status": "pass|warn|fail",
        "summary": "<2-3 sentences>",
        "strengths": ["<covered teaching methodology>"],
        "gaps": ["<missing teaching methodology>"],
        "evidence": [
          {{"source": "transcript", "timestamp": "HH:MM:SS", "detail": "<what this shows>"}}
        ]
      }},
      "content_coverage": {{
        "status": "pass|warn|fail",
        "topics_covered": ["<covered topic from syllabus>"],
        "topics_skipped": ["<skipped topic from syllabus>"],
        "summary": "<2-3 sentences>",
        "evidence": [
          {{"source": "transcript", "timestamp": "HH:MM:SS", "detail": "<topic evidence>"}}
        ]
      }}
    }},
    "escalation": {{
      "low_rating": {{
        "status": "no_input|triggered",
        "note": "<overall summary or 'No low rating feedback provided for this audit.'>",
        "claims": [
          {{
            "feedback": "<exact student feedback text>",
            "verdict": "valid|invalid",
            "reasoning": "<why this feedback is valid/invalid based on transcript/chat>"
          }}
        ]
      }}
    }},
    "session_quality": {{
      "camera": {{
        "status": "pass|fail|needs_video",
        "note": "<finding with timestamp, or 'No camera issue detected from chat/transcript'>"
      }},
      "audio_video": {{
        "status": "pass|fail|warn",
        "note": "<finding with timestamp, or 'No clear audio/video issue detected'>"
      }},
      "screen_sharing": {{
        "status": "pass|warn|unverifiable",
        "note": "<finding with timestamp, or 'No internal document detected'>"
      }}
    }}
  }}
}}

---------

# Context

# Session Transcript
{transcript_text}

# Session Chat
{chat_text}

# Content to be covered
{syllabus if syllabus else ''}

# Doubt Windows (unresponded only)
{doubt_context}

# Subjective Feedback (Escalation)
{escalation_feedback if escalation_feedback else ''}

# Final instructions and prompt to think step by step
Take your time and think through every step - remember to check your result rigorously and watch out for all evaluation rules with respect to the context provided, especially with the result you made. Your results must be perfect. If not, continue working on it.
"""

    # ── Route to the correct provider ────────────────────────────────────────
    if model in _GEMINI_MODELS or model.startswith("gemini"):
        result = _call_gemini(model, SYSTEM_PROMPT, api_key=api_key)
    else:
        result = _call_openai(model, SYSTEM_PROMPT, api_key=api_key)

    # Compute scores from flags at code level
    result = _compute_scores(result)

    # ── Write full prompt + result to chat.log ────────────────────────────────
    _write_chat_log(SYSTEM_PROMPT, result, model_name=model)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Provider-specific helpers
# ─────────────────────────────────────────────────────────────────────────────

def _call_openai(model: str, prompt: str, api_key: str = "") -> dict:
    """Call OpenAI chat completions and return enriched result dict."""
    key = _resolve_key("OPENAI_API_KEY", api_key)
    if not key:
        raise ValueError("OpenAI API key is not set. Provide it via the sidebar, st.secrets, or a .env file.")
    client = OpenAI(api_key=key)
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"},
    )

    usage = response.usage
    # Pricing based on model
    if model == "gpt-4.1":
        # gpt-4.1 pricing: $2.00/1M input, $0.50/1M cached input, $8.00/1M output
        input_cost  = (usage.prompt_tokens) * 0.00000200
        output_cost = usage.completion_tokens * 0.00000800
    else:
        # gpt-4.1-mini pricing: $0.40/1M input, $0.10/1M cached input, $1.60/1M output
        input_cost  = (usage.prompt_tokens) * 0.00000040
        output_cost = usage.completion_tokens * 0.00000160

    cost_usd    = input_cost + output_cost
    cost_inr    = cost_usd * 95.09
    
    print(f"[Audit Tokens] prompt={usage.prompt_tokens} | completion={usage.completion_tokens}")
    print(f"[Audit Cost]   ${cost_usd:.5f} = ₹{cost_inr:.2f}")

    result = json.loads(response.choices[0].message.content)
    result['_cost_usd']          = round(cost_usd, 5)
    result['_cost_inr']          = round(cost_inr, 2)
    result['_tokens_prompt']     = usage.prompt_tokens
    result['_tokens_completion'] = usage.completion_tokens
    return result


def _call_gemini(model: str, prompt: str, api_key: str = "") -> dict:
    """Call Google Gemini (google-genai SDK) and return enriched result dict."""
    key = _resolve_key("GEMINI_API_KEY", api_key)
    if not key:
        raise ValueError("Gemini API key is not set. Provide it via the sidebar, st.secrets, or a .env file.")
    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )

    # Token usage
    usage        = response.usage_metadata
    prompt_tok   = getattr(usage, 'prompt_token_count', 0) or 0
    complete_tok = getattr(usage, 'candidates_token_count', 0) or 0

    # gemini-2.0-flash pricing: $0.10/1M input, $0.40/1M output
    cost_usd = (prompt_tok * 0.00000010) + (complete_tok * 0.00000040)
    cost_inr = cost_usd * 95.09
    
    print(f"[Audit Tokens] prompt={prompt_tok} | completion={complete_tok}")
    print(f"[Audit Cost]   ${cost_usd:.5f} = ₹{cost_inr:.2f}")

    result = json.loads(response.text)
    result['_cost_usd']          = round(cost_usd, 5)
    result['_cost_inr']          = round(cost_inr, 2)
    result['_tokens_prompt']     = prompt_tok
    result['_tokens_completion'] = complete_tok
    return result
