"""
Test script for web search functionality.
Tests different models to find one that works with web search.
"""
import os
import sys
from dotenv import load_dotenv
from openai import OpenAI
from colorama import init, Fore, Style

init(autoreset=True)

# Load environment variables
load_dotenv()

# Get API key
API_KEY = os.getenv("ROUTER_API_KEY")
if not API_KEY:
    print(Fore.RED + "Error: ROUTER_API_KEY not found in environment variables.")
    sys.exit(1)

# Initialize client
client = OpenAI(
    api_key=API_KEY,
    base_url="https://openrouter.ai/api/v1",
    default_headers={"Authorization": f"Bearer {API_KEY}"}
)

# Test article title
ARTICLE_TITLE = "AIPyCraft - AI-Assisted Software Development Lifecycle for 6G Blockchain Oracle Validation"

# Prompt template
PROMPT = f"""You are an expert assistant specialized in researching scientific articles.

TASK:
The article being analyzed has the following title: "{ARTICLE_TITLE}"

IMPORTANT: You MUST search the internet for this article. Use your web search capability to find information about this paper.

Provide a brief summary in English (2-3 paragraphs maximum) that includes:
1. The main topic/focus of the article
2. The key contributions or findings
3. Any relevant context about the authors or publication

If you cannot find ANY information about this article after searching the web, respond with EXACTLY "SUMMARY_NOT_FOUND".

Provide only the summary or SUMMARY_NOT_FOUND, nothing else."""

# Models to test
MODELS_TO_TEST = [
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "openai/gpt-4-turbo",
    "x-ai/grok-4-fast",
]

def test_model_no_param(model_name: str):
    """Test a single model WITHOUT web search parameter."""
    print(Fore.CYAN + f"\n{'='*60}")
    print(Fore.CYAN + f"Testing model (NO param): {model_name}")
    print(Fore.CYAN + f"{'='*60}")
    
    try:
        print(Fore.YELLOW + "Trying WITHOUT enable_web_search parameter...")
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a research assistant that searches the web."},
                {"role": "user", "content": PROMPT}
            ]
        )
        
        if response.choices:
            result = response.choices[0].message.content.strip()
            print(Fore.GREEN + f"Response: {result[:200]}..." if len(result) > 200 else Fore.GREEN + f"Response: {result}")
            
            if result == "SUMMARY_NOT_FOUND":
                print(Fore.YELLOW + "Result: SUMMARY_NOT_FOUND")
            elif any(pattern in result.lower() for pattern in ["could not find", "cannot find", "not found", "no information"]):
                print(Fore.YELLOW + "Result: Article not found in response")
            else:
                print(Fore.GREEN + "SUCCESS! Found article summary!")
                return True
        else:
            print(Fore.RED + "No choices in response")
            
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg and "No endpoints found" in error_msg:
            print(Fore.RED + f"Model not available: {error_msg[:100]}...")
        elif "404" in error_msg:
            print(Fore.RED + f"404 Error: {error_msg[:100]}...")
        else:
            print(Fore.RED + f"Error: {type(e).__name__}: {error_msg[:200]}...")
    
    return False

def test_model_with_param(model_name: str):
    """Test a single model WITH web search parameter."""
    print(Fore.CYAN + f"\n{'='*60}")
    print(Fore.CYAN + f"Testing model (WITH param): {model_name}")
    print(Fore.CYAN + f"{'='*60}")
    
    try:
        print(Fore.YELLOW + "Trying with enable_web_search: True...")
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a research assistant that searches the web."},
                {"role": "user", "content": PROMPT}
            ],
            extra_body={"enable_web_search": True}
        )
        
        if response.choices:
            result = response.choices[0].message.content.strip()
            print(Fore.GREEN + f"Response: {result[:200]}..." if len(result) > 200 else Fore.GREEN + f"Response: {result}")
            
            if result == "SUMMARY_NOT_FOUND":
                print(Fore.YELLOW + "Result: SUMMARY_NOT_FOUND")
            elif any(pattern in result.lower() for pattern in ["could not find", "cannot find", "not found", "no information"]):
                print(Fore.YELLOW + "Result: Article not found in response")
            else:
                print(Fore.GREEN + "SUCCESS! Found article summary!")
                return True
        else:
            print(Fore.RED + "No choices in response")
            
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg and "No endpoints found" in error_msg:
            print(Fore.RED + f"Model not available: {error_msg[:100]}...")
        elif "404" in error_msg:
            print(Fore.RED + f"404 Error: {error_msg[:100]}...")
        else:
            print(Fore.RED + f"Error: {type(e).__name__}: {error_msg[:200]}...")
    
    return False

def main():
    """Run tests on all models."""
    print(Fore.CYAN + "="*60)
    print(Fore.CYAN + "Web Search Test Script - WITHOUT extra_body param")
    print(Fore.CYAN + "="*60)
    print(Fore.CYAN + f"\nTesting article: {ARTICLE_TITLE}\n")
    
    # First test WITHOUT the parameter
    print(Fore.CYAN + "\n=== PHASE 1: Testing WITHOUT enable_web_search parameter ===")
    success = False
    for model in MODELS_TO_TEST:
        if test_model_no_param(model):
            print(Fore.GREEN + f"\n>>> WORKING MODEL FOUND (NO PARAM): {model}")
            success = True
            break
    
    if not success:
        print(Fore.RED + "\nNo model worked without param. Trying WITH param...")
        
        # Now test WITH the parameter
        print(Fore.CYAN + "\n=== PHASE 2: Testing WITH enable_web_search parameter ===")
        for model in MODELS_TO_TEST:
            if test_model_with_param(model):
                print(Fore.GREEN + f"\n>>> WORKING MODEL FOUND (WITH PARAM): {model}")
                success = True
                break
    
    if not success:
        print(Fore.RED + "\n" + "="*60)
        print(Fore.RED + "No working model found!")
        print(Fore.RED + "="*60)

if __name__ == "__main__":
    main()