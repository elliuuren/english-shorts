"""Sound effects made with numpy (no downloads, no copyright). Natural: filtered noise, thumps, soft clicks, a quiet bell."""
import wave

import numpy as np

SR = 44100
_rng = np.random.default_rng(7)


def _noise(n):
    return _rng.standard_normal(n)


def _lp(x, a):
    y = np.zeros_like(x)
    s = 0.0
    for i in range(len(x)):
        s += (a[i] if hasattr(a, "__len__") else a) * (x[i] - s)
        y[i] = s
    return y


def whoosh(d=0.7, vol=0.5):
    n = int(d * SR)
    a = np.linspace(0.015, 0.5, n) ** 1.6
    y = _lp(_noise(n), a) * np.sin(np.pi * np.arange(n) / n) ** 2
    return vol * y / (np.max(np.abs(y)) + 1e-9)


def swish():
    return whoosh(0.22, 0.28)


def hit():
    """a low impact for the title: sub thump plus a short noisy attack"""
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 48 + 90 * np.exp(-t * 18)
    thump = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
    k = int(0.03 * SR)
    att = np.zeros(n)
    att[:k] = _lp(_noise(k), 0.35) * np.exp(-np.arange(k) / (0.008 * SR))
    y = 0.85 * thump + 0.5 * att
    return 0.8 * y / (np.max(np.abs(y)) + 1e-9)


def tick(i=0):
    n = int(0.018 * SR)
    x = _noise(n)
    x = x - _lp(x, 0.2)  # keep the bright part: a soft keyboard-like click
    return 0.45 * x * np.exp(-np.arange(n) / (0.004 * SR))


def pop():
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * (280 - 120 * t / 0.12) * t) * np.exp(-t * 40)
    k = int(0.012 * SR)
    snap = np.zeros(n)
    snap[:k] = (_noise(k) - _lp(_noise(k), 0.3)) * np.exp(-np.arange(k) / (0.003 * SR))
    return 0.6 * body + 0.3 * snap


def click():
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    x = _noise(n)
    x = (x - _lp(x, 0.15)) * np.exp(-t * 90)
    return 0.55 * x / (np.max(np.abs(x)) + 1e-9)


def ding():
    """a small soft bell (inharmonic partials, quick decay), quiet"""
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    y = np.zeros(n)
    for r, a, dec in ((1.0, 1.0, 5.0), (2.76, 0.45, 8.0), (5.4, 0.2, 12.0)):
        y += a * np.sin(2 * np.pi * 880 * r * t) * np.exp(-t * dec)
    y *= np.minimum(1, t / 0.003)
    return 0.32 * y / (np.max(np.abs(y)) + 1e-9)


def thud():
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * (70 - 25 * t / 0.25) * t) * np.exp(-t * 16)
    return 0.55 * y


SOUNDS = {"whoosh": whoosh, "swish": swish, "hit": hit, "pop": pop, "click": click, "ding": ding, "thud": thud,
          "chime": ding, "error": thud}


def make_track(events, total, path):
    """events: [(seconds, kind)]"""
    out = np.zeros(int((total + 1.5) * SR), dtype=np.float32)
    cache = {k: f() for k, f in SOUNDS.items()}
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
