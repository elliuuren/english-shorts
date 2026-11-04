"""Cinematic colour looks as real 3D LUTs (.cube), made with numpy. No downloads. Used with ffmpeg lut3d."""
import numpy as np

SIZE = 33


def _s(x, k):  # gentle S-curve
    return np.clip(x + k * (x - 0.5) * (1 - np.abs(2 * x - 1)) * 2 * 0.5 + 0.0, 0, 1) if k else x


def _look(rgb, sh, hi, sat, con, lift, gamma, mid=(0, 0, 0)):
    """sh/hi: tint added to shadows/highlights (r,g,b); sat: saturation; con: contrast; lift: raise blacks; gamma: >1 darker mids"""
    lum = (rgb * np.array([0.2126, 0.7152, 0.0722])).sum(-1, keepdims=True)
    out = rgb + np.array(sh) * (1 - lum) ** 2 + np.array(hi) * lum ** 2 + np.array(mid) * (4 * lum * (1 - lum))
    lum2 = (out * np.array([0.2126, 0.7152, 0.0722])).sum(-1, keepdims=True)
    out = lum2 + (out - lum2) * sat
    out = np.clip(out, 0, 1) ** gamma
    out = 0.5 + (out - 0.5) * con
    out = lift + out * (1 - lift)
    return np.clip(out, 0, 1)


LOOKS = {  # name: (shadow tint, highlight tint, saturation, contrast, lifted blacks, gamma, mid tint)
    "teal_orange": ((-0.05, 0.01, 0.07), (0.08, 0.03, -0.07), 1.12, 1.10, 0.015, 1.04, (0, 0, 0)),
    "steel_blue": ((-0.04, 0.0, 0.10), (0.01, 0.02, 0.05), 0.86, 1.12, 0.02, 1.06, (0, 0.01, 0.02)),
    "golden_hour": ((0.03, 0.0, -0.03), (0.10, 0.05, -0.08), 1.14, 1.07, 0.01, 1.03, (0.01, 0.0, -0.01)),
    "faded_film": ((0.0, 0.01, 0.03), (0.04, 0.02, 0.0), 0.88, 0.96, 0.055, 1.0, (0.0, 0.01, 0.0)),
    "moody_green": ((-0.03, 0.04, 0.02), (0.05, 0.04, -0.05), 0.92, 1.12, 0.02, 1.08, (-0.01, 0.02, -0.01)),
    "midnight": ((-0.02, -0.01, 0.09), (0.0, 0.01, 0.06), 0.82, 1.16, 0.0, 1.10, (0.0, 0.0, 0.03)),
}


def write_lut(name, path):
    p = LOOKS[name]
    n = SIZE
    g = np.linspace(0, 1, n)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")  # .cube order: red varies fastest
    rgb = np.stack([r, gg, b], -1).reshape(-1, 3)
    out = _look(rgb, *p)
    with open(path, "w") as f:
        f.write(f'TITLE "{name}"\nLUT_3D_SIZE {n}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        for v in out:
            f.write(f"{v[0]:.5f} {v[1]:.5f} {v[2]:.5f}\n")
    return path
