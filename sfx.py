"""Sound effects made from scratch with numpy (no downloads, no copyright). make_track(events, total, path) writes a mono wav."""
import wave

import numpy as np

SR = 44100


def _env(n, attack=0.004, decay=6.0):
    t = np.arange(n) / SR
    return np.minimum(1.0, t / attack) * np.exp(-decay * t / (n / SR))


def tick(i=0):
    n = int(0.022 * SR)
    t = np.arange(n) / SR
    f = 1500 + (i % 3) * 140
    return 0.5 * np.sign(np.sin(2 * np.pi * f * t)) * _env(n, 0.0008, 7)


def click():
    n = int(0.07 * SR)
    t = np.arange(n) / SR
    return 0.7 * np.sin(2 * np.pi * 320 * t) * _env(n, 0.001, 8)


def pop():
    n = int(0.14 * SR)
    t = np.arange(n) / SR
    f = 800 + 700 * t / (n / SR)
    return 0.6 * np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.003, 6)


def error():
    n = int(0.34 * SR)
    t = np.arange(n) / SR
    f = 190 - 70 * t / (n / SR)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return 0.45 * (2 * ((ph / (2 * np.pi)) % 1) - 1) * _env(n, 0.004, 5) * 0.8


def chime():
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    a = np.sin(2 * np.pi * 660 * t) * _env(n, 0.004, 5)
    b = np.zeros(n)
    k = int(0.11 * SR)
    b[k:] = (np.sin(2 * np.pi * 990 * t[: n - k]) * _env(n - k, 0.004, 5))
    c = np.zeros(n)
    k2 = int(0.22 * SR)
    c[k2:] = (np.sin(2 * np.pi * 1320 * t[: n - k2]) * _env(n - k2, 0.004, 6)) * 0.6
    return 0.4 * (a + b + c)


def whoosh(d=0.75, seed=1):
    n = int(d * SR)
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    a = np.linspace(0.02, 0.55, n) ** 1.5  # filter opens: low rumble to bright air
    y = np.zeros(n)
    s = 0.0
    for i in range(n):
        s += a[i] * (x[i] - s)
        y[i] = s
    env = np.sin(np.pi * np.arange(n) / n) ** 2
    y = y * env
    return 0.9 * y / (np.max(np.abs(y)) + 1e-9) * 0.5


def make_track(events, total, path):
    """events: [(seconds, kind)] with kind in tick, click, pop, error, chime, whoosh"""
    out = np.zeros(int((total + 1.5) * SR), dtype=np.float32)
    cache = {"click": click(), "pop": pop(), "error": error(), "chime": chime(), "whoosh": whoosh()}
    for k, (t, kind) in enumerate(sorted(events)):
        snd = tick(k) if kind == "tick" else cache.get(kind)
        if snd is None:
            continue
        i = int(max(0, t) * SR)
        if i >= len(out):
            continue
        seg = snd[: len(out) - i]
        out[i: i + len(seg)] += seg.astype(np.float32)
    out = np.clip(out, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((out * 32767 * 0.9).astype(np.int16).tobytes())
    return path
