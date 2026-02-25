import json
import urllib.request

url = "https://openrouter.ai/api/v1/models"
with urllib.request.urlopen(url) as response:
    data = json.load(response)

models = data.get('data', [])

# Known models that support web search/browsing (built-in capability)
# These are models with known web search capability
web_search_models = [
    'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-4',
    'gemini-2.0-flash', 'gemini-2.0-flash-exp', 'gemini-pro', 'gemini-flash',
    'claude-3-opus', 'claude-3-sonnet', 'claude-3.5-sonnet', 'claude-3-haiku',
    'grok-4-fast', 'grok-4', 'grok-2-vision-1212',
    'qwen-turbo', 'qwen-plus', 'qwen-max',
]

# Filter models that likely support web search
web_search_candidates = []
for m in models:
    model_id = m.get('id', '').lower()
    # Check if model name matches known web search models
    for wsm in web_search_models:
        if wsm in model_id:
            web_search_candidates.append(m)
            break

# Filter and sort by price
web_search_with_price = [m for m in web_search_candidates if m.get('pricing', {}).get('prompt')]
web_search_with_price.sort(key=lambda x: float(x['pricing']['prompt']) if x['pricing'].get('prompt') else 999)

print("Models with web search capability (sorted by price):\n")
for m in web_search_with_price:
    prompt_price = m.get('pricing', {}).get('prompt', 'N/A')
    completion_price = m.get('pricing', {}).get('completion', 'N/A')
    print(f"{m['id']}")
    print(f"  Prompt: ${prompt_price}/1M tokens")
    print(f"  Completion: ${completion_price}/1M tokens")
    print()
