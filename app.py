import streamlit as st
import json
import os
import io
import textwrap
import pandas as pd
from parser import parse_vtt, parse_chat
from analyzer import analyze_session
from curriculum import CurriculumService

st.set_page_config(
    page_title="Live Class Audit — Coding Ninjas",
    page_icon="🎯",
    layout="wide",
)

# ── Global CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');

:root {
    --bg-main: #0B0B0D;
    --bg-card: #161618;
    --bg-sidebar: #0F0F11;
    --accent: #0A84FF;
    --border: rgba(255, 255, 255, 0.08);
    --text-primary: #FFFFFF;
    --text-secondary: #8E8E93;
}

html, body {
    font-family: 'Inter', sans-serif;
    background-color: var(--bg-main);
}

/* Apply font to Streamlit main content area only */
.stApp, .main .block-container {
    font-family: 'Inter', sans-serif;
}

h1, h2, h3, .metric-label {
    font-family: 'Outfit', sans-serif;
}

.stApp { background: var(--bg-main); }

/* Sidebar */
section[data-testid="stSidebar"] { 
    background: var(--bg-sidebar) !important; 
    border-right: 1px solid var(--border) !important; 
}
section[data-testid="stSidebar"] * { color: #E5E5EA !important; }

/* Metrics */
[data-testid="stMetricValue"] {
    font-family: 'Outfit', sans-serif;
    font-size: 32px !important;
    font-weight: 700 !important;
    background: linear-gradient(135deg, #fff 0%, #888 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

/* Cards */
.report-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 16px;
    transition: transform 0.2s ease, border-color 0.2s ease;
}
.report-card:hover {
    border-color: rgba(10, 132, 255, 0.3);
}

.stButton > button {
    background: linear-gradient(135deg, #0A84FF 0%, #0060C4 100%) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 600 !important;
    font-size: 15px !important;
    padding: 12px 24px !important;
    width: 100% !important;
    box-shadow: 0 4px 12px rgba(10, 132, 255, 0.2) !important;
    transition: all .3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
.stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 16px rgba(10, 132, 255, 0.3) !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-main); }
::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }

/* Hide Streamlit branding — do NOT hide header (contains sidebar toggle & toolbar icons) */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
/* Keep the deploy button hidden but leave the rest of the header visible */
[data-testid="stToolbarActions"] { display: none; }

/* Animation */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
.animate-in {
    animation: fadeIn 0.5s ease forwards;
}
</style>
""", unsafe_allow_html=True)

# ── Report HTML Renderer ─────────────────────────────────────────────────────
def badge(text, color):
    colors = {
        "pass":     ("#1A3A25", "#32D74B"),
        "flagged":  ("#3A2000", "#FF9F0A"),
        "warn":     ("#3A2000", "#FF9F0A"),
        "fail":     ("#3A0A0A", "#FF453A"),
        "gray":     ("#2C2C2E", "#8E8E93"),
    }
    bg, fg = colors.get(color, colors["gray"])
    return f'<span style="background:{bg};color:{fg};padding:3px 10px;border-radius:6px;font-size:12px;font-weight:600;white-space:nowrap">{text}</span>'


def source_tag(source):
    if source == "transcript":
        return '<span style="background:#0A3A6E;color:#64C8FF;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;margin-right:8px">Transcript</span>'
    return '<span style="background:#1A3A1A;color:#32D74B;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;margin-right:8px">Chat</span>'


def score_bar(label, score, color="#FF9F0A"):
    pct = (max(0, min(10, score)) / 10) * 100
    return textwrap.dedent(f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
      <div style="flex:1;min-width:0">
        <span style="color:#8E8E93;font-size:13px">{label}</span>
      </div>
      <div style="flex:2;background:#3A3A3C;border-radius:4px;height:6px">
        <div style="width:{pct}%;background:{color};border-radius:4px;height:6px"></div>
      </div>
      <span style="color:#E5E5EA;font-size:13px;font-weight:600;min-width:24px;text-align:right">{score}</span>
    </div>""").strip()


def sub_check_row(label, status, detail):
    s = status.lower()
    color = "pass" if s == "pass" else ("fail" if s == "fail" else "warn")
    detail_html = f'<div style="color:#8E8E93;font-size:12px;margin-top:4px">{detail}</div>' if detail else ""
    return textwrap.dedent(f"""
    <div style="display:flex;align-items:flex-start;justify-content:space-between;padding:10px 0;
         border-bottom:1px solid #2C2C2E;gap:12px">
      <div style="flex:1">
        <span style="color:#E5E5EA;font-size:13px">{label}</span>
        {detail_html}
      </div>
      {badge(status.title(), color)}
    </div>""").strip()


def evidence_item(ev):
    return textwrap.dedent(f"""
    <div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:10px">
      {source_tag(ev.get('source','transcript'))}
      <span style="color:#FF9F0A;font-size:12px;font-weight:600;white-space:nowrap">{ev.get('timestamp','')}</span>
      <span style="color:#8E8E93;font-size:12px;flex:1">{ev.get('detail','')}</span>
    </div>""").strip()


def render_report(data, meta):
    p = data.get("parameters", {})
    overall = data.get("overall_score", 0)

    # ── Score bar color
    def bar_color(score):
        if score >= 8: return "#32D74B"
        if score >= 6: return "#FF9F0A"
        return "#FF453A"

    # ── Overall score color
    oc = bar_color(overall)

    # ── Scoreable params for bar chart
    ce = p.get("content_evaluation", {})
    sq = p.get("session_quality", {})
    esc = p.get("escalation", {})
    scoreable = [
        ("Instructor behaviour", p.get("instructor_behaviour", {}).get("score", 0)),
        ("Engagement",           p.get("engagement", {}).get("score", 0)),
        ("Content evaluation",   ce.get("score", 0)),
        ("Session quality",      sq.get("score", 0)),
        ("Escalation",           esc.get("score", 0)),
    ]

    bars_html = "".join(score_bar(l, s, bar_color(s)) for l, s in scoreable)

    header = textwrap.dedent(f"""
    <div class="report-card animate-in" style="background: linear-gradient(135deg, #1C1C1E 0%, #111113 100%); border-color: rgba(255,255,255,0.12)">
      <h2 style="color:#fff;margin:0 0 18px;font-size:18px;font-weight:700;letter-spacing:-0.5px">
        {meta.get('session_title','Audit Report')}
      </h2>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:16px">
        <div><div style="color:#8E8E93;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Date</div>
             <div style="color:#fff;font-size:14px;font-weight:500">{meta.get('date','—')}</div></div>
        <div><div style="color:#8E8E93;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Session Name</div>
             <div style="color:#fff;font-size:14px;font-weight:500">{meta.get('session_name','—')}</div></div>
      </div>
    </div>""").strip()

    # ── Overall score card
    score_card = textwrap.dedent(f"""
    <div class="report-card animate-in" style="display:flex;gap:32px;align-items:center; background: linear-gradient(135deg, #1C1C1E 0%, #161618 100%)">
      <div style="text-align:center;min-width:120px; padding-right:32px; border-right: 1px solid var(--border)">
        <div style="font-size:56px;font-weight:800;color:{oc};line-height:1;font-family:'Outfit',sans-serif;letter-spacing:-2px">{overall:.1f}</div>
        <div style="color:#8E8E93;font-size:12px;margin-top:8px;text-transform:uppercase;letter-spacing:1px">Overall score</div>
      </div>
      <div style="flex:1">{bars_html}</div>
    </div>""").strip()

    # ── Parameter cards
    ib = p.get("instructor_behaviour", {})
    eng = p.get("engagement", {})
    
    ce = p.get("content_evaluation", {})
    tm = ce.get("teaching_methodology", {})
    cc = ce.get("content_coverage", {})
    
    sq = p.get("session_quality", {})
    cam = sq.get("camera", {})
    ss = sq.get("screen_sharing", {})
    av = sq.get("audio_video", {})
    
    esc = p.get("escalation", {})
    lr = esc.get("low_rating", {})

    def card_header(icon, title, score_text, badge_text, badge_color):
        score_html = f"<span style='color:#E5E5EA;font-size:14px;font-weight:700;margin-right:12px'>{score_text}</span>" if score_text else ""
        return textwrap.dedent(f"""
        <div style="display:flex;align-items:center;gap:12px">
          <span style="font-size:20px">{icon}</span>
          <span style="color:#fff;font-size:15px;font-weight:600;flex:1">{title}</span>
          {score_html}
          {badge(badge_text, badge_color)}
        </div>""").strip()

    def section_card(inner_html):
        return f'<div class="report-card animate-in">{inner_html}</div>'

    # Instructor Behaviour
    ib_flags = ib.get("flag_count", 0)
    ib_sub = ib.get("sub_checks", {})
    sub_labels = {
        "abusive_language": "Abusive language",
        "vague_conversation": "Vague / incoherent conversation",
        "long_break": "Long / unannounced break",
        "on_time_start": "On time start",
        "forcing_ratings": "Forcing ratings",
        "stretching_session": "Stretching session (waiting for joins)",
    }
    ib_subs_html = "".join(
        sub_check_row(sub_labels.get(k, k), v.get("status","pass"), v.get("detail",""))
        for k, v in ib_sub.items()
    )
    ib_ev_html = "".join(evidence_item(e) for e in ib.get("evidence", []))
    ib_badge_color = "flagged" if ib_flags > 0 else "pass"
    ib_badge_text = f"{ib_flags} flag{'s' if ib_flags != 1 else ''}" if ib_flags > 0 else "Pass"

    ib_html = card_header("🔵", "Instructor behavioural issues",
                           f"{ib.get('score',0):.1f}/10", ib_badge_text, ib_badge_color)
    evidence_html = f"<div style='margin-top:14px'><div style='color:#8E8E93;font-size:11px;text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px'>Evidence</div>{ib_ev_html}</div>" if ib_ev_html else ""
    ib_html += textwrap.dedent(f"""
    <div style="margin-top:14px">
      <p style="color:#8E8E93;font-size:13px;line-height:1.6;margin-bottom:14px">{ib.get('summary','')}</p>
      {ib_subs_html}
      {evidence_html}
    </div>""").strip()

    # Engagement
    eng_flags = eng.get("flag_count", 0)
    eng_sub = eng.get("sub_checks", {})
    eng_badge_text = f"{eng_flags} flag{'s' if eng_flags != 1 else ''}" if eng_flags > 0 else "Pass"
    eng_badge_color = "flagged" if eng_flags > 0 else "pass"

    # ── Doubts Engagement sub-check
    de = eng_sub.get("doubts_engagement", {})
    de_addressed = de.get("addressed_count", 0)
    de_total = de.get("total_student_questions", 0)
    de_detail = f"Addressed {de_addressed} of {de_total} student question{'s' if de_total != 1 else ''}" if de_total > 0 else ""
    eng_subs_html = sub_check_row("Doubts engagement", de.get("status", "pass"), de.get("detail", ""))

    # ── Missed doubts list (nested under doubts_engagement)
    eng_missed = de.get("missed_doubts", [])
    eng_missed_html = ""
    if eng_missed:
        md_list_html = ""
        for md in eng_missed:
            md_list_html += textwrap.dedent(f"""
            <div style="background:#2C2C2E;border-radius:8px;padding:10px 14px;margin-bottom:8px">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                {source_tag(md.get('source','chat'))}
                <span style="color:#FF9F0A;font-size:12px;font-weight:600">{md.get('timestamp','')}</span>
              </div>
              <div style="color:#E5E5EA;font-size:13px;margin-bottom:4px">"{md.get('question','')}"</div>
              <div style="color:#8E8E93;font-size:12px">{md.get('reason','')}</div>
            </div>""").strip()
        eng_missed_html = f"<div style='margin-top:12px;margin-bottom:4px'><div style='color:#8E8E93;font-size:11px;text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px'>Missed Doubts</div>{md_list_html}</div>"

    # ── In-class engagement + Class elongation sub-check rows
    ince = eng_sub.get("in_class_engagement", {})
    class_elong = eng_sub.get("class_elongation", {})
    eng_subs_html += sub_check_row("In-class engagement", ince.get("status", "pass"), ince.get("detail", ""))
    eng_subs_html += sub_check_row("Class elongation", class_elong.get("status", "pass"), class_elong.get("detail", ""))

    eng_ev_html = "".join(evidence_item(e) for e in eng.get("evidence", []))
    eng_html = card_header("💬", "Engagement",
                            f"{eng.get('score',0):.1f}/10", eng_badge_text, eng_badge_color)
    evidence_html = f"<div style='margin-top:14px'><div style='color:#8E8E93;font-size:11px;text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px'>Evidence</div>{eng_ev_html}</div>" if eng_ev_html else ""
    eng_body_extras = eng_missed_html + evidence_html
    eng_html += textwrap.dedent(f"""
    <div style="margin-top:14px">
      <p style="color:#8E8E93;font-size:13px;line-height:1.6;margin-bottom:14px">{eng.get('summary','')}</p>
      {eng_subs_html}
      {eng_body_extras}
    </div>""").strip()

    # ── Content Evaluation
    tm_status = tm.get("status", "pass")
    tm_badge_color = "pass" if tm_status == "pass" else ("warn" if tm_status == "warn" else "fail")
    tm_ev_html = "".join(evidence_item(e) for e in tm.get("evidence", []))
    tm_strengths = "".join(f'<div style="color:#32D74B;font-size:12px;margin-bottom:4px">✓ {s}</div>' for s in tm.get("strengths", []))
    tm_gaps = "".join(f'<div style="color:#FF9F0A;font-size:12px;margin-bottom:4px">⚠ {g}</div>' for g in tm.get("gaps", []))

    cc_status = cc.get("status", "pass")
    cc_badge_color = "pass" if cc_status == "pass" else ("warn" if cc_status == "warn" else "fail")
    cc_topics = "".join(f'<span style="background:#1A3A25;color:#32D74B;padding:3px 8px;border-radius:4px;font-size:12px;margin:2px;display:inline-block">✓ {t}</span>' for t in cc.get("topics_covered", []))
    cc_brief = "".join(f'<span style="background:#3A2800;color:#FF9F0A;padding:3px 8px;border-radius:4px;font-size:12px;margin:2px;display:inline-block">~ {t}</span>' for t in cc.get("topics_brief", []))
    cc_skip = "".join(f'<span style="background:#3A0A0A;color:#FF453A;padding:3px 8px;border-radius:4px;font-size:12px;margin:2px;display:inline-block">✗ {t}</span>' for t in cc.get("topics_skipped", []))
    cc_ev_html = "".join(evidence_item(e) for e in cc.get("evidence", []))

    ce_badge_color = "pass" if tm_status == "pass" and cc_status == "pass" else "warn"
    ce_badge_text = "Pass" if ce_badge_color == "pass" else "Needs Review"

    ce_html = card_header("📚", "Content Evaluation", f"{ce.get('score',0):.1f}/10", ce_badge_text, ce_badge_color)
    ce_html += textwrap.dedent(f"""
    <div style="margin-top:14px">
      <div style="margin-bottom: 16px; border-bottom: 1px solid #2C2C2E; padding-bottom: 16px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
              <span style="color:#E5E5EA;font-size:14px;font-weight:600">Teaching Methodology</span>
              {badge(tm_status.title(), tm_badge_color)}
          </div>
          <p style="color:#8E8E93;font-size:13px;line-height:1.6;margin-bottom:10px">{tm.get('summary','')}</p>
          <div style="margin-bottom:10px">{tm_strengths}{tm_gaps}</div>
          {"<div style='color:#8E8E93;font-size:11px;text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px'>Evidence</div>" + tm_ev_html if tm_ev_html else ""}
      </div>
      <div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
              <span style="color:#E5E5EA;font-size:14px;font-weight:600">Content Coverage</span>
              {badge(cc_status.title(), cc_badge_color)}
          </div>
          <p style="color:#8E8E93;font-size:13px;line-height:1.6;margin-bottom:10px">{cc.get('summary','')}</p>
          <div style="margin-bottom:10px">{cc_topics}{cc_brief}{cc_skip}</div>
          {"<div style='color:#8E8E93;font-size:11px;text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px'>Evidence</div>" + cc_ev_html if cc_ev_html else ""}
      </div>
    </div>""").strip()

    # ── Session Quality
    cam_status = cam.get("status", "needs_video").replace("_", " ")
    ss_status = ss.get("status", "unverifiable").replace("_", " ")
    av_status = av.get("status", "pass").replace("_", " ")

    sq_subs_html = ""
    sq_subs_html += sub_check_row("Camera ON/OFF", cam_status, cam.get("note", ""))
    sq_subs_html += sub_check_row("Screen sharing internal document", ss_status, ss.get("note", ""))
    sq_subs_html += sub_check_row("Audio & video quality", av_status, av.get("note", ""))

    sq_issues = (cam_status.lower() == "flagged") + (ss_status.lower() == "warn") + (av_status.lower() in ["flagged", "warn"])
    sq_badge_color = "flagged" if sq_issues > 0 else "pass"
    sq_badge_text = f"{sq_issues} issue{'s' if sq_issues != 1 else ''}" if sq_issues > 0 else "Pass"

    sq_html = card_header("⚙️", "Session Quality", f"{sq.get('score',0):.1f}/10", sq_badge_text, sq_badge_color)
    sq_html += textwrap.dedent(f"""
    <div style="margin-top:14px">
      {sq_subs_html}
    </div>""").strip()

    # ── Escalation Evaluation
    lr_status = lr.get("status", "no_input")
    lr_badge = "No low rating input" if lr_status == "no_input" else "Triggered"
    lr_color = "gray" if lr_status == "no_input" else "flagged"
    lr_claims = lr.get("claims", [])
    lr_claims_html = ""
    if lr_claims:
        claims_list = ""
        for claim in lr_claims:
            try:
                rating = int(claim.get("rating", 0))
            except (ValueError, TypeError):
                rating = 0
            stars = "★" * rating + "☆" * (5 - rating)
            feedback = claim.get("feedback", "")
            verdict = claim.get("verdict", "invalid")
            reasoning = claim.get("reasoning", "")
            v_color = "flagged" if verdict == "valid" else "pass"
            v_text = "Valid" if verdict == "valid" else "Invalid"
            claims_list += textwrap.dedent(f"""
            <div style="background:#2C2C2E;border-radius:8px;padding:12px 14px;margin-bottom:8px">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                <span style="color:#FF9F0A;font-size:15px;letter-spacing:2px">{stars}</span>
                {badge(v_text, v_color)}
              </div>
              <div style="color:#E5E5EA;font-size:13px;margin-bottom:6px">"{feedback}"</div>
              <div style="color:#8E8E93;font-size:12px">{reasoning}</div>
            </div>""").strip()
        lr_claims_html = f"<div style='margin-top:12px'><div style='color:#8E8E93;font-size:11px;text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px'>Student Feedback Claims</div>{claims_list}</div>"
    
    esc_html = card_header("⭐", "Escalation Evaluation", f"{esc.get('score',0):.1f}/10", lr_badge, lr_color)
    esc_html += f'<div style="margin-top:12px"><p style="color:#8E8E93;font-size:13px;line-height:1.6">{lr.get("note", "No low rating feedback provided.")}</p>{lr_claims_html}</div>'

    html = (
        header + score_card +
        section_card(ib_html) +
        section_card(eng_html) +
        section_card(ce_html) +
        section_card(sq_html) +
        section_card(esc_html)
    )

    return html


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🎯 Live Class Audit")
    st.markdown("---")

    st.markdown("### Session Files")
    vtt_file = st.file_uploader("Transcript (.vtt)", type=["vtt"])
    chat_file = st.file_uploader("Chat (.txt)", type=["txt"])

    use_demo = st.checkbox("Use demo session files", value=True,
                            help="Uses the Recording.transcript.vtt and Chat.txt from this folder")


    st.markdown("### Model Configuration")
    model_choice = st.selectbox(
        "LLM Model",
        ["GPT-4.1 mini", "Gemini 3.1 Flash","GPT-4.1"],
        index=0,
        help="Select the model to perform the audit analysis."
    )
    _model_map = {
        "GPT-4.1 mini": "gpt-4.1-mini",
        "Gemini 3.1 Flash": "gemini-3.1-flash-lite-preview",
        "GPT-4.1": "gpt-4.1",
    }
    selected_model = _model_map[model_choice]

    with st.expander("🔑 API Keys & Credentials", expanded=False):
        st.caption("Keys are resolved in order: input below → Streamlit Secrets → .env file")
        _openai_env = os.getenv("OPENAI_API_KEY", "") or ""
        _gemini_env = os.getenv("GEMINI_API_KEY", "") or ""
        _sa_local   = os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "service_account.json"))
        try:
            _openai_env = _openai_env or st.secrets.get("OPENAI_API_KEY", "")
            _gemini_env = _gemini_env or st.secrets.get("GEMINI_API_KEY", "")
            _sa_secrets = bool(st.secrets.get("gcp_service_account", None))
        except Exception:
            _sa_secrets = False
        st.caption(f"OpenAI: {'✅ found in env/secrets' if _openai_env else '❌ not set'}")
        st.caption(f"Gemini: {'✅ found in env/secrets' if _gemini_env else '❌ not set'}")
        st.caption(f"Service Account: {'✅ found in secrets' if _sa_secrets else ('✅ local file found' if _sa_local else '❌ not set — upload below')}")
        api_key_val = st.text_input(
            "Paste API Key (overrides env/secrets)",
            value="",
            type="password",
            placeholder="sk-... or AIza...",
            help="Paste your OpenAI or Gemini key here. This takes priority over all other sources."
        )

        st.markdown("**Service Account JSON**")
        sa_file = st.file_uploader(
            "Upload service_account.json",
            type=["json"],
            help="Upload your Google Cloud service account JSON. Required for curriculum/syllabus lookup."
        )
        if sa_file is not None:
            try:
                st.session_state['credentials_dict'] = json.loads(sa_file.read().decode("utf-8"))
                st.success("✅ Service account loaded.")
            except Exception as e:
                st.error(f"❌ Failed to parse service account file: {e}")

        if 'credentials_dict' in st.session_state:
            st.caption("✅ Service account active from this session.")


    st.markdown("### Session Name")
    session_name_val = st.text_area(
        "Session Name",
        value="",
        height=50,
    )

    st.markdown("### Escalation Feedback")

    _sample_csv = "S.No,User Id,Feedback,Rating\n1,23123,Teaching is not good,2\n2,31242,Abusing !!,1\n"
    st.download_button(
        label="⬇ Download Sample CSV",
        data=_sample_csv,
        file_name="escalation_feedback_sample.csv",
        mime="text/csv",
        use_container_width=True,
    )

    escalation_file = st.file_uploader(
        "Low Rating Feedback (CSV / Excel)",
        type=["csv", "xlsx"],
        help="Upload a CSV or Excel file with columns: S.No, User Id, Feedback, Rating"
    )

    escalation_feedback_val = ""
    if escalation_file is not None:
        try:
            if escalation_file.name.endswith(".xlsx"):
                df_esc = pd.read_excel(io.BytesIO(escalation_file.read()))
            else:
                df_esc = pd.read_csv(io.StringIO(escalation_file.read().decode("utf-8")))

            # Normalize column names: strip whitespace, lowercase
            df_esc.columns = [c.strip() for c in df_esc.columns]

            # Resolve "User Id" column flexibly
            uid_col = next(
                (c for c in df_esc.columns if c.lower().replace(" ", "") in ["userid", "uid", "id"]),
                None
            )
            fb_col = next(
                (c for c in df_esc.columns if c.lower() in ["feedback", "feedack", "comment", "comments"]),
                None
            )

            if uid_col and fb_col:
                lines = [
                    f"{str(row[uid_col]).strip()}: {str(row[fb_col]).strip()}"
                    for _, row in df_esc.iterrows()
                    if str(row[fb_col]).strip() and str(row[fb_col]).strip().lower() != "nan"
                ]
                escalation_feedback_val = "\n".join(lines)
                st.success(f"✅ {len(lines)} feedback row{'s' if len(lines) != 1 else ''} loaded.")
            else:
                st.error("❌ Could not find 'User Id' or 'Feedback' columns in the uploaded file.")
        except Exception as e:
            st.error(f"❌ Failed to parse escalation file: {e}")

    run_btn = st.button("🚀 Run Audit")

# ── Main Area ─────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="padding: 10px 0 24px">
  <h1 style="color:#fff;font-size:24px;font-weight:700;margin:0">Live Class Audit System</h1>
  <p style="color:#8E8E93;margin:4px 0 0;font-size:14px">Powered by {model_choice} · Coding Ninjas</p>
</div>
""", unsafe_allow_html=True)

if run_btn:
    # Load files
    vtt_content = None
    chat_content = None

    base_dir = os.path.dirname(os.path.abspath(__file__))

    if use_demo:
        vtt_path = os.path.join(base_dir, "Recording.transcript.vtt")
        chat_path = os.path.join(base_dir, "Chat.txt")
        if os.path.exists(vtt_path) and os.path.exists(chat_path):
            with open(vtt_path, 'r', encoding='utf-8') as f:
                vtt_content = f.read()
            with open(chat_path, 'r', encoding='utf-8') as f:
                chat_content = f.read()
        else:
            st.error("Demo files not found. Please upload files manually.")
    else:
        if vtt_file:
            vtt_content = vtt_file.read().decode('utf-8')
        if chat_file:
            chat_content = chat_file.read().decode('utf-8')

    if not vtt_content or not chat_content:
        st.error("Please provide both the VTT transcript and Chat file.")
    else:
        with st.spinner("🔍 Parsing transcript and chat..."):
            turns = parse_vtt(vtt_content)
            messages = parse_chat(chat_content)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Speaker Turns", len(turns))
        col2.metric("Chat Messages", len(messages))
        col3.metric("Instructor Turns", sum(1 for t in turns if t.get('role') == 'instructor'))
        cost_placeholder = col4.empty()
        cost_placeholder.metric("Audit Cost", "—")

        st.markdown("---")

        with st.spinner(f"🤖 Analyzing session with {model_choice}..."):
            from datetime import date as _date
            meta = {
                "session_title": "Audit Report",
                "date": _date.today().strftime("%d %b %Y"),
                "session_name": session_name_val or "—",
            }
            try:
                result = analyze_session(
                    turns,
                    messages,
                    session_name_val,
                    escalation_feedback=escalation_feedback_val,
                    model=selected_model,
                    api_key=api_key_val,
                    credentials_dict=st.session_state.get('credentials_dict'),
                )
                st.session_state['audit_result'] = result
                st.session_state['audit_meta'] = meta
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                result = None

        if result:
            cost_inr = result.get('_cost_inr', 0)
            cost_usd = result.get('_cost_usd', 0)
            tok_p    = result.get('_tokens_prompt', 0)
            tok_c    = result.get('_tokens_completion', 0)

            # Update cost placeholder now that we have the real value
            cost_placeholder.metric("Audit Cost", f"₹{cost_inr:.2f}")
            st.caption(
                f"🔢 Tokens — prompt: {tok_p:,} | completion: {tok_c:,} | "
                f"total: {tok_p + tok_c:,} | ${cost_usd:.5f}"
            )

            report_html = render_report(result, meta)
            st.markdown(report_html, unsafe_allow_html=True)

            # Download JSON
            st.download_button(
                "⬇ Download JSON Report",
                data=json.dumps(result, indent=2),
                file_name="audit_report.json",
                mime="application/json",
            )

elif 'audit_result' in st.session_state:
    report_html = render_report(st.session_state['audit_result'], st.session_state['audit_meta'])
    st.markdown(report_html, unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="background:#1C1C1E;border-radius:14px;padding:60px;text-align:center;margin-top:20px">
      <div style="font-size:48px;margin-bottom:16px">🎯</div>
      <h3 style="color:#fff;margin:0 0 8px;font-weight:600">Ready to Audit</h3>
      <p style="color:#8E8E93;margin:0;font-size:14px">
        Configure session details in the sidebar and click <strong style="color:#0A84FF">Run Audit</strong> to begin.
      </p>
    </div>
    """, unsafe_allow_html=True)
