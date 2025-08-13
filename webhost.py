from flask import Flask, request, jsonify, send_file, Response, abort, render_template
import os, io, re, json, base64, hashlib, mimetypes, threading, uuid, PIL
from PIL import Image, ImageDraw, ImageFont, ImageFilter 
from functools import lru_cache

from mutagen.id3 import ID3, ID3NoHeaderError, POPM, COMM, TXXX
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.oggvorbis import OggVorbis
from mutagen.flac import FLAC, Picture
from mutagen import File as MutaFile
from mutagen.wave import WAVE

try:
    import tkinter as tk
    from tkinter import filedialog
    TK_OK = True
except Exception:
    TK_OK = False

app = Flask(__name__)
app.url_map.strict_slashes = False

FORCE_SELECT_ON_START = True
CONFIG = {"library": None}
CONFIG_PATH = os.path.join(os.environ["LOCALAPPDATA"], "Rately", "config.json")
print(f"Config will be stored in {CONFIG_PATH}")
ALLOWED = {".mp3", ".ogg", ".wav", ".m4a", ".flac", ".aac"}

DEFAULT_IMAGE_SIZE = (1080, 1440)
THEME = {
    "bg": "#0B0C0F",
    "panel": "#111318",
    "panel2": "#161821",
    "text": "#FFFFFF",
    "sub": "#B9C0D0",
    "border": "#1E2230",
    "accent": "#FF2D55"
}

os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
if os.path.exists(CONFIG_PATH):
    try:
        CONFIG.update(json.load(open(CONFIG_PATH, "r", encoding="utf-8")))
    except:
        pass

def save_config():
    try:
        json.dump(CONFIG, open(CONFIG_PATH, "w", encoding="utf-8"), indent=2)
    except:
        pass

if FORCE_SELECT_ON_START:
    CONFIG["library"] = None
    save_config()

def b64u(s: bytes) -> str:
    return base64.urlsafe_b64encode(s).decode().rstrip("=")

def tid_for(path: str) -> str:
    return b64u(hashlib.sha1(path.encode("utf-8", "ignore")).digest())

@lru_cache(maxsize=8192)
def path_for_tid(tid: str) -> str:
    for p in scan_files(CONFIG.get("library") or ""):
        if tid_for(p) == tid:
            return p
    raise FileNotFoundError

def scan_files(root: str):
    if not root or not os.path.isdir(root): return []
    out = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            if ext in ALLOWED:
                out.append(os.path.join(dp, fn))
    out.sort(key=lambda p: p.lower())
    return out

def guess_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".mp3":"audio/mpeg",".ogg":"audio/ogg",".wav":"audio/wav",
        ".m4a":"audio/mp4",".flac":"audio/flac",".aac":"audio/aac"
    }.get(ext, mimetypes.guess_type(path)[0] or "application/octet-stream")

def safe(v, default): return v if (v is not None and str(v).strip() != "") else default

def read_meta(path: str):
    ext = os.path.splitext(path)[1].lower()
    title = artist = comment = None
    duration = None
    rating_exact = None
    rating_approx = None
    cover_bytes, cover_mime = None, None

    try:
        mf = MutaFile(path, easy=True)
        if mf and getattr(mf, "info", None):
            try: duration = float(mf.info.length)
            except: pass
        if mf:
            title = (mf.get("title", [None]) or [None])[0]
            artist = (mf.get("artist", [None]) or [None])[0]
            comment = (mf.get("comment", [None]) or [None])[0]
    except Exception:
        pass

    try:
        if ext == ".mp3":
            try: tags = ID3(path)
            except ID3NoHeaderError: tags = ID3()
            title  = safe(title,  (tags.get("TIT2").text[0] if tags.get("TIT2") else None))
            artist = safe(artist, (tags.get("TPE1").text[0] if tags.get("TPE1") else None))
            if not comment:
                comms = [f.text for f in tags.getall("COMM")]
                if comms:
                    comment = ", ".join([c if isinstance(c, str) else "".join(c) for c in comms])
            pops = tags.getall("POPM")
            if pops:
                popv = max([getattr(p, "rating", 0) for p in pops])
                rating_exact = round((popv/255.0)*10.0, 2)
            tx = [t for t in tags.getall("TXXX") if t.desc.upper() == "EXACT_RATING"]
            if tx:
                try: rating_exact = float(tx[0].text[0])
                except: pass
            apics = tags.getall("APIC")
            if apics:
                cover_bytes = apics[0].data
                cover_mime = apics[0].mime or "image/jpeg"

        elif ext == ".flac":
            f = FLAC(path)
            title  = safe(title,  f.get("title",  [None])[0])
            artist = safe(artist, f.get("artist", [None])[0])
            comment = safe(comment, f.get("comment", [None])[0] or f.get("description", [None])[0])
            if "EXACT_RATING" in f:
                try: rating_exact = float(f["EXACT_RATING"][0])
                except: pass
            elif "RATING" in f:
                try: rating_exact = round(float(f["RATING"][0])/10.0, 2)
                except: pass
            elif "FMPS_RATING" in f:
                try: rating_exact = round(float(f["FMPS_RATING"][0])*10.0, 2)
                except: pass
            if f.pictures:
                cover_bytes = f.pictures[0].data
                cover_mime = f.pictures[0].mime

        elif ext == ".ogg":
            og = OggVorbis(path)
            title  = safe(title,  og.get("title",  [None])[0])
            artist = safe(artist, og.get("artist", [None])[0])
            comment = safe(comment, og.get("comment", [None])[0])
            if "EXACT_RATING" in og:
                try: rating_exact = float(og["EXACT_RATING"][0])
                except: pass
            elif "RATING" in og:
                try: rating_exact = round(float(og["RATING"][0])/10.0, 2)
                except: pass
            elif "FMPS_RATING" in og:
                try: rating_exact = round(float(og["FMPS_RATING"][0])*10.0, 2)
                except: pass
            picb64 = og.get("metadata_block_picture", [])
            if picb64:
                try:
                    pic = Picture(base64.b64decode(picb64[0]))
                    cover_bytes, cover_mime = pic.data, pic.mime
                except: pass

        elif ext == ".m4a":
            mp = MP4(path)
            if mp.tags:
                title  = safe(title,  (mp.tags.get("\xa9nam", [None]) or [None])[0])
                artist = safe(artist, (mp.tags.get("\xa9ART", [None]) or [None])[0])
                comment = safe(comment, (mp.tags.get("\xa9cmt", [None]) or [None])[0])
                ff = mp.tags.get("----:com.apple.iTunes:EXACT_RATING")
                if ff and isinstance(ff[0], MP4FreeForm):
                    try: rating_exact = float(ff[0].decode("utf-8"))
                    except: pass
                if rating_exact is None and "rate" in mp.tags:
                    try: rating_exact = round(float(mp.tags["rate"][0]) / 10.0, 2)
                    except: pass
                cov = mp.tags.get("covr")
                if cov:
                    c = cov[0]
                    cover_bytes = bytes(c)
                    cover_mime = "image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"

        elif ext == ".wav":
            w = WAVE(path)
            try:
                tags = w.tags
                if tags:
                    title  = safe(title,  tags.get("TIT2").text[0] if tags.get("TIT2") else None)
                    artist = safe(artist, tags.get("TPE1").text[0] if tags.get("TPE1") else None)
                    if not comment:
                        comms = [f.text for f in tags.getall("COMM")]
                        if comms:
                            comment = ", ".join([c if isinstance(c, str) else "".join(c) for c in comms])
                    pops = tags.getall("POPM")
                    if pops:
                        popv = max([getattr(p, "rating", 0) for p in pops])
                        rating_exact = round((popv/255.0)*10.0, 2)
                    tx = [t for t in tags.getall("TXXX") if t.desc.upper() == "EXACT_RATING"]
                    if tx:
                        try: rating_exact = float(tx[0].text[0])
                        except: pass
                    apics = tags.getall("APIC")
                    if apics:
                        cover_bytes = apics[0].data
                        cover_mime = apics[0].mime or "image/jpeg"
            except:
                pass

    except Exception:
        pass

    title = safe(title, "Unknown Title")
    artist = safe(artist, "Unknown Artist")
    if rating_exact is not None:
        rating_approx = round(max(0, min(5, (rating_exact/2.0)*2))/2, 2)
    else:
        rating_approx = None
    return {
        "title": title, "artist": artist, "duration": duration,
        "rating_exact": rating_exact, "rating_stars": rating_approx,
        "comment": comment, "has_cover": bool(cover_bytes),
        "cover": (cover_bytes, cover_mime)
    }

def write_rating(path: str, r10: float | None, comment_text: str | None):
    def clamp(v, lo, hi): return max(lo, min(hi, v))
    def is_noneish(x):
        try: return x is None or (isinstance(x, float) and (x != x))
        except: return x is None
    ext = os.path.splitext(path)[1].lower()

    if not is_noneish(r10):
        r10 = round(clamp(float(r10), 0.0, 10.0), 2)

    def append_comment(existing, newtxt):
        if not newtxt: return existing
        if not existing or str(existing).strip() == "": return newtxt
        return f"{existing} | {newtxt}"

    if ext == ".mp3":
        try:
            try: tags = ID3(path)
            except ID3NoHeaderError: tags = ID3()
            if is_noneish(r10):
                tags.delall("POPM")
                tags.delall("TXXX:EXACT_RATING")
            else:
                pop = int(round((r10/10.0)*255))
                tags.delall("POPM"); tags.add(POPM(email="TuneRater@local", rating=pop, count=0))
                tags.delall("TXXX:EXACT_RATING"); tags.add(TXXX(encoding=3, desc="EXACT_RATING", text=[f"{r10:.2f}"]))
            if comment_text: tags.add(COMM(encoding=3, lang="eng", desc="", text=comment_text))
            tags.save(path)
        except Exception as e:
            raise

    elif ext == ".flac":
        f = FLAC(path)
        if is_noneish(r10):
            for k in ("RATING","EXACT_RATING","FMPS_RATING"):
                if k in f: del f[k]
        else:
            f["RATING"] = [str(int(round(r10*10)))]
            f["EXACT_RATING"] = [f"{r10:.2f}"]
            f["FMPS_RATING"] = [f"{r10/10.0:.3f}"]
        if comment_text: f["comment"] = [append_comment(f.get("comment", [None])[0], comment_text)]
        f.save()

    elif ext == ".ogg":
        og = OggVorbis(path)
        if is_noneish(r10):
            for k in ("RATING","EXACT_RATING","FMPS_RATING"):
                if k in og: del og[k]
        else:
            og["RATING"] = [str(int(round(r10*10)))]
            og["EXACT_RATING"] = [f"{r10:.2f}"]
            og["FMPS_RATING"] = [f"{r10/10.0:.3f}"]
        if comment_text: og["comment"] = [append_comment(og.get("comment", [None])[0], comment_text)]
        og.save()

    elif ext == ".m4a":
        mp = MP4(path)
        if mp.tags is None: mp.add_tags()
        if is_noneish(r10):
            for k in ("----:com.apple.iTunes:EXACT_RATING",
                      "----:com.apple.iTunes:RATE10",
                      "rate"):
                if k in mp.tags: del mp.tags[k]
        else:
            mp.tags["----:com.apple.iTunes:EXACT_RATING"] = [MP4FreeForm(f"{r10:.2f}".encode("utf-8"))]
            mp.tags["----:com.apple.iTunes:RATE10"] = [MP4FreeForm(f"{int(round(r10*10))}".encode("utf-8"))]
        if comment_text:
            prev = mp.tags.get("\xa9cmt", [""])[0]
            mp.tags["\xa9cmt"] = [append_comment(prev, comment_text)]
        mp.save()

    elif ext == ".wav":
        w = WAVE(path)
        try:
            tags = w.tags
            if tags is None: tags = ID3(); w.tags = tags
            if is_noneish(r10):
                tags.delall("POPM")
                tags.delall("TXXX:EXACT_RATING")
            else:
                pop = int(round((r10/10.0)*255))
                tags.delall("POPM"); tags.add(POPM(email="TuneRater@local", rating=pop, count=0))
                tags.delall("TXXX:EXACT_RATING"); tags.add(TXXX(encoding=3, desc="EXACT_RATING", text=[f"{r10:.2f}"]))
            if comment_text: tags.add(COMM(encoding=3, lang="eng", desc="", text=comment_text))
            w.save()
        except Exception:
            pass

def fallback_cover(size=512):
    img = Image.new("RGB", (size, size), THEME["panel2"])
    d = ImageDraw.Draw(img)
    r = size//3
    d.ellipse((size//2 - r, size//2 - r, size//2 + r, size//2 + r), fill=(35,38,52))
    d.ellipse((size//2 - 20, size//2 - 20, size//2 + 20, size//2 + 20), fill=(20,22,28))
    bio = io.BytesIO(); img.save(bio, format="PNG"); bio.seek(0)
    return bio.getvalue(), "image/png"

def extract_cover_bytes(path: str):
    m = read_meta(path)
    if m["cover"][0]:
        return m["cover"]
    for name in ("cover.jpg","folder.jpg","cover.png","Folder.jpg"):
        p = os.path.join(os.path.dirname(path), name)
        if os.path.exists(p):
            with open(p,"rb") as f: return f.read(), ("image/png" if p.endswith(".png") else "image/jpeg")
    return fallback_cover()
  
PICK_JOBS = {}

def _start_pick_job(job_id):
    out = {"status":"done", "path":"", "canceled": False}
    try:
        if not TK_OK:
            out["canceled"] = True
        else:
            root = tk.Tk()
            root.attributes("-topmost", True)
            root.withdraw()
            path = filedialog.askdirectory(title="Select music folder", parent=root)
            root.attributes("-topmost", False)
            try: root.destroy()
            except: pass
            if path: out["path"] = path
            else: out["canceled"] = True
    except Exception:
        out["canceled"] = True
    PICK_JOBS[job_id] = out

@app.route("/health", methods=["GET", "POST"])
def health():
    return ("", 200)

@app.post("/pick_library_start")
def pick_library_start():
    job_id = uuid.uuid4().hex
    PICK_JOBS[job_id] = {"status":"pending", "path":"", "canceled": False}
    t = threading.Thread(target=_start_pick_job, args=(job_id,), daemon=True)
    t.start()
    return jsonify(ok=True, job_id=job_id)

@app.get("/pick_library_status")
def pick_library_status():
    jid = request.args.get("job_id","")
    st = PICK_JOBS.get(jid)
    if not st:
        return jsonify(ok=False, done=False)

    done = (st.get("status") == "done") or (st.get("path") != "" or st.get("canceled"))
    path = st.get("path","")
    canceled = st.get("canceled", False)

    if done:
        PICK_JOBS.pop(jid, None)

    return jsonify(ok=True, done=done, path=path, canceled=canceled)

def should_auto_pick_on_load() -> bool:
    return bool(FORCE_SELECT_ON_START and not CONFIG.get("library"))

@app.get("/")
def home():
    return render_template("home.html", theme=THEME, auto_pick_on_load=should_auto_pick_on_load())

@app.get("/rate")
def rate_page():
    return render_template("rate.html", theme=THEME, auto_pick_on_load=should_auto_pick_on_load())

@app.get("/render")
def render_page():
    return render_template("render.html", theme=THEME, auto_pick_on_load=should_auto_pick_on_load(), CARDRES=f"{DEFAULT_IMAGE_SIZE[0]}x{DEFAULT_IMAGE_SIZE[1]}")
    
@app.get("/api/library_status")
def api_library_status():
    return jsonify(has_library=bool(CONFIG.get("library")))

@app.post("/set_library")
def set_library():
    data = request.get_json(force=True, silent=True) or {}
    path = (data.get("path") or "").strip().strip('"')
    if not os.path.isdir(path):
        return jsonify(ok=False, error="Folder not found")
    CONFIG["library"] = os.path.abspath(path)
    save_config()
    path_for_tid.cache_clear()
    return jsonify(ok=True, count=len(scan_files(CONFIG["library"])))

@app.get("/api/tracks")
def api_tracks():
    root = CONFIG.get("library")
    tracks = []
    for p in scan_files(root or ""):
        meta = read_meta(p)

        fname = os.path.splitext(os.path.basename(p))[0]

        title = meta.get("title") or ""
        if title.strip() == "" or title.strip().lower() == "unknown title":
            title = fname

        artist = meta.get("artist") or ""
        if artist.strip().lower() == "unknown artist":
            artist = ""

        tracks.append({
            "id": tid_for(p),
            "title": meta["title"],
            "artist": meta["artist"],
            "display_title": title,
            "display_artist": artist,
            "duration": meta["duration"],
            "rating_exact": meta["rating_exact"],
            "rating_stars": meta["rating_stars"],
            "comment": meta["comment"],
        })
    return jsonify(tracks=tracks)


@app.get("/audio/<tid>")
def audio(tid):
    try: path = path_for_tid(tid)
    except: return abort(404)
    rng = request.headers.get("Range", None)
    size = os.path.getsize(path)
    mime = guess_mime(path)
    if rng:
        m = re.match(r"bytes=(\d+)-(\d*)", rng or "")
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size-1
            end = min(end, size-1); length = end - start + 1
            with open(path, "rb") as f:
                f.seek(start); data = f.read(length)
            rv = Response(data, 206, mimetype=mime, direct_passthrough=True)
            rv.headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            rv.headers["Accept-Ranges"] = "bytes"
            rv.headers["Content-Length"] = str(length)
            return rv
    return send_file(path, mimetype=mime)

@app.get("/cover/<tid>")
def cover_route(tid):
    try:
        path = path_for_tid(tid)
        data, mime = extract_cover_bytes(path)
    except:
        data, mime = fallback_cover()
    return Response(data, 200, mimetype=mime)

@app.post("/api/rate/<tid>")
def api_rate(tid):
    try:
        path = path_for_tid(tid)
    except:
        return jsonify(ok=False, error="Not found"), 404

    body = request.get_json(force=True, silent=True) or {}
    rating = body.get("rating")
    comment = body.get("comment")

    try:
        write_rating(path, rating, comment)
        return jsonify(ok=True)
    except Exception as e:
        # log server-side so you get a stack trace in the console
        app.logger.exception("Failed to save rating")
        return jsonify(ok=False, error=str(e)), 500

def draw_card(path, width, height):
    COVER_SCALE = 0.75 # fraction of min(panel_w, panel_h)
    TEXT_SCALE = 1.00 # All text
    TITLE_SCALE = 0.67 # Song name
    ARTIST_SCALE = 1.10 # Artist name
    RATING_SCALE = 1.75 # rating/comment block
    
    meta = read_meta(path)
    title = meta["title"] or ""
    artist = meta["artist"] or ""
    rating = meta["rating_exact"]
    comment = (meta["comment"] or "").strip()

    BASE_TITLE_PX = 92
    BASE_ARTIST_PX = 40
    BASE_TEXT_PX = 30
    
    s = max(0.75, width / 1080.0)
    
    img = Image.new("RGB", (width, height), THEME["bg"])
    draw = ImageDraw.Draw(img)

    cov_bytes, _ = extract_cover_bytes(path)
    cov = Image.open(io.BytesIO(cov_bytes)).convert("RGB")
    blur = max(20, int(40 * s))
    bg = cov.resize((width, height), Image.LANCZOS).filter(ImageFilter.GaussianBlur(blur))
    overlay = Image.new("RGBA", (width, height), (12, 14, 20, 168))
    bg = bg.convert("RGBA"); bg.alpha_composite(overlay)
    img.paste(bg.convert("RGB"), (0, 0))
    
    pad_x = int(width * 0.06)
    pad_y = int(height * 0.06)
    pw, ph = width - 2 * pad_x, height - 2 * pad_y
    radius = max(16, int(32 * s))
    panel = Image.new("RGBA", (pw, ph), (17, 19, 26, 220))
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw, ph], radius=radius, fill=255)
    img.paste(panel, (pad_x, pad_y), mask)
    
    cov_size = int(min(pw, ph) * COVER_SCALE)
    cov_round = Image.new("L", (cov_size, cov_size), 0)
    ImageDraw.Draw(cov_round).rounded_rectangle([0, 0, cov_size, cov_size], radius=max(16, int(24 * s)), fill=255)
    cov_img = cov.resize((cov_size, cov_size), Image.LANCZOS)
    cx = pad_x + (pw - cov_size) // 2
    cy = pad_y + int(ph * 0.06)
    img.paste(cov_img, (cx, cy), cov_round)
    
    def tf(bold=True, sz=48):
        here = os.path.dirname(os.path.abspath(__file__))
        prefer = [
            os.path.join(here, "Inter-Bold.ttf") if bold else os.path.join(here, "Inter-Regular.ttf"),
            "Inter-Bold.ttf" if bold else "Inter-Regular.ttf",
        ]
        win = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        win_candidates = [
            os.path.join(win, "arialbd.ttf") if bold else os.path.join(win, "arial.ttf"),
            os.path.join(win, "segoeuib.ttf") if bold else os.path.join(win, "segoeui.ttf"),
        ]
        pil_fonts = os.path.join(os.path.dirname(PIL.__file__), "fonts")
        dejavu = os.path.join(pil_fonts, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
        for p in (prefer + win_candidates + [dejavu]):
            try:
                return ImageFont.truetype(p, sz)
            except:
                pass
        return ImageFont.load_default()

    def break_word_hard(token, font, max_w):
        out, cur = [], ""
        for ch in token:
            test = cur + ch
            if draw.textlength(test, font=font) <= max_w or not cur:
                cur = test
            else:
                out.append(cur); cur = ch
        if cur: out.append(cur)
        return out

    def wrap_text(text, font, max_w):
        if not text: return []
        words = text.split()
        lines, cur = [], ""
        for w in words:
            cand = (cur + " " + w).strip() if cur else w
            if draw.textlength(cand, font=font) <= max_w:
                cur = cand
            else:
                if cur:
                    lines.append(cur); cur = ""
                if draw.textlength(w, font=font) > max_w:
                    parts = break_word_hard(w, font, max_w)
                    lines.extend(parts[:-1]); cur = parts[-1]
                else:
                    cur = w
        if cur: lines.append(cur)
        return lines

    text_top = cy + cov_size + max(24, int(36 * s))
    inner_side_pad = int(pw * 0.06)
    max_w = pw - inner_side_pad * 2
    text_bottom = pad_y + ph - max(90, int(120 * s))
    text_h_avail = max(120, text_bottom - text_top)

    title_sz = max(24, int(BASE_TITLE_PX  * s * TITLE_SCALE))
    artist_sz = max(16, int(BASE_ARTIST_PX * s * ARTIST_SCALE))
    meta_sz = max(14, int(BASE_TEXT_PX   * s * TEXT_SCALE))

    lh_title = lambda sz: int(sz * 1.22)
    lh_artist = lambda sz: int(sz * 1.12)
    lh_meta = lambda sz: int(sz * 1.22)

    rating_str = None
    if rating is not None:
        rtxt = f"{rating:.2f}".rstrip("0").rstrip(".")
        rating_str = f"{rtxt}/10"
    meta_text = (f"{rating_str} - {comment}" if (rating_str and comment) else rating_str or comment or "")

    for _ in range(40):
        ft = tf(True, title_sz); fa = tf(False, artist_sz)

        title_lines  = wrap_text(title,  ft, max_w) or [""]
        artist_lines = wrap_text(artist, fa, max_w) or [""]

        meta_rating_sz = int(meta_sz * RATING_SCALE)
        fm = tf(False, meta_rating_sz)
        meta_lines = wrap_text(meta_text, fm, max_w) if meta_text else []

        gap_title_artist = max(4, int(6 * s))
        extra_gap = lh_artist(artist_sz) if meta_lines else 0

        total_h = (
            len(title_lines)  * lh_title(title_sz) +
            gap_title_artist +
            len(artist_lines) * lh_artist(artist_sz) +
            extra_gap +
            len(meta_lines)   * lh_meta(meta_rating_sz)
        )

        if total_h <= text_h_avail:
            break

        scale = max(0.85, text_h_avail / (total_h + 1e-6))
        title_sz  = max(24, int(title_sz  * scale))
        artist_sz = max(16, int(artist_sz * scale))
        meta_sz   = max(14, int(meta_sz   * scale))

    def draw_center_lines(lines, font, y0, line_h, fill=(255,255,255)):
        ycur = y0
        for ln in lines:
            wln = draw.textlength(ln, font=font)
            x = (width - wln) / 2
            draw.text((x, ycur), ln, font=font, fill=fill)
            ycur += line_h
        return ycur

    y = text_top
    ft = tf(True, title_sz); fa = tf(False, artist_sz)
    title_lines  = wrap_text(title,  ft, max_w) or [""]
    artist_lines = wrap_text(artist, fa, max_w) or [""]

    y = draw_center_lines(title_lines, ft, y, lh_title(title_sz))
    y += max(4, int(6 * s))
    y = draw_center_lines(artist_lines, fa, y, lh_artist(artist_sz))

    meta_rating_sz = int(meta_sz * RATING_SCALE)
    fm = tf(False, meta_rating_sz)
    meta_lines = wrap_text(meta_text, fm, max_w) if meta_text else []
    if meta_lines:
        y += lh_artist(artist_sz)
        draw_center_lines(meta_lines, fm, y, lh_meta(meta_rating_sz))

    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

@app.get("/api/render/<tid>")
def api_render(tid):
    try: path = path_for_tid(tid)
    except: return Response("Not found", 404)
    w = int(request.args.get("w", DEFAULT_IMAGE_SIZE[0]))
    h = int(request.args.get("h", DEFAULT_IMAGE_SIZE[1]))
    w = max(600, min(4096, w)); h = max(600, min(4096, h))
    out = draw_card(path, w, h)
    return send_file(out, mimetype="image/png", as_attachment=False, download_name="card.png")

if __name__ == "__main__":
    app.run(port=3478, debug=False)