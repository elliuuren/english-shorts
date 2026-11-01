# English Shorts Autopilot

Makes and uploads one English-teaching YouTube Short every day. Runs on GitHub's servers, so your computer can be off. Total cost: $0.

**What it does each day:** picks a lesson type and hook style, writes a spoken script (Gemini), has a second pass check the English is correct, records it with a natural neural voice (edge-tts), finds matching stock footage (Pexels), adds word-by-word captions with wrong/right phrase cards, and uploads to YouTube.

---

## One-time setup (about 40 minutes)

### 1. Put the project on GitHub
1. Create a free GitHub account, then a **new public repository** (public = unlimited free run time; your keys stay hidden in Secrets).
2. Upload everything in this folder. The hidden `.github/workflows/daily.yml` file is the important one. If the web uploader skips it: **Add file → Create new file**, type `.github/workflows/daily.yml` as the name, and paste its contents.

### 2. Get two free API keys
- **Gemini** (writes the scripts): https://aistudio.google.com/apikey
- **Pexels** (stock videos): https://www.pexels.com/api/

### 3. Connect your YouTube channel
1. Go to https://console.cloud.google.com, create a project, then **APIs & Services → Library → YouTube Data API v3 → Enable**.
2. **OAuth consent screen**: choose External, fill the basic info, add your own Google account as a test user. Then click **Publish app** (move it to "In production"). Skip this and the login expires after 7 days.
3. **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON and save it next to these files as `client_secret.json`.
4. On your computer, run:
   ```
   pip install google-auth-oauthlib
   python get_youtube_token.py client_secret.json
   ```
   Log in with the Google account that owns your channel (you'll see an "unverified app" warning; that's normal for your own app: Advanced → continue). It prints 3 values.

### 4. Add the secrets
In your repo: **Settings → Secrets and variables → Actions → New repository secret**. Add these five:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | from step 2 |
| `PEXELS_API_KEY` | from step 2 |
| `YT_CLIENT_ID` | printed in step 3 |
| `YT_CLIENT_SECRET` | printed in step 3 |
| `YT_REFRESH_TOKEN` | printed in step 3 |

### 5. Test it
1. **Actions tab → Daily English Short → Run workflow**, tick **"Make the video but don't upload it"**.
2. When it finishes, open the run and download the `short-video` file. Watch it.
3. Happy? Run it again with the box unticked. The video lands on your channel as **private** (see YT_PRIVACY below). Check it in YouTube Studio.
4. After you've checked 3 to 5 videos, open `.github/workflows/daily.yml` and change `YT_PRIVACY: private` to `public`. From then on it's fully automatic, once a day.

If a run fails, GitHub emails you automatically.

---

## Make it yours (all in `daily.yml`)
- `VOICE`: other natural voices: `en-US-AvaNeural`, `en-US-BrianNeural`, `en-US-EmmaNeural`, `en-GB-RyanNeural`, `en-GB-SoniaNeural`.
- `GREETING`: e.g. `"Hey friends!"`. It's spoken right before the hook. Empty = straight into the hook (usually better for retention).
- Run time: the `cron` line (UTC). `17 2,8,14 * * *` = three runs a day, at 08:17, 14:17 and 20:17 Bangladesh time (the hours are UTC: 2, 8, 14).
- Lesson types and hook styles: the `CATEGORIES` and `HOOK_STYLES` lists at the top of `main.py`. Add your own ideas there.
- Background music: put any royalty-free audio file (`.mp3`, `.m4a`, `.wav`) in a folder called `assets/`. With several files, one is picked per video. Loudness: `MUSIC_VOLUME` (default `0.07`).
- Footage rules: by default no people appear at all (`NO_PEOPLE: "1"`), and clips tagged with women, alcohol, pork, romance, nightlife, gambling or smoking are skipped. Add your own banned words with `EXTRA_BLOCKED_WORDS: "word1,word2"`. Tags can miss things, so check videos while `YT_PRIVACY` is `private`.

- Motion graphics (default `MOTION_ENGINE: html`): a kinetic title in the first two seconds, glass key-phrase cards (wrong = red X and a strike, right = green check and a small burst, idea = blue star), and serif subtitles with a gliding gold highlight. Drawn by a headless browser, frame by frame, in three separate lanes so nothing overlaps (`motion.py` + `motion_template.html`). Adds about 3 minutes per run. If the browser step fails, the video is still made with the classic look below. `MOTION_ENGINE: ass` forces the classic look.
- Classic look (fallback; `MOTION: "0"` = plain, `MOTION: "0"` = plain): slow camera moves on the footage, real transitions between scenes, key phrases on solid panels above the centre line (wrong = red, slams in and shakes; right = green, unfolds; neutral = white, rises), and elegant subtitles just below the centre: no outline, a soft shadow, the spoken word in gold. Panels and subtitles use fixed lanes, so they never overlap.

## Getting the video
Each run also publishes the MP4 as a **Release** (repo page, right side, "Releases"; keeps the newest 30). Open it and tap the .mp4 under Assets. It also stays in the run's Artifacts for 7 days. Note: a public repo means releases are public too.

## Instagram and TikTok
Every run keeps the MP4 for 7 days under the run's **Artifacts**. Download it and post it by hand (30 seconds). Fully automatic posting to those two needs business accounts and extra approvals, so it's best added later once the YouTube side is working.

## Good to know
- Topics are remembered in `history.json` so lessons don't repeat.
- If the Pexels key is missing or down, the video still renders over a coloured gradient instead of failing.
- Google's free model names change now and then. The script picks the newest working "flash" model automatically; to force one, add `GEMINI_MODEL` to the `env:` block.
- Platform rules and free limits change. Re-check YouTube's policy on repetitive/mass-produced content every so often, and keep varying the lessons.
- To test the video assembly on your own computer without any keys: `python main.py --offline-test` (needs ffmpeg).

## Branding and fonts
- Channel name `Elliuuren English` (`CHANNEL_NAME`), creator `Elliuuren` (`CREATOR_NAME`). The name is not spoken or shown in the video; the YouTube description and hashtags carry it. `SHOW_BRAND_CARD: "1"` or `CHANNEL_TAG` would show it on screen too (both off).
- Subtitles: Playfair Display SemiBold (elegant serif). Cards: Anton. Both are downloaded at run time (fallback: Montserrat). To use your own fonts, put `subtitle.ttf` (or .otf) and/or `title.ttf` in a `fonts/` folder in the repo; they win over the defaults.
- Footage safety: every stock clip is checked by Gemini (3 frames per clip) and rejected if it shows people, hands, women, alcohol, pork, worship scenes, violence, large text and similar. If the check can't run, the scene uses a calm gradient instead of an unchecked clip. `VET_FOOTAGE: "0"` turns the check off (not recommended).

## Voice
- Default: **Kokoro** (open-source, natural, male: `KOKORO_VOICE: am_michael`; others: am_adam, am_fenrir, am_puck, bm_george, bm_lewis). It installs and downloads its model on the server on every run (about 2 to 3 extra minutes). If anything goes wrong it falls back to the Microsoft voice by itself; the log says which voice was used. `VOICE_ENGINE: edge` forces the old voice.

## Voice and sound effects
- Default voice: Gemini speech (`VOICE_ENGINE: gemini`, `GEMINI_TTS_VOICE: Achird`). Each sentence gets its own acting note (punchy hook, curious question, warm ending). If it fails or the free limit is hit it falls back to Kokoro, then to the Microsoft voice.
- Sound effects (whoosh, typing ticks, error tone, pop, click, chime) are generated by `sfx.py`, no downloads. Quiet under the voice.
- Wrong and right phrases appear in an animated chat panel: the wrong sentence is typed and flagged, then a suggestion is clicked and fixed.
