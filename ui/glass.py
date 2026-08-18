"""
Shared design system — Figtree, pitch black, pure white.
"""

import math
from PyQt5.QtCore import QEasingCurve, QRectF, QPointF
from PyQt5.QtGui import QColor, QPainterPath

ACCENT = QColor(255, 255, 255)
ACCENT_RGB = "255, 255, 255"

WARNING = QColor(255, 90, 70)
WARNING_RGB = "255, 90, 70"

SUCCESS = QColor(255, 255, 255)

# Glass recipe — pitch black base
GLASS_FILL_ALPHA = 0
GLASS_BORDER_ALPHA = 56          # ~22% white
GLASS_SPECULAR_ALPHA = 0
GLASS_SHADOW_ALPHA = 60

ACCENT_BORDER_ALPHA = 56
ACCENT_GLOW_ALPHA = 0
ACCENT_TINT_ALPHA = 0

WARNING_BORDER_ALPHA = 100
WARNING_TINT_ALPHA = 0

RADIUS_PILL = 999
RADIUS_CARD = 18
RADIUS_PANEL = 18
SQUIRCLE_RADIUS = 40  # fixed pixel corner radius for squircle_path() panels
RADIUS_MENU = 12
RADIUS_CONTROL = 9
RADIUS_BUTTON = 9

GROW_DURATION_MS = 220
SHRINK_DURATION_MS = 170
MESSAGE_DURATION_MS = 380

# Figtree font family
# Inter is bundled at assets/fonts/Inter.ttf and registered via
# QFontDatabase.addApplicationFont() in main.py before any window is built.
# It's listed first (not just as a fallback) because 'Figtree' was never
# actually bundled anywhere in this app — on any machine that doesn't
# happen to have Figtree installed system-wide, every QFont/QSS reference
# to it was silently falling through to whatever's next, usually landing
# on Windows' default Segoe UI. Inter is metric-matched to San Francisco
# (Apple's system font) and free to bundle, so it's the actual Mac-like
# look this app renders with everywhere now, guaranteed rather than hoped-for.
FONT_FAMILY = "'Inter Variable', 'Inter', 'Figtree', 'Segoe UI', system-ui, sans-serif"

# For QFont(family, size) calls, which take one literal family name rather
# than a CSS-style fallback list — every such call in the codebase should
# reference this constant instead of hardcoding "Figtree" directly, or it
# silently bypasses FONT_FAMILY above and the bundled font entirely.
QFONT_FAMILY = "Inter"


def grow_curve() -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.OutBack)
    curve.setOvershoot(1.4)
    return curve


def shrink_curve() -> QEasingCurve:
    return QEasingCurve(QEasingCurve.OutCubic)


def message_curve() -> QEasingCurve:
    return QEasingCurve(QEasingCurve.OutCubic)


# ---------------------------------------------------------------------------
# Squircle geometry — continuous-curvature corners of a FIXED radius applied
# to a rect, not a superellipse stretched across the whole width/height.
#
# Why: stretching a superellipse across an entire panel means the curvature
# is a fraction of each full dimension, so on anything but a roughly-square
# shape (like this app's tall settings panel) almost the whole edge reads
# as dead straight and only a sliver near each corner curves — it just
# looks like a slightly-rounded rectangle, not a squircle.
#
# This instead traces a small superellipse arc of fixed pixel radius at
# each of the 4 corners and connects them with straight edges — the same
# construction iOS/Figma "corner smoothing" uses. Radius stays legible and
# consistent no matter the panel's aspect ratio.
# ---------------------------------------------------------------------------
def squircle_path(rect: QRectF, radius: float = 40.0, n: float = 4.0, samples: int = 20) -> QPainterPath:
    l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
    radius = min(radius, rect.width() / 2.0, rect.height() / 2.0)

    steps = [(i / samples) * (math.pi / 2.0) for i in range(samples + 1)]
    qx = [math.cos(p) ** (2.0 / n) for p in steps]
    qy = [math.sin(p) ** (2.0 / n) for p in steps]

    path = QPainterPath()
    path.moveTo(QPointF(l + radius, t))
    path.lineTo(QPointF(r - radius, t))

    cx, cy = r - radius, t + radius  # top-right corner
    for i in range(len(steps)):
        path.lineTo(QPointF(cx + radius * qy[i], cy - radius * qx[i]))

    path.lineTo(QPointF(r, b - radius))

    cx, cy = r - radius, b - radius  # bottom-right corner
    for i in range(len(steps)):
        path.lineTo(QPointF(cx + radius * qx[i], cy + radius * qy[i]))

    path.lineTo(QPointF(l + radius, b))

    cx, cy = l + radius, b - radius  # bottom-left corner
    for i in range(len(steps)):
        path.lineTo(QPointF(cx - radius * qy[i], cy + radius * qx[i]))

    path.lineTo(QPointF(l, t + radius))

    cx, cy = l + radius, t + radius  # top-left corner
    for i in range(len(steps)):
        path.lineTo(QPointF(cx - radius * qx[i], cy - radius * qy[i]))

    path.closeSubpath()
    return path


# Depth recipe — layered, decreasing-alpha shadow rings painted behind a
# squircle panel to fake a soft drop shadow without relying on native
# window shadows (which don't render on WA_TranslucentBackground windows).
SHADOW_LAYERS = [
    # (extra_px_per_side, alpha)
    (2, 90),
    (6, 55),
    (12, 32),
    (20, 18),
    (30, 8),
]
SHADOW_MARGIN = 34  # px of transparent margin a window needs around a
                     # squircle panel for the shadow layers above to fit


GLASS_QSS_PANEL = f"""
    background: #000000;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: {RADIUS_PANEL}px;
"""

GLASS_BUTTON_STYLE = f"""
    QPushButton {{
        background: rgba(255, 255, 255, 0.06);
        color: rgba(255, 255, 255, 0.40);
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: {RADIUS_BUTTON}px;
        padding: 0px;
        font-family: 'Inter Variable', 'Inter', 'Figtree', system-ui, sans-serif;
        font-weight: 700;
    }}
    QPushButton:hover {{
        background: rgba(255, 255, 255, 0.10);
        border: 1px solid rgba(255, 255, 255, 0.18);
    }}
    QPushButton:pressed {{
        background: rgba(255, 255, 255, 0.04);
    }}
"""

GLASS_PRIMARY_BUTTON_STYLE = f"""
    QPushButton {{
        background: #ffffff;
        color: #000000;
        border: none;
        border-radius: {RADIUS_BUTTON}px;
        padding: 0px;
        font-family: 'Inter Variable', 'Inter', 'Figtree', system-ui, sans-serif;
        font-weight: 800;
    }}
    QPushButton:hover {{
        background: rgba(255, 255, 255, 0.90);
    }}
    QPushButton:pressed {{
        background: rgba(255, 255, 255, 0.75);
    }}
"""
