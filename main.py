#!/usr/bin/env python3
"""
English Shorts autopilot
------------------------
idea -> script -> human-sounding voice -> stock footage + word-by-word captions
-> vertical MP4 -> YouTube Short.

Run:
    python main.py                 # make a video and upload it
    python main.py --no-upload     # make a video only (output/short_YYYY-MM-DD.mp4)
    python main.py --offline-test  # no internet needed: checks ffmpeg + captions work
"""
import argparse
import asyncio
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
WORK = OUT / "work"
HISTORY_FILE = ROOT / "history.json"
MUSIC_DIR = ROOT / "assets"  # optional: drop a royalty-free music.mp3 in here

# ----------------------------------------------------------------- settings
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
PEXELS_KEY = os.getenv("PEXELS_API_KEY", "")
VOICE = os.getenv("VOICE", "en-US-AndrewNeural")
VOICE_RATE = os.getenv("VOICE_RATE", "+6%")
VOICE_PITCH = os.getenv("VOICE_PITCH", "+0Hz")
YT_PRIVACY = os.getenv("YT_PRIVACY", "private")  # private | unlisted | public
GREETING = os.getenv("GREETING", "").strip()  # optional spoken greeting before the hook
CTA = os.getenv("CTA", "Follow for one tip every day.").strip()  # "" = no spoken CTA
FONT = os.getenv("CAPTION_FONT", "Montserrat")
FPS = 30
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

CATEGORIES = [
    "a common mistake learners make (wrong version vs right version)",
    "a boring everyday word to replace with a stronger, more natural one",
    "a phrasal verb everyone uses but learners rarely get taught",
    "an everyday idiom and what it really means (only mention its origin if you are 100% sure)",
    "two words people mix up (pick a less obvious pair than affect/effect)",
    "a pronunciation trap in a very common word",
    "a polite way to say something that sounds rude when said bluntly",
    "what natives actually say instead of the textbook phrase",
    "a quick 'spot the mistake' challenge",
    "a small grammar rule that is easier than people think",
    "a casual expression and when NOT to use it",
    "phrases that sound confident at work or in a job interview",
    "a word learners misuse because of translation (false friend)",
    "a tiny word that changes the meaning (like 'a few' vs 'few')",
]

HOOK_STYLES = [
    "'Stop saying X, say this instead'",
    "challenge a belief ('your teacher never told you this about ...')",
    "curiosity gap: tease the answer, then hold it back for a few seconds",
    "quiz: 'Which one is correct?' and a beat before the answer",
    "social stakes: 'this one word makes you sound like a beginner'",
    "a real situation: 'Your boss says X. What do you reply?'",
    "a direct question the viewer cannot help answering in their head",
    "a bold contrarian line ('you don't need more vocabulary, you need this')",
    "a tiny list teaser ('two words that ...') that you actually deliver on",
]

BANNED = [
    "dive in", "delve", "game-changer", "game changer", "unlock", "elevate",
    "in today's video", "welcome back", "let's get started", "buckle up",
    "tapestry", "in this video", "journey", "ultimate guide",
]

SAMPLE_LESSON = {
    "topic": "I am agree vs I agree",
    "title": "Stop saying \"I am agree\" (say this instead)",
    "description": "Agree is a verb, so you never need \"am\". Say \"I agree\" and you're done.",
    "hashtags": ["#learnenglish", "#english", "#englishtips", "#shorts"],
    "segments": [
        {"say": "Stop saying \"I am agree.\" Seriously.", "visual": "man shaking head", "card": "I am agree", "card_kind": "wrong"},
        {"say": "It feels natural in your head, but it's a tiny mistake.", "visual": "student thinking laptop", "card": "", "card_kind": "neutral"},
        {"say": "Agree is a verb. Not an adjective. So you don't need \"am\".", "visual": "teacher writing board", "card": "agree = verb", "card_kind": "neutral"},
        {"say": "Just say... \"I agree.\" That's it.", "visual": "friends talking cafe", "card": "I agree", "card_kind": "right"},
        {"say": "Want to disagree? Same rule. \"I disagree.\" No \"am\", no stress.", "visual": "woman smiling phone", "card": "I disagree", "card_kind": "right"},
        {"say": "Quick test. Your friend says pizza beats burgers. What do you reply? Tell me in the comments.", "visual": "pizza burger table", "card": "", "card_kind": "neutral"},
        {"say": "Follow for one tip every day.", "visual": "city street evening", "card": "", "card_kind": "neutral"},
    ],
}


def log(*a):
    print(*a, flush=True)


def run(cmd, cwd=None):
    p = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd))[:300]}\n{p.stderr[-1500:]}")
    return p.stdout


def q(t):
    """snap a time to the video frame grid"""
    return round(t * FPS) / FPS


# ------------------------------------------------------------------ history
def load_history():
    try:
        return json.loads(HISTORY_FILE.read_text())
    except Exception:
        return []


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history[-300:], indent=2, ensure_ascii=False))


# ------------------------------------------------------------------- Gemini
_models = None


def gemini_models():
    """Pick the newest stable 'flash' model your key can use (names change over time)."""
    global _models
    if _models:
        return _models
    forced = os.getenv("GEMINI_MODEL", "").strip()
    if forced:
        _models = [forced]
        return _models
    found = []
    try:
        r = requests.get(f"{GEMINI_BASE}/models", params={"key": GEMINI_KEY, "pageSize": 200}, timeout=30)
        r.raise_for_status()
        for m in r.json().get("models", []):
            name = m["name"].split("/")[-1]
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if "flash" not in name:
                continue
            if re.search(r"lite|image|tts|live|audio|thinking|exp|preview|vision|robotics|computer|learnlm|gemma", name):
                continue
            found.append(name)
    except Exception as e:
        log("could not list Gemini models:", e)

    def ver(n):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0.0

    found.sort(key=ver, reverse=True)
    ordered = [n for n in found if n.endswith("latest")] + [n for n in found if not n.endswith("latest")]
    _models = ordered or ["gemini-2.5-flash", "gemini-2.0-flash"]
    log("Gemini models to try:", _models[:3])
    return _models


def gemini_json(prompt, temperature=1.0):
    last = None
    for model in gemini_models():
        for attempt in range(3):
            try:
                r = requests.post(
                    f"{GEMINI_BASE}/models/{model}:generateContent",
                    params={"key": GEMINI_KEY},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
                    },
                    timeout=120,
                )
                if r.status_code in (429, 500, 503):
                    last = f"{model}: HTTP {r.status_code}"
                    time.sleep(15 * (attempt + 1))
                    continue
                if r.status_code in (400, 403, 404):
                    last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                    break  # try the next model
                r.raise_for_status()
                parts = r.json()["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                data = json.loads(text)
                if isinstance(data, list):
                    data = data[0]
                return data
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last = f"{model}: bad response ({e})"
                time.sleep(3)
    raise RuntimeError(f"Gemini failed: {last}")


def build_prompt(category, hook_style, recent):
    recent_txt = "\n".join(f"- {t}" for t in recent[-60:]) or "- (none yet)"
    greet = (
        f'Begin the very first sentence with exactly: "{GREETING}" and then go straight into the hook.'
        if GREETING
        else "No greeting, no intro, no channel name. The very first words ARE the hook."
    )
    cta = (
        f'The last segment is only this short call to action: "{CTA}"'
        if CTA
        else "End on the comment question. No call to action."
    )
    shape = {
        "topic": "3-6 word label of the lesson, used to avoid repeats",
        "title": "YouTube title, max 60 characters, makes a learner curious, no lies",
        "description": "1-2 plain sentences summarising the tip",
        "hashtags": ["#learnenglish", "#english", "#englishtips", "#shorts"],
        "segments": [
            {"say": "spoken line(s)", "visual": "2-4 word stock video search", "card": "optional big on-screen text or empty string", "card_kind": "wrong | right | neutral"}
        ],
    }
    return f"""You write spoken scripts for a YouTube Shorts channel that teaches English to learners around the world (roughly B1-B2 level).

LESSON TYPE TODAY: {category}
HOOK STYLE TO ADAPT (do not copy it word for word): {hook_style}

Never repeat or closely resemble these earlier topics:
{recent_txt}

HOW IT MUST SOUND
Write the way a warm, funny friend explains something over coffee, not the way a teacher or textbook talks. Use contractions (you're, it's, don't). Mix very short sentences with slightly longer ones. It's fine to start with "And", "But" or "Look,". Plain everyday words only. One idea per sentence. Imagine reading every line out loud; if it sounds written instead of spoken, rewrite it.
Never use: "dive in", "delve", "game-changer", "unlock", "elevate", "journey", "in today's video", "welcome back", "let's get started", "buckle up". No emojis, hashtags, stage directions or sound effects inside spoken lines. Write numbers as words.

THE HOOK (segment 1)
- 6 to 14 words. It must stop a learner from scrolling within two seconds: challenge something they believe, name a mistake they probably make, or ask a question they can't help answering in their head.
- Style examples only, do not reuse: "Stop saying 'I am agree.' Seriously." / "This one word makes you sound like a beginner." / "Your teacher never told you this about 'actually'."
- {greet}
- No clickbait lies. Never invent statistics, studies or personal stories.

SHAPE: hook, then the problem (one beat of tension), then the reveal (the correct answer), then one real-life example sentence someone would actually say, then an optional quick memory trick, then the ending. The ending asks one tiny question the viewer can answer in the comments. {cta}

ACCURACY
Teach only things that are definitely correct and natural in standard English today. If American and British usage differ, say so in one short sentence.

LENGTH: 6 to 8 segments, 85 to 110 spoken words in total.

VISUALS: for each segment give "visual", a 2 to 4 word search phrase for stock video that a camera could really film (for example "woman laughing cafe", "man typing laptop night", "friends walking city"). Never abstract ideas, never text.
CARD: optional big on-screen text for the key phrase of that segment, max 5 words, otherwise "". card_kind is "wrong" for an incorrect version, "right" for a correct version, "neutral" otherwise. Use cards on 3 to 5 segments.

Return only JSON in exactly this shape:
{json.dumps(shape, indent=2)}"""


def clean_text(s):
    s = str(s or "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", ", ").replace("–", "-").replace("…", "...")
    s = re.sub(r"[*_#`]", "", s)
    s = re.sub(r"[^\x20-\x7E]", "", s)  # drop emojis / odd characters
    return re.sub(r"\s+", " ", s).strip()


def validate(lesson):
    segs = lesson.get("segments")
    if not isinstance(segs, list) or not 5 <= len(segs) <= 9:
        raise ValueError("need 5-9 segments")
    clean = []
    for s in segs:
        say = clean_text(s.get("say"))
        if len(say.split()) < 2:
            raise ValueError("a segment is too short")
        if not re.search(r"[.!?\"]$", say):
            say += "."
        kind = s.get("card_kind") if s.get("card_kind") in ("wrong", "right", "neutral") else "neutral"
        clean.append({
            "say": say,
            "visual": clean_text(s.get("visual")) or "city street",
            "card": clean_text(s.get("card"))[:40],
            "card_kind": kind,
        })
    words = sum(len(s["say"].split()) for s in clean)
    if not 60 <= words <= 135:
        raise ValueError(f"{words} words is outside the 60-135 range")
    spoken = " ".join(s["say"] for s in clean).lower()
    for b in BANNED:
        if b in spoken:
            raise ValueError(f"contains robotic phrase: {b}")
    tags = [t if t.startswith("#") else "#" + t for t in map(clean_text, lesson.get("hashtags") or [])]
    tags = [t.replace(" ", "") for t in tags if len(t) > 1][:6]
    if "#shorts" not in [t.lower() for t in tags]:
        tags.append("#Shorts")
    return {
        "topic": clean_text(lesson.get("topic")) or clean_text(lesson.get("title")),
        "title": clean_text(lesson.get("title"))[:95] or "English tip",
        "description": clean_text(lesson.get("description")),
        "hashtags": tags,
        "segments": clean,
    }


def verify_lesson(lesson):
    lines = []
    for s in lesson["segments"]:
        lines.append(s["say"] + (f'   [on screen: {s["card"]} ({s["card_kind"]})]' if s["card"] else ""))
    prompt = (
        "You are a strict, experienced English teacher (CELTA/DELTA level). Review this short lesson script for accuracy.\n"
        "Check that every rule stated is true, every 'wrong' example really is wrong or unnatural, every 'right' example is natural, "
        "nothing is misleading, and nothing is an invented fact.\n"
        'Reply as JSON: {"ok": true or false, "issues": "short explanation, empty if ok"}\n\nLESSON:\n' + "\n".join(lines)
    )
    try:
        res = gemini_json(prompt, temperature=0.2)
        return bool(res.get("ok")), str(res.get("issues", ""))
    except Exception as e:  # if the checker itself is down, don't block the pipeline
        log("verification skipped:", e)
        return True, ""


def make_lesson(history):
    recent_cats = [h.get("category") for h in history[-4:]]
    category = random.choice([c for c in CATEGORIES if c not in recent_cats] or CATEGORIES)
    hook_style = random.choice(HOOK_STYLES)
    recent_topics = [h.get("topic", "") for h in history]
    log(f"lesson type: {category}\nhook style: {hook_style}")
    last_err = None
    for attempt in range(1, 6):
        try:
            lesson = validate(gemini_json(build_prompt(category, hook_style, recent_topics)))
            ok, issues = verify_lesson(lesson)
            if not ok:
                raise ValueError(f"teacher check failed: {issues}")
            lesson["category"] = category
            return lesson
        except Exception as e:
            last_err = e
            log(f"attempt {attempt} rejected: {e}")
    raise RuntimeError(f"could not get a good lesson: {last_err}")


# ---------------------------------------------------------------- voice (TTS)
async def _synth(text, voice, out_path):
    import edge_tts

    try:
        comm = edge_tts.Communicate(text, voice, rate=VOICE_RATE, pitch=VOICE_PITCH, boundary="WordBoundary")
    except TypeError:  # older edge-tts versions only send word boundaries by default
        comm = edge_tts.Communicate(text, voice, rate=VOICE_RATE, pitch=VOICE_PITCH)
    words = []
    with open(out_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append((chunk["text"], start, start + chunk["duration"] / 1e7))
    if os.path.getsize(out_path) < 2000:
        raise RuntimeError("TTS returned no audio")
    return words


def tts(text, out_path):
    voices = [VOICE] + [v for v in ("en-US-AriaNeural", "en-US-GuyNeural") if v != VOICE]
    last = None
    for voice in voices:
        for attempt in range(3):
            try:
                words = asyncio.run(_synth(text, voice, out_path))
                log(f"voice: {voice}, word timings: {len(words)}")
                return words
            except Exception as e:
                last = e
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"text-to-speech failed: {last}")


def probe_duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())


def align(tokens, wb, total):
    """(start, end) in seconds for every spoken word."""
    n = len(tokens)
    times = []
    if wb:
        for i in range(n):
            j = i if len(wb) == n else min(len(wb) - 1, int(i * len(wb) / n))
            times.append((wb[j][1], wb[j][2]))
    else:  # no word timings: spread words over the audio, weighted by length and punctuation pauses
        weights = []
        for t in tokens:
            w = len(re.sub(r"\W", "", t)) + 2
            if re.search(r"[.!?]\"?$", t):
                w += 5
            elif re.search(r"[,;:]\"?$", t) or t.endswith("..."):
                w += 2
            weights.append(w)
        scale = (total - 0.3) / sum(weights)
        t0 = 0.05
        for w in weights:
            times.append((t0, t0 + w * scale))
            t0 += w * scale
    fixed, prev = [], 0.0
    for s, e in times:  # keep it monotonic
        s = max(s, prev)
        e = max(e, s + 0.05)
        fixed.append((s, e))
        prev = s
    return fixed


# --------------------------------------------------------------- footage
def pexels_pick(query, used):
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_KEY},
        params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 15},
        timeout=30,
    )
    r.raise_for_status()
    vids = [v for v in r.json().get("videos", []) if v["id"] not in used and v.get("duration", 0) >= 4]
    random.shuffle(vids)
    for v in vids:
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= (f.get("width") or 0)]
        files.sort(key=lambda f: abs((f.get("height") or 0) - 1920))
        if files:
            return v["id"], files[0]["link"]
    return None


def download(url, dest):
    with requests.get(url, stream=True, timeout=90) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


FALLBACK_QUERIES = ["people talking", "city street evening", "typing laptop", "coffee shop", "walking city", "reading book"]
GRADIENTS = [("0x0f2027", "0x2c5364"), ("0x41295a", "0x2f0743"), ("0x134e5e", "0x71b280"), ("0x232526", "0x414345"), ("0x1f4037", "0x99f2c8")]
CLIP_VF = (
    "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,"
    f"fps={FPS},eq=brightness=-0.07:saturation=1.08,format=yuv420p"
)
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]


def get_footage(query, used, dest):
    """download one stock clip for this query; returns True on success"""
    if not PEXELS_KEY:
        return False
    words = query.split()
    attempts = [query] + ([" ".join(words[-2:])] if len(words) > 2 else []) + random.sample(FALLBACK_QUERIES, 2)
    for qy in attempts:
        try:
            pick = pexels_pick(qy, used)
            if pick:
                used.add(pick[0])
                download(pick[1], dest)
                return True
        except Exception as e:
            log(f"pexels problem for '{qy}': {e}")
    return False


def make_clip(src, dur, out):
    if src:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", src, "-t", f"{dur:.4f}", "-vf", CLIP_VF, *X264, out])
    else:
        c0, c1 = random.choice(GRADIENTS)
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", f"gradients=s=1080x1920:r={FPS}:d={dur:.4f}:speed=0.04:c0={c0}:c1={c1}:nb_colors=2",
            "-vf", "format=yuv420p", *X264, out,
        ])


# --------------------------------------------------------------- captions
def ass_time(t):
    cs = int(round(max(0, t) * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def esc(t):
    return t.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


HL = r"{\c&H00E5FF&}"  # active word colour (yellow)
RS = r"{\c&HFFFFFF&}"
POP = r"{\fscx108\fscy108\t(0,90,\fscx100\fscy100)}"
CARD_COLORS = {"wrong": r"{\c&H4B4BFF&\s1}", "right": r"{\c&H78DC50&}", "neutral": r"{\c&HFFFFFF&}"}


def chunk_tokens(tokens, size=3):
    chunks, cur = [], []
    for i, t in enumerate(tokens):
        cur.append(i)
        if len(cur) >= size or re.search(r"[.!?,;:]\"?$", t):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(tokens, times, segs, seg_bounds, total):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT},88,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,2,70,70,560,1
Style: Card,{FONT},118,&H00FFFFFF,&H00FFFFFF,&H99000000,&H99000000,-1,0,0,0,100,100,0,0,3,26,0,8,80,80,330,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    chunks = chunk_tokens(tokens)
    for ci, chunk in enumerate(chunks):
        nxt_chunk_start = times[chunks[ci + 1][0]][0] if ci + 1 < len(chunks) else total
        for k, idx in enumerate(chunk):
            start = times[idx][0]
            if k + 1 < len(chunk):
                end = times[chunk[k + 1]][0]
            else:
                end = nxt_chunk_start if nxt_chunk_start - times[idx][1] < 0.5 else times[idx][1] + 0.2
            end = max(end, start + 0.08)
            parts = []
            for j in chunk:
                w = esc(tokens[j]).replace('"', "").rstrip(".,;:")
                parts.append(f"{HL}{w}{RS}" if j == idx else w)
            text = ("" if k else POP) + " ".join(parts)
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,{text}")
    for (a, b), s in zip(seg_bounds, segs):
        if s["card"]:
            body = f"{{\\fad(120,120)}}{CARD_COLORS[s['card_kind']]}{esc(s['card'])}"
            lines.append(f"Dialogue: 1,{ass_time(a + 0.1)},{ass_time(b)},Card,,0,0,0,,{body}")
    return head + "\n".join(lines) + "\n"


# ------------------------------------------------------------------ render
def render_final(total, out):
    music = next(iter(sorted(MUSIC_DIR.glob("music.*"))), None) if MUSIC_DIR.exists() else None
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", "video.mp4", "-i", "voice.mp3"]
    tail = "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100[a]"
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        fc = f"[1:a]apad=pad_dur=1[v];[2:a]volume=0.07[m];[v][m]amix=inputs=2:duration=first:normalize=0,{tail}"
    else:
        fc = f"[1:a]apad=pad_dur=1,{tail}"
    fc += ";[0:v]ass=captions.ass[vv]"
    cmd += [
        "-filter_complex", fc, "-map", "[vv]", "-map", "[a]", "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out,
    ]
    run(cmd, cwd=WORK)


# ----------------------------------------------------------------- YouTube
def upload_youtube(path, lesson):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    tags_line = " ".join(lesson["hashtags"])
    body = {
        "snippet": {
            "title": lesson["title"],
            "description": f"{lesson['description']}\n\n{tags_line}",
            "tags": [t.lstrip("#") for t in lesson["hashtags"]],
            "categoryId": "27",  # Education
        },
        "status": {"privacyStatus": YT_PRIVACY, "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(path), mimetype="video/mp4", chunksize=-1, resumable=True),
    )
    response, tries = None, 0
    while response is None:
        try:
            _, response = req.next_chunk()
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and tries < 5:
                tries += 1
                time.sleep(2 ** tries)
                continue
            raise
    return response["id"]


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true", help="make the video but don't upload it")
    ap.add_argument("--offline-test", action="store_true", help="no internet: sample lesson, fake audio, gradient background")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} is not installed")
    if not args.offline_test and not GEMINI_KEY:
        sys.exit("GEMINI_API_KEY is missing")

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    history = load_history()
    lesson = validate(SAMPLE_LESSON) if args.offline_test else make_lesson(history)
    segs = lesson["segments"]
    log("\nTITLE:", lesson["title"])
    for s in segs:
        log("  -", s["say"])

    text = " ".join(s["say"] for s in segs)
    tokens = text.split()
    voice_path = WORK / "voice.mp3"
    if args.offline_test:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=36",
             "-af", "volume=0.1", "-ar", "24000", "-ac", "1", voice_path])
        wb = []
    else:
        wb = tts(text, voice_path)
    audio_dur = probe_duration(voice_path)
    total = q(audio_dur + 0.6)
    times = align(tokens, wb, audio_dur)

    # which words belong to which segment -> time range of each segment
    starts, idx = [], 0
    for s in segs:
        starts.append(0.0 if not starts else q(times[idx][0]))
        idx += len(s["say"].split())
    bounds = [(starts[i], starts[i + 1] if i + 1 < len(starts) else total) for i in range(len(segs))]

    used, clip_files = set(), []
    for i, (s, (a, b)) in enumerate(zip(segs, bounds)):
        src = WORK / f"raw_{i}.mp4"
        got = False if args.offline_test else get_footage(s["visual"], used, src)
        clip = WORK / f"clip_{i:02d}.mp4"
        make_clip(src if got else None, max(b - a, 0.5), clip)
        clip_files.append(clip.name)
        log(f"clip {i + 1}/{len(segs)}: {'stock footage' if got else 'gradient'} ({b - a:.1f}s) - {s['visual']}")
    (WORK / "concat.txt").write_text("".join(f"file '{n}'\n" for n in clip_files))
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "video.mp4"], cwd=WORK)

    (WORK / "captions.ass").write_text(build_ass(tokens, times, segs, bounds, total))
    final = OUT / f"short_{date.today().isoformat()}.mp4"
    render_final(total, final)
    log(f"\nvideo ready: {final} ({probe_duration(final):.1f}s)")

    if args.offline_test:
        return
    if args.no_upload:
        log("--no-upload: skipping YouTube")
    elif not all(os.getenv(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
        log("YouTube secrets not set: skipping upload (video is saved in output/)")
    else:
        vid = upload_youtube(final, lesson)
        log(f"uploaded: https://youtube.com/shorts/{vid}  ({YT_PRIVACY})")

    history.append({"date": date.today().isoformat(), "topic": lesson["topic"], "title": lesson["title"], "category": lesson.get("category", "")})
    save_history(history)


if __name__ == "__main__":
    main()
