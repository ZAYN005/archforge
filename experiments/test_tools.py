import os, json
from openai import OpenAI

client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")

tools = [{
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two numbers",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
}]

messages = [{"role": "user", "content": "What is 17 + 25? Use the add tool."}]
r = client.chat.completions.create(model="deepseek-v4-pro", messages=messages, tools=tools)
msg = r.choices[0].message
print("1) Tool call:", msg.tool_calls)

call = msg.tool_calls[0]
args = json.loads(call.function.arguments)
result = args["a"] + args["b"]

messages.append(msg)
messages.append({"role": "tool", "tool_call_id": call.id, "content": str(result)})
r2 = client.chat.completions.create(model="deepseek-v4-pro", messages=messages, tools=tools)
print("2) Final answer:", r2.choices[0].message.content)
print("Tokens:", r2.usage.total_tokens)