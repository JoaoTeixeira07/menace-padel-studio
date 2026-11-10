#!/usr/bin/env python3
"""thrill.com MATCH ANNOUNCEMENT (1080x1350): final / semi-final of a tournament.

Usage:
    python3 match_render.py data.json out.png photo.jpg

data.json:
{
  "teams": [[{"name": "A. Galán", "flag": "es"}, {"name": "F. Chingotto", "flag": "ar"}], [...]],  # left, right
                                       # (plain strings also work; flags are needed for "name_style": "flags")
  "name_style": "editorial",            # editorial (default), flags, classic
  "round": "Final",                     # FINAL / SEMIFINAL (any text; set in capitals)
  "tournament": "Pretoria P1",
  "logo": "logo_pretoria_p1.png",       # optional, top-right (from GitHub)
  "local": "za", "date": "2026-11-15", "time": "15:00",   # LOCAL time in the tournament's country (flag shown first)
                                                          # + Spain + Argentina + 1-2 audience countries with a different time
  "times": [["es", "15:00"], ["ar", "10:00"]],                       # optional: set the times by hand instead
  "bg_focus_y": 0.35, "bg_focus_x": 0.5, "bg_zoom": 1.0, "bw": false
}
Layout measured from the published announcements (Pretoria P1, London P1, Madrid P1, Rotterdam P2).
"""
import io, json, os, re, sys, urllib.request, datetime as dt
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

W, H = 1080, 1350
HERE = os.path.dirname(os.path.abspath(__file__))
NAME_CX = (240, 838)          # centre of the left / right pair names
NAME_TOP = 888                # cap top of the first name line
NAME_SIZE, NAME_PITCH = 64, 56
NAME_CONDENSE = 0.84          # names are narrower than plain Anton in the published posts
NAME_MAX_W = 400
TITLE_TOP, TITLE_CAP, TITLE_MAX_W = 1031, 112, 900
TOUR_TOP, TOUR_CAP, TOUR_TRACK = 1187, 40, 0.16
TIME_BASE = 1304
FLAG_W, FLAG_H = 64, 40
ZONES = {"za": "Africa/Johannesburg", "nl": "Europe/Amsterdam", "de": "Europe/Berlin", "be": "Europe/Brussels",
         "se": "Europe/Stockholm", "cl": "America/Santiago", "py": "America/Asuncion", "sa": "Asia/Riyadh",
         "kw": "Asia/Kuwait", "eg": "Africa/Cairo", "es": "Europe/Madrid", "ar": "America/Argentina/Buenos_Aires", "pt": "Europe/Lisbon",
         "uk": "Europe/London", "gb": "Europe/London", "ae": "Asia/Dubai", "qa": "Asia/Qatar", "it": "Europe/Rome",
         "fr": "Europe/Paris", "us": "America/New_York", "mx": "America/Mexico_City", "br": "America/Sao_Paulo"}

SEARCH_DIRS = [HERE, os.getcwd(), "/mnt/project", "/mnt/user-data/uploads"]
DOWNLOADS = {
    "Anton.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
    "Montserrat-var.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
}
FLAG_SVG = "https://raw.githubusercontent.com/lipis/flag-icons/main/flags/4x3/{}.svg"


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def asset(name, required=True):
    stem, ext = os.path.splitext(name)
    key = _norm(stem)
    for d in SEARCH_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                fs, fe = os.path.splitext(f)
                if fe.lower() == ext.lower() and _norm(fs).startswith(key):
                    return os.path.join(d, f)
    if name in DOWNLOADS:
        dst = os.path.join(HERE, name)
        urllib.request.urlretrieve(DOWNLOADS[name], dst)
        return dst
    if required:
        raise FileNotFoundError(f"Missing asset: {name}")
    return None


def anton(size):
    return ImageFont.truetype(asset("Anton.ttf"), size)


def mont(weight, size):
    f = ImageFont.truetype(asset("Montserrat-var.ttf"), size)
    f.set_variation_by_name(weight)
    return f


def cap_of(f):
    return -f.getbbox("H", anchor="ls")[1]


def size_for_cap(fn, cap, *a):
    f = fn(*a, 100)
    return max(8, round(100 * cap / cap_of(f)))


def flag(code, w, h):
    code = {"uk": "gb", "en": "gb-eng"}.get(code.lower(), code.lower())
    p = asset(f"flag_{code}.png", False)
    if p:
        im = Image.open(p).convert("RGBA")
    else:
        svg = urllib.request.urlopen(FLAG_SVG.format(code.lower()), timeout=15).read()
        try:
            import cairosvg
            im = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg, output_width=w * 3, output_height=h * 3))).convert("RGBA")
        except ImportError:
            import subprocess, tempfile
            t = tempfile.NamedTemporaryFile(suffix=".svg", delete=False); t.write(svg); t.close()
            subprocess.run(["rsvg-convert", "-w", str(w * 3), "-h", str(h * 3), t.name, "-o", t.name + ".png"], check=True)
            im = Image.open(t.name + ".png").convert("RGBA")
    return im.resize((w, h), Image.LANCZOS)


def white_logo(path, box):
    im = Image.open(path)
    if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 250:
        out = im.convert("RGBA")
    else:
        out = Image.new("RGBA", im.size, (255, 255, 255, 255)); out.putalpha(im.convert("L"))
    out.thumbnail(box, Image.LANCZOS)
    return out


def glow_text(base, xy, text, f, anchor, glow=0.55, blur=16, tracking=0.0):
    m = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(m)
    if tracking:
        x, y = xy
        total = sum(f.getlength(c) for c in text) + tracking * f.size * (len(text) - 1)
        if anchor[0] == "m":
            x -= total / 2
        for c in text:
            d.text((x, y), c, font=f, fill=255, anchor="l" + anchor[1])
            x += f.getlength(c) + tracking * f.size
    else:
        d.text(xy, text, font=f, fill=255, anchor=anchor)
    if glow:
        g = Image.new("RGBA", base.size, (255, 255, 255, 0))
        g.putalpha(m.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(min(255, v * glow))))
        base.alpha_composite(g)
    layer = Image.new("RGBA", base.size, (255, 255, 255, 0)); layer.putalpha(m)
    base.alpha_composite(layer)


def shadow_text(base, xy, text, f, anchor, scale_x=1.0):
    """White text with a soft drop shadow; scale_x < 1 condenses it (like the Canva names)."""
    l, t, r, b = f.getbbox(text, anchor="ls")
    pad = 20
    m0 = Image.new("L", (r - l + 2 * pad, b - t + 2 * pad), 0)
    ImageDraw.Draw(m0).text((pad - l, pad - t), text, font=f, fill=255, anchor="ls")
    m0 = m0.resize((max(1, round(m0.width * scale_x)), m0.height), Image.LANCZOS)
    x, y = xy
    w = (r - l) * scale_x
    ox = x - w / 2 if anchor[0] == "m" else x
    m = Image.new("L", base.size, 0)
    m.paste(m0, (round(ox - pad * scale_x), round(y + t - pad)))
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    a = Image.new("L", base.size, 0); a.paste(m, (0, 3))
    sh.putalpha(a.filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.7)))
    base.alpha_composite(sh)
    layer = Image.new("RGBA", base.size, (255, 255, 255, 0)); layer.putalpha(m)
    base.alpha_composite(layer)


AUDIENCE = ["mx", "us", "pt", "ae", "br"]   # extra audience countries, in order of priority
COUNTRY_TZ_DEFAULT = ZONES


def compute_times(data):
    """Local time (tournament country) + Spain + Argentina + 1-2 audience countries whose time differs."""
    if data.get("times"):
        return [(c, t) for c, t in data["times"]]
    from zoneinfo import ZoneInfo
    day = dt.date.fromisoformat(data["date"]) if data.get("date") else dt.date.today()
    hh, mm = [int(x) for x in data["time"].split(":")]
    local = (data.get("local") or "es").lower()
    tz = data.get("tz") or ZONES.get(local, "Europe/Madrid")
    src = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=ZoneInfo(tz))
    fmt = lambda c: src.astimezone(ZoneInfo(ZONES[c])).strftime("%H:%M")
    out = [(local, src.strftime("%H:%M"))]
    for c in ["es", "ar"]:
        if c != local:
            out.append((c, fmt(c)))
    seen = {t for _, t in out}
    extra = data.get("audience", AUDIENCE)
    n_extra = data.get("extra", 2 if len(out) < 4 else 1)
    for c in extra:
        if len([x for x in out]) >= 3 + n_extra:
            break
        if c in [x[0] for x in out] or c not in ZONES:
            continue
        t = fmt(c)
        if t not in seen:
            out.append((c, t)); seen.add(t)
    return out


def player(p):
    """'A. Galán' or {"name": "A. Galán", "flag": "es"} -> (NAME, flag)"""
    if isinstance(p, dict):
        return p["name"].strip().upper(), p.get("flag")
    return p.strip().upper(), None


def split_name(n):
    parts = n.split(" ", 1) if "." in n.split(" ")[0] else ["", n]
    if len(parts) == 1:
        parts = ["", parts[0]]
    return parts[0], parts[1]


def text_mask(text, f, scale_x=1.0):
    l, t, r, b = f.getbbox(text, anchor="ls")
    pad = 24
    m = Image.new("L", (r - l + 2 * pad, b - t + 2 * pad), 0)
    ImageDraw.Draw(m).text((pad - l, pad - t), text, font=f, fill=255, anchor="ls")
    if scale_x != 1.0:
        m = m.resize((max(1, round(m.width * scale_x)), m.height), Image.LANCZOS)
    return m, (r - l) * scale_x, pad * scale_x, pad - t   # mask, ink width, left pad, baseline in mask


def paste_glow(base, m, xy, glow=0.35, blur=12, shadow=0.65):
    x, y = int(round(xy[0])), int(round(xy[1]))
    full = Image.new("L", base.size, 0); full.paste(m, (x, y))
    if shadow:
        sh = Image.new("RGBA", base.size, (0, 0, 0, 0)); a = Image.new("L", base.size, 0); a.paste(full, (0, 3))
        sh.putalpha(a.filter(ImageFilter.GaussianBlur(7)).point(lambda v: int(v * shadow))); base.alpha_composite(sh)
    if glow:
        g = Image.new("RGBA", base.size, (255, 255, 255, 0))
        g.putalpha(full.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * glow))); base.alpha_composite(g)
    layer = Image.new("RGBA", base.size, (255, 255, 255, 0)); layer.putalpha(full); base.alpha_composite(layer)


def draw_names(base, data):
    style = data.get("name_style", "editorial")
    pairs = [[player(p) for p in pair] for pair in data["teams"]]
    if style == "classic":   # first version: Anton, condensed
        fs = NAME_SIZE
        while fs > 30 and max(anton(fs).getlength(n) * NAME_CONDENSE for pr in pairs for n, _ in pr) > NAME_MAX_W:
            fs -= 1
        f = anton(fs); cap = cap_of(f); pitch = NAME_PITCH * fs / NAME_SIZE
        for cx, pr in zip(NAME_CX, pairs):
            for j, (n, _) in enumerate(pr):
                shadow_text(base, (cx, NAME_TOP + cap + j * pitch), n, f, "ms", NAME_CONDENSE)
        return
    # editorial / flags: initial thin, surname heavy (Montserrat), soft glow; optional round flag before each name
    use_flags = style == "flags" and all(fl for pr in pairs for _, fl in pr)
    cap_target = 40
    fb = mont("ExtraBold", size_for_cap(mont, cap_target, "ExtraBold"))
    fl_ = mont("Light", fb.size)
    fd = int(cap_target * 1.15)                 # flag diameter
    def width(n):
        ini, sur = split_name(n)
        w = fb.getlength(sur) + (fl_.getlength(ini + " ") if ini else 0)
        return w + (fd + 14 if use_flags else 0)
    k = min(1.0, (NAME_MAX_W - 10) / max(width(n) for pr in pairs for n, _ in pr))
    if k < 1.0:
        fb = mont("ExtraBold", max(18, int(fb.size * k))); fl_ = mont("Light", fb.size); fd = int(fd * k)
    cap = cap_of(fb); pitch = cap * 1.62
    for side, (cx, pr) in enumerate(zip(NAME_CX, pairs)):
        # both lines share the same alignment edge: left pair right-aligned to its centre column, right pair left-aligned
        ws = [width(n) for n, _ in pr]
        block_w = max(ws)
        for j, (n, fl) in enumerate(pr):
            ini, sur = split_name(n)
            base_y = NAME_TOP + 6 + cap + j * pitch
            x = cx - ws[j] / 2
            if use_flags:
                fimg = round_flag(fl, fd)
                base.alpha_composite(fimg, (int(x), int(base_y - cap / 2 - fd / 2)))
                x += fd + 14
            if ini:
                m, w, padl, bl = text_mask(ini + " ", fl_)
                paste_glow(base, m, (x - padl, base_y - bl), glow=0.18, blur=10)
                x += fl_.getlength(ini + " ")
            m, w, padl, bl = text_mask(sur, fb)
            paste_glow(base, m, (x - padl, base_y - bl), glow=0.28, blur=12)


def round_flag(code, d):
    im = flag(code, int(d * 1.34), d)
    im = im.crop(((im.width - d) // 2, 0, (im.width - d) // 2 + d, d))
    m = Image.new("L", (d * 4, d * 4), 0); ImageDraw.Draw(m).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    im.putalpha(m.resize((d, d), Image.LANCZOS))
    out = Image.new("RGBA", (d + 4, d + 4), (0, 0, 0, 0))
    ring = Image.new("L", ((d + 4) * 4, (d + 4) * 4), 0); ImageDraw.Draw(ring).ellipse((0, 0, ring.width - 1, ring.height - 1), fill=255)
    w = Image.new("RGBA", out.size, (255, 255, 255, 0)); w.putalpha(ring.resize(out.size, Image.LANCZOS)); out.alpha_composite(w)
    out.alpha_composite(im, (2, 2))
    return out


def render(data, out_path, photo=None):
    photo = photo or data.get("photo")
    if not photo:
        raise SystemExit("A background photo is required: match_render.py data.json out.png photo.jpg")
    bg = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    if data.get("bw"):
        bg = ImageOps.grayscale(bg).convert("RGB")
    k = max(W / bg.width, H / bg.height) * data.get("bg_zoom", 1.0)
    bg = bg.resize((round(bg.width * k), round(bg.height * k)), Image.LANCZOS)
    fx, fy = data.get("bg_focus_x", 0.5), data.get("bg_focus_y", 0.35)
    x0, y0 = round((bg.width - W) * fx), round((bg.height - H) * fy)
    base = bg.crop((x0, y0, x0 + W, y0 + H)).convert("RGBA")

    # fades: soft dark at the top (logos), strong at the bottom (text)
    col = np.zeros(H, np.float32)
    ys = np.arange(H)
    col += np.clip((180 - ys) / 180, 0, 1) ** 1.5 * 120
    col += np.clip((ys - 760) / 420, 0, 1) ** 1.3 * 235
    col = np.clip(col, 0, 245).astype(np.uint8)
    fade = Image.new("RGBA", (W, H), (0, 0, 0, 255)); fade.putalpha(Image.fromarray(np.repeat(col[:, None], W, 1), "L"))
    base.alpha_composite(fade)

    # logos
    lg = Image.open(asset("thrill_logo.png")).convert("RGBA")
    lg = lg.resize((285, round(lg.height * 285 / lg.width)), Image.LANCZOS)
    base.alpha_composite(lg, (50, 50))
    if data.get("logo"):
        lp = asset(data["logo"], False)
        if lp:
            tl = white_logo(lp, (290, 110))
            base.alpha_composite(tl, (W - 62 - tl.width, 46 + (110 - tl.height) // 2))

    # names: two lines per pair, centred on each side; one size for all four names
    draw_names(base, data)

    # title
    title = data.get("round", "Final").upper()
    ts = size_for_cap(mont, TITLE_CAP, "ExtraBold")
    while ts > 40 and mont("ExtraBold", ts).getlength(title) > TITLE_MAX_W:
        ts -= 2
    f_t = mont("ExtraBold", ts)
    glow_text(base, (W / 2, TITLE_TOP + cap_of(f_t)), title, f_t, "ms", glow=0.9, blur=20)

    # tournament (thin, letter-spaced)
    tour = data.get("tournament", "").upper()
    f_r = mont("Light", size_for_cap(mont, TOUR_CAP, "Light"))
    glow_text(base, (W / 2, TOUR_TOP + cap_of(f_r)), tour, f_r, "ms", glow=0.25, blur=10, tracking=TOUR_TRACK)

    # times with flags (one row, up to 5)
    times = compute_times(data)
    n = len(times)
    fw, fh_, fs_h, gap = (64, 40, 38, 46) if n <= 2 else (54, 34, 34, 34) if n <= 4 else (48, 30, 30, 26)
    f_h = mont("Regular", fs_h)
    parts = [(c, t, fw + 12 + f_h.getlength(t)) for c, t in times]
    total = sum(p[2] for p in parts) + gap * (n - 1)
    x = W / 2 - total / 2
    for c, t, w in parts:
        base.alpha_composite(flag(c, fw, fh_), (int(x), int(TIME_BASE - cap_of(f_h) / 2 - fh_ / 2)))
        ImageDraw.Draw(base).text((x + fw + 12, TIME_BASE), t, font=f_h, fill=(255, 255, 255), anchor="ls")
        x += w + gap

    base.convert("RGB").save(out_path, quality=95)
    return {"title": title, "tournament": tour, "times": times, "name_style": data.get("name_style", "editorial")}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(render(data, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None), ensure_ascii=False))
