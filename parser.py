import re

# All instructor Zoom accounts use this display name
INSTRUCTOR_NAME = "Coding Ninjas"


def time_to_seconds(time_str):
    time_str = time_str.strip().split(' ')[0].replace(',', '.')
    parts = time_str.split(':')
    try:
        h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
        return h * 3600 + m * 60 + s
    except:
        return 0


def seconds_to_hms(seconds):
    s = int(seconds)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def parse_vtt(content):
    """Parse WebVTT file → list of merged speaker turns."""
    lines = content.strip().split('\n')
    cues = []
    i = 0

    # Skip to first timestamp
    while i < len(lines) and '-->' not in lines[i]:
        i += 1

    while i < len(lines):
        line = lines[i].strip()

        if '-->' in line:
            parts = line.split('-->')
            start_raw = parts[0].strip()
            i += 1

            # Collect text until blank line or digit-only line
            text_parts = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().isdigit():
                text_parts.append(lines[i].strip())
                i += 1

            text = ' '.join(text_parts)
            if not text:
                continue

            # Extract speaker (text before first colon)
            if ':' in text:
                colon_idx = text.index(':')
                speaker = text[:colon_idx].strip()
                utterance = text[colon_idx + 1:].strip()
            else:
                speaker = 'Unknown'
                utterance = text

            if utterance:
                cues.append({
                    'speaker': speaker,
                    'role': 'instructor' if speaker == INSTRUCTOR_NAME else 'student',
                    'text': utterance,
                    'start_time': start_raw,
                    'start_seconds': time_to_seconds(start_raw),
                })
        else:
            i += 1

    # Merge consecutive same-speaker cues into turns
    turns = []
    if not cues:
        return turns

    current = dict(cues[0])
    for cue in cues[1:]:
        if cue['speaker'] == current['speaker']:
            current['text'] += ' ' + cue['text']
        else:
            turns.append(current)
            current = dict(cue)
    turns.append(current)

    return turns


def parse_chat(content):
    """Parse Zoom chat TXT → list of messages."""
    lines = content.strip().split('\n')
    messages = []
    current = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = line.split('\t')
        if len(parts) >= 3:
            ts = parts[0].strip()
            # Validate HH:MM:SS
            ts_parts = ts.split(':')
            if len(ts_parts) == 3:
                try:
                    h, m, s = int(ts_parts[0]), int(ts_parts[1]), int(ts_parts[2])
                    seconds = h * 3600 + m * 60 + s
                    name = parts[1].strip().rstrip(':')
                    msg = '\t'.join(parts[2:]).strip()
                    if current:
                        messages.append(current)
                    current = {
                        'timestamp': ts,
                        'seconds': seconds,
                        'name': name,
                        'message': msg,
                    }
                    continue
                except:
                    pass

        # Continuation line
        if current:
            current['message'] += ' ' + line

    if current:
        messages.append(current)

    return messages


def format_turns_for_prompt(turns):
    """Format all speaker turns for the LLM prompt.
    No character cap — gpt-4.1-mini supports 1M token context;
    a full 2h session is ~17k tokens, well within limits.
    """
    lines = []
    for t in turns:
        ts = t['start_time'].split('.')[0]
        role_tag = '[INSTRUCTOR]' if t.get('role') == 'instructor' else '[STUDENT]'
        lines.append(f"[{ts}] {role_tag} {t['speaker']}: {t['text']}")
    return '\n'.join(lines)


def format_chat_for_prompt(messages):
    lines = []
    for m in messages:
        lines.append(f"[{m['timestamp']}] {m['name']}: {m['message']}")
    return '\n'.join(lines)


def compute_doubt_windows(chat_messages, turns, window_seconds=300):
    """
    Pre-compute the 5-minute instructor response window for every student
    chat message. Code handles the mechanical window check; the LLM uses this
    data to make only the semantic judgment (is this a real doubt?).

    Returns a list of dicts, one per student message:
      - timestamp, student, message          : original message data
      - instructor_responded (bool)          : did instructor speak within 5 min?
      - instructor_context  (list[str])      : up to 3 instructor turn snippets
                                               from that window (first 120 chars each)
    """
    instructor_turns = [t for t in turns if t.get('role') == 'instructor']

    enriched = []
    for msg in chat_messages:
        if msg['name'] == INSTRUCTOR_NAME:
            continue                           # skip instructor's own chat messages

        window_end = msg['seconds'] + window_seconds

        # Collect instructor turns that fall in the 5-minute response window
        response_snippets = [
            t['text'][:120]
            for t in instructor_turns
            if msg['seconds'] <= t['start_seconds'] <= window_end
        ]

        enriched.append({
            'timestamp':             msg['timestamp'],
            'student':               msg['name'],
            'message':               msg['message'],
            'instructor_responded':  len(response_snippets) > 0,
            'instructor_context':    response_snippets[:3],   # max 3 snippets
        })

    return enriched
