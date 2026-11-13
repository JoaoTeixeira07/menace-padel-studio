#!/usr/bin/env python3
"""thrill.com 1-WORD template generator (1080x1350).

Usage:
    python3 1word_render.py data.json out.png photo.jpg

data.json:
{
  "word": "GENIUS",                 # one line (1-2 words), typed exactly as wanted
  "subtitle": "Kuwait Major: ...",  # optional; always set in capitals
  "position": "top",                # "top" (default, player in front of the word) or "bottom"
  "bw": false,                      # true = black & white photo
  "bg_focus_y": 0.35,               # optional; for "top" the photo is auto-framed on the player
  "bg_focus_x": 0.5,
  "bg_zoom": 1.0,
  "cutout": "player.png"            # optional: own cut-out PNG (same framing as the photo)
}

Top:    photo -> black gradient (from the top) -> word -> cut-out player; logo bottom-right.
Bottom: photo -> black gradient (from the bottom) -> word (+ subtitle); logo top-left.
Measurements from 1WORD_bottom.psd and the published examples.
"""
import json, os, re, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EDIT = None        # studio_editor.Scene while the editor page is being built (see studio_editor.py)
_FRAMING = {}      # exact photo framing of the last render (zoom, fx, fy), for the editor
W, H = 1080, 1350

# --- design constants ---
W_FONT = "NeuePlak-CompBlack.ttf"
W_STRETCH = 0.7 / 0.6          # PSD: horizontal 70%, vertical 60%
W_MAX_W = 976                  # widest word (side margins ~52)
W_MAX_CAP = 355                # tallest word (short words stop here)
W_TOP_Y = 40                   # cap top, "top" layout
SUB_GAP = 33                   # "bottom" layout: word baseline -> subtitle cap top (PSD)
W_BOTTOM_BASE = 1300           # baseline, "bottom" layout without subtitle
W_TOP_GREY = (255, 255, 255)
W_BOT_GREY = (184, 184, 184)   # gradient overlay white -> #B8B8B8 (scale 88%)
OUTER_GLOW = dict(opacity=0.14, size=24)
INNER_GLOW = dict(opacity=0.19, size=16, noise=0.79)

S_FONT = "Poppins-Bold.ttf"
S_SIZE = 32                    # measured on the published examples (caps)
S_MAX_W = 910
S_LEAD = 31
S_BASE_1 = 1310                # single-line baseline
S_BASE_2 = 1321                # last baseline when 2 lines
S_TOP = (248, 248, 248)
S_BOT = (232, 232, 232)

LOGO_W = 285
LOGO_TOP_LEFT = (50, 50)       # bottom layout
LOGO_BOTTOM_RIGHT = (747, 1153)  # top layout

SHADE_FROM, SHADE_MAX = 1000, 215   # "top" layout with subtitle: soft black shade at the bottom
PLAYER_HEAD_Y = 210            # top layout: where the top of the player's head lands
# black gradient behind the word (user's gradient PNG, alpha every 10 px from the word's edge, 0 after 710 px).
# "top": from the top edge down. "bottom": the same, flipped (from the bottom edge up).
FADE = [252, 251, 250, 249, 248, 247, 246, 244, 243, 241, 239, 237, 235, 232, 229, 226, 223, 219, 216, 211,
        207, 203, 198, 193, 188, 184, 177, 173, 166, 161, 154, 149, 141, 136, 129, 124, 116, 111, 104, 99,
        92, 87, 81, 76, 70, 65, 61, 55, 51, 46, 43, 38, 35, 31, 28, 25, 22, 19, 17, 15, 13, 11, 10, 8, 7,
        6, 5, 5, 4, 3, 3, 0]


def fade_layer(layout):
    col = np.interp(np.arange(H), np.arange(len(FADE)) * 10, FADE, right=0).astype(np.uint8)
    if layout == "bottom":
        col = col[::-1]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    layer.putalpha(Image.fromarray(np.repeat(col[:, None], W, 1), "L"))
    return layer


# ---------- assets ----------
SEARCH_DIRS = [HERE, os.getcwd(), "/mnt/project", "/mnt/user-data/uploads"]
DOWNLOADS = {
    "Poppins-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf",
}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _files():
    for d in SEARCH_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                yield d, f


def asset(name):
    """Find an asset (case/space/dot-insensitive). Licensed fonts may be stored as <Font>_font_b64.txt."""
    stem, ext = os.path.splitext(name)
    key = _norm(stem)
    for d, f in _files():
        fs, fe = os.path.splitext(f)
        if fe.lower() == ext.lower() and _norm(fs).startswith(key):
            return os.path.join(d, f)
    if ext.lower() in (".otf", ".ttf"):
        for d, f in _files():
            if f.lower().endswith(".txt") and _norm(f).startswith(key) and "b64" in f.lower():
                import base64, zlib
                txt = open(os.path.join(d, f), encoding="utf-8").read()
                body = "".join(l.strip() for l in txt.splitlines() if l.strip() and not l.startswith("#"))
                dst = os.path.join(HERE, name)
                open(dst, "wb").write(zlib.decompress(base64.b64decode(body)))
                return dst
    if name in DOWNLOADS:
        import urllib.request
        dst = os.path.join(HERE, name)
        urllib.request.urlretrieve(DOWNLOADS[name], dst)
        return dst
    raise FileNotFoundError(f"Missing asset: {name}. Copy it next to the script (or ask the user to attach it).")


def font(name, size):
    return ImageFont.truetype(asset(name), size)


# ---------- photo ----------
def cover_scale(im, zoom=1.0):
    s = max(W / im.width, H / im.height) * zoom
    return im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)


_SESSION = None
MODEL_MIRROR = "https://github.com/JoaoTeixeira07/menace-padel-studio/releases/download/models/u2net_human_seg.onnx"


def person_mask(im):
    """Alpha mask of the person (rembg, u2net_human_seg). Installs rembg on first use."""
    global _SESSION
    try:
        from rembg import new_session, remove
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages",
                        "rembg", "onnxruntime"], check=True)
        from rembg import new_session, remove
    if _SESSION is None:
        try:
            _SESSION = new_session("u2net_human_seg")
        except Exception:
            # fallback: copy of the model kept in the studio's GitHub release
            import urllib.request
            path = "/tmp/u2net_human_seg.onnx"
            if not os.path.exists(path):
                urllib.request.urlretrieve(MODEL_MIRROR, path)
            _SESSION = new_session("u2net_custom", model_path=path)
    m = remove(im.convert("RGB"), session=_SESSION, only_mask=True, post_process_mask=True)
    # tighten the edge a touch so no background halo shows over the word
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.7))
    return m


def main_people(mask):
    """Bounding box (left, top, right, bottom) of the main person/people, ignoring small passers-by."""
    from scipy import ndimage
    a = np.array(mask) > 128
    lab, n = ndimage.label(a)
    if n == 0:
        return None
    sizes = ndimage.sum(a, lab, range(1, n + 1))
    keep = [i + 1 for i, v in enumerate(sizes) if v >= 0.35 * sizes.max()]
    ys, xs = np.where(np.isin(lab, keep))
    return xs.min(), ys.min(), xs.max(), ys.max()


def place_photo(photo, data, need_cutout, autoframe=None):
    im = Image.open(photo)
    im = ImageOps.exif_transpose(im).convert("RGB")
    if data.get("bw"):
        im = ImageOps.grayscale(im).convert("RGB")
    fx, fy, zoom = data.get("bg_focus_x"), data.get("bg_focus_y"), data.get("bg_zoom")
    own_cut = data.get("cutout")
    autoframe = need_cutout if autoframe is None else autoframe
    auto = autoframe and need_cutout and not own_cut and (fx is None or fy is None or zoom is None)
    head = cx = None
    if auto:
        base = cover_scale(im, 1.0)
        bb = main_people(person_mask(base))
        if bb:
            l, t, r, b = bb
            if zoom is None:
                # zoom in until the top of the head can sit inside the word (PLAYER_HEAD_Y)
                need = (H - PLAYER_HEAD_Y) / max(1, base.height - t)
                zoom = float(np.clip(need, 1.0, 2.5))
            head, cx = t * zoom, (l + r) / 2 * zoom
    zoom = zoom or 1.0
    big = cover_scale(im, zoom)
    if fy is None:
        if head is not None and big.height > H:
            fy = float(np.clip(head - PLAYER_HEAD_Y, 0, big.height - H)) / (big.height - H)
        else:
            fy = 0.35
    if fx is None:
        if cx is not None and big.width > W:
            fx = float(np.clip(cx - W / 2, 0, big.width - W)) / (big.width - W)
        else:
            fx = 0.5
    x0, y0 = round((big.width - W) * fx), round((big.height - H) * fy)
    box = (x0, y0, x0 + W, y0 + H)
    bg = big.crop(box)
    cut = None
    if need_cutout:
        if own_cut:
            c = Image.open(own_cut).convert("RGBA")
            if c.size != bg.size:
                c = cover_scale(c, zoom).crop(box)
            if data.get("bw"):
                c = Image.merge("RGBA", (*ImageOps.grayscale(c.convert("RGB")).convert("RGB").split(), c.getchannel("A")))
            cut = c
        else:
            cut = bg.convert("RGBA")
            cut.putalpha(person_mask(bg))  # recomputed on the final crop for crisp edges
    _FRAMING.update(zoom=zoom, fx=fx, fy=fy)
    return bg.convert("RGBA"), cut, {"zoom": round(zoom, 2), "focus_x": round(fx, 2), "focus_y": round(fy, 2)}


# ---------- word ----------
def word_layer(text, layout, has_sub, sub_cap_top=None):
    """Return RGBA layer (W x H) with the word and its effects, plus its cap box."""
    probe = 600
    f = font(W_FONT, probe)
    cap = -f.getbbox("H", anchor="ls")[1]
    l, t, r, b = f.getbbox(text, anchor="ls")
    k = min(W_MAX_W / ((r - l) * W_STRETCH), W_MAX_CAP / cap)
    size = max(20, int(probe * k))
    f = font(W_FONT, size)
    cap = -f.getbbox("H", anchor="ls")[1]
    l, t, r, b = f.getbbox(text, anchor="ls")
    pad = 60
    m = Image.new("L", (r - l + 2 * pad, b - t + 2 * pad), 0)
    base_in = pad - t
    ImageDraw.Draw(m).text((pad - l, base_in), text, font=f, fill=255, anchor="ls")
    m = m.resize((round(m.width * W_STRETCH), m.height), Image.LANCZOS)
    # position
    if layout == "top":
        base = W_TOP_Y + cap
        accent_top = base + t  # t is negative (ink above baseline)
        if accent_top < 18:
            base += 18 - accent_top
    else:
        base = (sub_cap_top - SUB_GAP) if has_sub and sub_cap_top else W_BOTTOM_BASE
    x = round(W / 2 - m.width / 2)
    y = base - base_in
    mask = Image.new("L", (W, H), 0)
    mask.paste(m, (x, y))
    cap_top, cap_bot = base - cap, base

    # fill: white -> light grey over the cap height (gradient overlay, scale 88%)
    col = np.zeros((H, 3), np.float32)
    ys = np.arange(H)
    span = cap_bot - cap_top
    t_ = np.clip((ys - cap_top - 0.06 * span) / (0.88 * span), 0, 1)[:, None]
    col[:] = np.array(W_TOP_GREY) * (1 - t_) + np.array(W_BOT_GREY) * t_
    fill = np.repeat(col[:, None, :], W, axis=1)
    A = np.array(mask, np.float32) / 255
    # inner glow: white, noisy, along the inside edge
    inv = ImageChops.invert(mask).filter(ImageFilter.GaussianBlur(INNER_GLOW["size"] / 2.5))
    g = np.array(inv, np.float32) / 255 * A
    rng = np.random.default_rng(7)
    noise = rng.random((H, W)).astype(np.float32)
    n = INNER_GLOW["noise"]
    g = np.clip(g * ((1 - n) + n * 2 * noise), 0, 1) * INNER_GLOW["opacity"]
    fill = fill + (255 - fill) * g[..., None]
    rgba = np.dstack([fill, A * 255]).astype(np.uint8)
    word = Image.fromarray(rgba, "RGBA")
    # outer glow: soft white halo
    sz = OUTER_GLOW["size"]
    glow_a = mask.filter(ImageFilter.MaxFilter(2 * (sz // 6) + 1)).filter(ImageFilter.GaussianBlur(sz / 2))
    glow_a = glow_a.point(lambda v: min(255, int(v * OUTER_GLOW["opacity"] * 2.2)))
    glow = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    glow.putalpha(glow_a)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(word)
    return out, (cap_top, cap_bot)


# ---------- circle inset ----------
CIRCLE_D = 430                 # default diameter (circle.psd: 429 px)
CIRCLE_STROKE = 6              # white stroke, inside (circle.psd)
CIRCLE_POS = {                 # centre points for the usual spots; the user can also give "x,y"
    "top-left": (234, 424), "top-right": (846, 424), "top-center": (540, 430),
    "left": (234, 620), "right": (846, 620), "center": (540, 620),
}
X_RED = (237, 28, 36)


def _put(layer, img, xy):
    """alpha_composite that accepts positions partly outside the canvas."""
    x, y = xy
    l, t = max(0, -x), max(0, -y)
    if l >= img.width or t >= img.height:
        return
    img = img.crop((l, t, img.width, img.height))
    layer.alpha_composite(img, (x + l, y + t))


def circle_center(pos, d):
    if isinstance(pos, (list, tuple)) and len(pos) == 2:
        return int(pos[0]), int(pos[1])
    pos = (pos or "top-left").lower().replace(" ", "-").replace("_", "-")
    if "," in pos:
        x, y = pos.split(",")[:2]
        return int(float(x)), int(float(y))
    return CIRCLE_POS.get(pos, CIRCLE_POS["top-left"])


def head_point(mask):
    """(x, y_top) of the head of the largest person in a mask."""
    from scipy import ndimage
    a = np.array(mask) > 128
    lab, n = ndimage.label(a)
    if n == 0:
        return None
    sizes = ndimage.sum(a, lab, range(1, n + 1))
    big = lab == (int(np.argmax(sizes)) + 1)
    ys, xs = np.where(big)
    top, hgt = ys.min(), ys.max() - ys.min()
    sel = ys <= top + max(10, 0.18 * hgt)
    return float(np.median(xs[sel])), int(top)


def auto_position(d, person_alpha, avoid=None):
    """Pick the usual spot where the main player covers the least of the circle."""
    a = np.array(person_alpha, np.float32) / 255 if person_alpha is not None else None
    best = None
    for name in ("top-left", "top-right", "left", "right"):
        cx, cy = CIRCLE_POS[name]
        yy, xx = np.ogrid[:H, :W]
        disc = (xx - cx) ** 2 + (yy - cy) ** 2 <= (d / 2) ** 2
        cover = float(a[disc].mean()) if a is not None else 0.0
        if avoid is not None:
            cover += 0.5 * float(np.array(avoid, np.float32)[disc].mean() / 255)
        if best is None or cover < best[0] - 0.02:
            best = (cover, name)
    return best[1]


def circle_layers(spec, bw, person_alpha=None, avoid=None):
    """Returns (circle RGBA layer, red-X RGBA layer or None, position used) for the inset photo."""
    d = int(spec.get("size", CIRCLE_D))
    pos = spec.get("pos")
    if not pos or str(pos).lower() == "auto":
        pos = auto_position(d, person_alpha, avoid)
    cx, cy = circle_center(pos, d)
    im = ImageOps.exif_transpose(Image.open(spec["photo"])).convert("RGB")
    if bw:
        im = ImageOps.grayscale(im).convert("RGB")
    zoom = spec.get("zoom", 1.0)
    s = max(d / im.width, d / im.height) * zoom
    big = im.resize((max(d, round(im.width * s)), max(d, round(im.height * s))), Image.LANCZOS)
    fx, fy = spec.get("focus_x"), spec.get("focus_y")
    if fx is None or fy is None:
        try:  # centre on the head of the main person in the inset photo
            hc = head_point(person_mask(big))
        except Exception:
            hc = None
        if hc:
            hx, t = hc
            if fx is None and big.width > d:
                fx = float(np.clip(hx - d / 2, 0, big.width - d)) / (big.width - d)
            if fy is None and big.height > d:
                fy = float(np.clip(t - 0.08 * d, 0, big.height - d)) / (big.height - d)
    fx = 0.5 if fx is None else fx
    fy = 0.3 if fy is None else fy
    x0, y0 = round((big.width - d) * fx), round((big.height - d) * fy)
    disc = big.crop((x0, y0, x0 + d, y0 + d)).convert("RGBA")
    ss = 4  # supersampled circle edge
    m = Image.new("L", (d * ss, d * ss), 0)
    ImageDraw.Draw(m).ellipse((0, 0, d * ss - 1, d * ss - 1), fill=255)
    m = m.resize((d, d), Image.LANCZOS)
    disc.putalpha(m)
    ring = Image.new("L", (d * ss, d * ss), 0)
    ImageDraw.Draw(ring).ellipse((0, 0, d * ss - 1, d * ss - 1), outline=255, width=CIRCLE_STROKE * ss)
    ring = ring.resize((d, d), Image.LANCZOS)
    white = Image.new("RGBA", (d, d), (255, 255, 255, 0)); white.putalpha(ring)
    disc.alpha_composite(white)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _put(layer, disc, (cx - d // 2, cy - d // 2))
    if spec.get("pop"):
        # the inset person's head breaks out over the top of the frame (circle.psd "Layer 2 copy")
        try:
            top = max(0, y0 - int(0.12 * d))
            pm = person_mask(big)
            band = Image.new("L", big.size, 0)
            ImageDraw.Draw(band).rectangle((x0, top, x0 + d, y0 + d // 2), fill=255)
            pop = big.convert("RGBA"); pop.putalpha(ImageChops.multiply(pm, band))
            pop = pop.crop((x0, top, x0 + d, y0 + d // 2))
            _put(layer, pop, (cx - d // 2, cy - d // 2 - (y0 - top)))
        except Exception:
            pass
    xl = None
    if spec.get("x"):
        xs = int(d * 0.27); wdt = max(8, int(d * 0.05))
        xm = Image.new("L", (xs * 4, xs * 4), 0)
        dr = ImageDraw.Draw(xm); pad = wdt * 2
        dr.line((pad, pad, xs * 4 - pad, xs * 4 - pad), fill=255, width=wdt * 4)
        dr.line((pad, xs * 4 - pad, xs * 4 - pad, pad), fill=255, width=wdt * 4)
        xm = xm.resize((xs, xs), Image.LANCZOS)
        xi = Image.new("RGBA", (xs, xs), X_RED + (0,)); xi.putalpha(xm)
        sh = Image.new("RGBA", (xs + 40, xs + 40), (0, 0, 0, 0))
        sa = Image.new("L", (xs + 40, xs + 40), 0); sa.paste(xm, (20, 24))
        sh.putalpha(sa.filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.45)))
        xl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        _put(xl, sh, (cx - xs // 2 - 20, cy - d // 2 - int(xs * 0.55) - 20))
        _put(xl, xi, (cx - xs // 2, cy - d // 2 - int(xs * 0.55)))
    if EDIT is not None:   # editor page: the circle is drawn there (movable), not here
        EDIT.circle(spec["photo"], d, cx, cy, zoom, fx, fy, CIRCLE_STROKE, bw, bool(spec.get("x")),
                    bool(spec.get("pop")), person_mask)
    return layer, xl, pos


# ---------- subtitle ----------
def line_w(f, s, track=-0.02):
    return f.getlength(s) + track * f.size * (len(s) - 1)


def wrap_sub(text, f):
    if line_w(f, text) <= S_MAX_W:
        return [text]
    ws = text.split()
    best = None
    for i in range(1, len(ws)):
        a, b = " ".join(ws[:i]), " ".join(ws[i:])
        wa, wb = line_w(f, a), line_w(f, b)
        if max(wa, wb) <= S_MAX_W:
            score = abs(wa - wb) + (0 if wa >= wb else 40)  # balanced, first line a bit longer
            if best is None or score < best[0]:
                best = (score, [a, b])
    return best[1] if best else [text]


def subtitle_layer(text):
    f = font(S_FONT, S_SIZE)
    lines = wrap_sub(text.upper(), f)
    last = S_BASE_1 if len(lines) == 1 else S_BASE_2
    first = last - S_LEAD * (len(lines) - 1)
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    tr = -0.02 * S_SIZE
    for i, s in enumerate(lines):
        x = W / 2 - line_w(f, s) / 2
        for j, ch in enumerate(s):
            d.text((x + f.getlength(s[:j]) + tr * j, first + i * S_LEAD), ch, font=f, fill=255, anchor="ls")
    cap = -f.getbbox("H", anchor="ls")[1]
    y0, y1 = first - cap, last
    grad = Image.new("RGB", (1, H))
    for y in range(H):
        t = min(max((y - y0) / max(1, y1 - y0), 0), 1)
        grad.putpixel((0, y), tuple(int(S_TOP[c] + (S_BOT[c] - S_TOP[c]) * t) for c in range(3)))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(grad.resize((W, H)), (0, 0), mask)
    out.putalpha(mask)
    return out, lines, y0


def logo_img():
    lg = Image.open(asset("thrill_logo.png")).convert("RGBA")
    if lg.width != LOGO_W:
        lg = lg.resize((LOGO_W, round(lg.height * LOGO_W / lg.width)), Image.LANCZOS)
    return lg


def render(data, out_path, photo=None):
    photo = photo or data.get("photo")
    if not photo:
        raise SystemExit("A photo is required: 1word_render.py data.json out.png photo.jpg")
    layout = (data.get("position") or "top").lower()
    sub = (data.get("subtitle") or "").strip()
    word = data["word"].strip().upper()

    circ = data.get("circle")
    bg, cut, framing = place_photo(photo, data, need_cutout=(layout == "top" or bool(circ)),
                                   autoframe=(layout == "top"))
    canvas = bg
    if EDIT is not None:
        canvas = EDIT.photo(photo, _FRAMING["zoom"], _FRAMING["fx"], _FRAMING["fy"], bool(data.get("bw")))
    sl, lines, sub_top = subtitle_layer(sub) if sub else (None, [], None)
    wl, capbox = word_layer(word, layout, bool(sub), sub_top)
    cl = xl = cpos = None
    if circ:
        if EDIT is not None:
            EDIT.defer_circle = True
        cl, xl, cpos = circle_layers(circ, data.get("bw"), cut.getchannel("A") if cut else None)

    def front(with_circle):
        # editor page: circle and player cutout are movable layers; here: composite them
        nonlocal canvas
        if EDIT is not None:
            canvas = EDIT.split(canvas)
            if with_circle:
                EDIT.flush_circle()
            EDIT.cutout(person_mask, cut.getchannel("A"))
            if xl is not None:
                EDIT.xmark()
            return
        if with_circle:
            canvas.alpha_composite(cl)
        canvas.alpha_composite(cut)
        if xl is not None:
            canvas.alpha_composite(xl)

    if layout == "top":
        # photo -> gradient -> word -> circle -> player (front)
        canvas.alpha_composite(fade_layer("top"))
        canvas.alpha_composite(wl)
        front(cl is not None)
        if sub:
            canvas.alpha_composite(bottom_shade())  # over the player too: keeps the subtitle readable
    else:
        # photo -> circle -> player -> gradient -> word
        if cl is not None:
            front(True)
        canvas.alpha_composite(fade_layer("bottom"))
        canvas.alpha_composite(wl)
    if sl is not None:
        canvas.alpha_composite(sl)
    lg = logo_img()
    canvas.alpha_composite(lg, LOGO_BOTTOM_RIGHT if layout == "top" else LOGO_TOP_LEFT)
    if EDIT is not None:
        EDIT.static(canvas)
    canvas.convert("RGB").save(out_path, quality=95)
    return {"word": word, "position": layout, "cap_box": capbox, "subtitle_lines": lines, "bw": bool(data.get("bw")), "framing": framing, "circle": cpos}


def bottom_shade():
    col = (np.clip((np.arange(H) - SHADE_FROM) / (H - SHADE_FROM), 0, 1) ** 1.2 * SHADE_MAX).astype(np.uint8)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    layer.putalpha(Image.fromarray(np.repeat(col[:, None], W, 1), "L"))
    return layer


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--editor"]
    if len(args) < 2:
        print(__doc__); sys.exit(1)
    data = json.load(open(args[0], encoding="utf-8"))
    photo = args[2] if len(args) > 2 else None
    info = render(data, args[1], photo)
    if "--editor" in sys.argv or data.get("editor"):
        # interactive page to drag / zoom the photos: <out>_editor.html (see studio_editor.py)
        import studio_editor
        info["editor"] = studio_editor.run(sys.modules[__name__], data, args[1], photo, accent="#2E7BFF")
    print(json.dumps(info, ensure_ascii=False))
