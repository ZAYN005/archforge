import os
from openai import OpenAI

key = os.environ.get("DEEPSEEK_API_KEY")
if not key:
    print("ERROR: key not found. Did you reopen PowerShell after setx?")
    raise SystemExit

client = OpenAI(api_key=key, base_url="https://api.deepseek.com")

print("Models:", [m.id for m in client.models.list().data])

resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Say hello in 5 words."}],
)
print("Reply:", resp.choices[0].message.content)
print("Tokens:", resp.usage)