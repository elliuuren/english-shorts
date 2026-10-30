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
- `CTA`: the closing line. Set to `""` to remove it.
- Run time: the `cron` line (UTC). `30 11 * * *` = 17:30 Bangladesh time. Two runs a day: add a second `- cron:` line.
- Lesson types and hook styles: the `CATEGORIES` and `HOOK_STYLES` lists at the top of `main.py`. Add your own ideas there.
- Background music: put a royalty-free `music.mp3` in a folder called `assets/`. It's mixed in quietly. YouTube Audio Library has free tracks.

## Instagram and TikTok
Every run keeps the MP4 for 7 days under the run's **Artifacts**. Download it and post it by hand (30 seconds). Fully automatic posting to those two needs business accounts and extra approvals, so it's best added later once the YouTube side is working.

## Good to know
- Topics are remembered in `history.json` so lessons don't repeat.
- If the Pexels key is missing or down, the video still renders over a coloured gradient instead of failing.
- Google's free model names change now and then. The script picks the newest working "flash" model automatically; to force one, add `GEMINI_MODEL` to the `env:` block.
- Platform rules and free limits change. Re-check YouTube's policy on repetitive/mass-produced content every so often, and keep varying the lessons.
- To test the video assembly on your own computer without any keys: `python main.py --offline-test` (needs ffmpeg).
