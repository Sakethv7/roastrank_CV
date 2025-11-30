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
    ip TEXT,
    date TEXT,
    count INTEGER,
    PRIMARY KEY (ip, date)
)
""")

conn.commit()

# ---------------------------------------------------
# ----------------------- ROUTES ---------------------
# ---------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute(
        "SELECT score, roast_text, created_at FROM roasts ORDER BY score DESC LIMIT 50"
    ).fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": roasts
    })


# ============================================================
#   🔥 UPLOAD ROUTE — WITH DEFAULT MODE = "full" (FIX APPLIED)
# ============================================================

@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("full")   # DEFAULT FIX → prevents “mode missing”
):
    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # ---------- RATE LIMIT ----------
    cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today))
    row = cursor.fetchone()

    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    # ---------- HASH FILE ----------
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # Already roasted?
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
                "fun_obs": "",
            }
        )

    # ---------- EXTRACT TEXT ----------
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
                tmp_file = tmp.name

            doc = Document(tmp_file)
            text = "\n".join([p.text for p in doc.paragraphs])
            os.unlink(tmp_file)

        elif filename.endswith(".txt"):
            text = content.decode("utf-8")

        else:
            return HTMLResponse("<h1>Invalid File Type</h1>")

    except Exception:
        return HTMLResponse("<h1>Error Reading File</h1>")

    # ---------- GENERATE PROMPT ----------
    REAL_DATE = "November 22, 2025"

    # If quick roast — keep it short
    if mode == "quick":
        prompt = f"""
Give a VERY short, 4-line roast of this resume.
70% savage roast, 30% supportive.
Return ONLY JSON:

{{
  "score": int,
  "one_line": str
}}

Resume text:
{text[:12000]}
"""
    else:
        # Full roast (compact)
        prompt = f"""
You are ROASTRANK — a 70% brutal CV roaster and 30% supportive career coach.

IMPORTANT DATE RULES:
- Today's REAL date is: {REAL_DATE}
- Assume all resume dates are valid.
- Do NOT accuse user of time travel.

OUTPUT STRICTLY JSON:
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
- 70% roast, 30% helpful
- Compact, NOT overly long
- Score only 60–95 for strong resumes

Resume:
{text[:15000]}
"""

    # ---------- CALL GEMINI ----------
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)

        raw = response.text.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)

        if not match:
            raise ValueError("Gemini returned no JSON")

        data = json.loads(match.group(0))

    except Exception as e:
        print("ERROR:", e)

        if mode == "quick":
            data = {
                "score": 60,
                "one_line": "Your CV broke the AI — impressive in the worst way."
            }
        else:
            data = {
                "score": 55,
                "one_line": "Fallback roast.",
                "overview": "Gemini error occurred.",
                "detailed": "Your resume broke the model.",
                "strengths": "- consistent\n- resilient",
                "improvements": "- formatting\n- clarity",
                "fun_observation": "Even AI needed therapy after your CV."
            }

    score = data.get("score", 60)

    # ---------- SCORE FIX ----------
    sentiment_text = (
        data.get("overview", "") + data.get("detailed", "") +
        data.get("strengths", "")
    ).lower()

    positive_words = ["excellent", "strong", "advanced", "impact", "robust"]

    if score < 40 and any(w in sentiment_text for w in positive_words):
        score = 70

    # ---------- SAVE ----------
    cursor.execute(
        "INSERT INTO roasts (file_hash, score, roast_text) VALUES (?, ?, ?)",
        (
            file_hash,
            score,
            json.dumps(data, indent=2)
        )
    )

    cursor.execute("""
        INSERT OR REPLACE INTO daily_limits (ip, date, count)
        VALUES (?, ?, COALESCE((SELECT count FROM daily_limits 
                                WHERE ip=? AND date=?), 0) + 1)
    """, (ip, today, ip, today))

    conn.commit()

    # ---------- RENDER TEMPLATE ----------
    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "score": score,
            "one_line": data.get("one_line", ""),
            "overview": data.get("overview", ""),
            "detailed": data.get("detailed", ""),
            "strengths": data.get("strengths", ""),
            "improvements": data.get("improvements", ""),
            "fun_obs": data.get("fun_observation", "")
        }
    )
