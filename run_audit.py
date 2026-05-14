import json
from analyzer import analyze_session
from parser import parse_vtt, parse_chat

# Read inputs
with open("Recording.transcript.vtt", "r", encoding="utf-8") as f:
    vtt_text = f.read()
with open("Chat.txt", "r", encoding="utf-8") as f:
    chat_text = f.read()

turns = parse_vtt(vtt_text)
messages = parse_chat(chat_text)

syllabus = ""

print("Running audit...")
res = analyze_session(turns, messages, syllabus, escalation_feedback="He literally abused !!!", model="gpt-4.1-mini")
print("Done. Check chat.log.")
