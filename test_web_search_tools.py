"""
Test script for web search functionality using OpenAI Tools.
Tests different models to find one that works with web search.
Sorted by cost-effectiveness (cheapest first).

Usage:
    python test_web_search_tools.py "Article Title Here"
"""
import os
import sys
import json
import argparse
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

# Prompt template (same as summary_prompt.txt)
PROMPT_TEMPLATE = """You have the ability to search the web.

TASK: Find information about this scientific article:
"{article_title}"

Instructions:
1. Use your web browsing/search capability to look up this article
2. Provide a summary if you find it, or "SUMMARY_NOT_FOUND" if you cannot find any information

Summary (in English, 2-3 paragraphs):
"""

# Models to test - sorted by cost-effectiveness (cheapest first)
# These are models with known web search capability
MODELS_TO_TEST = [
    "qwen/qwen-turbo",              # $0.00005/1M - cheapest
    "google/gemini-2.0-flash-lite-001",  # $0.000075/1M
    "openai/gpt-4.1-nano",          # $0.0001/1M
    "google/gemini-2.0-flash-001",  # $0.0001/1M
    "openai/gpt-4o-mini",           # $0.00015/1M
    "x-ai/grok-4-fast",             # $0.0002/1M
    "x-ai/grok-4.1-fast",           # $0.0002/1M
    "anthropic/claude-3-haiku",     # $0.00025/1M
    "qwen/qwen-plus",                # $0.0004/1M
    "openai/gpt-4.1-mini",          # $0.0004/1M
    "qwen/qwen-max",                # $0.0016/1M
    "openai/gpt-4.1",               # $0.002/1M
    "openai/gpt-4o",                # $0.0025/1M
    "x-ai/grok-4",                   # $0.003/1M
    "anthropic/claude-3.5-sonnet",   # $0.006/1M
]


def test_model_direct(model_name: str, article_title: str):
    """Test a model with direct search prompt."""
    print(Fore.CYAN + f"\n{'='*60}")
    print(Fore.CYAN + f"Testing model: {model_name}")
    print(Fore.CYAN + f"{'='*60}")
    
    prompt = PROMPT_TEMPLATE.replace("{article_title}", article_title)
    
    try:
        print(Fore.YELLOW + "Sending request with search prompt...")
        
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a research assistant with web browsing capabilities. Always search the web when asked about articles or papers."},
                {"role": "user", "content": prompt}
            ]
        )
        
        if response.choices:
            result = response.choices[0].message.content.strip()
            print(Fore.GREEN + f"Response: {result[:200]}..." if len(result) > 200 else Fore.GREEN + f"Response: {result}")
            
            if result == "SUMMARY_NOT_FOUND":
                print(Fore.YELLOW + "Result: SUMMARY_NOT_FOUND")
            elif any(pattern in result.lower() for pattern in ["could not find", "cannot find", "not found", "no information", "unable to locate", "don't have information"]):
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
    parser = argparse.ArgumentParser(
        description="Test web search models for article summarization"
    )
    parser.add_argument(
        "article_title", 
        nargs="?", 
        default="AIPyCraft - AI-Assisted Software Development Lifecycle for 6G Blockchain Oracle Validation",
        help="Title of the article to search for"
    )
    
    args = parser.parse_args()
    article_title = args.article_title
    
    print(Fore.CYAN + "="*60)
    print(Fore.CYAN + "Web Search Test - Sorted by Cost-Effectiveness")
    print(Fore.CYAN + "="*60)
    print(Fore.CYAN + f"\nTesting article: {article_title}\n")
    
    success = False
    
    # Test all models in order
    for model in MODELS_TO_TEST:
        if test_model_direct(model, article_title):
            print(Fore.GREEN + f"\n>>> WORKING MODEL FOUND: {model}")
            success = True
            break
    
    if not success:
        print(Fore.RED + "\n" + "="*60)
        print(Fore.RED + "No working model found!")
        print(Fore.RED + "="*60)
    else:
        print(Fore.GREEN + "\n" + "="*60)
        print(Fore.GREEN + "Test completed successfully!")
        print(Fore.GREEN + "="*60)

if __name__ == "__main__":
    main()
