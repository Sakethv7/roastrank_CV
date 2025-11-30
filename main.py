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
import re

# ======================================================
#                 INIT + CONFIG
# ======================================================

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

if api_key:
    print("✅ OpenAI API key loaded")
else:
    print("❌ No OPENAI_API_KEY found!")


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_PATH = "roasts.db"


# ======================================================
#       CREATE DATABASE IF NOT EXISTS
# ======================================================

def ensure_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS roasts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      file_hash TEXT UNIQUE,
      name TEXT DEFAULT 'Anonymous',
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_limits (
      ip TEXT,
      date TEXT,
      count INTEGER,
      PRIMARY KEY (ip, date)
    )
    """)

    conn.commit()
    conn.close()


ensure_db()

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()


# ======================================================
#       JSON EXTRACTION (Safe)
# ======================================================

def extract_json(raw: str):
    """Extract strict JSON from LLM output safely."""
    raw = raw.replace("```json", "").replace("```", "").strip()

    matches = re.findall(r"\{[\s\S]*?\}", raw)
    if not matches:
        raise ValueError("No JSON found in output.")

    block = max(matches, key=len)

    # Fix common LLM mistakes
    block = re.sub(r",\s*}", "}", block)
    block = re.sub(r",\s*\]", "]", block)

    try:
        return json.loads(block)
    except:
        raise ValueError("Invalid JSON returned by model.")


# ======================================================
#       NAME EXTRACTION
# ======================================================

def extract_name_from_text(text: str):
    """Extract candidate name from resume (best effort)."""
    if not client:
        return "Anonymous"

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"""
Extract ONLY the person's full name from this resume.
- If uncertain, return "Anonymous".
- No extra words.

Resume text:
{text[:2500]}
"""
            }]
        )

        name = resp.choices[0].message.content.strip()
        if len(name.split()) > 6:
            return "Anonymous"
        return name

    except Exception:
        return "Anonymous"


# ======================================================
#                   ROUTES
# ======================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute("""
        SELECT name, score, one_line, overview, detailed, strengths, improvements, fun_obs, created_at
        FROM roasts
        ORDER BY score DESC
        LIMIT 50
    """).fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": roasts
    })


@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("quick")
):

    # ---------------- Rate Limit ----------------
    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    row = cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today)).fetchone()
    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    # ---------------- Read File ----------------
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # Check if roast already exists
    existing = cursor.execute("""
        SELECT name, score, one_line, overview, detailed, strengths, improvements, fun_obs 
        FROM roasts WHERE file_hash=?
    """, (file_hash,)).fetchone()

    if existing:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "name": existing[0],
            "score": existing[1],
            "one_line": existing[2],
            "overview": existing[3],
            "detailed": existing[4],
            "strengths": existing[5],
            "improvements": existing[6],
            "fun_obs": existing[7]
        })

    # ---------------- Extract Text ----------------
    text = ""
    filename = file.filename.lower()

    try:
        if filename.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for p in reader.pages:
                text += (p.extract_text() or "") + "\n"

        elif filename.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                path = tmp.name
            doc = Document(path)
            text = "\n".join([p.text for p in doc.paragraphs])
            os.unlink(path)

        elif filename.endswith(".txt"):
            text = content.decode()

        else:
            return HTMLResponse("<h1>Unsupported file type</h1>")

    except Exception:
        return HTMLResponse("<h1>Error reading file</h1>")

    text = text[:15000]

    # ---------------- Extract Name ----------------
    name = extract_name_from_text(text)

    # ======================================================
    #               PROMPTS - UPDATED & FUNNY
    # ======================================================

    # ---------- QUICK ROAST ----------
    if mode == "quick":
        prompt = f"""
You are RoastGPT — a savage, witty AI who roasts resumes.

Return ONLY this JSON:
{{
 "score": int,
 "one_line": str
}}

Rules:
- One-line MUST reference résumé content.
- No generic lines.
- Must be sharp + funny.
- MAX length = 1 sentence.

Resume:
{text}
"""
    else:
        # ---------- FULL ROAST ----------
        prompt = f"""
You are RoastGPT — the world's funniest resume roasting AI.

Return ONLY this JSON:
{{
 "score": int,
 "one_line": str,
 "overview": str,
 "detailed": str,
 "strengths": list,
 "improvements": list,
 "fun_observation": str
}}

STRICT RULES:
- One-line: 1 sentence MAX.
- Overview: 2 short lines max.
- Detailed roast: 4 lines max.
- strengths: EXACTLY 3 bullet-style short items.
- improvements: EXACTLY 3 bullet-style short items.
- fun_observation: 1 funny line.
- MUST reference actual resume content.
- ZERO generic filler allowed.

Resume:
{text}
"""

    # ======================================================
    #             CALL OPENAI API
    # ======================================================

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.choices[0].message.content
        data = extract_json(raw)

    except Exception as e:
        print("ERROR:", e)

        if mode == "quick":
            data = {
                "score": 60,
                "one_line": "Your CV confused the AI."
            }
        else:
            data = {
                "score": 65,
                "one_line": "Your CV confused the AI.",
                "overview": "",
                "detailed": "",
                "strengths": [],
                "improvements": [],
                "fun_observation": ""
            }

    # ======================================================
    #               FORMAT BULLET LISTS
    # ======================================================

    strengths = "\n".join(data.get("strengths", []))
    improvements = "\n".join(data.get("improvements", []))

    # ======================================================
    #          SAVE ROAST TO DATABASE
    # ======================================================

    cursor.execute("""
        INSERT INTO roasts (
            file_hash, name, score, one_line, overview, detailed, strengths, improvements, fun_obs
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_hash,
        name,
        data.get("score", 70),
        data.get("one_line", ""),
        data.get("overview", ""),
        data.get("detailed", ""),
        strengths,
        improvements,
        data.get("fun_observation", "")
    ))

    cursor.execute("""
        INSERT OR REPLACE INTO daily_limits (ip, date, count)
        VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0)+1)
    """, (ip, today, ip, today))

    conn.commit()

    # ======================================================
    #                     RENDER RESULT
    # ======================================================

    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": data.get("score", 70),
        "one_line": data.get("one_line", ""),
        "overview": data.get("overview", ""),
        "detailed": data.get("detailed", ""),
        "strengths": strengths,
        "improvements": improvements,
        "fun_obs": data.get("fun_observation", "")
    })
