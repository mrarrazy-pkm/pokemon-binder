#!/usr/bin/env python3
"""
Pokemon Binder — local card scanner (EasyOCR + OpenCV)

Reads a folder of card photos, preprocesses each image, OCRs the Pokemon name
and the collector number, resolves the exact card on the Pokemon TCG API, and
writes a JSON file in the web app's own format so you can Import (Merge) it.

Usage:
    python3 scan.py <photos_folder> [-o scanned.json] [-b "Binder 1"]
                    [--lang en id ja] [--api-key KEY] [--debug]

Then in the web app: Import → pick scanned.json  (use "Merge import" so it ADDS
to your collection instead of overwriting it).
"""
import argparse, base64, json, os, re, sys, time, urllib.parse, urllib.request

API = "https://api.pokemontcg.io/v2"
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".tif", ".tiff"}

# ---- lazy heavy imports so --help works without the libs installed ----
def _need(mod, pipname=None):
    try:
        return __import__(mod)
    except ImportError:
        sys.exit(f"Missing '{mod}'. Install deps first:\n"
                 f"    python3 -m pip install -r requirements.txt\n"
                 f"(or: python3 -m pip install {pipname or mod})")

# ---------------- image preprocessing (OpenCV) ----------------
def preprocess(path, debug_dir=None):
    """Return a list of candidate images (BGR np arrays) to OCR: the whole
    straightened card, plus cropped name (top) and number (bottom) bands."""
    cv2 = _need("cv2", "opencv-python-headless")
    np = _need("numpy")
    data = np.fromfile(path, dtype=np.uint8)          # unicode-safe read
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return []
    # downscale very large phone photos for speed, keep aspect
    h, w = img.shape[:2]
    scale = 1600 / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    # try to locate the card as the largest 4-point contour and deskew it
    card = _find_card(cv2, np, img)
    base = card if card is not None else img

    H, W = base.shape[:2]
    name_band = base[0:int(H * 0.22), 0:W]            # name sits near the top
    num_band = base[int(H * 0.80):H, 0:W]             # collector number near bottom

    outs = [_enhance(cv2, base), _enhance(cv2, name_band), _enhance(cv2, num_band)]
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        for i, o in enumerate(outs):
            cv2.imwrite(os.path.join(debug_dir, f"{stem}_{i}.png"), o)
    return outs

def _find_card(cv2, np, img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    big = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(big) < 0.25 * img.shape[0] * img.shape[1]:
        return None  # no card-sized region found; use the whole frame
    peri = cv2.arcLength(big, True)
    approx = cv2.approxPolyDP(big, 0.02 * peri, True)
    if len(approx) != 4:
        return None
    return _warp(cv2, np, img, approx.reshape(4, 2))

def _warp(cv2, np, img, pts):
    s = pts.sum(axis=1); d = np.diff(pts, axis=1)
    tl, br = pts[np.argmin(s)], pts[np.argmax(s)]
    tr, bl = pts[np.argmin(d)], pts[np.argmax(d)]
    rect = np.array([tl, tr, br, bl], dtype="float32")
    wA = np.linalg.norm(br - bl); wB = np.linalg.norm(tr - tl)
    hA = np.linalg.norm(tr - br); hB = np.linalg.norm(tl - bl)
    W, H = int(max(wA, wB)), int(max(hA, hB))
    if W < 50 or H < 50:
        return None
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(img, M, (W, H))

def _enhance(cv2, bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)

# ---------------- OCR (EasyOCR) ----------------
_reader = None
def get_reader(langs):
    global _reader
    if _reader is None:
        easyocr = _need("easyocr")
        print(f"Loading EasyOCR models {langs} (first run downloads ~1GB)…", flush=True)
        _reader = easyocr.Reader(langs, gpu=False)
    return _reader

NUM_RE = re.compile(r"\b([A-Za-z]{0,3}\d{1,3}[A-Za-z]?)\s*/\s*\d{1,3}\b")
PROMO_RE = re.compile(r"\b([A-Z]{1,4}\d{1,4})\b")
NOISE = re.compile(r"\b(HP|PS|BASIC|DASAR|STAGE|TAHAP|EX|GX|VMAX|VSTAR|ABILITY|"
                   r"KEMAMPUAN|POKEMON|WEAKNESS|KELEMAHAN|RESISTANCE|RETREAT)\b", re.I)

def ocr_fields(reader, imgs):
    """Return (name_guess, number_guess) from the preprocessed image bands."""
    texts = []
    for im in imgs:
        for t in reader.readtext(im, detail=0, paragraph=False):
            texts.append(t.strip())
    joined = "\n".join(texts)
    number = ""
    m = NUM_RE.search(joined) or PROMO_RE.search(joined)
    if m:
        number = m.group(1)
    # name: first line with alphabetic content, noise words stripped
    name = ""
    for t in texts:
        c = NOISE.sub(" ", t)
        c = re.sub(r"[^A-Za-z'\- ]", " ", c)
        c = re.sub(r"\s+", " ", c).strip()
        words = [w for w in c.split(" ") if len(w) >= 2]
        if words:
            name = " ".join(words[:2]); break
    return name, number

# ---------------- TCG API ----------------
def api_get(path, api_key=None, tries=5):
    url = f"{API}{path}"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pkbinder-scanner"})
            if api_key:
                req.add_header("X-Api-Key", api_key)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (500, 502, 503, 429) and i < tries - 1:
                time.sleep(0.5 * (i + 1)); continue
            raise
        except Exception:
            if i < tries - 1:
                time.sleep(0.5 * (i + 1)); continue
            raise
    return {"data": []}

def resolve_card(name, number, api_key=None):
    def q(parts):
        return "/cards?q=" + urllib.parse.quote(" ".join(parts)) + \
               "&pageSize=5&orderBy=-set.releaseDate"
    # precise: name + number, then fall back to name only
    for parts in ([f'name:"{name}*"', f'number:"{number}"'] if number else None,
                  [f'name:"{name}*"']):
        if not parts:
            continue
        data = api_get(q(parts), api_key).get("data", [])
        if data:
            return data[0]
    return None

def to_card(c):
    img = (c.get("images") or {})
    price = None
    tp = ((c.get("tcgplayer") or {}).get("prices") or {})
    for variant in ("holofoil", "normal", "reverseHolofoil", "1stEditionHolofoil"):
        if variant in tp and tp[variant].get("market") is not None:
            price = tp[variant]["market"]; break
    return {
        "id": c["id"], "name": c["name"], "set": c["set"]["name"],
        "setId": c["set"]["id"], "number": c.get("number", ""),
        "rarity": c.get("rarity", ""), "artist": c.get("artist", ""),
        "image": img.get("large") or img.get("small", ""), "price": price,
    }

# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(description="Local Pokemon card scanner → web app JSON")
    ap.add_argument("folder", help="folder of card photos")
    ap.add_argument("-o", "--out", default="scanned.json", help="output JSON (default scanned.json)")
    ap.add_argument("-b", "--binder", default="", help="file all scanned cards into this binder name")
    ap.add_argument("--lang", nargs="+", default=["en"],
                    help="EasyOCR langs: en id ja (default en). Japanese='ja', Indonesian='id'")
    ap.add_argument("--api-key", default=os.environ.get("POKEMONTCG_API_KEY", ""),
                    help="optional PokemonTCG API key (higher rate limit)")
    ap.add_argument("--debug", action="store_true", help="save preprocessed crops to ./debug/")
    args = ap.parse_args()

    if not os.path.isdir(args.folder):
        sys.exit(f"Not a folder: {args.folder}")
    files = sorted(f for f in os.listdir(args.folder)
                   if os.path.splitext(f)[1].lower() in IMG_EXT)
    if not files:
        sys.exit(f"No images in {args.folder} (looked for {sorted(IMG_EXT)})")

    reader = get_reader(args.lang)
    cards, unresolved = {}, []
    debug_dir = os.path.join(os.getcwd(), "debug") if args.debug else None

    for i, f in enumerate(files, 1):
        path = os.path.join(args.folder, f)
        print(f"[{i}/{len(files)}] {f} … ", end="", flush=True)
        imgs = preprocess(path, debug_dir)
        if not imgs:
            print("could not read image"); unresolved.append(f); continue
        name, number = ocr_fields(reader, imgs)
        if not name:
            print("no name read"); unresolved.append(f); continue
        try:
            c = resolve_card(name, number, args.api_key)
        except Exception as e:
            print(f"API error ({e})"); unresolved.append(f); continue
        if not c:
            print(f"no match (read name='{name}' num='{number}')"); unresolved.append(f); continue
        cd = to_card(c)
        cid = cd["id"]
        if cid in cards:
            cards[cid]["qty"] += 1
        else:
            cards[cid] = {**cd, "qty": 1, "cond": "NM",
                          "binder": args.binder, "page": "", "slot": "",
                          "added": int(time.time() * 1000)}
        print(f"✓ {cd['name']} — {cd['set']} #{cd['number']}")

    out = {"cards": cards,
           "binders": [{"name": args.binder, "cols": 3, "rows": 3}] if args.binder else []}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(cards)} card(s) → {args.out}")
    if unresolved:
        print(f"{len(unresolved)} photo(s) not matched (add these manually in the app):")
        for u in unresolved:
            print("   -", u)
    print("\nNext: open the web app → Import → pick this file → use 'Merge import'.")

if __name__ == "__main__":
    main()
