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
import re


# ------------------ INIT ------------------
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

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


# ------------------ CLEAN + SAFE JSON EXTRACTOR ------------------
def extract_json(raw_text: str):
    """
    Extract the largest JSON block from model output.
    Removes code fences and parses using json.loads.
    """
    if not raw_text:
        raise ValueError("Empty model response")

    # Remove ```json ... ``` blocks if present
    raw_text = re.sub(r"```.*?```", "", raw_text, flags=re.DOTALL)

    # Extract all JSON-looking blocks
    matches = re.findall(r"\{(?:.|\n)*?\}", raw_text, flags=re.DOTALL)
    if not matches:
        raise ValueError("No JSON found")

    candidate = max(matches, key=len)  # choose largest block

    try:
        return json.loads(candidate)
    except Exception:
        raise ValueError("Invalid JSON structure")


# ------------------ ROUTES ------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute(
        "SELECT score, one_line || '\n\n' || detailed, created_at FROM roasts ORDER BY score DESC LIMIT 50"
    ).fetchall()
    return templates.TemplateResponse("leaderboard.html", {"request": request, "roasts": roasts})


@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("quick")
):

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

    # ---- If already roasted ----
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

    # ---- Extract resume text ----
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
                tmp_path = tmp.name
            doc = Document(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.unlink(tmp_path)

        elif fname.endswith(".txt"):
            text = content.decode()

        else:
            return HTMLResponse("<h1>Unsupported file type</h1>")

    except Exception:
        return HTMLResponse("<h1>Could not read file</h1>")

    text = text[:15000]  # safety limit


    # ---------------- PROMPTS ----------------
    REAL_DATE = "November 30, 2025"

    if mode == "quick":
        prompt = f"""
You are ROASTRANK — brutal, funny, punchy.

Return ONLY this JSON:
{{
  "score": int,
  "one_line": str
}}

RULES:
- Max 4 lines
- Keep compact, witty, sharp
- Score must be between 60 and 90 normally

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

RULES:
- No section longer than 5–6 lines
- Be funny, not hostile
- Assume all resume dates are valid
- Today's date: {REAL_DATE}

RESUME:
{text}
"""


    # ---------------- CALL GEMINI ----------------
    try:
        model = genai.GenerativeModel("gemini-2.0-flash-exp")
        response = model.generate_content(prompt)
        raw = response.text.strip()
        data = extract_json(raw)

    except Exception as e:
        print("ERROR:", e)

        # fallback
        if mode == "quick":
            data = {
                "score": 65,
                "one_line": "Even Gemini refused to roast your CV — that’s a roast in itself."
            }
        else:
            data = {
                "score": 68,
                "one_line": "Your CV confused the AI.",
                "overview": "Gemini failed to produce structured output.",
                "detailed": "Your resume made Gemini reconsider its life choices.",
                "strengths": "You keep going — respectable.",
                "improvements": "Try re-uploading; the model might be braver next time.",
                "fun_observation": "Your CV broke a trillion-dollar AI. Iconic."
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
        VALUES (
            ?, ?, 
            COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0) + 1
        )
    """, (ip, today, ip, today))

    conn.commit()

    # ---------------- RENDER ----------------
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
