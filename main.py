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

# ---------------- CONFIG ----------------
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ---------------- APP SETUP ----------------
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
    ip TEXT,
    date TEXT,
    count INTEGER,
    PRIMARY KEY (ip, date)
)
""")

conn.commit()

# ---------------- ROUTES ----------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    rows = cursor.execute(
        "SELECT score, roast_text, created_at FROM roasts ORDER BY score DESC LIMIT 50"
    ).fetchall()
    return templates.TemplateResponse("leaderboard.html", {"request": request, "roasts": rows})


# ---------------- UPLOAD ROUTE ----------------

@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("full")
):

    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # -------- RATE LIMIT (FULL mode only) --------
    if mode == "full":
        cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today))
        row = cursor.fetchone()
        if row and row[0] >= 10:
            return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    # -------- FILE READ + HASH --------
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()
    filename = file.filename.lower()

    # -------- RETURN CACHED FULL ROAST --------
    if mode == "full":
        existing = cursor.execute(
            "SELECT score, roast_text FROM roasts WHERE file_hash=?",
            (file_hash,)
        ).fetchone()

        if existing:
            score, roast_text = existing
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
                    "fun_obs": ""
                }
            )

    # -------- TEXT EXTRACTION --------
    text = ""

    try:
        if filename.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"

        elif filename.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                path = tmp.name
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.unlink(path)

        elif filename.endswith(".txt"):
            text = content.decode("utf-8")

        else:
            return HTMLResponse("<h1>Invalid File Type</h1>")

    except Exception:
        return HTMLResponse("<h1>Error Reading File</h1>")

    # ==================================================================
    # 🔥 QUICK ROAST MODE — EXACTLY 4 LINES 🔥
    # ==================================================================
    if mode == "quick":
        quick_prompt = f"""
Give EXACTLY 4 LINES of savage roast.
No sections.
No JSON.
Just 4 brutal, funny lines.

Resume:
{text[:15000]}
"""
        model = genai.GenerativeModel("gemini-2.5-flash")
        res = model.generate_content(quick_prompt)
        roast_text = res.text.strip()

        return templates.TemplateResponse(
            "quick_result.html",
            {"request": request, "roast": roast_text}
        )

    # ==================================================================
    # 🔥 FULL ROAST (COMPACT OPTION A) — JSON ONLY 🔥
    # ==================================================================
    full_prompt = f"""
Return COMPACT JSON only:

{{
  "score": int,
  "one_line": "max 1 line",
  "overview": "max 2 lines",
  "detailed": "4-5 short roast lines",
  "strengths": "- bullet 1\\n- bullet 2",
  "improvements": "- bullet 1\\n- bullet 2",
  "fun_observation": "1 witty line"
}}

Tone:
70% savage roast  
30% helpful  
Short, punchy, readable.

Resume:
{text[:15000]}
"""

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        res = model.generate_content(full_prompt)
        raw = res.text.strip()

        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        data = {
            "score": 60,
            "one_line": "Fallback roast.",
            "overview": "Gemini error occurred.",
            "detailed": "Your resume broke the model.",
            "strengths": "- consistent\n- resilient",
            "improvements": "- formatting\n- clarity",
            "fun_observation": "Even AI needed therapy after this CV."
        }

    score = data.get("score", 60)

    # -------- Store Full Roast --------
    roast_text = (
        f"ONE-LINE:\n{data['one_line']}\n\n"
        f"OVERVIEW:\n{data['overview']}\n\n"
        f"DETAILED:\n{data['detailed']}\n\n"
        f"STRENGTHS:\n{data['strengths']}\n\n"
        f"IMPROVEMENTS:\n{data['improvements']}\n\n"
        f"FUN:\n{data['fun_observation']}"
    )

    cursor.execute(
        "INSERT INTO roasts (file_hash, score, roast_text) VALUES (?, ?, ?)",
        (file_hash, score, roast_text)
    )

    cursor.execute("""
        INSERT OR REPLACE INTO daily_limits (ip, date, count)
        VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0)+1)
    """, (ip, today, ip, today))

    conn.commit()

    # -------- Render Full Roast --------
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
