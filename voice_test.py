"""Voice test: reads the same short script in several voices, including a clone of YOUR voice, so you can listen and choose.
Your recording goes in the repo as assets/voice_ref.m4a (or .mp3 / .wav / .ogg): 10 to 20 seconds, quiet room, talking the way you'd talk to a friend."""
import asyncio, glob, subprocess, time, traceback
from pathlib import Path

OUT = Path("voice_test_out")
OUT.mkdir(exist_ok=True)
TEXT = ("Stop saying, \"I am agree.\" It feels natural, but it's a tiny mistake. "
        "Agree is a verb, not an adjective. So just say, \"I agree.\" That's it. "
        "Use it once today, and see how good it feels.")


def mp3(src, dst):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-ac", "1", "-b:a", "96k", str(dst)], check=True)


def edge_samples():
    import edge_tts
    for v in ("en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-ChristopherNeural", "en-GB-RyanNeural"):
        try:
            asyncio.run(edge_tts.Communicate(TEXT, v, rate="+3%").save(str(OUT / f"microsoft_{v.split('-', 2)[2]}.mp3")))
            print("ok", v, flush=True)
        except Exception as e:
            print("skipped", v, e, flush=True)


def clone_samples():
    ref = sorted(glob.glob("assets/voice_ref.*"))
    if not ref:
        print("NO assets/voice_ref.* file found: skipping the clone of your voice", flush=True)
        return
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", ref[0], "-t", "20", "-ac", "1", "-ar", "24000", "ref.wav"], check=True)
    import torchaudio as ta
    from chatterbox.tts import ChatterboxTTS
    t = time.time()
    model = ChatterboxTTS.from_pretrained(device="cpu")
    print(f"model loaded in {time.time() - t:.0f}s", flush=True)
    for tag, ex, cfg in (("natural", 0.5, 0.5), ("lively", 0.7, 0.3), ("calm", 0.35, 0.6)):
        t = time.time()
        wav = model.generate(TEXT, audio_prompt_path="ref.wav", exaggeration=ex, cfg_weight=cfg)
        w = OUT / f"YOUR_VOICE_{tag}.wav"
        ta.save(str(w), wav, model.sr)
        mp3(w, OUT / f"YOUR_VOICE_{tag}.mp3")
        w.unlink()
        print(f"your voice ({tag}): {time.time() - t:.0f}s to make {len(TEXT.split())} words", flush=True)


for fn in (edge_samples, clone_samples):
    try:
        fn()
    except Exception:
        traceback.print_exc()
print(sorted(p.name for p in OUT.iterdir()))
