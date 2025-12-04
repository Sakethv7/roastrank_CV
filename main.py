import os
import io
import json
import sqlite3
import tempfile
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai import OpenAI
import PyPDF2
from docx import Document
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# -------------------------------------------------------
# FASTAPI APP
# -------------------------------------------------------
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize OpenAI client with API key from environment
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("❌ OPENAI_API_KEY missing! Add it to your .env file.")

client = OpenAI(api_key=api_key)
print("✅ OpenAI client initialized successfully")

# -------------------------------------------------------
# DATABASE
# -------------------------------------------------------
DB_PATH = "roasts.db"

def init_db():
    """Initialize database with schema"""
    conn = sqlite3.connect(DB_PATH)
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
    conn.close()

# Initialize DB on startup
init_db()

def get_db():
    """Get database connection (thread-safe)"""
    conn = sqlite3.connect(DB_PATH)
    return conn

# -------------------------------------------------------
# FILE → TEXT
# -------------------------------------------------------
def extract_text(file: UploadFile) -> str:
    """Extract text from PDF, DOCX, or TXT files"""
    ext = file.filename.lower()
    raw = file.file.read()

    # ---- PDF ----
    if ext.endswith(".pdf"):
        try:
            pdf = PyPDF2.PdfReader(io.BytesIO(raw))
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            if text.strip():
                return text
        except Exception as e:
            print(f"PDF extraction error: {e}")

    # ---- DOCX ----
    if ext.endswith(".docx"):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(raw)
                tmp_path = tmp.name

            doc = Document(tmp_path)
            os.remove(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            if text.strip():
                return text
        except Exception as e:
            print(f"DOCX extraction error: {e}")

    # ---- TXT ----
    try:
        text = raw.decode("utf-8", errors="ignore")
        if text.strip():
            return text
    except Exception as e:
        print(f"TXT extraction error: {e}")

    return ""


# -------------------------------------------------------
# NAME GUESS
# -------------------------------------------------------
def guess_name(text):
    """Try to extract candidate name from first few lines"""
    lines = text.split("\n")[:5]
    for line in lines:
        line = line.strip()
        if 2 <= len(line.split()) <= 4:
            if all(c.isalpha() or c.isspace() for c in line):
                return line
    return "Anonymous"


# -------------------------------------------------------
# SAFE JSON
# -------------------------------------------------------
def safe_json(raw):
    """Safely parse JSON with fallback"""
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"JSON parse error: {e}")
        print(f"Raw response: {raw}")
        return {
            "one_line": "Your CV confused the AI.",
            "overview": "Model failed JSON parsing.",
            "fun_obs": "",
            "score": 1
        }


# -------------------------------------------------------
# ROAST ENGINE
# -------------------------------------------------------
def roast_resume(text, mode):
    """Generate brutal resume roast using OpenAI"""
    if not text.strip():
        return {
            "one_line": "Your file contains no readable text.",
            "overview": "Extraction failed — try uploading a cleaner PDF/DOCX.",
            "fun_obs": "",
            "score": 1
        }

    # Limit text to avoid token limits
    text_sample = text[:4000]

    prompt = f"""You are RoastRank — a brutal resume roasting AI.

Analyze this resume and return ONLY valid JSON with exactly these keys:
- one_line: A short, savage one-liner roast (max 15 words)
- overview: Funny but factual criticism of the resume (2-3 sentences)
- fun_obs: One punchline observation about the candidate
- score: Integer from 1-100 representing resume quality (be brutally honest)

Mode: {mode}

Resume text:
{text_sample}

Return ONLY the JSON object, nothing else."""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are RoastRank, a brutal resume critic. Return ONLY valid JSON with keys: one_line, overview, fun_obs, score"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        raw = res.choices[0].message.content
        return safe_json(raw)
    except Exception as e:
        print(f"OpenAI API Error: {e}")
        return {
            "one_line": "AI roast engine crashed.",
            "overview": f"Error calling OpenAI API: {str(e)}",
            "fun_obs": "Maybe check your API key?",
            "score": 1
        }


# -------------------------------------------------------
# ROUTES
# -------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Home page with upload form"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile, mode: str = Form(...)):
    """Handle resume upload and generate roast"""
    text = extract_text(file)
    name = guess_name(text)
    roast = roast_resume(text, mode)

    # Save to database
    conn = get_db()
    cursor = conn.cursor()
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
    conn.close()

    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": roast["score"],
        "one_line": roast["one_line"],
        "overview": roast["overview"],
        "fun_obs": roast["fun_obs"]
    })


@app.get("/leaderboard", response_class=HTMLResponse)
def leaderboard(request: Request):
    """Show top 40 roasts"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name, score, one_line, created_at
        FROM roasts
        ORDER BY score DESC, created_at DESC
        LIMIT 40
    """)
    rows = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        "leaderboard.html",
        {"request": request, "roasts": rows}
    )


@app.get("/test-api")
def test_api():
    """Test endpoint to verify OpenAI API connection"""
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'API works!'"}],
            max_tokens=10
        )
        return {
            "status": "success", 
            "response": res.choices[0].message.content,
            "model": res.model
        }
    except Exception as e:
        return {
            "status": "error", 
            "message": str(e),
            "api_key_set": bool(os.getenv("OPENAI_API_KEY"))
        }


# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)