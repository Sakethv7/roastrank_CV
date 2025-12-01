# RoastRank
## Overview

RoastRank is an AI-powered resume roasting engine with a cinematic Star-Wars-inspired interface.
Upload your CV and receive sharp, compact, and brutally funny AI roasts powered by OpenAI.

## Features
Resume Roasting

    Quick Roast: fast, punchy one-liner + fun observation

    Full Roast: one-liner, overview, detailed roast, fun observation

    Consistent scoring across roast modes

    Star Wars-Inspired UI

    Cinematic intro text scroll

    Animated starfield background

    Neon cyber-sci-fi interface

## Supported File Types

    PDF

    DOCX

    TXT

## Leaderboard

    Displays top 50 roasted candidates

    Auto-extracts candidate names from resumes

## Database

    SQLite storage for all roast entries

Auto-creates tables on launch

## Tech Stack
    Backend

    Python

    FastAPI

    SQLite

    AI Model

    OpenAI GPT-4.1-mini

    Frontend

    TailwindCSS

    Jinja2 Templates

    Canvas-based starfield animation

    Deployment

    Docker

    Hugging Face Spaces

## Project Structure
    roastrank/
    │── main.py
    │── requirements.txt
    │── Dockerfile
    │── README.md
    │── .env
    │── static/
    │     ├── starfield.js
    │     └── style.css
    │── templates/
    │     ├── index.html
    │     ├── result.html
    │     └── leaderboard.html

## Local Setup
1. Clone the Repository
git clone https://github.com/<your-username>/roastrank
cd roastrank

2. Create a Virtual Environment
python3 -m venv .venv
source .venv/bin/activate

3. Install Dependencies
pip install -r requirements.txt

4. Add Environment Variables

Create a .env file:

OPENAI_API_KEY=your_key_here

5. Run the Application
uvicorn main:app --reload --port 7860

6. Open in Browser
http://localhost:7860

## Deployment on Hugging Face Spaces
    Add Space Secret

    In Settings → Variables → New Variable:

    OPENAI_API_KEY

    Deploy

    Hugging Face automatically builds and deploys the Docker app.

    API Routes
    GET /

    Landing page

    POST /upload

    Upload and process the CV

    GET /leaderboard

    View top roasted candidates

## License

MIT License

### If you want, I can also add:

    GitHub badges

    Screenshot previews

    Demo GIF

A dark-themed banner