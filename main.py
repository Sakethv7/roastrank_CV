import os
import sqlite3
import json
import zipfile
import io
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai import OpenAI
import PyPDF2
from bs4 import BeautifulSoup  # NEW for docx XML parsing


# --------------------------------------------------------------------
# FASTAPI APP
# --------------------------------------------------------------------
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

client = OpenAI()


# --------------------------------------------------------------------
# DATABASE SETUP
# --------------------------------------------------------------------
DB_PATH = "roasts.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    score INTEGER,
    one_line TEXT,
    overview TEXT,
    fun_obs TEXT,
    created_at TEXT
)
""")
conn.commit()


# --------------------------------------------------------------------
# TEXT EXTRACTION
# --------------------------------------------------------------------
def extract_text_from_file(file: UploadFile) -> str:
    """Extract text safely from PDF, DOCX, or TXT."""

    ext = file.filename.lower()

    # --- PDF ---
    if ext.endswith(".pdf"):
        try:
            reader = PyPDF2.PdfReader(file.file)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except:
            return ""

    # --- DOCX SAFE PARSER (no seek errors) ---
    elif ext.endswith(".docx"):
        try:
            file.file.seek(0)
            data = file.file.read()

            with zipfile.ZipFile(io.BytesIO(data)) as z:
                with z.open("word/document.xml") as doc_xml:
                    soup = BeautifulSoup(doc_xml.read(), "xml")
                    return " ".join(t.get_text() for t in soup.find_all("w:t"))
        except:
            return ""

    # --- TXT fallback ---
    else:
        try:
            return file.file.read().decode("utf-8", errors="ignore")
        except:
            return ""


# --------------------------------------------------------------------
# AI-POWERED NAME EXTRACTION
# --------------------------------------------------------------------
def guess_name(text: str) -> str:
    """Extract candidate's name using LLM (most reliable)."""

    prompt = f"""
Extract ONLY the candidate's real full name from this resume.
Rules:
- 1–4 words max.
- No email, no phone numbers, no punctuation.
- If unsure, return: Anonymous

Resume:
{text[:2000]}
"""

    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt
        )

        name = resp.output_text().strip()

        # sanity check
        if 1 <= len(name.split()) <= 4:
            return name

        return "Anonymous"

    except:
        return "Anonymous"


# --------------------------------------------------------------------
# ROAST GENERATION (STRONGER PROMPTS)
# --------------------------------------------------------------------
def roast_resume(text: str, mode: str):
    """Generate a roast (quick = short + spicy, full = deeper + still spicy)."""

    if mode == "quick":
        prompt = f"""
You are RoastRank, a brutally honest but hilarious resume roaster.
Give SHORT but MEAN roasts.

Respond ONLY in JSON with keys:
one_line, overview, fun_obs, score

Rules:
- one_line: 1 brutal line.
- overview: 2 funny factual lines about resume quality.
- fun_obs: 1 witty observation.
- score: integer 1–100.

Resume:
{text}
"""
    else:
        prompt = f"""
You are RoastRank, a savage expert in mocking resumes.
Give a FUNNY but COMPACT roast. No long essays.

Respond ONLY in JSON with keys:
one_line, overview, fun_obs, score

Rules:
- one_line: One punchline roast.
- overview: 3–4 lines MAX. Funny but factual.
- fun_obs: 1–2 lines MAX.
- score: integer 1–100.

IMPORTANT:
Keep quick roast & full roast scores within a similar range (±15).
No generic compliments. Be witty, sarcastic, and smart.

Resume:
{text}
"""

    # ---- Make the request ----
    try:
        resp = client.responses.create(
            model="gpt-4.1",
            input=prompt
        )

        raw = resp.output_text().strip()
        data = json.loads(raw)
        return data

    except Exception as e:
        print("ERROR PARSING ROAST:", e)
        return {
            "one_line": "Your CV confused the AI.",
            "overview": "Model failed parsing JSON.",
            "fun_obs": "",
            "score": 10
        }


# --------------------------------------------------------------------
# ROUTES
# --------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile, mode: str = Form(...)):
    text = extract_text_from_file(file)
    name = guess_name(text)

    roast = roast_resume(text, mode)

    cursor.execute("""
        INSERT INTO roasts (name, score, one_line, overview, fun_obs, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        name,
        roast["score"],
        roast["one_line"],
        roast["overview"],
        roast["fun_obs"],
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()

    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": roast["score"],
        "one_line": roast["one_line"],
        "overview": roast["overview"],
        "fun_obs": roast["fun_obs"],
    })


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    cursor.execute("""
        SELECT name, score, one_line, created_at
        FROM roasts
        ORDER BY score DESC, created_at DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": rows
    })


# Hugging Face handles uvicorn, so no __main__ needed.


