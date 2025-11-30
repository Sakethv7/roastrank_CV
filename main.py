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

# ---------------- INIT ----------------
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ---------------- DATABASE ----------------
conn = sqlite3.connect("roasts.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash TEXT UNIQUE,
    score INTEGER,
    roast_text TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_limits (
    ip TEXT, date TEXT, count INTEGER, PRIMARY KEY (ip, date)
)
""")

conn.commit()

# ---------------- HOME ----------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute(
        "SELECT score, roast_text, created_at FROM roasts ORDER BY score DESC LIMIT 50"
    ).fetchall()

    return templates.TemplateResponse(
        "leaderboard.html",
        {"request": request, "roasts": roasts}
    )

# ---------------- UPLOAD HANDLER ----------------

@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form(...)      # "quick" OR "full"
):
    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # ---------- RATE LIMITING ----------
    cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today))
    row = cursor.fetchone()
    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    # ---------- HASH FILE ----------
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # If roasted already → fetch and return immediately
    existing = cursor.execute(
        "SELECT score, roast_text FROM roasts WHERE file_hash=?", (file_hash,)
    ).fetchone()

    if existing:
        score, roast_text = existing

        # QUICK MODE (reuse first 4 lines only)
        if mode == "quick":
            lines = roast_text.split("\n")
            quick = "\n".join(lines[:4])
            return templates.TemplateResponse(
                "quick_result.html",
                {"request": request, "quick_text": quick, "score": score}
            )

        # FULL MODE
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "score": score,
                "one_line": "",
                "overview": "",
                "detailed": roast_text,
                "strengths": "",
                "improvements": "",
                "fun_obs": "",
            }
        )

    # ---------- EXTRACT RESUME TEXT ----------
    text = ""
    filename = file.filename.lower()

    try:
        if filename.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"

        elif filename.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            doc = Document(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.unlink(tmp_path)

        elif filename.endswith(".txt"):
            text = content.decode("utf-8")

        else:
            return HTMLResponse("<h1>Invalid File Type</h1>")

    except:
        return HTMLResponse("<h1>Error Reading File</h1>")

    # ---------------- PROMPTS ----------------

    REAL_DATE = "November 22, 2025"

    if mode == "quick":
        prompt = f"""
You are ROASTRANK — deliver a *brutal but funny* 4-LINE roast summary of this resume.

Rules:
- EXACTLY 4 lines.
- No intro, no conclusion, no JSON.
- Savage but useful.
- Today’s date is {REAL_DATE}. DO NOT mention future dates.

Resume:
{text[:6000]}
"""
    else:
        # FULL COMPACT ROAST
        prompt = f"""
You are ROASTRANK — a 70% savage CV roaster and 30% supportive career coach.

Today's REAL date is {REAL_DATE}. Never accuse the user of time travel.
Assume all resume dates are valid.

Return STRICT JSON ONLY:

{{
  "score": int,
  "one_line": str,
  "overview": str,
  "detailed": str,
  "strengths": str,
  "improvements": str,
  "fun_observation": str
}}

Compact, punchy, readable.

Resume:
{text[:15000]}
"""

    # ---------------- CALL GEMINI ----------------

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)

        raw = response.text.strip()

        if mode == "quick":
            quick_text = raw.strip()

            # Save even quick roasts with no JSON
            score = 60
            cursor.execute(
                "INSERT INTO roasts (file_hash, score, roast_text) VALUES (?, ?, ?)",
                (file_hash, score, quick_text)
            )
            cursor.execute(
                "INSERT OR REPLACE INTO daily_limits (ip, date, count) VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0)+1)",
                (ip, today, ip, today)
            )
            conn.commit()

            return templates.TemplateResponse(
                "quick_result.html",
                {"request": request, "quick_text": quick_text, "score": score}
            )

        # -------- FULL MODE JSON --------
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group(0))

    except Exception as e:
        print("ERROR:", e)
        data = {
            "score": 55,
            "one_line": "Fallback one-liner.",
            "overview": "Model failed but your CV survives.",
            "detailed": "Your resume confused the AI so hard it rage-quit.",
            "strengths": "Still standing.",
            "improvements": "Formatting and clarity.",
            "fun_observation": "Even AI needed therapy after parsing your CV."
        }

    # ----- SCORE FIX -----
    score = data.get("score", 55)

    sentiment = (
        data.get("overview", "") +
        data.get("detailed", "") +
        data.get("strengths", "")
    ).lower()

    positive_words = ["excellent", "strong", "impressive", "advanced", "impact"]

    if score < 40 and any(w in sentiment for w in positive_words):
        score = 70

    # ----- SAVE FULL ROAST -----
    roast_text = (
        f"ONE-LINE: {data['one_line']}\n"
        f"OVERVIEW: {data['overview']}\n"
        f"DETAILED: {data['detailed']}\n"
        f"STRENGTHS: {data['strengths']}\n"
        f"IMPROVEMENTS: {data['improvements']}\n"
        f"FUN: {data['fun_observation']}"
    )

    cursor.execute(
        "INSERT INTO roasts (file_hash, score, roast_text) VALUES (?, ?, ?)",
        (file_hash, score, roast_text)
    )

    cursor.execute(
        "INSERT OR REPLACE INTO daily_limits (ip, date, count) VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0)+1)",
        (ip, today, ip, today)
    )

    conn.commit()

    # ----- RENDER FULL PAGE -----
    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "score": score,
            "one_line": data["one_line"],
            "overview": data["overview"],
            "detailed": data["detailed"],
            "strengths": data["strengths"],
            "improvements": data["improvements"],
            "fun_obs": data["fun_observation"]
        }
    )
