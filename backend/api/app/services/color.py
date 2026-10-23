"""sRGB <-> CIELAB (D65) conversion and the CIEDE2000 color difference."""

from math import atan2, cos, degrees, exp, hypot, radians, sin, sqrt

Lab = tuple[float, float, float]

_WHITE = (0.95047, 1.0, 1.08883)
_EPS = (6 / 29) ** 3


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return min(max(c, 0.0), 1.0)


def _f(t: float) -> float:
    return t ** (1 / 3) if t > _EPS else t / (3 * (6 / 29) ** 2) + 4 / 29


def _f_inv(t: float) -> float:
    return t**3 if t > 6 / 29 else 3 * (6 / 29) ** 2 * (t - 4 / 29)


def hex_to_lab(hex_color: str) -> Lab:
    value = hex_color.lstrip("#")
    r, g, b = (_to_linear(int(value[i : i + 2], 16) / 255) for i in (0, 2, 4))
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    fx, fy, fz = _f(x / _WHITE[0]), _f(y / _WHITE[1]), _f(z / _WHITE[2])
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def lab_to_hex(lab: Lab) -> str:
    lightness, a, b = lab
    fy = (lightness + 16) / 116
    x = _WHITE[0] * _f_inv(fy + a / 500)
    y = _WHITE[1] * _f_inv(fy)
    z = _WHITE[2] * _f_inv(fy - b / 200)
    rgb = (
        3.2404542 * x - 1.5371385 * y - 0.4985314 * z,
        -0.9692660 * x + 1.8760108 * y + 0.0415560 * z,
        0.0556434 * x - 0.2040259 * y + 1.0572252 * z,
    )
    return "#" + "".join(f"{round(_to_srgb(c) * 255):02x}" for c in rgb)


def ciede2000(lab1: Lab, lab2: Lab) -> float:
    """CIEDE2000 (kL = kC = kH = 1). Verified against Sharma et al. (2005) test data."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2

    c_bar = (hypot(a1, b1) + hypot(a2, b2)) / 2
    g = 0.5 * (1 - sqrt(c_bar**7 / (c_bar**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = hypot(a1p, b1), hypot(a2p, b2)
    h1p = degrees(atan2(b1, a1p)) % 360
    h2p = degrees(atan2(b2, a2p)) % 360

    dl = l2 - l1
    dc = c2p - c1p
    if c1p * c2p == 0:
        dh = 0.0
    else:
        dh = h2p - h1p
        if dh > 180:
            dh -= 360
        elif dh < -180:
            dh += 360
    d_h = 2 * sqrt(c1p * c2p) * sin(radians(dh / 2))

    l_bar = (l1 + l2) / 2
    cp_bar = (c1p + c2p) / 2
    if c1p * c2p == 0:
        h_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        h_bar = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        h_bar = (h1p + h2p + 360) / 2
    else:
        h_bar = (h1p + h2p - 360) / 2

    t = (
        1
        - 0.17 * cos(radians(h_bar - 30))
        + 0.24 * cos(radians(2 * h_bar))
        + 0.32 * cos(radians(3 * h_bar + 6))
        - 0.20 * cos(radians(4 * h_bar - 63))
    )
    d_theta = 30 * exp(-(((h_bar - 275) / 25) ** 2))
    r_c = 2 * sqrt(cp_bar**7 / (cp_bar**7 + 25**7))
    s_l = 1 + 0.015 * (l_bar - 50) ** 2 / sqrt(20 + (l_bar - 50) ** 2)
    s_c = 1 + 0.045 * cp_bar
    s_h = 1 + 0.015 * cp_bar * t
    r_t = -sin(radians(2 * d_theta)) * r_c

    return sqrt(
        (dl / s_l) ** 2 + (dc / s_c) ** 2 + (d_h / s_h) ** 2 + r_t * (dc / s_c) * (d_h / s_h)
    )
