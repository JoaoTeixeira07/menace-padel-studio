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


def place_photo(photo, data, need_cutout):
    im = Image.open(photo)
    im = ImageOps.exif_transpose(im).convert("RGB")
    if data.get("bw"):
        im = ImageOps.grayscale(im).convert("RGB")
    fx, fy, zoom = data.get("bg_focus_x"), data.get("bg_focus_y"), data.get("bg_zoom")
    own_cut = data.get("cutout")
    auto = need_cutout and not own_cut and (fx is None or fy is None or zoom is None)
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

    bg, cut, framing = place_photo(photo, data, need_cutout=(layout == "top"))
    canvas = bg
    canvas.alpha_composite(fade_layer(layout))  # photo -> gradient -> word -> (player)
    sl, lines, sub_top = subtitle_layer(sub) if sub else (None, [], None)
    wl, capbox = word_layer(word, layout, bool(sub), sub_top)
    canvas.alpha_composite(wl)
    if cut is not None:
        canvas.alpha_composite(cut)
    if sl is not None:
        canvas.alpha_composite(sl)
    lg = logo_img()
    canvas.alpha_composite(lg, LOGO_BOTTOM_RIGHT if layout == "top" else LOGO_TOP_LEFT)
    canvas.convert("RGB").save(out_path, quality=95)
    return {"word": word, "position": layout, "cap_box": capbox, "subtitle_lines": lines, "bw": bool(data.get("bw")), "framing": framing}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(render(data, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None), ensure_ascii=False))
