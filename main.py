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
import base64
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
PIXABAY_KEY = os.getenv("PIXABAY_API_KEY", "")
VOICE = os.getenv("VOICE", "en-US-AndrewMultilingualNeural")
VOICE_RATE = os.getenv("VOICE_RATE", "+3%")
VOICE_PITCH = os.getenv("VOICE_PITCH", "+0Hz")
YT_PRIVACY = os.getenv("YT_PRIVACY", "private")  # private | unlisted | public
GREETING = os.getenv("GREETING", "").strip()  # optional spoken greeting before the hook
# No spoken closing line or name in the video (branding comes from the channel itself).
CTA = ""
# How the voice should say the name. A respelling written as ONE word works best, e.g. "Elliooren".
SPOKEN_NAME = os.getenv("SPOKEN_NAME", "Elliooren").strip()
# Voice: "kokoro" = a newer, more natural open-source voice that runs on the GitHub server (male voices: am_michael,
# am_adam, am_fenrir, am_puck, bm_george, bm_lewis). "edge" = Microsoft's voice. Kokoro falls back to edge by itself.
VOICE_ENGINE = os.getenv("VOICE_ENGINE", "edge").strip().lower()  # gemini (most expressive) | kokoro | edge; each falls back to the next
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "am_michael").strip()
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))


def pick_font():
    """best installed heavy font: CAPTION_FONT if set, else Montserrat ExtraBold > Poppins ExtraBold > Inter > DejaVu"""
    forced = os.getenv("CAPTION_FONT", "").strip()
    for name in ([forced] if forced else []) + ["Montserrat ExtraBold", "Poppins ExtraBold", "Inter", "DejaVu Sans"]:
        try:
            fam = subprocess.run(["fc-match", "-f", "%{family}", name], capture_output=True, text=True).stdout.lower()
        except Exception:
            continue
        if name.split()[0].lower() in fam:
            return name
    return "DejaVu Sans"


FONT = pick_font()
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "Elliuuren English").strip()
CREATOR_NAME = os.getenv("CREATOR_NAME", "Elliuuren").strip()
# Subtitles: elegant serif (Playfair Display). Titles/cards: bold condensed display (Anton).
# Both are downloaded at run time; if that fails the run silently falls back to the font picked above.
CAP_FONT, CAP_BOLD, CAP_SIZE = FONT, "extrabold" not in FONT.lower(), 92
TITLE_FONT, TITLE_BOLD, TITLE_SCALE = FONT, "extrabold" not in FONT.lower(), 1.0
FONTS_DIR = OUT / "fonts"
FONT_URLS = ("https://raw.githubusercontent.com/google/fonts/main/", "https://github.com/google/fonts/raw/main/")
FONT_FILES = {
    "caption": ["ofl/playfairdisplay/static/PlayfairDisplay-SemiBold.ttf", "ofl/playfairdisplay/static/PlayfairDisplay-Bold.ttf",
                "ofl/playfairdisplay/PlayfairDisplay-Bold.ttf", "ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf"],
    "title": ["ofl/anton/Anton-Regular.ttf"],
    "ui": ["ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf"],
}


def _fetch_font(paths):
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    for p in paths:
        for base in FONT_URLS:
            try:
                r = requests.get(base + p, timeout=30)
                if r.status_code == 200 and r.content[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
                    dest = FONTS_DIR / Path(p.replace("%5B", "[").replace("%5D", "]")).name
                    dest.write_bytes(r.content)
                    return dest
            except Exception:
                pass
    return None


def _family(path):
    try:
        out = subprocess.run(["fc-scan", "--format", "%{family[0]}\\n", str(path)], capture_output=True, text=True).stdout.strip()
        return (out.splitlines()[0].strip() if out else "") or None
    except Exception:
        return None


def setup_fonts():
    global CAP_FONT, CAP_BOLD, CAP_SIZE, TITLE_FONT, TITLE_BOLD, TITLE_SCALE
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    notes = []
    # 1) fonts you put in the repo's "fonts" folder win: fonts/subtitle.ttf|otf and fonts/title.ttf|otf
    mine = ROOT / "fonts"
    for role in ("subtitle", "title"):
        found = next((p for p in sorted(mine.glob(f"{role}.*")) if p.suffix.lower() in (".ttf", ".otf")), None) if mine.exists() else None
        if not found:
            continue
        dest = FONTS_DIR / f"your_{role}{found.suffix.lower()}"
        shutil.copy(found, dest)
        fam = _family(dest)
        if fam and role == "subtitle":
            CAP_FONT, CAP_BOLD, CAP_SIZE = fam, False, 88
            notes.append(f"your subtitle font ({fam})")
        elif fam:
            TITLE_FONT, TITLE_BOLD, TITLE_SCALE = fam, False, 1.0
            notes.append(f"your title font ({fam})")
    # 2) otherwise download the free defaults
    if os.getenv("FONT_DOWNLOAD", "1") == "1":
        if not any("subtitle" in n for n in notes):
            f = _fetch_font(FONT_FILES["caption"])
            fam = f and _family(f)
            if fam:
                CAP_FONT, CAP_BOLD, CAP_SIZE = fam, True, 88
        if not any("title" in n for n in notes):
            f = _fetch_font(FONT_FILES["title"])
            fam2 = f and _family(f)
            if fam2:
                TITLE_FONT, TITLE_BOLD, TITLE_SCALE = fam2, False, 1.24
        _fetch_font(FONT_FILES["ui"])  # used by the HTML motion graphics only; optional
    if CAP_FONT == FONT:
        CAP_SIZE = 80  # the fallback font is wider
    print(f"fonts: subtitles={CAP_FONT!r}, titles={TITLE_FONT!r}" + (f"  [{', '.join(notes)}]" if notes else ""), flush=True)


NO_PEOPLE = os.getenv("NO_PEOPLE", "1") == "1"  # 1 = no humans at all in the footage; 0 = men allowed
MUSIC_VOLUME = os.getenv("MUSIC_VOLUME", "0.07")  # background music loudness (0.03 quiet ... 0.15 loud)
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

PACES = {  # how an editor would cut each kind of video: voice speed, seconds per shot, transition length
    "slow": {"rate": "-3%", "cut": 6.5, "trans": 0.5},
    "medium": {"rate": "+3%", "cut": 4.5, "trans": 0.32},
    "fast": {"rate": "+9%", "cut": 3.2, "trans": 0.2},
    "superfast": {"rate": "+14%", "cut": 2.4, "trans": 0.12},
}


def load_ideas():
    """every numbered line in the channel's idea files (*.md next to main.py, or in an 'ideas' folder)"""
    folder = ROOT / "ideas"
    files = sorted(folder.glob("*.md")) if folder.exists() else []
    files += [f for f in sorted(ROOT.glob("*.md")) if f.name.lower() != "readme.md"]
    ideas = []
    for f in files:
        series = re.sub(r"^.*?\d+_{2,}", "", f.stem).replace("_", " ").strip()
        section = ""
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line in lines:
            h = re.match(r"^#{2,3}\s*(.+)", line)
            if h:
                section = re.sub(r"\s*\(\d+\s*[-\u2013]\s*\d+\)\s*$", "", h.group(1)).strip()
                continue
            m = re.match(r"^\s*\d+\.\s+(.+)", line)
            if not m:
                continue
            txt = re.sub(r"\([^)]*[^\x00-\x7F][^)]*\)", "", m.group(1))  # drop the (Bangla) glosses
            txt = re.sub(r"[^\x20-\x7E\u2014\u2013\u2192]", "", txt)
            txt = re.sub(r"\s+,", ",", re.sub(r"\s+", " ", txt)).strip(" -")
            if len(txt) >= 4 and not txt.lower().startswith(("skip", "bonus round")):
                ideas.append({"series": series, "section": section, "idea": txt})
    return ideas


BANNED = [
    "dive in", "delve", "game-changer", "game changer", "unlock", "elevate",
    "in today's video", "welcome back", "let's get started", "buckle up",
    "tapestry", "in this video", "journey", "ultimate guide",
]

# Footage rules: stock clips are skipped if their tags/title contain any of these words.
BLOCKED_ALWAYS = {
    "woman", "women", "girl", "girls", "lady", "ladies", "female", "females", "bride", "wedding", "bikini",
    "lingerie", "swimsuit", "sexy", "lips", "kiss", "kissing", "romantic", "romance", "dating", "couple",
    "couples", "makeup", "beauty", "fashion", "dress", "wine", "beer", "alcohol", "cocktail", "cocktails",
    "whisky", "whiskey", "vodka", "champagne", "bar", "pub", "nightclub", "club", "party", "dance",
    "dancing", "casino", "gambling", "poker", "pork", "bacon", "pig", "cigarette", "cigarettes", "smoking",
    "hookah", "tattoo", "greenscreen", "chroma", "keying", "alpha", "matte", "overlay",
}
BLOCKED_PEOPLE = {
    "man", "men", "boy", "boys", "people", "person", "persons", "crowd", "family", "child", "children", "kid",
    "kids", "baby", "human", "humans", "face", "student", "students", "teacher", "friend", "friends", "guy",
    "male", "businessman", "audience", "teen", "teenager", "adult", "portrait", "selfie", "pedestrian",
    "pedestrians", "tourist", "tourists", "worker", "workers", "team", "community",
    "hand", "hands", "finger", "fingers", "nail", "nails", "manicure", "ring", "rings", "jewelry", "jewellery",
    "body", "skin", "legs", "feet", "foot", "arm", "arms", "hair", "silhouette", "shadow", "walking", "running",
}


def blocked_words():
    words = set(BLOCKED_ALWAYS)
    if NO_PEOPLE:
        words |= BLOCKED_PEOPLE
    words |= {w.strip().lower() for w in os.getenv("EXTRA_BLOCKED_WORDS", "").split(",") if w.strip()}
    return words


def is_clean(text):
    toks = set(re.findall(r"[a-z]+", str(text).lower()))
    toks |= {t[:-1] for t in toks if t.endswith("s")}
    return not (toks & blocked_words())


def clean_query(query):
    """drop blocked words from a footage search; if nothing is left, use a calm default"""
    bad = blocked_words()
    kept = [w for w in str(query).split() if re.sub(r"[^a-z]", "", w.lower()) not in bad]
    return " ".join(kept) if kept else random.choice(FALLBACK_QUERIES)


SAMPLE_LESSON = {
    "topic": "I am agree vs I agree",
    "title": "Stop saying \"I am agree\" (say this instead)",
    "hook_title": "STOP SAYING THIS",
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


T0 = time.time()


def log(*a):
    s = int(time.time() - T0)
    print(f"[{s // 60}:{s % 60:02d}]", *a, flush=True)


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
            if re.search(r"image|tts|live|audio|thinking|exp|preview|vision|robotics|computer|learnlm|gemma", name):
                continue
            found.append(name)
    except Exception as e:
        log("could not list Gemini models:", e)

    def ver(n):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0.0

    found.sort(key=ver, reverse=True)
    full = [n for n in found if "lite" not in n]
    lite = [n for n in found if "lite" in n]  # smaller models: last resort when the others are out of free quota
    ordered = [n for n in full if n.endswith("latest")] + [n for n in full if not n.endswith("latest")] + lite
    _models = ordered or ["gemini-2.5-flash", "gemini-2.0-flash"]
    log("Gemini models to try:", _models[:3])
    return _models


_dead_models = {}  # model -> time it failed; skipped for 70 s (per-minute limits clear after a minute)


def _alive(m):
    return time.time() - _dead_models.get(m, 0) > 70


def gemini_json(prompt, temperature=1.0, images=None):
    last = None
    parts_in = [{"text": prompt}] + [{"inline_data": {"mime_type": "image/jpeg", "data": b}} for b in (images or [])]
    models = [m for m in gemini_models() if _alive(m)]
    if not models:
        time.sleep(15)  # everything is rate-limited right now: wait a bit, then try the full list once
        models = gemini_models()
    for model in models:
        for attempt in range(2):
            try:
                r = requests.post(
                    f"{GEMINI_BASE}/models/{model}:generateContent",
                    params={"key": GEMINI_KEY},
                    json={
                        "contents": [{"parts": parts_in}],
                        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
                    },
                    timeout=(10, 50),
                )
                if r.status_code in (429, 500, 503):
                    last = f"{model}: HTTP {r.status_code}"
                    if attempt == 0:
                        time.sleep(8)
                        continue
                    _dead_models[model] = time.time()
                    break
                if r.status_code in (400, 403, 404):
                    last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                    _dead_models[model] = time.time()
                    break  # try the next model
                r.raise_for_status()
                parts = r.json()["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                data = json.loads(text)
                if isinstance(data, list):
                    data = data[0]
                return data
            except requests.exceptions.RequestException as e:  # timeout or network trouble: switch model right away
                last = f"{model}: {type(e).__name__}"
                log(f"{model} too slow or unreachable ({type(e).__name__}); switching model")
                _dead_models[model] = time.time()
                break
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last = f"{model}: bad response ({e})"
                time.sleep(3)
    raise RuntimeError(f"Gemini failed: {last}")


def build_prompt(category, hook_style, recent, notes="", idea=None):
    recent_txt = "\n".join(f"- {t}" for t in recent[-120:]) or "- (none yet)"
    greet = (
        f'Begin the very first sentence with exactly: "{GREETING}" and then go straight into the hook.'
        if GREETING
        else "No greeting, no intro, no channel name. The very first words ARE the hook."
    )
    cta = "End on the comment question. Do NOT add a call to action or a sign-off: the closing line is added automatically afterwards."
    if NO_PEOPLE:
        visual_rule = (
            'VISUALS: for each segment give "visual", a 2 to 4 word search phrase for stock video that a camera could really film. '
            "This channel's audience wants modest, family-friendly visuals: NO people at all (no men, women, children, crowds, faces, hands, fingers or any body parts), "
            "no alcohol, no pork, no romance, no nightlife, no gambling, no smoking. Use calm things instead: nature, sky, ocean, "
            "mountains, rain, city skylines, buildings, books, desks, keyboards, tea or coffee cups, clocks, plants, lamps "
            '(for example "rain window", "books library", "sunrise mountains", "keyboard closeup", "tea cup steam"). Never abstract ideas, never text.'
        )
    else:
        visual_rule = (
            'VISUALS: for each segment give "visual", a 2 to 4 word search phrase for stock video that a camera could really film. '
            "Modest, family-friendly visuals only: no women or girls, no alcohol, no pork, no romance, no nightlife, no gambling, no smoking. "
            'Prefer nature, cities, objects, books, desks, keyboards, hands. Never abstract ideas, never text.'
        )
    shape = {
        "topic": "3-6 word label of the lesson, used to avoid repeats",
        "title": "YouTube title, max 60 characters, makes a learner curious, no lies",
        "pace": "slow | medium | fast | superfast (how an editor would cut this video, see PACE)",
        "mood": "one word: calm, playful, serious, energetic, funny, encouraging ...",
        "hook_title": "2 to 4 words (max 20 characters in total) shown HUGE on screen during the first two seconds. It teases the lesson, for example STOP SAYING THIS or THE WORD YOU MISUSE or SOUND MORE NATURAL",
        "description": "1-2 plain sentences summarising the tip",
        "hashtags": ["#learnenglish", "#english", "#englishtips", "#shorts"],
        "segments": [
            {"say": "spoken line(s)", "visual": "2-4 word stock video search", "card": "optional big on-screen text or empty string", "card_kind": "wrong | right | neutral"}
        ],
    }
    return f"""You write spoken scripts for a YouTube Shorts channel that teaches English to learners around the world (roughly B1-B2 level).

LESSON TYPE TODAY: {category}
{("TOPIC FROM THE CHANNEL'S IDEA BANK (teach exactly this; if it lists several items, pick the ONE most useful and teach only that): " + idea['series'] + " / " + idea['section'] + " / " + idea['idea']) if idea else ""}
HOOK STYLE TO ADAPT (do not copy it word for word): {hook_style}

Never repeat or closely resemble these earlier topics:
{recent_txt}
{notes}
HOW IT MUST SOUND
Write the way a warm, funny friend explains something over coffee, not the way a teacher or textbook talks. Use contractions (you're, it's, don't). Mix very short sentences with slightly longer ones. It's fine to start with "And", "But" or "Look,". Plain everyday words only. One idea per sentence. Imagine reading every line out loud; if it sounds written instead of spoken, rewrite it.
Never use: "dive in", "delve", "game-changer", "unlock", "elevate", "journey", "in today's video", "welcome back", "let's get started", "buckle up". No emojis, hashtags, stage directions or sound effects inside spoken lines. Write numbers as words.

THE HOOK (segment 1) - this decides everything
- 4 to 10 words. The viewer decides in the first second whether to keep watching, so the first three words must already create tension, a question, or a "wait, am I wrong?" feeling.
- Use a concrete phrase or word from the lesson in the hook, never something vague. Name the mistake, the trap, or the surprise directly.
- Strong formulas (adapt, never copy): "Stop saying '...'." / "You've been saying '...' wrong." / "'...' sounds rude. Here's why." / "Only 1 in 10 learners get this right." only if you do NOT invent statistics, so prefer "Most learners get this wrong." / "Which one is correct?" / "Native speakers never say '...'."
- Banned openers: "Did you know", "Today we", "Hey guys", "Let's talk about", "In this video". No greeting, no channel name.
- {greet}
- No clickbait lies. Never invent statistics, studies or personal stories.
- Also write "hook_title": 2 or 3 punchy words (max 18 characters) shown huge on screen at the very first frame, e.g. STOP SAYING THIS / WRONG ENGLISH / SOUNDS RUDE.

PACE (choose like a video editor who reads the mood of the topic): slow = calm explanations, pronunciation, comfort and confidence topics; medium = most lessons; fast = quizzes, slang, challenges, funny comparisons, texting; superfast = rapid-fire lists, word upgrades, speed drills. Fast and superfast scripts use shorter sentences.

SHAPE: hook, then the problem (one beat of tension), then the reveal (the correct answer), then one real-life example sentence someone would actually say, then an optional quick memory trick, then the ending. The ending asks one tiny question the viewer can answer in the comments. {cta}

ACCURACY
Teach only things that are definitely correct and natural in standard English today. If American and British usage differ, say so in one short sentence.

LENGTH: 6 to 7 segments, 70 to 90 spoken words in total. Short and punchy beats thorough.

{visual_rule}
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


def clean_hook_title(s):
    """2 to 4 short words, letters only, upper case; "" if unusable (a safe default is used instead)"""
    words = re.sub(r"[^A-Za-z' ]", " ", clean_text(s)).upper().split()[:4]
    text = " ".join(words)
    return text if 1 <= len(words) <= 4 and len(text) <= 22 else ""


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
            "visual": clean_query(clean_text(s.get("visual"))),
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
    pace = str(lesson.get("pace", "medium")).lower().strip()
    return {
        "pace": pace if pace in PACES else "medium",
        "mood": clean_text(lesson.get("mood"))[:20].lower() or "neutral",
        "topic": clean_text(lesson.get("topic")) or clean_text(lesson.get("title")),
        "title": clean_text(lesson.get("title"))[:95] or "English tip",
        "hook_title": clean_hook_title(lesson.get("hook_title")),
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


def ensure_cta(lesson):
    """the last line of every video is exactly the closing line (it says the creator's name out loud)"""
    if not CTA:
        return lesson
    segs = lesson["segments"]
    if re.search(r"\bfollow\b", segs[-1]["say"], re.I):
        segs[-1] = {**segs[-1], "say": CTA, "card": ""}
    else:
        segs.append({"say": CTA, "visual": random.choice(FALLBACK_QUERIES), "card": "", "card_kind": "neutral"})
    return lesson


def make_lesson(history):
    recent_cats = [h.get("category") for h in history[-4:]]
    category = random.choice([c for c in CATEGORIES if c not in recent_cats] or CATEGORIES)
    hook_style = random.choice(HOOK_STYLES)
    ideas = load_ideas()
    done = {h.get("idea") for h in history if h.get("idea")}
    fresh = [i for i in ideas if i["idea"] not in done] or ideas

    def pick_idea():
        # rotate through the idea files so one series doesn't dominate
        last = [h.get("series") for h in history[-2:]]
        pool = [i for i in fresh if i["series"] not in last] or fresh
        return random.choice(pool) if pool else None

    idea = pick_idea()
    if idea:
        category = f"{idea['series']}: {idea['section']}"
        log(f"idea bank: {len(ideas)} ideas; today: {idea['series']} / {idea['idea'][:80]}")
    recent_topics = [h.get("topic", "") for h in history]
    log(f"lesson type: {category}\nhook style: {hook_style}")
    last_err, notes = None, ""
    for attempt in range(1, 9):
        if time.time() - T0 > 600:  # never let one run drag on
            break
        if attempt in (4, 7):  # still failing: try a different lesson type
            category = random.choice(CATEGORIES)
            idea = pick_idea() if idea else None
            if idea:
                category = f"{idea['series']}: {idea['section']}"
            log(f"switching lesson type to: {category}")
        try:
            lesson = validate(gemini_json(build_prompt(category, hook_style, recent_topics, notes, idea)))
            ok, issues = verify_lesson(lesson)
            if not ok:
                notes = (
                    "\nA strict teacher REJECTED your previous attempt for this reason, so avoid it: "
                    f"{issues[:300]}\nOnly teach points that are 100% correct. Never label a natural, correct phrase as wrong.\n"
                )
                raise ValueError(f"teacher check failed: {issues}")
            lesson["category"] = category
            lesson["idea"] = idea["idea"] if idea else ""
            lesson["series"] = idea["series"] if idea else ""
            return lesson
        except Exception as e:
            last_err = e
            log(f"attempt {attempt} rejected: {e}")
    raise RuntimeError(f"could not get a good lesson: {last_err}")


# ---------------------------------------------------------------- voice (TTS)
async def _synth(text, voice, out_path, boundary="WordBoundary"):
    import edge_tts

    try:
        comm = edge_tts.Communicate(text, voice, rate=VOICE_RATE, pitch=VOICE_PITCH, boundary=boundary)
    except TypeError:  # older edge-tts versions have no 'boundary' option
        comm = edge_tts.Communicate(text, voice, rate=VOICE_RATE, pitch=VOICE_PITCH)
    events = []
    with open(out_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                start = chunk["offset"] / 1e7
                events.append((chunk["text"], start, start + chunk["duration"] / 1e7))
    if os.path.getsize(out_path) < 2000:
        raise RuntimeError("TTS returned no audio")
    return events


def tts(text, out_path):
    """returns (word_timings, sentence_timings). Sentence timings are only used when a voice gives no word timings."""
    voices = [VOICE] + [v for v in ("en-US-BrianMultilingualNeural", "en-US-AndrewNeural", "en-US-GuyNeural") if v != VOICE]
    n_words = len(text.split())
    last = None
    for voice in voices:
        for attempt in range(3):
            try:
                events = asyncio.run(_synth(text, voice, out_path, "WordBoundary"))
                if len(events) >= n_words * 0.8:
                    log(f"voice: {voice}, word timings: {len(events)}")
                    return events, []
                # this voice only reports sentences: ask again so audio and timings come from the same take
                events = asyncio.run(_synth(text, voice, out_path, "SentenceBoundary"))
                if len(events) >= n_words * 0.8:  # old edge-tts ignored the option and sent words
                    log(f"voice: {voice}, word timings: {len(events)}")
                    return events, []
                log(f"voice: {voice}, sentence timings: {len(events)}")
                return [], events
            except Exception as e:
                last = e
                log(f"voice attempt failed ({voice}): {e}")
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"text-to-speech failed: {last}")


# ---- Kokoro: open-source neural voice (kokoro-onnx). Needs no key; ~310 MB model downloaded on each run.
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_DIR = OUT / "kokoro"
_kokoro = None


def _kokoro_engine():
    global _kokoro
    if _kokoro:
        return _kokoro
    try:
        from kokoro_onnx import Kokoro
    except ImportError:
        log("installing kokoro-onnx ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "kokoro-onnx"], check=True, timeout=900)
        import importlib

        importlib.invalidate_caches()
        from kokoro_onnx import Kokoro
    KOKORO_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        p = KOKORO_DIR / name
        if not p.exists() or p.stat().st_size < 1_000_000:
            log(f"downloading voice file {name} ...")
            download(f"{KOKORO_URL}/{name}", p)
        paths.append(str(p))
    _kokoro = Kokoro(*paths)
    return _kokoro


def split_sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def tts_kokoro(display, spoken, out_path):
    """one sentence at a time, so every sentence has an exact start/end time (that is what keeps captions in sync)"""
    import wave

    eng = _kokoro_engine()  # installs kokoro-onnx (and numpy) on first use
    import numpy as np

    disp, spk = split_sentences(display), split_sentences(spoken)
    if len(disp) != len(spk):
        raise RuntimeError("sentence count mismatch")
    parts, sents, t, sr = [], [], 0.0, 24000
    for d, s in zip(disp, spk):
        samples, sr = eng.create(s.replace('"', ""), voice=KOKORO_VOICE, speed=KOKORO_SPEED, lang="en-us")
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        loud = np.where(np.abs(x) > 0.012)[0]
        if len(loud):  # trim the silence the model leaves at both ends
            x = x[max(0, loud[0] - int(0.03 * sr)): loud[-1] + int(0.08 * sr)]
        dur = len(x) / sr
        gap = 0.40 if d.rstrip().endswith("?") else 0.26  # a human-sized breath between sentences
        sents.append((d, t, t + dur))
        parts += [x, np.zeros(int(gap * sr), dtype=np.float32)]
        t += dur + gap
    audio = np.concatenate(parts)
    wav = Path(out_path).with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav, "-c:a", "libmp3lame", "-b:a", "192k", out_path])
    return [], sents


GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Achird").strip()  # male voices: Achird (friendly), Puck (upbeat), Charon, Orus, Fenrir
_tts_models = None


def _gemini_tts_models():
    global _tts_models
    if _tts_models is None:
        found = []
        try:
            r = requests.get(f"{GEMINI_BASE}/models", params={"key": GEMINI_KEY, "pageSize": 200}, timeout=30)
            r.raise_for_status()
            for m in r.json().get("models", []):
                n = m.get("name", "").replace("models/", "")
                if "tts" in n and "generateContent" in m.get("supportedGenerationMethods", []):
                    found.append(n)
        except Exception as e:
            log("could not list speech models:", repr(e)[:120])
        found.sort(key=lambda n: ("flash" not in n, "preview" in n, n))
        _tts_models = found or ["gemini-2.5-flash-preview-tts"]
    return _tts_models


def sentence_direction(i, n, d):
    """one short style word per sentence (long instructions get read out loud by the speech model)"""
    if i == 0:
        return "energetically"
    if d.rstrip().endswith("?"):
        return "curiously"
    if i == n - 1:
        return "warmly"
    if '"' in d:
        return "clearly"
    return "naturally"


def _norm_words(t):
    return re.sub(r"[^a-z0-9' ]", " ", t.lower()).split()


def _transcribe(pcm, sr=24000):
    """ask a Gemini text model what was actually said (None if it can't tell)"""
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    body = {"contents": [{"parts": [{"text": "Transcribe this audio exactly, word for word. Output only the transcript, nothing else."},
                                    {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(buf.getvalue()).decode()}}]}],
            "generationConfig": {"temperature": 0}}
    for model in gemini_models()[:2]:
        try:
            r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", params={"key": GEMINI_KEY}, json=body, timeout=(10, 60))
            if r.status_code == 429:
                time.sleep(15)
                continue
            r.raise_for_status()
            return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"]).strip()
        except Exception:
            continue
    return None


def said_ok(transcript, sentence):
    """True if the audio says the sentence and nothing extra (no stage directions read aloud)"""
    if transcript is None:
        return True
    exp, got = _norm_words(sentence), _norm_words(transcript)
    if not got:
        return False
    if len(got) > len(exp) + max(2, len(exp) // 4) or len(got) < len(exp) * 0.7:
        return False
    return sum(1 for a, b in zip(exp[:3], got[:3]) if a == b) >= min(2, len(exp))


def refine_words(x, sr, words, t0):
    """word start/end times inside one sentence: boundaries snap to the quietest moments near where each word should begin"""
    import numpy as np

    n = len(words)
    dur = len(x) / sr
    ws = []
    for w in words:
        k = len(re.sub(r"\W", "", w)) + 2
        ws.append(k + (4 if re.search(r"[,;:]$", w) else 0))
    cum = np.cumsum(ws) / sum(ws)
    hop = int(0.01 * sr)
    m = len(x) // hop
    if n < 2 or m < 8:
        edges = [0.0] + [float(c) * dur for c in cum]
    else:
        env = np.sqrt(np.mean(x[: m * hop].reshape(m, hop) ** 2, axis=1))
        env = np.convolve(env, np.ones(3) / 3, mode="same")
        edges, last = [0.0], 0.0
        for k in range(n - 1):
            e = float(cum[k]) * dur
            lo, hi = max(last + 0.06, e - 0.22), min(dur - 0.06 * (n - 1 - k), e + 0.22)
            if hi <= lo:
                edges.append(min(max(e, last + 0.05), dur))
            else:
                a, b = int(lo * 100), max(int(hi * 100), int(lo * 100) + 1)
                seg = env[a:b] + 0.0008 * np.abs(np.arange(a, b) - e * 100) / 22.0  # prefer quiet AND near the expected spot
                edges.append((a + int(np.argmin(seg))) / 100.0)
            last = edges[-1]
        edges.append(dur)
    return [(t0 + edges[i], t0 + edges[i + 1]) for i in range(n)]


def tts_gemini(display, spoken, out_path):
    """Gemini speech model, one sentence at a time with its own acting note. Returns ([], sentence timings)."""
    import base64
    import wave

    import numpy as np

    disp, spk = split_sentences(display), split_sentences(spoken)
    if len(disp) != len(spk):
        raise RuntimeError("sentence count mismatch")
    parts, sents, wb, t, sr = [], [], [], 0.0, 24000
    for i, (d, s) in enumerate(zip(disp, spk)):
        plain = s.replace(chr(34), "")
        pcm = None
        for style in (sentence_direction(i, len(spk), d), ""):  # second try: no style word at all
            prompt = f"Say {style}: {plain}" if style else plain
            body = {"contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"],
                                         "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_TTS_VOICE}}}}}
            got = None
            for attempt in range(6):
                model = _gemini_tts_models()[attempt % len(_gemini_tts_models())]
                try:
                    r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", params={"key": GEMINI_KEY}, json=body, timeout=(10, 90))
                    if r.status_code == 429:
                        time.sleep(22)
                        continue
                    r.raise_for_status()
                    for p in r.json()["candidates"][0]["content"]["parts"]:
                        if "inlineData" in p:
                            got = base64.b64decode(p["inlineData"]["data"])
                            break
                    if got:
                        break
                except Exception as e:
                    log(f"  speech attempt {attempt + 1} failed: {repr(e)[:110]}")
                    time.sleep(4)
            if not got:
                continue
            heard = _transcribe(got[: len(got) // 2 * 2])
            if said_ok(heard, plain):
                pcm = got
                break
            log(f"  sentence {i + 1}: audio did not match the script (heard: {str(heard)[:80]!r}); " + ("retrying without style" if style else "giving up"))
        if not pcm:
            raise RuntimeError(f"no clean audio for sentence {i + 1}")
        x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
        loud = np.where(np.abs(x) > 0.01)[0]
        if len(loud):
            x = x[max(0, loud[0] - int(0.03 * sr)): loud[-1] + int(0.09 * sr)]
        dur = len(x) / sr
        gap = 0.34 if d.rstrip().endswith("?") else 0.2
        sents.append((d, t, t + dur))
        wb += [("", a, b) for a, b in refine_words(x, sr, d.split(), t)]
        parts += [x, np.zeros(int(gap * sr), dtype=np.float32)]
        t += dur + gap
    audio = np.concatenate(parts)
    peak = float(np.max(np.abs(audio))) or 1.0
    audio = audio * min(1.0, 0.89 / peak)
    wav = Path(out_path).with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    nwords = sum(len(d.split()) for d in disp)
    if t / 1.4 > 62:
        raise RuntimeError(f"voice too long ({t:.0f}s)")
    tempo = max(1.0, min(1.4, 2.6 / max(nwords / max(t, 1.0), 0.1)))  # too slow? speed the whole voice up (pitch stays)
    if tempo > 1.04:
        log(f"voice pace: {nwords / t:.2f} words/s, speeding up x{tempo:.2f}")
        sents = [(d, a / tempo, b / tempo) for d, a, b in sents]
        wb = [(w, a / tempo, b / tempo) for w, a, b in wb]
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav, "-af", f"atempo={tempo:.3f}", "-c:a", "libmp3lame", "-b:a", "192k", out_path])
    else:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav, "-c:a", "libmp3lame", "-b:a", "192k", out_path])
    return wb, sents


def make_voice(display, spoken, out_path):
    """display = the words shown as captions, spoken = what the voice reads (the name respelled). Returns (word_timings, sentence_timings)."""
    if VOICE_ENGINE == "gemini":
        try:
            res = tts_gemini(display, spoken, out_path)
            log(f"voice: Gemini speech ({GEMINI_TTS_VOICE}), {len(res[1])} sentences")
            return res
        except Exception as e:
            log(f"Gemini voice not available ({type(e).__name__}: {str(e)[:160]}); trying Kokoro")
    if VOICE_ENGINE in ("gemini", "kokoro"):
        try:
            res = tts_kokoro(display, spoken, out_path)
            log(f"voice: Kokoro ({KOKORO_VOICE}), {len(res[1])} sentences")
            return res
        except Exception as e:
            log(f"Kokoro voice not available ({type(e).__name__}: {str(e)[:160]}); using the edge voice instead")
    return tts(spoken, out_path)


def probe_duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())


def _spread(tokens, start, end):
    """spread words between two times, weighted by word length and punctuation pauses"""
    ws = []
    for t in tokens:
        w = len(re.sub(r"\W", "", t)) + 2
        if re.search(r"[.!?]\"?$", t):
            w += 5
        elif re.search(r"[,;:]\"?$", t) or t.endswith("..."):
            w += 2
        ws.append(w)
    scale = max(end - start, 0.1) / sum(ws)
    out, t0 = [], start
    for w in ws:
        out.append((t0, t0 + w * scale))
        t0 += w * scale
    return out


def align(tokens, wb, total, sents=None):
    """(start, end) in seconds for every spoken word."""
    n = len(tokens)
    times = []
    if wb:
        for i in range(n):
            j = i if len(wb) == n else min(len(wb) - 1, int(i * len(wb) / n))
            times.append((wb[j][1], wb[j][2]))
    elif sents and sum(len(s[0].split()) for s in sents) == n:  # anchor every sentence at its real time
        i = 0
        for text_, s0, s1 in sents:
            c = len(text_.split())
            if c:
                times += _spread(tokens[i:i + c], s0, s1)
                i += c
    else:  # no usable timings: spread the words over the whole audio
        times = _spread(tokens, 0.05, total - 0.25)
    fixed, prev = [], 0.0
    for s, e in times:  # keep it monotonic
        s = max(s, prev)
        e = max(e, s + 0.05)
        fixed.append((s, e))
        prev = s
    return fixed


# --------------------------------------------------------------- footage
def pexels_list(query, used):
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_KEY},
        params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 15},
        timeout=30,
    )
    r.raise_for_status()
    vids = [v for v in r.json().get("videos", []) if f"pexels:{v['id']}" not in used and v.get("duration", 0) >= 4 and is_clean(v.get("url", ""))]
    random.shuffle(vids)
    out = []
    for v in vids:
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= (f.get("width") or 0)]
        files.sort(key=lambda f: abs((f.get("height") or 0) - 1920))
        if files:
            out.append((f"pexels:{v['id']}", files[0]["link"]))
    return out


def pixabay_list(query, used):
    r = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": PIXABAY_KEY, "q": query[:100], "per_page": 20, "safesearch": "true", "min_height": 720, "video_type": "film"},
        timeout=30,
    )
    r.raise_for_status()
    hits = [h for h in r.json().get("hits", []) if f"pixabay:{h['id']}" not in used and h.get("duration", 0) >= 4 and is_clean(h.get("tags", ""))]
    random.shuffle(hits)
    out = []
    for h in hits:
        sizes = [v for v in (h.get("videos") or {}).values() if v.get("url")]
        if not sizes:
            continue
        fit = [v for v in sizes if (v.get("width") or 0) <= 2000]  # avoid giant 4K files
        best = max(fit, key=lambda v: v.get("width") or 0) if fit else min(sizes, key=lambda v: v.get("width") or 0)
        out.append((f"pixabay:{h['id']}", best["url"]))
    return out


def stock_candidates(query, used):
    """clips from every stock site you have a key for (tag-filtered; the real check happens in vet_clip)"""
    out = []
    for fn, key in ((pexels_list, PEXELS_KEY), (pixabay_list, PIXABAY_KEY)):
        if not key:
            continue
        try:
            out += fn(query, used)
        except Exception as e:
            log(f"{fn.__name__} problem for '{query}': {e}")
    return out


VET = os.getenv("VET_FOOTAGE", "1") == "1"  # 1 = Gemini looks at the clip's frames before it is used


def vet_prompt():
    people = (
        "any person or part of a person (face, hands, fingers, arms, legs, silhouette, crowd, statue or drawing of a person)"
        if NO_PEOPLE else "any woman or girl, or any person who is partly undressed (adult men dressed normally are fine)"
    )
    return (
        "You are a strict reviewer for a modest, family-friendly educational channel with a Muslim audience. "
        "You are shown 3 frames from ONE stock video clip. Answer ok=true ONLY if all 3 frames are clearly clean.\n"
        f"Reject (ok=false) if ANY frame shows: {people}; alcohol, pork, smoking, gambling, nightlife, romance or revealing clothing; "
        "worship or religious rituals or symbols of any religion, idols; fire, explosions, weapons, war, violence or disasters; "
        "large readable text, logos or brand names; anything dark, disturbing or creepy; a green screen or flat placeholder graphic.\n"
        "Calm nature, sky, sea, rain, buildings and cityscapes without people, books, desks, keyboards, cups, plants and similar objects are fine.\n"
        'Reply as JSON: {"ok": true or false, "reason": "short reason"}'
    )


_vet_errors = 0  # consecutive checks that could not run (quota, network): after 4 we stop using stock footage


def vet_clip(path, tag):
    """True only if Gemini says the clip is clean. Fails closed: if the check can't run, the clip is not used."""
    global _vet_errors
    if not VET:
        return True
    try:
        d = probe_duration(path)
        imgs = []
        for k, frac in enumerate((0.15, 0.5, 0.85)):
            jpg = WORK / f"vet_{tag}_{k}.jpg"
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{d * frac:.2f}", "-i", path,
                 "-frames:v", "1", "-vf", "scale=384:-2", "-q:v", "5", jpg])
            imgs.append(base64.b64encode(jpg.read_bytes()).decode())
        res = gemini_json(vet_prompt(), 0.0, images=imgs)
        _vet_errors = 0
        ok = res.get("ok") is True
        if not ok:
            log(f"  footage check said no: {str(res.get('reason', ''))[:110]}")
        return ok
    except Exception as e:
        _vet_errors += 1
        log(f"  footage check could not run ({str(e)[:100]}); not using this clip")
        return False


def download(url, dest):
    with requests.get(url, stream=True, timeout=90) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


FALLBACK_QUERIES = [
    "city skyline", "books library", "open book pages", "keyboard closeup", "clouds sky",
    "mountains nature", "ocean waves", "tea cup steam", "rain window", "sunrise hills",
]
GRADIENTS = [("0x0f2027", "0x2c5364"), ("0x41295a", "0x2f0743"), ("0x134e5e", "0x71b280"), ("0x232526", "0x414345"), ("0x1f4037", "0x99f2c8")]
MOTION_ENGINE = os.getenv("MOTION_ENGINE", "html").strip().lower()  # html = animated overlay made with a headless browser | ass = classic look
MOTION = os.getenv("MOTION", "1") == "1"  # slow camera push, vignette, progress bar, animated cards. 0 = plain


def clip_vf(dur, i):
    """cover-fit to 1080x1920, then a slow, subtle camera move (push-in on even clips, pull-out on odd ones)"""
    if not MOTION:
        return (
            f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps={FPS},"
            "eq=brightness=-0.07:saturation=1.08,format=yuv420p"
        )
    # fit to 1620x2880 (1.5x), then zoompan crops a window that slowly shrinks/grows and outputs a fixed 1080x1920
    n = max(int(dur * FPS), 1)
    z = f"1.5+0.105*on/{n}" if i % 2 == 0 else f"1.605-0.105*on/{n}"
    return (
        f"fps={FPS},scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,setsar=1,"
        f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps={FPS},"
        "vignette=angle=0.45,eq=brightness=-0.07:saturation=1.08,format=yuv420p"
    )
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]
TRANS = 0.32  # length of the transition between two scenes (seconds)
XFADES = ["smoothleft", "zoomin", "fadeblack", "smoothright", "circleopen", "dissolve", "smoothup"]


def assemble(clip_names, bounds):
    """join the scene clips into video.mp4; with MOTION on, scenes blend with real transitions centred on each cut"""
    n = len(clip_names)
    if n == 1 or not MOTION:
        (WORK / "concat.txt").write_text("".join(f"file '{c}'\n" for c in clip_names))
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "video.mp4"], cwd=WORK)
        return
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for c in clip_names:
        cmd += ["-i", c]
    fc = [f"[{i}:v]settb=AVTB,fps={FPS},setpts=PTS-STARTPTS,format=yuv420p[s{i}]" for i in range(n)]
    last, prev = "s0", None
    for k in range(1, n):
        tr = random.choice([t for t in XFADES if t != prev])
        prev = tr
        off = max(bounds[k][0] - TRANS / 2, 0.1)
        fc.append(f"[{last}][s{k}]xfade=transition={tr}:duration={TRANS}:offset={off:.3f}[x{k}]")
        last = f"x{k}"
    cmd += ["-filter_complex", ";".join(fc), "-map", f"[{last}]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", "video.mp4"]
    run(cmd, cwd=WORK)


def get_footage(query, used, dest, tag="x"):
    """find one clean stock clip for this query (checked frame by frame); returns True on success"""
    if not (PEXELS_KEY or PIXABAY_KEY):
        return False
    if VET and _vet_errors >= 4:
        log("  footage check keeps failing: using a calm gradient for this scene")
        return False
    words = query.split()
    attempts = [query] + ([" ".join(words[-2:])] if len(words) > 2 else []) + random.sample(FALLBACK_QUERIES, 2)
    checked = 0
    for qy in attempts:
        for cid, url in stock_candidates(qy, used)[:4]:
            if checked >= 6 or (VET and _vet_errors >= 4):  # give up on this scene: a calm gradient beats a risky clip
                return False
            used.add(cid)
            try:
                download(url, dest)
            except Exception as e:
                log(f"download problem for '{qy}': {e}")
                continue
            checked += 1
            if vet_clip(dest, tag):
                return True
    return False


def make_clip(src, dur, out, i=0):
    tmp = Path(out).with_name(Path(out).stem + ".part.mp4")  # a stopped render can't leave a short, playable-looking scene
    if src:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", src, "-t", f"{dur:.4f}", "-vf", clip_vf(dur, i), *X264, tmp])
    else:
        c0, c1 = random.choice(GRADIENTS)
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", f"gradients=s=1080x1920:r={FPS}:d={dur:.4f}:speed=0.04:c0={c0}:c1={c1}:nb_colors=2",
            "-vf", "format=yuv420p", *X264, tmp,
        ])
    os.replace(tmp, out)


# --------------------------------------------------------------- captions
def ass_time(t):
    cs = int(round(max(0, t) * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def esc(t):
    return t.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


HL = r"\c&H3CC8FF&"  # the word being spoken: warm gold
WHITE = r"\c&HFFFFFF&"
# Fixed lanes (1080x1920). The card is anchored by its BOTTOM edge at CARD_Y (it grows upward);
# captions are anchored by their TOP edge at CAP_Y. The gap between them means they can never overlap.
CARD_Y = 860
CAP_Y = 960
ENTER_MS = 170  # how long a new caption phrase takes to settle in
CHUNK_CHARS = 18  # short phrases keep each caption on ONE line, so nothing jumps
CHANNEL_TAG = os.getenv("CHANNEL_TAG", "").strip()  # optional small on-screen name at the top ("" = none: the name is spoken instead)
SHOW_BRAND_CARD = os.getenv("SHOW_BRAND_CARD", "0") == "1"  # optional closing name card
# card panel colours (BGR): panel, text
CARD_LOOK = {
    "wrong": (r"\3c&H2626DC&", r"\c&HFFFFFF&\s1"),   # red panel, white struck-through text
    "right": (r"\3c&H3D8015&", r"\c&HFFFFFF&"),      # green panel, white text
    "neutral": (r"\3c&HFFFFFF&", r"\c&H271811&"),    # white panel, dark text
    "brand": (r"\3c&H3CC8FF&", r"\c&H271811&"),      # gold panel, dark text (optional closing name card)
}


def chunk_tokens(tokens, size=3, max_chars=CHUNK_CHARS):
    chunks, cur = [], []
    for i, t in enumerate(tokens):
        if cur and sum(len(tokens[j]) + 1 for j in cur) + len(t) > max_chars:  # keep lines short and steady
            chunks.append(cur)
            cur = []
        cur.append(i)
        if len(cur) >= size or re.search(r"[.!?,;:]\"?$", t):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    for ci in range(1, len(chunks)):  # avoid a lone word on screen: borrow one from the chunk before it
        prev, this = chunks[ci - 1], chunks[ci]
        if len(this) == 1 and len(prev) >= 3 and not re.search(r"[.!?,;:]\"?$", tokens[prev[-1]]):
            if sum(len(tokens[j]) + 1 for j in this) + len(tokens[prev[-1]]) <= max_chars + 4:
                chunks[ci] = [prev[-1]] + this
                chunks[ci - 1] = prev[:-1]
    return chunks


def card_events(s, a, b):
    """one key-phrase card: solid panel; entrance depends on its meaning; gentle float while on screen; soft exit"""
    kind = s["card_kind"]
    n = len(s["card"])
    size = int((100 if n <= 14 else 88 if n <= 22 else 76) * TITLE_SCALE)
    panel, textcol = CARD_LOOK[kind]
    base = f"\\an2\\fs{size}\\bord30\\shad0\\4a&HFF&{panel}{textcol}"
    t0 = a + 0.1
    dur = max(int((b - t0) * 1000), 400)
    if not MOTION:
        extra = f"\\pos(540,{CARD_Y})\\fad(100,100)"
    else:
        float_ = f"\\move(540,{CARD_Y + 8},540,{CARD_Y - 8},0,{dur})"
        fade_in = r"\alpha&HFF&\t(0,140,\alpha&H00&)"
        leave = f"\\t({max(dur - 160, 320)},{dur},\\fscx94\\fscy94\\alpha&HFF&)"
        if kind == "wrong":    # slams in, then a short shake: "nope"
            extra = float_ + fade_in + r"\fscx135\fscy135\t(0,120,\fscx100\fscy100)\t(150,210,\frz2.5)\t(210,270,\frz-2.5)\t(270,330,\frz0)" + leave
        elif kind == "right":  # unfolds from the centre
            extra = float_ + fade_in + r"\clip(540,0,540,1920)\t(0,300,\clip(0,0,1080,1920))\fscx92\fscy92\t(0,300,\fscx100\fscy100)" + leave
        else:                  # rises into place, softly blurred at first
            extra = f"\\move(540,{CARD_Y + 40},540,{CARD_Y},0,280)" + fade_in + r"\blur6\t(0,280,\blur0)" + leave
    return f"Dialogue: 2,{ass_time(t0)},{ass_time(b)},Card,,0,0,0,,{{{base}{extra}}}{esc(s['card'])}"


def build_ass(tokens, times, segs, seg_bounds, total):
    capb = -1 if CAP_BOLD else 0
    titleb = -1 if TITLE_BOLD else 0
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{CAP_FONT},{CAP_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H70000000,{capb},0,0,0,100,100,0.6,0,1,0,3,8,90,90,{CAP_Y},1
Style: Card,{TITLE_FONT},100,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,&H00000000,{titleb},0,0,0,100,100,1,0,3,30,0,2,90,90,0,1
Style: Tag,{CAP_FONT},32,&H00FFFFFF,&H00FFFFFF,&H00000000,&H70000000,{capb},0,0,0,100,100,8,0,1,0,2,8,80,80,175,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    chunks = chunk_tokens(tokens)
    for ci, chunk in enumerate(chunks):
        chunk_start = times[chunk[0]][0]
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
                parts.append(f"{{{HL}}}{w}{{{WHITE}}}" if j == idx else w)  # spoken word in gold; size never changes
            # every event in a phrase sits at the SAME spot with the SAME text, so only the colour moves.
            # A new phrase rises in softly (blur -> sharp); words spoken during that moment continue the same motion.
            rem = max(0, ENTER_MS - int((start - chunk_start) * 1000)) if MOTION else 0
            if rem:
                p = rem / ENTER_MS
                tr = (f"\\an8\\move(540,{CAP_Y + int(30 * p)},540,{CAP_Y},0,{rem})\\blur{7 * p:.1f}\\t(0,{rem},\\blur1)"
                      f"\\alpha&H{int(255 * p):02X}&\\t(0,{rem},\\alpha&H00&)")
            else:
                tr = f"\\an8\\pos(540,{CAP_Y})\\blur1"
            lines.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,{{{tr}}}{' '.join(parts)}")
    for (a, b), s in zip(seg_bounds, segs):
        if s["card"]:
            lines.append(card_events(s, a, b))
    brand_card = bool(SHOW_BRAND_CARD and CHANNEL_NAME and segs and not segs[-1]["card"])
    if brand_card:  # optional closing name card over the last line
        a, b = seg_bounds[-1]
        lines.append(card_events({"card": CHANNEL_NAME.upper(), "card_kind": "brand"}, a, b))
    if CHANNEL_TAG:
        tag_end = seg_bounds[-1][0] if brand_card else total
        lines.append(f"Dialogue: 1,{ass_time(0.3)},{ass_time(tag_end)},Tag,,0,0,0,,{{\\fad(500,0)\\1a&H55&}}{esc(CHANNEL_TAG)}")
    return head + "\n".join(lines) + "\n"


# --------------------------------------------------- HTML motion graphics
def hook_lines(title):
    """split the hook title into 1 to 3 big lines; returns (lines, index of the gold line)"""
    words = (title or "").split() or ["QUICK", "ENGLISH", "TIP"]
    if len(words) <= 3:
        lines = words
    else:  # 4 words -> 2 + 2
        lines = [" ".join(words[:2]), " ".join(words[2:])]
    return lines, (1 if len(lines) > 1 else 0)


def build_motion_spec(lesson, tokens, times, segs, bounds, total, cuts=None):
    chunks = chunk_tokens(tokens)
    out_chunks = []
    for ci, chunk in enumerate(chunks):
        a = max(0.0, times[chunk[0]][0] - 0.02)
        nxt = times[chunks[ci + 1][0]][0] if ci + 1 < len(chunks) else total
        last = times[chunk[-1]]
        b = nxt if nxt - last[1] < 0.5 else last[1] + 0.2
        b = min(b, nxt, total)
        words = [[esc(tokens[j]).replace('"', ""), round(times[j][0], 3)] for j in chunk]
        out_chunks.append({"a": round(a, 3), "b": round(max(b, a + 0.45), 3), "words": words})
    for i in range(len(out_chunks) - 1):  # two phrases are never on screen together
        out_chunks[i]["b"] = round(min(out_chunks[i]["b"], out_chunks[i + 1]["a"] - 0.02), 3)
        out_chunks[i]["b"] = max(out_chunks[i]["b"], round(out_chunks[i]["a"] + 0.1, 3))
    lines, gold = hook_lines(lesson.get("hook_title"))
    hook = {"lines": lines, "gold": gold, "a": 0.05, "b": 2.2}
    cards, last_wrong = [], None
    for (a, b), s in zip(bounds, segs):
        if not s["card"]:
            continue
        start = a + 0.1
        if a < hook["b"]:  # the first card waits until the hook title has left the screen
            start = max(start, hook["b"] - 0.1)
        if b - start < 0.7:
            continue
        if set(re.sub(r"[^a-z ]", "", s["card"].lower()).split()) <= set(re.sub(r"[^a-z ]", "", (lesson.get("hook_title") or "").lower()).split()) and a < hook["b"]:
            continue  # the title already says it
        text = s["card"]
        if text.isupper() and len(text) > 3:  # sentence case looks like a real typed sentence
            text = re.sub(r"\bi\b", "I", text[0] + text[1:].lower())
        card = {"a": round(start, 3), "b": round(b, 3), "text": text, "kind": s["card_kind"]}
        d, n = b - start, len(text)
        if s["card_kind"] == "wrong":
            last_wrong = text
        if s["card_kind"] == "neutral" and d >= 2.4:
            ts = start + 0.8
            dt = min(0.07, max(0.03, ((b - 0.55) - ts - 0.7) / max(n, 1)))
            card["ui"] = {"mode": "idea", "ts": round(ts, 3), "dt": round(dt, 4), "err": round(ts + n * dt + 0.1, 3)}
        elif s["card_kind"] in ("wrong", "right") and d >= 2.4:  # these get the animated chat panel
            if s["card_kind"] == "right" and last_wrong:
                ck = min(start + 1.5, b - 1.3)
                card["ui"] = {"mode": "fix", "old": last_wrong, "chip": round(start + 0.5, 3), "click": round(ck, 3)}
            else:
                ts = start + 0.9
                dt = min(0.09, max(0.035, ((b - 0.55) - ts - 0.9) / max(n, 1)))
                te = ts + n * dt
                card["ui"] = {"mode": "wrong" if s["card_kind"] == "wrong" else "ok", "ts": round(ts, 3), "dt": round(dt, 4), "err": round(te + 0.12, 3)}
        cards.append(card)
    spec = {"total": round(total, 3), "fps": FPS, "hook": hook, "cards": cards, "chunks": out_chunks,
            "cuts": [round(c, 3) for c in (cuts or [])], "pace": lesson.get("pace", "medium")}
    spec["sfx"] = sfx_events(spec)
    return spec


def sfx_events(spec):
    """quiet, natural cues: an impact with the title, a soft pop as each card appears, a click for the strike, a small bell for the right answer, a swish on fast cuts"""
    ev = [(0.05, "whoosh"), (0.18, "hit")]
    for c in spec["cards"]:
        ev.append((c["a"] + 0.05, "pop"))
        if c["kind"] == "wrong":
            ev.append((c["a"] + 0.75, "click"))
        elif c["kind"] == "right":
            ev.append((c["a"] + 0.55, "ding"))
    if spec.get("pace") in ("fast", "superfast"):
        ev += [(t - 0.05, "swish") for t in spec.get("cuts", [])]
    elif spec.get("pace") == "medium":
        ev += [(t - 0.05, "swish") for i, t in enumerate(spec.get("cuts", [])) if i % 3 == 0]
    return [(round(t, 3), k) for t, k in ev if 0 <= t < spec["total"]]


# ------------------------------------------------------------------ render
def render_final(total, out, motion_dir=None, sfx_path=None):
    exts = (".mp3", ".m4a", ".wav", ".ogg", ".aac")
    tracks = [p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in exts] if MUSIC_DIR.exists() else []
    music = random.choice(tracks) if tracks else None  # any audio file in assets/ works; one is picked per video
    log(f"background music: {music.name if music else 'none (add a file to the assets folder)'}")
    # soft dark band behind the text lanes, so captions stay readable on any footage
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1920",
         "-vf", ("format=gbrap,geq=r='0':g='0':b='0':a='255*(0.12+0.26*exp(-pow((Y/H-0.5)/0.30,2)))'" if motion_dir
                 else "format=gbrap,geq=r='0':g='0':b='0':a='255*(0.14+0.30*exp(-pow((Y/H-0.47)/0.2,2)))'"),
         "-frames:v", "1", "scrim.png"], cwd=WORK)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", "video.mp4", "-i", "voice.mp3", "-i", "scrim.png"]
    tail = "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100[a]"
    mi = 3  # input number of the music file
    if motion_dir:
        cmd += ["-framerate", str(FPS), "-i", str(Path(motion_dir) / "%05d.png")]
        mi = 4
    si = None
    if sfx_path:
        si = mi
        cmd += ["-i", str(sfx_path)]
        mi += 1
    mus = []
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        mus.append(f"[{mi}:a]volume={MUSIC_VOLUME}[m]")
    mix = ["[v]"] + (["[m]"] if music else []) + (["[fx]"] if sfx_path else [])
    pre = ["[1:a]apad=pad_dur=1[v]"] + mus + ([f"[{si}:a]volume=0.55,apad=pad_dur=1[fx]"] if sfx_path else [])
    if len(mix) > 1:
        fc = ";".join(pre) + f";{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,{tail}"
    else:
        fc = f"[1:a]apad=pad_dur=1,{tail}"
    fd = f":fontsdir='{FONTS_DIR}'" if FONTS_DIR.exists() and any(FONTS_DIR.iterdir()) else ""
    if motion_dir:
        fc += ";[0:v][2:v]overlay=0:0:format=auto[bg];[bg][3:v]overlay=0:0:format=auto[vv]"
    else:
        fc += f";[0:v][2:v]overlay=0:0:format=auto[bg];[bg]ass=captions.ass{fd}[vv]"
    cmd += [
        "-filter_complex", fc, "-map", "[vv]", "-map", "[a]", "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
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
    brand_tag = "#" + re.sub(r"\W", "", CHANNEL_NAME)
    tags_line = " ".join(lesson["hashtags"] + [brand_tag])
    about = f"Hi, I'm {CREATOR_NAME}. On {CHANNEL_NAME} I share one short English tip at a time. Follow for more."
    body = {
        "snippet": {
            "title": lesson["title"],
            "description": f"{lesson['description']}\n\n{about}\n\n{tags_line}",
            "tags": [t.lstrip("#") for t in lesson["hashtags"]] + [CHANNEL_NAME],
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
    setup_fonts()

    history = load_history()
    lesson = ensure_cta(validate(SAMPLE_LESSON) if args.offline_test else make_lesson(history))
    if os.getenv("PACE_FORCE") in PACES:
        lesson["pace"] = os.getenv("PACE_FORCE")
    segs = lesson["segments"]
    log("\nTITLE:", lesson["title"])
    for s in segs:
        log("  -", s["say"])

    pace = PACES[lesson.get("pace", "medium")]
    globals()["VOICE_RATE"] = os.getenv("VOICE_RATE_FORCE") or pace["rate"]
    globals()["TRANS"] = pace["trans"]
    log(f"editor: pace={lesson.get('pace', 'medium')} mood={lesson.get('mood', '')} (voice {VOICE_RATE}, cut every ~{pace['cut']}s)")
    text = " ".join(s["say"] for s in segs)
    tokens = text.split()
    voice_path = WORK / "voice.mp3"
    if args.offline_test:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=36",
             "-af", "volume=0.1", "-ar", "24000", "-ac", "1", voice_path])
        wb, sents = [], []
    else:
        spoken = text
        wb, sents = make_voice(text, spoken, voice_path)  # the voice says SPOKEN_NAME; captions keep the real spelling
    audio_dur = probe_duration(voice_path)
    total = q(audio_dur + 0.6)
    times = align(tokens, wb, audio_dur, sents)

    # which words belong to which segment -> time range of each segment
    starts, idx = [], 0
    for s in segs:
        starts.append(0.0 if not starts else q(times[idx][0]))
        idx += len(s["say"].split())
    bounds = [(starts[i], starts[i + 1] if i + 1 < len(starts) else total) for i in range(len(segs))]

    # the editor cuts each segment into shots; faster pace = shorter shots (capped so footage checks stay cheap)
    shots = []
    for sg, (a, b) in zip(segs, bounds):
        d = b - a
        k = max(1, min(4, int(round(d / pace["cut"])), int(d / 1.0)))
        shots += [(sg["visual"], a + d * j / k, a + d * (j + 1) / k) for j in range(k)]
    while len(shots) > 14:  # merge the shortest neighbours
        j = min(range(len(shots) - 1), key=lambda x: shots[x + 1][2] - shots[x][1])
        shots[j:j + 2] = [(shots[j][0], shots[j][1], shots[j + 1][2])]
    used, clip_files = set(), []
    for i, (vis, a, b) in enumerate(shots):
        src = WORK / f"raw_{i}.mp4"
        got = False if args.offline_test else get_footage(vis, used, src, i)
        clip = WORK / f"clip_{i:02d}.mp4"
        pad = (TRANS / 2 if i > 0 else 0) + (TRANS / 2 + 0.4 if i < len(shots) - 1 else 0.4) if MOTION else 0
        make_clip(src if got else None, max(b - a, 0.5) + pad, clip, i)
        clip_files.append(clip.name)
        log(f"shot {i + 1}/{len(shots)}: {'stock footage' if got else 'gradient'} ({b - a:.1f}s) - {vis}")
    bounds_v = [(a, b) for _, a, b in shots]
    assemble(clip_files, bounds_v)

    (WORK / "captions.ass").write_text(build_ass(tokens, times, segs, bounds, total))  # classic look (also the fallback)
    motion_dir, sfx_path = None, None
    if MOTION and MOTION_ENGINE == "html":
        try:
            import motion
            spec = build_motion_spec(lesson, tokens, times, segs, bounds, total, [a for _, a, _ in shots[1:]])
            problems, _ = motion.check_layout(spec, WORK / "motion_check", FONTS_DIR, step=0.1)
            if problems:
                log("motion layout check:", problems[:6])
                raise RuntimeError(f"layout check found {len(problems)} problem(s)")
            motion.render_overlay(spec, WORK / "motion", FONTS_DIR, log)
            motion_dir = WORK / "motion"
            try:
                import sfx
                sfx_path = sfx.make_track(spec["sfx"], total, WORK / "sfx.wav")
                log(f"sound effects: {len(spec['sfx'])} cues")
            except Exception as e:
                log(f"sound effects skipped ({e!r})")
        except Exception as e:
            log(f"HTML motion graphics unavailable ({e!r}); using the classic look instead")
            motion_dir = None
    final = OUT / f"short_{date.today().isoformat()}.mp4"
    try:
        render_final(total, final, motion_dir, sfx_path)
    except Exception as e:
        if not motion_dir:
            raise
        log(f"final render with motion graphics failed ({e!r}); using the classic look instead")
        render_final(total, final, None)
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

    history.append({"date": date.today().isoformat(), "topic": lesson["topic"], "title": lesson["title"], "category": lesson.get("category", ""), "idea": lesson.get("idea", ""), "series": lesson.get("series", "")})
    save_history(history)


if __name__ == "__main__":
    main()
