import os
from dotenv import load_dotenv
from openai import OpenAI

# Load local .env file
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("❌ OPENAI_API_KEY missing! Add it to your .env or HF Secrets.")

client = OpenAI(api_key=api_key)

print("🔍 Testing OpenAI API...")

try:
    # Simple small request to avoid cost
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a test bot."},
            {"role": "user", "content": "Say hi in 5 words."}
        ]
    )

    print("\n✅ OpenAI API is working!")
    print("Response:", response.choices[0].message.content)

except Exception as e:
    print("\n❌ OpenAI API test failed.")
    print("Error:", str(e))
