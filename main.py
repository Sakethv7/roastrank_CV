from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import sqlite3
import os
import io
import hashlib
from datetime import datetime
from dotenv import load_dotenv

import google.generativeai as genai
from PyPDF2 import PdfReader
from docx import Document
import tempfile
import json
import json5
import re

# ------------------ INIT ------------------
load_dotenv()

# Try both possible environment variable names
api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

if api_key:
    print(f"✅ API Key found and loaded (length: {len(api_key)})")
    genai.configure(api_key=api_key)
else:
    print("❌ WARNING: No API key found! Set GOOGLE_API_KEY or GEMINI_API_KEY")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ------------------ DATABASE ------------------
conn = sqlite3.connect("roasts.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_hash TEXT UNIQUE,
  score INTEGER,
  one_line TEXT,
  overview TEXT,
  detailed TEXT,
  strengths TEXT,
  improvements TEXT,
  fun_obs TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_limits (
  ip TEXT, date TEXT, count INTEGER,
  PRIMARY KEY (ip, date)
)
""")

conn.commit()

# ------------------ JSON EXTRACTION ------------------
def extract_json(raw):
    """Extract the largest JSON block and sanitize using json5."""
    raw = re.sub(r"```.*?```", "", raw, flags=re.DOTALL)  # remove fences

    matches = re.findall(r"\{.*?\}", raw, flags=re.DOTALL)
    if not matches:
        raise ValueError("No JSON found")

    candidate = max(matches, key=len)

    try:
        return json.loads(candidate)
    except:
        return json5.loads(candidate)

# ------------------ HOME ------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ------------------ LEADERBOARD ------------------
@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute(
        "SELECT score, one_line || '\n\n' || detailed, created_at FROM roasts ORDER BY score DESC LIMIT 50"
    ).fetchall()
    return templates.TemplateResponse("leaderboard.html", {"request": request, "roasts": roasts})

# ------------------ UPLOAD ------------------
@app.post("/upload")
async def upload_cv(request: Request, file: UploadFile = File(...), mode: str = Form("quick")):

    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # ---- RATE LIMIT ----
    cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today))
    row = cursor.fetchone()
    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    # ---- READ FILE ----
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # ---- If same file roasted before ----
    existing = cursor.execute(
        "SELECT score, one_line, overview, detailed, strengths, improvements, fun_obs "
        "FROM roasts WHERE file_hash=?",
        (file_hash,)
    ).fetchone()

    if existing:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "score": existing[0],
            "one_line": existing[1],
            "overview": existing[2],
            "detailed": existing[3],
            "strengths": existing[4],
            "improvements": existing[5],
            "fun_obs": existing[6]
        })

    # ---- Extract text ----
    text = ""
    fname = file.filename.lower()

    try:
        if fname.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for p in reader.pages:
                text += (p.extract_text() or "") + "\n"

        elif fname.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                path = tmp.name
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.unlink(path)

        elif fname.endswith(".txt"):
            text = content.decode()

        else:
            return HTMLResponse("<h1>Unsupported file type</h1>")
    except Exception as e:
        print(f"❌ File reading error: {e}")
        return HTMLResponse("<h1>Could not read file</h1>")

    text = text[:15000]  # safety

    # ---------------- PROMPT ----------------
    REAL_DATE = "November 30, 2025"

    if mode == "quick":
        prompt = f"""
You are ROASTRANK, the savage CV roaster.

Give ONLY this JSON:
{{
  "score": int,
  "one_line": str
}}

RULES:
- 4-line roast MAX
- Short, punchy, funny
- Avoid long paragraphs
- Score 60–90 for normal CVs

RESUME:
{text}
"""
    else:  # full
        prompt = f"""
You are ROASTRANK — mix of 70% roast, 30% career coach.

Return ONLY this JSON:
{{
  "score": int,
  "one_line": str,
  "overview": str,
  "detailed": str,
  "strengths": str,
  "improvements": str,
  "fun_observation": str
}}

RULES:
- Keep sections SHORT (3–6 lines max)
- No extremely long essays
- Be funny but not hostile
- Today's date is {REAL_DATE}
- Assume ALL dates in resume are valid.

RESUME:
{text}
"""

    # ---------------- GEMINI CALL ----------------
    try:
        print(f"🤖 Calling Gemini API (mode: {mode})...")
        model = genai.GenerativeModel("gemini-2.0-flash-exp")
        response = model.generate_content(prompt)
        raw = response.text.strip()
        print(f"✅ Gemini responded (length: {len(raw)})")
        data = extract_json(raw)
        print(f"✅ JSON parsed successfully")

    except Exception as e:
        print(f"❌ GEMINI ERROR: {type(e).__name__}: {str(e)}")

        if mode == "quick":
            data = {
                "score": 65,
                "one_line": "Even Gemini refused to roast your CV — that's a roast in itself."
            }
        else:
            data = {
                "score": 68,
                "one_line": "Your CV confused the AI.",
                "overview": "Gemini failed to produce structured output.",
                "detailed": "Your resume made Gemini reconsider its life choices.",
                "strengths": "You keep going, that's something.",
                "improvements": "Try re-uploading; the model might be braver next time.",
                "fun_observation": "Your CV broke a trillion-dollar AI. Iconic."
            }

    # ---------------- SCORE FIX ----------------
    score = data.get("score", 70)

    # ---------------- SAVE ----------------
    cursor.execute("""
        INSERT INTO roasts (file_hash, score, one_line, overview, detailed, strengths, improvements, fun_obs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_hash,
        score,
        data.get("one_line", ""),
        data.get("overview", ""),
        data.get("detailed", ""),
        data.get("strengths", ""),
        data.get("improvements", ""),
        data.get("fun_observation", "")
    ))

    cursor.execute("""
        INSERT OR REPLACE INTO daily_limits (ip, date, count)
        VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0)+1)
    """, (ip, today, ip, today))

    conn.commit()

    # ---------------- RENDER RESULT ----------------
    return templates.TemplateResponse("result.html", {
        "request": request,
        "score": score,
        "one_line": data.get("one_line", ""),
        "overview": data.get("overview", ""),
        "detailed": data.get("detailed", ""),
        "strengths": data.get("strengths", ""),
        "improvements": data.get("improvements", ""),
        "fun_obs": data.get("fun_observation", "")
    })