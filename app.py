"""
Smile Check - a kid-friendly AI tooth screening demo.

How it works:
  1. A kid uploads (or takes) a photo of their teeth.
  2. The photo is shrunk and cleaned (location data removed) in memory - it is never saved.
  3. Azure OpenAI GPT-4o looks at the photo and returns a simple JSON report.
  4. The web page turns that report into stars, a tooth map and kid-friendly tips.

If Azure is not set up, or the internet is down, the site switches to
PRACTICE MODE and shows a clearly-labelled sample result instead.

This is a school demonstration, NOT a medical device.
"""

import base64
import io
import json
import logging
import os

from flask import Flask, jsonify, render_template, request, send_from_directory
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
# encoding="utf-8-sig" also handles files saved by Notepad with a hidden "BOM" mark
# test 


def load_env_file(path: str) -> None:
    """Read KEY=value lines from .env into the environment (no extra package needed).
    utf-8-sig also handles files saved by Notepad with a hidden "BOM" mark."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_env_file(ENV_PATH)

AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
AZURE_KEY = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o").strip()
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21").strip()
FORCE_PRACTICE = os.getenv("PRACTICE_MODE", "").lower() in ("1", "true", "yes")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB upload limit

REGIONS = ["upper-left", "upper-front", "upper-right",
           "lower-left", "lower-front", "lower-right"]

SYSTEM_PROMPT = f"""
You are "Toothie", a friendly tooth helper inside a school science-fair demo for kids aged 8-14.
You look at ONE photo and describe what you can SEE on the teeth. You are not a dentist and you never diagnose.

Rules:
- Speak to a child: short sentences, simple words, warm and encouraging. Never scary, never shaming.
- Always say "might be" or "looks like". Never say "you have a cavity".
- Brown, black or grey spots, holes or chalky white patches can be possible cavities.
  Yellow or white fuzzy build-up near the gums is plaque. Hard yellow/brown crust at the gum line is tartar.
  Even light brown colour on the surface may just be a stain (from tea, juice, etc.).
- A big plastic or model tooth with painted spots is fine: treat it like a real tooth.
- Healthy teeth are NOT spots: natural grooves and their shadows, light yellow or ivory colour,
  see-through edges, shine, and the dark gaps between teeth are all normal.
- Dental mirrors, cheek holders (clear plastic), lips, tongue, gums and the roof of the mouth are not teeth. Never flag them.
- Only flag a spot when you can clearly see it. If you are not sure, do not flag it.
  Clean teeth with no spots is a great, common result: return an empty spots list.
- If the photo does not clearly show teeth, set is_teeth_photo to false and leave spots empty.
- If the photo is too blurry, dark or far away to judge, say so in photo_quality and give tips.
- Do not comment on the person's face, skin, age, gender or anything except the teeth.
- If anything is flagged, gently suggest showing the photo to a grown-up and a dentist.

Return ONLY a JSON object with exactly these keys:
{{
  "is_teeth_photo": true/false,
  "jaw": "upper" | "lower" | "both"  (which teeth the photo shows: palate/roof of mouth visible = upper, tongue in the middle = lower, a front smile = both),
  "photo_quality": "good" | "blurry" | "too_dark" | "too_bright" | "too_far",
  "photo_tip": "one short tip to take a better photo, or empty string",
  "overall": "sparkly" | "okay" | "check_soon",
  "stars": integer 1-5 (5 = teeth look very clean and healthy),
  "headline": "max 8 words, fun and kind",
  "summary": "2 short sentences for a kid",
  "spots": [
    {{
      "region": one of {REGIONS} (as seen in the photo; left = left side of the picture),
      "kind": "possible cavity" | "plaque" | "tartar" | "stain",
      "what_i_see": "max 12 words describing colour/shape",
      "why_it_matters": "1 short kid-friendly sentence",
      "certainty": "low" | "medium" | "high",
      "cell": "the grid square from the SECOND image where the spot is, e.g. \"C4\""
    }}
  ],
  "good_things": ["up to 3 short positive things you notice"],
  "missions": [
    {{"emoji": "one emoji", "title": "max 5 words", "detail": "1 short sentence"}}
  ],
  "dentist_note": "1 kind sentence about visiting the dentist"
}}
You get two copies of the same photo. The SECOND copy has a grid: letters A-F are columns (left to right),
numbers 1-6 are rows (top to bottom). For each spot, give the grid square that contains the spot ON THE TOOTH itself
(not the gums, tongue or roof of the mouth). Look at the grid labels carefully before answering.
Give 3 missions. Give at most 6 spots.
""".strip()


def azure_ready() -> bool:
    return bool(AZURE_ENDPOINT and AZURE_KEY and not FORCE_PRACTICE)


def setup_report() -> None:
    """Print a plain-English check of the Azure settings when the app starts."""
    print("\n  ---- Azure setup check ----")
    print(f"  Looking for settings file: {ENV_PATH}")
    if os.path.exists(ENV_PATH):
        print("  [OK] .env file found")
        with open(ENV_PATH, "rb") as f:
            start = f.read(4)
        if start.startswith(b"\xff\xfe") or start.startswith(b"\xfe\xff"):
            print("  [PROBLEM] .env is saved as UTF-16. Open it in Notepad > Save As > Encoding: UTF-8.")
    else:
        print("  [PROBLEM] No .env file in this folder.")
        others = [n for n in os.listdir(HERE) if "env" in n.lower() and n != ".env.example"]
        if others:
            print(f"  Found these instead: {others}")
            print("  Rename it to exactly  .env  (no .txt at the end).")
            print("  Tip: in File Explorer, View > Show > File name extensions to see hidden '.txt'.")
    print(f"  AZURE_OPENAI_ENDPOINT    : {'[OK] ' + AZURE_ENDPOINT if AZURE_ENDPOINT else '[MISSING]'}")
    print(f"  AZURE_OPENAI_API_KEY     : {'[OK] ****' + AZURE_KEY[-4:] if AZURE_KEY else '[MISSING]'}")
    print(f"  AZURE_OPENAI_DEPLOYMENT  : {AZURE_DEPLOYMENT}")
    print(f"  AZURE_OPENAI_API_VERSION : {AZURE_API_VERSION}")
    if FORCE_PRACTICE:
        print("  [PROBLEM] PRACTICE_MODE is set to 1 in .env. Change it to 0.")
    if AZURE_ENDPOINT and "openai.azure.com" not in AZURE_ENDPOINT and "cognitiveservices.azure.com" not in AZURE_ENDPOINT:
        print("  [CHECK] Endpoint usually looks like https://NAME.openai.azure.com/")
    if azure_ready():
        try:
            from openai import AzureOpenAI
            client = AzureOpenAI(azure_endpoint=AZURE_ENDPOINT, api_key=AZURE_KEY,
                                 api_version=AZURE_API_VERSION, timeout=30)
            chat(client, max_out=20, messages=[{"role": "user", "content": "Say OK"}])
            print("  [OK] Test message to Azure worked! AI mode is ON.")
        except Exception as exc:
            print(f"  [PROBLEM] Azure test failed: {exc}")
            print("  401 = wrong key | 404 = wrong deployment name or endpoint | "
                  "connection error = no internet")
    print("  ---------------------------\n")


GRID = 6
COLS = "ABCDEF"

# Sample photos visitors can tap to try Smile Check (files in static/samples/)
SAMPLES = [
    # file names say what each photo shows, so a label can never point at the wrong picture
    {"id": "s1", "label": "Bottom teeth A", "jaw": "lower", "file": "bottom-healthy.jpg"},
    {"id": "s2", "label": "Top teeth A",    "jaw": "upper", "file": "top-healthy.jpg"},
    {"id": "s3", "label": "Bottom teeth B", "jaw": "lower", "file": "bottom-early-spots.jpg"},
    {"id": "s4", "label": "Bottom teeth C", "jaw": "lower", "file": "bottom-cavities.jpg"},
    {"id": "s5", "label": "Top teeth B",    "jaw": "upper", "file": "top-cavities.jpg"},
]
SAMPLE_BY_ID = {x["id"]: x for x in SAMPLES}
SAMPLE_CACHE = {}  # sample id -> AI result, so repeat taps are instant and consistent


def prepare_image(file_bytes: bytes) -> Image.Image:
    """Rotate correctly, remove EXIF/location data and shrink. Kept in memory only."""
    img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((1024, 1024))
    return img


def to_b64(img: Image.Image) -> str:
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)  # re-saving drops all metadata
    return base64.b64encode(out.getvalue()).decode()


def grid_copy(img: Image.Image) -> Image.Image:
    """Draw a labelled A1-F6 grid so the AI can point at squares instead of guessing x/y."""
    g = img.copy()
    d = ImageDraw.Draw(g)
    w, h = g.size
    size = max(14, w // 40)
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:  # older Pillow
        font = ImageFont.load_default()
    for i in range(1, GRID):
        d.line([(w * i / GRID, 0), (w * i / GRID, h)], fill=(0, 255, 255), width=2)
        d.line([(0, h * i / GRID), (w, h * i / GRID)], fill=(0, 255, 255), width=2)
    for r in range(GRID):
        for c in range(GRID):
            x, y = w * c / GRID + 3, h * r / GRID + 3
            label = f"{COLS[c]}{r + 1}"
            d.rectangle([x, y, x + size * 1.6, y + size * 1.2], fill=(0, 0, 0))
            d.text((x + 2, y), label, fill=(255, 255, 0), font=font)
    return g


def place_spot(img: Image.Image, spot: dict) -> None:
    """Turn the AI's grid square into an exact dot: look inside that square for
    brown/dark (cavity, stain, tartar) or yellow (plaque) tooth-coloured pixels."""
    cell = spot.get("cell", "")
    if len(cell) < 2 or cell[0] not in COLS or not cell[1:].isdigit() or not 1 <= int(cell[1:]) <= GRID:
        return  # keep whatever x/y we have
    c, r = COLS.index(cell[0]), int(cell[1:]) - 1
    w, h = img.size
    # look in the square plus a quarter-square margin, in case the spot sits on a line
    x0 = int(max(0, (c - 0.25) * w / GRID)); x1 = int(min(w, (c + 1.25) * w / GRID))
    y0 = int(max(0, (r - 0.25) * h / GRID)); y1 = int(min(h, (r + 1.25) * h / GRID))
    a = np.asarray(img.crop((x0, y0, x1, y1)), dtype=np.int16)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    V = a.max(axis=2)
    if spot["kind"] == "plaque":
        mask = (R > 140) & (G > 120) & (R - B > 35) & (G - B > 30)
        score = (G - B).astype(float)
    else:  # brown/black: red >= green > blue (gums and tongue are pink: blue >= green)
        # pink tissue has a big red-green gap; brown/black teeth have a bigger green-blue gap
        # and must be clearly yellow-brown OR clearly dark (the roof of the mouth is neither)
        mask = ((R >= G) & (G > B + 10) & ((G - B) > 0.45 * (R - G)) & (R - B > 25) & (V < 200)
                & (((G - B) >= 22) | (V < 110)))
        score = (G - B) + (200 - V) * 0.6
    spot["x"], spot["y"] = (c + 0.5) / GRID, (r + 0.5) / GRID
    if mask.sum() < 12:
        spot["snapped"] = False
        return
    spot["snapped"] = True
    ys, xs = np.nonzero(mask)
    s = score[ys, xs]
    keep = s >= np.percentile(s, 70)  # strongest-coloured pixels only
    spot["x"] = (x0 + xs[keep].mean()) / w
    spot["y"] = (y0 + ys[keep].mean()) / h


def make_client():
    from openai import AzureOpenAI
    return AzureOpenAI(azure_endpoint=AZURE_ENDPOINT, api_key=AZURE_KEY,
                       api_version=AZURE_API_VERSION, timeout=40)


def ask_azure(image_b64: str, grid_b64: str) -> dict:
    client = make_client()
    text = chat(
        client,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Please check the teeth in this photo. "
                                         "First the clean photo, then the same photo with a grid."},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}", "detail": "high"}},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{grid_b64}", "detail": "high"}},
            ]},
        ],
    )
    return json.loads(text)


def chat(client, max_out: int = 1500, **kwargs) -> str:
    """Call the model. Works with gpt-4o/4.1 style models AND newer gpt-5 style models,
    which reject 'temperature' and 'max_tokens'."""
    from openai import BadRequestError
    try:
        r = client.chat.completions.create(model=AZURE_DEPLOYMENT, temperature=0,
                                           max_tokens=max_out, **kwargs)
    except BadRequestError as exc:
        msg = str(exc).lower()
        if "unsupported" in msg and "operation" in msg:
            raise RuntimeError(
                f"The model '{AZURE_DEPLOYMENT}' can't do chat. Codex models only write code. "
                "Deploy gpt-4o-mini, gpt-4.1-mini or gpt-5-mini and use that name.") from exc
        # gpt-5 / reasoning models: no temperature, use max_completion_tokens (needs extra room for thinking)
        r = client.chat.completions.create(model=AZURE_DEPLOYMENT,
                                           max_completion_tokens=max_out * 4, **kwargs)
    return r.choices[0].message.content or ""



def mood_for(spots: list) -> str:
    """One rule for the face, colour and stars, so they always agree."""
    if any(s["kind"] == "possible cavity" and s["certainty"] in ("medium", "high") for s in spots):
        return "check_soon"   # pink, worried face: nudge to a dentist
    if spots:
        return "okay"         # blue, calm face: small things to watch
    return "sparkly"          # mint, happy face


STARS_RANGE = {"sparkly": (4, 5), "okay": (3, 4), "check_soon": (1, 3)}

HEALTHY_TEXT = {
    "headline": "Sparkly clean teeth!",
    "summary": "Toothie didn't find any spots in this photo. Keep up the great brushing!",
}


def spot_crop(img: Image.Image, spot: dict, size: int = 320) -> Image.Image:
    """Zoom in on one spot (its grid square plus a margin) for the double-check."""
    w, h = img.size
    cell = spot.get("cell", "")
    if len(cell) >= 2 and cell[0] in COLS and cell[1:].isdigit() and 1 <= int(cell[1:]) <= GRID:
        cx, cy = (COLS.index(cell[0]) + 0.5) / GRID, (int(cell[1:]) - 0.5) / GRID
    else:
        cx, cy = spot["x"], spot["y"]
    half = 0.9 / GRID
    box = (int(max(0, cx - half) * w), int(max(0, cy - half) * h),
           int(min(1, cx + half) * w), int(min(1, cy + half) * h))
    c = img.crop(box)
    c.thumbnail((size, size))
    return c


VERIFY_PROMPT = """You are double-checking a kids' tooth-screening demo.
Each close-up below was cut from one mouth photo. For each one, decide if it CLEARLY shows the named problem
ON A TOOTH. Answer "no" if the close-up shows only healthy tooth (normal grooves, shadows, shine, ivory colour),
or mostly gum, tongue, lips, the roof of the mouth, a dental mirror or a plastic cheek holder.
Return ONLY JSON: {"answers": [{"n": 1, "keep": true or false}, ...]} with one answer per close-up."""


def verify_spots(client, img: Image.Image, spots: list) -> list:
    """Second opinion on every flagged spot, using zoomed-in close-ups. Returns the spots that pass."""
    if not spots:
        return spots
    content = [{"type": "text", "text": "Check these close-ups."}]
    for i, sp in enumerate(spots, 1):
        content.append({"type": "text", "text": f"Close-up {i}: is there a {sp['kind']} on a tooth?"})
        content.append({"type": "image_url", "image_url": {
            "url": f"data:image/jpeg;base64,{to_b64(spot_crop(img, sp))}", "detail": "high"}})
    try:
        text = chat(client, max_out=300, response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": VERIFY_PROMPT},
                              {"role": "user", "content": content}])
        keep = {int(a.get("n", 0)) for a in json.loads(text).get("answers", []) if a.get("keep") is True}
        kept = [sp for i, sp in enumerate(spots, 1) if i in keep]
        logging.info("[Smile Check] double-check kept %d of %d spots", len(kept), len(spots))
        return kept
    except Exception as exc:  # if the double-check fails, keep only the confident spots
        logging.warning("[Smile Check] double-check failed, keeping medium/high spots: %s", exc)
        return [sp for sp in spots if sp["certainty"] in ("medium", "high")]


def finish_result(result: dict) -> dict:
    """After the double-check: make the mood, stars and words match what is left."""
    had_spots = result.get("_had_spots", bool(result["spots"]))
    result.pop("_had_spots", None)
    result["overall"] = mood_for(result["spots"])
    lo, hi = STARS_RANGE[result["overall"]]
    result["stars"] = max(lo, min(hi, result["stars"]))
    if had_spots and not result["spots"]:      # every spot was a false alarm
        result.update(HEALTHY_TEXT)
    return result


def clean_result(r: dict) -> dict:
    """Make sure the page always gets safe, well-formed data even if the AI slips up."""
    def num(v, lo, hi, default):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return default

    spots = []
    for s in (r.get("spots") or [])[:6]:
        if not isinstance(s, dict):
            continue
        spots.append({
            "region": s.get("region") if s.get("region") in REGIONS else "upper-front",
            "kind": s.get("kind") if s.get("kind") in
                    ("possible cavity", "plaque", "tartar", "stain") else "stain",
            "what_i_see": str(s.get("what_i_see", ""))[:120],
            "why_it_matters": str(s.get("why_it_matters", ""))[:200],
            "certainty": s.get("certainty") if s.get("certainty") in ("low", "medium", "high") else "low",
            "cell": str(s.get("cell", "")).strip().upper()[:3],
            "x": num(s.get("x"), 0, 1, 0.5),
            "y": num(s.get("y"), 0, 1, 0.5),
        })

    overall = r.get("overall") if r.get("overall") in ("sparkly", "okay", "check_soon") else "okay"
    overall = mood_for(spots)

    jaw = r.get("jaw") if r.get("jaw") in ("upper", "lower", "both") else None
    if jaw in ("upper", "lower"):   # keep spot regions on the jaw the photo shows
        for s in spots:
            s["region"] = jaw + "-" + s["region"].split("-", 1)[1]
    if not jaw:  # work it out from the spots if the AI left it out
        sides = {s["region"].split("-")[0] for s in spots}
        jaw = sides.pop() if len(sides) == 1 else "both"
        jaw = {"upper": "upper", "lower": "lower"}.get(jaw, "both")

    return {
        "is_teeth_photo": bool(r.get("is_teeth_photo", True)),
        "jaw": jaw,
        "photo_quality": r.get("photo_quality", "good"),
        "photo_tip": str(r.get("photo_tip", ""))[:200],
        "overall": overall,
        "stars": int(num(r.get("stars"), 1, 5, 3)),
        "headline": str(r.get("headline", "Here is your Smile Check!"))[:80],
        "summary": str(r.get("summary", ""))[:400],
        "spots": spots,
        "good_things": [str(g)[:120] for g in (r.get("good_things") or [])][:3],
        "missions": [
            {"emoji": str(m.get("emoji", "🪥"))[:4], "title": str(m.get("title", ""))[:40],
             "detail": str(m.get("detail", ""))[:160]}
            for m in (r.get("missions") or []) if isinstance(m, dict)
        ][:3],
        "dentist_note": str(r.get("dentist_note", "Visit your dentist every 6 months to keep your smile strong."))[:200],
    }


PRACTICE_RESULT = {
    "is_teeth_photo": True,
    "photo_quality": "good",
    "photo_tip": "",
    "overall": "check_soon",
    "stars": 3,
    "headline": "Nice smile! Two spots need a look",
    "summary": "Most of your teeth look clean and bright. I spotted two places that might need a dentist's eyes.",
    "spots": [
        {"region": "lower-left", "kind": "possible cavity",
         "what_i_see": "A small dark brown dot on a back tooth",
         "why_it_matters": "Germs make acid that can dig tiny holes, and a dentist can fix them while they are small.",
         "certainty": "medium", "x": 0.30, "y": 0.62},
        {"region": "upper-front", "kind": "plaque",
         "what_i_see": "Soft yellowish layer near the gums",
         "why_it_matters": "Plaque is a sticky germ party. Brushing breaks it up before it causes trouble.",
         "certainty": "low", "x": 0.52, "y": 0.38},
    ],
    "good_things": ["Front teeth look shiny", "Gums look pink", "No big holes seen"],
    "missions": [
        {"emoji": "🪥", "title": "Brush two whole minutes", "detail": "Hum a song in your head so you don't stop early."},
        {"emoji": "🧵", "title": "Floss before bed", "detail": "Floss reaches the gaps your brush can't."},
        {"emoji": "💧", "title": "Water after sweets", "detail": "A quick sip and swish washes sugar away."},
    ],
    "dentist_note": "Show this to a grown-up and ask your dentist to check the brown dot.",
}


@app.get("/")
@app.get("/home")   # backup address: use /home if Azure shows its own start page at /
def home():
    return render_template("index.html", samples=SAMPLES)


@app.get("/sw.js")
def service_worker():
    resp = send_from_directory(os.path.join(HERE, "static"), "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(os.path.join(HERE, "static"), "manifest.webmanifest",
                               mimetype="application/manifest+json")


@app.get("/.well-known/assetlinks.json")
def asset_links():
    """Proves to Android that the Smile Check app (APK) belongs to this website,
    so the app opens full-screen without a browser address bar.
    Put the assetlinks.json file from PWABuilder into static/.well-known/."""
    folder = os.path.join(HERE, "static", ".well-known")
    if not os.path.exists(os.path.join(folder, "assetlinks.json")):
        return jsonify([]), 404
    return send_from_directory(folder, "assetlinks.json", mimetype="application/json")


@app.get("/download/smile-check.apk")
def download_apk():
    """Lets the Downloader app (or any phone) download the app file.
    Put the .apk from PWABuilder into static/download/ and name it smile-check.apk."""
    folder = os.path.join(HERE, "static", "download")
    if not os.path.exists(os.path.join(folder, "smile-check.apk")):
        return "The app file isn't uploaded yet.", 404
    return send_from_directory(folder, "smile-check.apk",
                               mimetype="application/vnd.android.package-archive", as_attachment=True)


@app.get("/api/status")
def status():
    """Safe settings check (never shows the key). Open /api/status in a browser to debug Azure."""
    return jsonify({
        "ai_ready": azure_ready(),
        "deployment": AZURE_DEPLOYMENT if azure_ready() else None,
        "endpoint_set": bool(AZURE_ENDPOINT),
        "key_set": bool(AZURE_KEY),
        "practice_mode_forced": FORCE_PRACTICE,
        "running_on": "Azure Functions" if os.getenv("FUNCTIONS_WORKER_RUNTIME") else "this computer",
    })


@app.post("/api/check")
def check():
    sample = SAMPLE_BY_ID.get(request.form.get("sample", ""))
    if sample:
        if sample["id"] in SAMPLE_CACHE and azure_ready():
            return jsonify({"mode": "ai", "sample": sample["label"], "result": SAMPLE_CACHE[sample["id"]]})
        with open(os.path.join(HERE, "static", "samples", sample["file"]), "rb") as f:
            raw = f.read()
    else:
        photo = request.files.get("photo")
        if not photo:
            return jsonify({"error": "No photo was sent. Pick or take a photo first."}), 400
        raw = photo.read()
    try:
        img = prepare_image(raw)
    except Exception:
        return jsonify({"error": "That file isn't a photo I can open. Try a JPG or PNG picture."}), 400

    if azure_ready():
        try:
            result = clean_result(ask_azure(to_b64(img), to_b64(grid_copy(img))))
            result["_had_spots"] = bool(result["spots"])
            result["spots"] = verify_spots(make_client(), img, result["spots"])   # double-check
            for spot in result["spots"]:
                place_spot(img, spot)
            result = finish_result(result)
            if sample:
                result["jaw"] = sample["jaw"]
                SAMPLE_CACHE[sample["id"]] = result
                return jsonify({"mode": "ai", "sample": sample["label"], "result": result})
            return jsonify({"mode": "ai", "result": result})
        except Exception as exc:  # internet down, wrong key, content filter, etc.
            logging.warning("[Smile Check] Azure call failed, using practice mode: %s", exc)
            return jsonify({"mode": "practice",
                            "reason": f"The AI couldn't be reached ({type(exc).__name__}), so this is a sample result.",
                            "result": clean_result(PRACTICE_RESULT)})

    return jsonify({"mode": "practice", "reason": "AI is not connected yet, so this is a sample result.",
                    "result": clean_result(PRACTICE_RESULT)})


@app.errorhandler(413)
def too_big(_):
    return jsonify({"error": "That photo is too big. Pick one under 15 MB."}), 413


if __name__ == "__main__":
    # Set SHARE_ON_NETWORK=1 to let phones on the same hotspot open the site.
    setup_report()
    host = "0.0.0.0" if os.getenv("SHARE_ON_NETWORK") == "1" else "127.0.0.1"
    print("\n  Smile Check is running!  Open  http://localhost:5000  in your browser.")
    print(f"  AI mode: {'Azure ' + AZURE_DEPLOYMENT if azure_ready() else 'PRACTICE (sample results)'}\n")
    app.run(host=host, port=5000, debug=False)
