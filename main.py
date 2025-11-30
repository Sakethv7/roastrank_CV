from fastapi import FastAPI, Request, File, UploadFile
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

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ---------------- APP ----------------
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
)""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_limits (
    ip TEXT, date TEXT, count INTEGER, PRIMARY KEY (ip, date)
)""")
conn.commit()

# ---------------- JSON REPAIR ----------------

def force_json_fix(raw):
    """Extract and sanitize JSON from Gemini output."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("No JSON found")

    extracted = match.group(0)
    
    # Common fixes
    extracted = extracted.replace("\n", " ")
    extracted = re.sub(r",\s*}", "}", extracted)
    extracted = re.sub(r",\s*\]", "]", extracted)

    return json.loads(extracted)

def limit_lines(text, max_lines=4):
    """Limit long roast paragraphs to N lines."""
    lines = text.strip().split("\n")
    if len(lines) <= max_lines:
        return text.strip()
    return "\n".join(lines[:max_lines]).strip()

# ---------------- ROUTES ----------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute(
        "SELECT score, roast_text, created_at FROM roasts ORDER BY score DESC LIMIT 50"
    ).fetchall()
    return templates.TemplateResponse("leaderboard.html", {"request": request, "roasts": roasts})


@app.post("/upload")
async def upload_cv(request: Request, file: UploadFile = File(...)):
    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # -------- RATE LIMITING --------
    cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today))
    row = cursor.fetchone()
    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    # -------- READ FILE --------
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # If file already roasted earlier
    if cursor.execute("SELECT 1 FROM roasts WHERE file_hash=?", (file_hash,)).fetchone():
        score, roast_text = cursor.execute(
            "SELECT score, roast_text FROM roasts WHERE file_hash=?", (file_hash,)
        ).fetchone()

        # parse roast_text to sections
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

    # -------- EXTRACT TEXT --------
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
            text = "\n".join([p.text for p in doc.paragraphs])
            os.unlink(tmp_path)

        elif filename.endswith(".txt"):
            text = content.decode("utf-8", errors="ignore")

        else:
            return HTMLResponse("<h1>Invalid File Type</h1>")

    except Exception:
        return HTMLResponse("<h1>Error Reading File</h1>")

    # -------- GEMINI PROMPT (UPGRADED SHORT ROAST) --------
    REAL_DATE = "November 22, 2025"

    prompt = f"""
You are ROASTRANK — an elite CV roasting engine.

STRICT RULES:
- Respond ONLY in VALID JSON. Nothing outside JSON.
- KEEP IT SHORT.
- "detailed" must be MAX 4 LINES.
- Score must match quality.
- Score ranges:
  - Weak CV → 40–60
  - Normal → 60–75
  - Strong → 75–90

JSON FORMAT:
{{
  "score": 65,
  "one_line": "short roast",
  "overview": "1 sentence summary",
  "detailed": "max 4 lines roast",
  "strengths": "2–3 bullet style points",
  "improvements": "2–3 bullet style suggestions",
  "fun_observation": "1 funny line"
}}

Today's REAL date: {REAL_DATE}.
Ignore any future-looking resume dates — assume they are correct.

NOW ROAST THIS RESUME:

{text[:15000]}
"""

    # -------- CALL GEMINI --------
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)

        raw = response.text.strip()
        data = force_json_fix(raw)

    except Exception as e:
        print("GEMINI ERROR:", e)
        data = {
            "score": 60,
            "one_line": "Fallback roast.",
            "overview": "Gemini error occurred.",
            "detailed": "Your resume broke the model.",
            "strengths": "- consistent\n- resilient",
            "improvements": "- formatting\n- clarity",
            "fun_observation": "Even AI needed therapy after this CV."
        }

    # -------- ENFORCE SHORT LENGTH --------
    data["detailed"] = limit_lines(data.get("detailed", ""), 4)

    score = data.get("score", 60)

    # -------- SAVE TO DATABASE --------
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
    cursor.execute(
        "INSERT OR REPLACE INTO daily_limits (ip, date, count) "
        "VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?),0)+1)",
        (ip, today, ip, today)
    )
    conn.commit()

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
