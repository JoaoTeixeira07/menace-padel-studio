#!/usr/bin/env python3
"""thrill.com MULTI-LINE COVER generator (1080x1350).

Usage:
    python3 multiline_render.py data.json out.png photo.jpg

data.json:
{
  "text": "Arturo Coello | Season by season",   # 2-3 lines; "|" forces breaks, otherwise automatic
  "subtitle": "The stats showing performance over the years",   # optional, set in capitals
  "position": "bottom",            # "bottom" (default) or "top"
  "bw": false,
  "bg_focus_y": 0.35, "bg_focus_x": 0.5, "bg_zoom": 1.0
}
Lime: text in [brackets]. Without brackets: 2 lines -> 2nd line lime, 3 lines -> middle line lime.
Every line is scaled to the same width (like the published examples), so shorter lines are taller.
Bottom: photo -> black gradient from the bottom -> lines (+ subtitle); logo top-left.
Top:    photo -> black gradient from the top -> lines; logo bottom-right; subtitle stays at the bottom.
Same font and text effect as the 1-word template (Neue Plak Compressed Black, 70/60 stretch).
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
SUB_GAP = 30                   # "bottom" layout: last baseline -> subtitle cap top
W_BOTTOM_BASE = 1320           # last baseline, "bottom" layout without subtitle (multiline.psd)
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


# ---------- lines ----------
L_W = 1010                     # every line is scaled to this width: the "boxy" block (multiline.psd, ~35 px side margins)
L_MAX_CAP = 190                # very short lines stop growing here
L_GAP = 18                     # gap between lines, baseline -> next cap top (multiline.psd)
L_TOP_Y = 40                   # "top" layout: cap top of the first line
SHADE_FROM, SHADE_MAX = 1000, 215   # "top" layout with subtitle: soft black shade at the bottom
LIME_TOP, LIME_BOT, LIME_MID = (194, 247, 33), (118, 200, 22), 0.77   # multiline.psd gradient overlay (midpoint 77%)
LIME_GLOW = dict(color=(201, 246, 64), opacity=0.05, size=24)
# black fade of the bottom layout (multiline.psd "Gradient Fill 1"), alpha every 10 px from y=0
ML_FADE = [0] * 76 + [1, 2, 5, 8, 11, 15, 19, 24, 30, 36, 42, 49, 56, 64, 72, 79, 88, 97, 106, 116, 126, 137,
                      148, 159, 171, 183, 194, 206, 218, 229, 240, 249] + [255] * 28


def parse_text(raw):
    raw = raw.strip().strip('"“”«»').strip()
    chars, lime, inside = [], [], False
    for ch in raw:
        if ch == "[":
            inside = True; continue
        if ch == "]":
            inside = False; continue
        chars.append(ch); lime.append(inside)
    text = "".join(chars).upper().replace("'", "’")
    has_marks = any(lime)
    words, cur, curf = [], "", []
    for ch, f in zip(text, lime):
        if ch in " |\n":
            if cur:
                words.append((cur, curf)); cur, curf = "", []
            if ch in "|\n":
                words.append(("|", []))
        else:
            cur += ch; curf.append(f)
    if cur:
        words.append((cur, curf))
    return words, has_marks


def split_lines(words, n_forced=None):
    if any(w == "|" for w, _ in words):
        lines, cur = [], []
        for w in words:
            if w[0] == "|":
                if cur: lines.append(cur)
                cur = []
            else:
                cur.append(w)
        if cur: lines.append(cur)
        return lines
    from itertools import combinations
    k = len(words)
    total = sum(len(w) for w, _ in words) + k - 1
    options = [n_forced] if n_forced else ([2] if total <= 34 else [3])
    options = [min(n, k) for n in options]
    lime_word = [bool(f) and all(f) for _, f in words]
    best = None
    for n in options:
        for cuts in combinations(range(1, k), n - 1):
            idx = (0,) + cuts + (k,)
            ls = [words[idx[i]:idx[i + 1]] for i in range(n)]
            lens = [sum(len(w) for w, _ in l) + len(l) - 1 for l in ls]
            score = max(lens) - min(lens)
            # breaks where white turns lime (or back) are strongly preferred
            score -= 100 * sum(lime_word[c] != lime_word[c - 1] for c in cuts)
            if best is None or score < best[0]:
                best = (score, ls)
    return best[1]


def line_mask(text):
    """Mask of one line, stretched like the PSD and scaled to L_W wide (cap <= L_MAX_CAP)."""
    probe = 400
    f = font(W_FONT, probe)
    cap = -f.getbbox("H", anchor="ls")[1]
    l, t, r, b = f.getbbox(text, anchor="ls")
    k = min(L_W / ((r - l) * W_STRETCH), L_MAX_CAP / cap)
    f = font(W_FONT, max(12, int(probe * k)))
    cap = -f.getbbox("H", anchor="ls")[1]
    l, t, r, b = f.getbbox(text, anchor="ls")
    pad = 40
    m = Image.new("L", (r - l + 2 * pad, b - t + 2 * pad), 0)
    base = pad - t
    return f, cap, base, pad, l, m


def lines_layer(lines, layout, has_marks, sub_cap_top):
    n = len(lines)
    rendered = []
    for i, line in enumerate(lines):
        text = " ".join(w for w, _ in line)
        flags = []
        default = (not has_marks) and ((n == 2 and i == 1) or (n == 3 and i == 1) or (n > 3 and i == n - 1))
        for j, (w, fl) in enumerate(line):
            if j:
                flags.append(flags[-1])
            flags.extend(fl if has_marks else [default] * len(w))
        f, cap, base, pad, l, m = line_mask(text)
        mw, mlime = m.copy(), m.copy()
        dw, dl = ImageDraw.Draw(mw), ImageDraw.Draw(mlime)
        for j, ch in enumerate(text):
            x = pad - l + f.getlength(text[:j])
            (dl if flags[j] else dw).text((x, base), ch, font=f, fill=255, anchor="ls")
        mw = mw.resize((round(mw.width * W_STRETCH), mw.height), Image.LANCZOS)
        mlime = mlime.resize((round(mlime.width * W_STRETCH), mlime.height), Image.LANCZOS)
        rendered.append((mw, mlime, cap, base))
    total = sum(c for _, _, c, _ in rendered) + L_GAP * (n - 1)
    if layout == "top":
        y_cap = L_TOP_Y
    else:
        bottom = (sub_cap_top - SUB_GAP) if sub_cap_top else W_BOTTOM_BASE
        y_cap = bottom - total
    text_rgba = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mask = Image.new("L", (W, H), 0)
    lime_mask = Image.new("L", (W, H), 0)
    rng = np.random.default_rng(7)
    for mw, ml_, cap, base in rendered:
        # colours per row of this line, measured from its cap top (rows outside the cap take the nearest colour)
        rows = np.clip(np.arange(mw.height) - (base - cap), 0, cap - 1)
        t = np.clip((rows - 0.06 * cap) / (0.88 * cap), 0, 1)[:, None]
        wcol = np.array(W_TOP_GREY) * (1 - t) + np.array(W_BOT_GREY) * t
        tl = np.clip((rows - 0.06 * cap) / (0.88 * cap), 0, 1) ** (np.log(0.5) / np.log(LIME_MID))
        lcol = np.array(LIME_TOP) * (1 - tl[:, None]) + np.array(LIME_BOT) * tl[:, None]
        Wm = np.array(mw, np.float32) / 255; Lm = np.array(ml_, np.float32) / 255
        A = np.clip(Wm + Lm, 0, 1)
        tot = np.clip(Wm + Lm, 1e-6, None)
        fill = (wcol[:, None, :] * Wm[..., None] + lcol[:, None, :] * Lm[..., None]) / tot[..., None]
        m_line = Image.fromarray((A * 255).astype(np.uint8), "L")
        inv = ImageChops.invert(m_line).filter(ImageFilter.GaussianBlur(INNER_GLOW["size"] / 2.5))
        g = np.array(inv, np.float32) / 255 * A
        nz = INNER_GLOW["noise"]
        g = np.clip(g * ((1 - nz) + nz * 2 * rng.random(A.shape).astype(np.float32)), 0, 1) * INNER_GLOW["opacity"]
        fill = fill + (255 - fill) * g[..., None]
        line_img = Image.fromarray(np.dstack([fill, A * 255]).astype(np.uint8), "RGBA")
        x = round(W / 2 - mw.width / 2); y = y_cap + cap - base
        text_rgba.alpha_composite(line_img, (x, y)) if x >= 0 and y >= 0 else text_rgba.paste(line_img, (x, y), line_img)
        mask.paste(m_line, (x, y), m_line)
        lime_mask.paste(ml_, (x, y), ml_)
        y_cap += cap + L_GAP
    word = text_rgba
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    white_mask = ImageChops.subtract(mask, lime_mask)
    for m_, col, op in ((white_mask, (255, 255, 255), OUTER_GLOW["opacity"]), (lime_mask, LIME_GLOW["color"], LIME_GLOW["opacity"])):
        sz = OUTER_GLOW["size"]
        ga = m_.filter(ImageFilter.MaxFilter(2 * (sz // 6) + 1)).filter(ImageFilter.GaussianBlur(sz / 2))
        ga = ga.point(lambda v, op=op: min(255, int(v * op * 2.2)))
        glow = Image.new("RGBA", (W, H), col + (0,)); glow.putalpha(ga)
        out.alpha_composite(glow)
    out.alpha_composite(word)
    return out, [" ".join(w for w, _ in l) for l in lines]


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
        raise SystemExit("A photo is required: multiline_render.py data.json out.png photo.jpg")
    layout = (data.get("position") or "bottom").lower()
    sub = (data.get("subtitle") or "").strip()
    words, has_marks = parse_text(data["text"])
    lines = split_lines(words, data.get("lines"))
    bg, _, framing = place_photo(photo, data, need_cutout=False)
    canvas = bg
    canvas.alpha_composite(fade_layer("top") if layout == "top" else ml_fade())
    sl, slines, sub_top = subtitle_layer(sub) if sub else (None, [], None)
    tl, out_lines = lines_layer(lines, layout, has_marks, sub_top)
    if layout == "top" and sub:
        canvas.alpha_composite(bottom_shade())  # keeps the subtitle readable, as in the examples
    canvas.alpha_composite(tl)
    if sl is not None:
        canvas.alpha_composite(sl)
    canvas.alpha_composite(logo_img(), LOGO_BOTTOM_RIGHT if layout == "top" else LOGO_TOP_LEFT)
    canvas.convert("RGB").save(out_path, quality=95)
    return {"lines": out_lines, "position": layout, "subtitle_lines": slines, "bw": bool(data.get("bw")), "framing": framing}


def ml_fade():
    col = np.interp(np.arange(H), np.arange(len(ML_FADE)) * 10, ML_FADE).astype(np.uint8)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    layer.putalpha(Image.fromarray(np.repeat(col[:, None], W, 1), "L"))
    return layer


def bottom_shade():
    col = (np.clip((np.arange(H) - SHADE_FROM) / (H - SHADE_FROM), 0, 1) ** 1.2 * SHADE_MAX).astype(np.uint8)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    layer.putalpha(Image.fromarray(np.repeat(col[:, None], W, 1), "L"))
    return layer


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(render(data, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None), ensure_ascii=False))
