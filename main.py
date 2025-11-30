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

from openai import OpenAI
from PyPDF2 import PdfReader
from docx import Document
import tempfile
import json
import pyjson5 as json5
import re

# ------------------ INIT ------------------
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    print("✅ OpenAI API key loaded")
    client = OpenAI(api_key=api_key)
else:
    print("❌ ERROR: OPENAI_API_KEY not found")
    client = None

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
def extract_json(raw: str):
    """Extract JSON from model output using json5 fallback."""
    raw = re.sub(r"```.*?```", "", raw, flags=re.DOTALL)

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
    rows = cursor.execute(
        "SELECT score, one_line || '\n\n' || detailed, created_at "
        "FROM roasts ORDER BY score DESC LIMIT 50"
    ).fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": rows
    })


# ------------------ UPLOAD ------------------
@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("quick")
):
    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # ---- RATE LIMIT ----
    row = cursor.execute(
        "SELECT count FROM daily_limits WHERE ip=? AND date=?",
        (ip, today)
    ).fetchone()

    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    # ---- READ FILE ----
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # ---- If same file roasted before ----
    found = cursor.execute("""
        SELECT score, one_line, overview, detailed, strengths, improvements, fun_obs
        FROM roasts WHERE file_hash=?
    """, (file_hash,)).fetchone()

    if found:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "score": found[0],
            "one_line": found[1],
            "overview": found[2],
            "detailed": found[3],
            "strengths": found[4],
            "improvements": found[5],
            "fun_obs": found[6]
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
            with tempfile.NamedTemporaryFile(delete=False) as t:
                t.write(content)
                p = t.name
            doc = Document(p)
            text = "\n".join(x.text for x in doc.paragraphs)
            os.unlink(p)

        elif fname.endswith(".txt"):
            text = content.decode()

        else:
            return HTMLResponse("<h1>Unsupported file type</h1>")
    except:
        return HTMLResponse("<h1>Could not read file</h1>")

    text = text[:15000]

    # ---------------- PROMPT BUILD ----------------
    REAL_DATE = "November 30, 2025"

    if mode == "quick":
        prompt = f"""
You are ROASTRANK.

Return only this JSON:
{{
  "score": int,
  "one_line": str
}}

Rules:
- MAX 4 lines
- Short, punchy roast
- Score 60–90 normally

RESUME:
{text}
"""
    else:
        prompt = f"""
You are ROASTRANK — 70% roast, 30% career coach.

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

Rules:
- Keep every section 3–6 lines max
- Today's date: {REAL_DATE}
- Assume all resume dates are valid

RESUME:
{text}
"""

    # ---------------- OPENAI CALL ----------------
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )

        raw = completion.choices[0].message.content
        data = extract_json(raw)

    except Exception as e:
        print("ERROR:", e)

        if mode == "quick":
            data = {
                "score": 65,
                "one_line": "Even GPT refused to roast your CV — that’s already a roast."
            }
        else:
            data = {
                "score": 68,
                "one_line": "Your CV confused GPT.",
                "overview": "The model could not parse your resume fully.",
                "detailed": "Your CV made even GPT take a coffee break.",
                "strengths": "Resilience.",
                "improvements": "Try uploading again.",
                "fun_observation": "Your CV broke a $10B AI model. Respect."
            }

    score = data.get("score", 70)

    # ---------------- SAVE ----------------
    cursor.execute("""
        INSERT INTO roasts 
        (file_hash, score, one_line, overview, detailed, strengths, improvements, fun_obs)
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

    # ---------------- RETURN RESULT ----------------
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
