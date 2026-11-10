#!/usr/bin/env python3
"""thrill.com MEME post (1080x1350): white background, thrill.com profile, text and the meme image(s)
with rounded corners, stacked in the order you choose.

Usage:
    python3 meme_render.py data.json out.png

data.json:
{
  "text": "Me thinking about my Padel partner, who has TWO FULLY FUNCTIONAL LEGS but can't hit two shots in a row",
  "images": ["/mnt/user-data/uploads/meme.jpg"],     # 1-4 images, shown side by side
  "order": ["profile", "text", "image"],               # default; any order of profile / text / image / text2
  "text2": "",                                         # optional second text (e.g. under the profile)
  "align": "center"                                    # center (default) or top
}
"""
import json, os, re, sys, urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageOps
import numpy as np

W, H = 1080, 1350
HERE = os.path.dirname(os.path.abspath(__file__))
X0, X1 = 65, 1015                      # content column (thrill meme example)
TOP_MARGIN, BOTTOM_MARGIN = 108, 108
GAP = {"profile": 42, "text": 50, "text2": 50, "image": 52}   # space after each block
AVATAR = 98                            # avatar size, radius 12
NAME = dict(size=33, weight="Bold", color=(0, 0, 0))
HANDLE = dict(size=26, weight="Regular", color=(122, 122, 122))
BODY = dict(size=37, lead=50, weight="Regular", color=(12, 12, 12))
IMG_RADIUS = 38
IMG_GAP = 6
PROFILE = dict(name="THRILL.COM", handle="@thrill_com", verified=True)

SEARCH_DIRS = [HERE, os.getcwd(), "/mnt/project", "/mnt/user-data/uploads"]
DOWNLOADS = {"Inter-var.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf"}
TWEMOJI = "https://raw.githubusercontent.com/jdecked/twemoji/main/assets/72x72/{}.png"


def asset(name, required=True):
    stem, ext = os.path.splitext(name)
    key = re.sub(r"[^a-z0-9]", "", stem.lower())
    for d in SEARCH_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                fs, fe = os.path.splitext(f)
                if fe.lower() == ext.lower() and re.sub(r"[^a-z0-9]", "", fs.lower()).startswith(key):
                    return os.path.join(d, f)
    if name in DOWNLOADS:
        dst = os.path.join(HERE, name)
        urllib.request.urlretrieve(DOWNLOADS[name], dst)
        return dst
    if required:
        raise FileNotFoundError(f"Missing asset: {name}")
    return None


_F = {}


def inter(weight, size):
    k = (weight, size)
    if k not in _F:
        f = ImageFont.truetype(asset("Inter-var.ttf"), size)
        f.set_variation_by_name(weight)
        _F[k] = f
    return _F[k]


# ---- emoji (Twemoji) so jokes with emoji render properly ----
def _is_emoji(cp):
    return 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF


def split_emoji(s):
    out, buf, i = [], "", 0
    while i < len(s):
        cp = ord(s[i])
        if _is_emoji(cp):
            if buf:
                out.append(("t", buf)); buf = ""
            j = i + 1
            if 0x1F1E6 <= cp <= 0x1F1FF and j < len(s) and 0x1F1E6 <= ord(s[j]) <= 0x1F1FF:
                j += 1
            while j < len(s) and (ord(s[j]) in (0xFE0F, 0x200D) or 0x1F3FB <= ord(s[j]) <= 0x1F3FF or (ord(s[j - 1]) == 0x200D)):
                j += 1
            out.append(("e", s[i:j])); i = j
        else:
            buf += s[i]; i += 1
    if buf:
        out.append(("t", buf))
    return out


_EM = {}


def emoji_img(seq, size):
    if seq not in _EM:
        import io
        cps = [ord(c) for c in seq]
        img = None
        for name in ("-".join(f"{c:x}" for c in cps if c != 0xFE0F), "-".join(f"{c:x}" for c in cps)):
            try:
                img = Image.open(io.BytesIO(urllib.request.urlopen(TWEMOJI.format(name), timeout=10).read())).convert("RGBA"); break
            except Exception:
                pass
        _EM[seq] = img
    return _EM[seq].resize((size, size), Image.LANCZOS) if _EM[seq] else None


def text_w(f, s):
    w = 0
    for k, t in split_emoji(s):
        w += f.size * 1.15 if k == "e" else f.getlength(t)
    return w


def draw_text(img, xy, s, f, color):
    x, y = xy
    d = ImageDraw.Draw(img)
    for k, t in split_emoji(s):
        if k == "e":
            e = emoji_img(t, int(f.size * 1.05))
            if e:
                img.alpha_composite(e, (int(x), int(y - f.size * 0.85)))
            x += f.size * 1.15
        else:
            d.text((x, y), t, font=f, fill=color, anchor="ls")
            x += f.getlength(t)


def wrap(s, f, max_w):
    lines = []
    for para in s.split("\n"):
        cur = ""
        for w in para.split(" "):
            t = (cur + " " + w) if cur else w
            if text_w(f, t) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur); cur = w
        lines.append(cur)
    return lines


def rounded(img, r, corners=(True, True, True, True)):
    """Round the chosen corners (tl, tr, br, bl) of an image."""
    w, h = img.size
    ss = 3
    m = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(m)
    R = r * ss
    d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), R, fill=255)
    W2, H2 = w * ss, h * ss
    squares = [(0, 0, R, R), (W2 - R, 0, W2, R), (W2 - R, H2 - R, W2, H2), (0, H2 - R, R, H2)]
    for keep, box in zip(corners, squares):
        if not keep:
            d.rectangle(box, fill=255)
    out = img.convert("RGBA")
    out.putalpha(m.resize((w, h), Image.LANCZOS))
    return out


def image_row(paths, width, max_h):
    ims = [ImageOps.exif_transpose(Image.open(p)).convert("RGB") for p in paths]
    n = len(ims)
    avail = width - IMG_GAP * (n - 1)
    ratios = [im.width / im.height for im in ims]
    h = avail / sum(ratios)
    crop_h = None
    if h > max_h:
        crop_h = max_h
    h_final = int(crop_h or h)
    row = Image.new("RGBA", (width, h_final), (0, 0, 0, 0))
    x = 0
    widths = [round(avail * r / sum(ratios)) for r in ratios]
    widths[-1] = avail - sum(widths[:-1])
    for i, (im, w) in enumerate(zip(ims, widths)):
        s = max(w / im.width, h_final / im.height)
        im2 = im.resize((max(w, round(im.width * s)), max(h_final, round(im.height * s))), Image.LANCZOS)
        ox, oy = (im2.width - w) // 2, int((im2.height - h_final) * 0.35)
        im2 = im2.crop((ox, oy, ox + w, oy + h_final))
        corners = (i == 0, i == n - 1, i == n - 1, i == 0)
        row.alpha_composite(rounded(im2, IMG_RADIUS, corners), (x, 0))
        x += w + IMG_GAP
    return row


def profile_block():
    """The thrill.com profile, exactly as supplied (meme_profile_thrill.png), scaled to the avatar height."""
    im = Image.open(asset("meme_profile_thrill.png")).convert("RGBA")
    bb = im.getchannel("A").getbbox()
    if bb:
        im = im.crop(bb)
    w = round(im.width * AVATAR / im.height)
    return im.resize((w, AVATAR), Image.LANCZOS)


def text_block(s):
    f = inter(BODY["weight"], BODY["size"])
    lines = wrap(s, f, X1 - X0)
    asc = int(BODY["size"] * 0.95)
    h = asc + BODY["lead"] * (len(lines) - 1) + int(BODY["size"] * 0.3)
    blk = Image.new("RGBA", (X1 - X0, h), (0, 0, 0, 0))
    for i, ln in enumerate(lines):
        draw_text(blk, (0, asc + i * BODY["lead"]), ln, f, BODY["color"])
    return blk


def render(data, out_path):
    order = data.get("order") or ["profile", "text", "image"]
    blocks = []
    for key in order:
        if key == "profile":
            blocks.append((key, profile_block()))
        elif key in ("text", "text2") and data.get(key):
            blocks.append((key, text_block(data[key])))
        elif key == "image":
            blocks.append((key, None))
    if not data.get("images"):
        raise SystemExit("At least one image is needed: \"images\": [\"meme.jpg\"]")
    fixed = sum(b.height for k, b in blocks if b is not None) + sum(GAP[k] for k, _ in blocks[:-1])
    max_h = H - TOP_MARGIN - BOTTOM_MARGIN - fixed
    img_row = image_row(data["images"], X1 - X0, max_h)
    blocks = [(k, img_row if k == "image" else b) for k, b in blocks]
    total = sum(b.height for _, b in blocks) + sum(GAP[k] for k, _ in blocks[:-1])
    y = TOP_MARGIN if data.get("align") == "top" else max(TOP_MARGIN // 2, (H - total) // 2)
    canvas = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    for i, (k, b) in enumerate(blocks):
        canvas.alpha_composite(b, (X0, int(y)))
        y += b.height + (GAP[k] if i < len(blocks) - 1 else 0)
    canvas.convert("RGB").save(out_path, quality=95)
    return {"order": [k for k, _ in blocks], "image_height": img_row.height, "images": len(data["images"])}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    print(json.dumps(render(json.load(open(sys.argv[1], encoding="utf-8")), sys.argv[2]), ensure_ascii=False))
