"""
Test script for web search functionality using OpenAI Tools.
Tests different models to find one that works with web search via function calling.
"""
import os
import sys
import json
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

# Define web search tool using OpenAI function calling format
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for information about a topic. Use this to find up-to-date information, articles, or facts.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find information on the web"
                }
            },
            "required": ["query"]
        }
    }
}

# Models to test - these should support function calling
MODELS_TO_TEST = [
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "google/gemini-2.0-flash",
    "anthropic/claude-3.5-sonnet",
    "x-ai/grok-4-fast",
]


def test_model_with_tools(model_name: str):
    """Test a single model with function calling for web search."""
    print(Fore.CYAN + f"\n{'='*60}")
    print(Fore.CYAN + f"Testing model (WITH tools): {model_name}")
    print(Fore.CYAN + f"{'='*60}")
    
    try:
        print(Fore.YELLOW + "Sending request with web_search tool...")
        
        # First call - send prompt with tool available
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a research assistant that searches the web. You have access to a web_search tool to find information."},
                {"role": "user", "content": PROMPT}
            ],
            tools=[WEB_SEARCH_TOOL],
            tool_choice={"type": "function", "function": {"name": "web_search"}}
        )
        
        # Check if model used the tool
        if response.choices and response.choices[0].message:
            message = response.choices[0].message
            
            # Check if model wants to call the tool
            if message.tool_calls:
                print(Fore.GREEN + f"Model wants to call tool: {message.tool_calls[0].function.name}")
                print(Fore.GREEN + f"Arguments: {message.tool_calls[0].function.arguments}")
                
                # Get the search query from the tool call
                try:
                    tool_args = json.loads(message.tool_calls[0].function.arguments)
                    search_query = tool_args.get("query", ARTICLE_TITLE)
                    print(Fore.CYAN + f"Search query: {search_query}")
                except:
                    search_query = ARTICLE_TITLE
                    print(Fore.YELLOW + "Could not parse tool arguments, using article title as query")
                
                # For testing, we'll simulate the search by doing another call
                # In production, you would call the actual search API here
                # Let's do a second call to get the final response after "searching"
                print(Fore.YELLOW + "Calling model again to get final answer after search simulation...")
                
                # Simulate a conversation with search results
                response2 = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You are a research assistant that searches the web. You have already searched for information about the article."},
                        {"role": "user", "content": f"Based on your web search, provide a summary of the article: {ARTICLE_TITLE}. If you found information, provide a summary. If not, respond with EXACTLY 'SUMMARY_NOT_FOUND'."}
                    ]
                )
                
                if response2.choices:
                    result = response2.choices[0].message.content.strip()
                    print(Fore.GREEN + f"Response: {result[:200]}..." if len(result) > 200 else Fore.GREEN + f"Response: {result}")
                    
                    if result == "SUMMARY_NOT_FOUND":
                        print(Fore.YELLOW + "Result: SUMMARY_NOT_FOUND")
                    elif any(pattern in result.lower() for pattern in ["could not find", "cannot find", "not found", "no information"]):
                        print(Fore.YELLOW + "Result: Article not found in response")
                    else:
                        print(Fore.GREEN + "SUCCESS! Found article summary!")
                        return True
            else:
                # Model responded directly without using tool
                result = message.content.strip() if message.content else ""
                print(Fore.YELLOW + f"Model did not use tool. Direct response: {result[:200]}..." if result else "Empty response")
                
                if result == "SUMMARY_NOT_FOUND":
                    print(Fore.YELLOW + "Result: SUMMARY_NOT_FOUND")
                elif result and not any(pattern in result.lower() for pattern in ["could not find", "cannot find", "not found", "no information"]):
                    print(Fore.GREEN + "SUCCESS! Found article summary!")
                    return True
                    
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg and "No endpoints found" in error_msg:
            print(Fore.RED + f"Model not available: {error_msg[:100]}...")
        elif "404" in error_msg:
            print(Fore.RED + f"404 Error: {error_msg[:100]}...")
        elif "tool_calls" in error_msg.lower():
            print(Fore.RED + f"Tool calling not supported: {error_msg[:200]}...")
        else:
            print(Fore.RED + f"Error: {type(e).__name__}: {error_msg[:200]}...")
    
    return False


def test_model_direct_with_search_prompt(model_name: str):
    """Test a model with a more direct search-focused prompt."""
    print(Fore.CYAN + f"\n{'='*60}")
    print(Fore.CYAN + f"Testing model (DIRECT with search prompt): {model_name}")
    print(Fore.CYAN + f"{'='*60}")
    
    # Enhanced prompt that explicitly asks for web search
    search_prompt = f"""You have the ability to search the web. 

TASK: Find information about this scientific article:
"{ARTICLE_TITLE}"

Instructions:
1. Use your web browsing/search capability to look up this article
2. Provide a summary if you find it, or "SUMMARY_NOT_FOUND" if you cannot find any information

Summary (in English, 2-3 paragraphs):"""

    try:
        print(Fore.YELLOW + "Sending request with explicit search instructions...")
        
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a research assistant with web browsing capabilities. Always search the web when asked about articles or papers."},
                {"role": "user", "content": search_prompt}
            ]
        )
        
        if response.choices:
            result = response.choices[0].message.content.strip()
            print(Fore.GREEN + f"Response: {result[:200]}..." if len(result) > 200 else Fore.GREEN + f"Response: {result}")
            
            if result == "SUMMARY_NOT_FOUND":
                print(Fore.YELLOW + "Result: SUMMARY_NOT_FOUND")
            elif any(pattern in result.lower() for pattern in ["could not find", "cannot find", "not found", "no information", "unable to locate"]):
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
    print(Fore.CYAN + "Web Search Test Script - Using Tools/Function Calling")
    print(Fore.CYAN + "="*60)
    print(Fore.CYAN + f"\nTesting article: {ARTICLE_TITLE}\n")
    
    success = False
    
    # Phase 1: Test with tools/function calling
    print(Fore.CYAN + "\n=== PHASE 1: Testing WITH function calling (tools) ===")
    for model in MODELS_TO_TEST:
        if test_model_with_tools(model):
            print(Fore.GREEN + f"\n>>> WORKING MODEL FOUND (TOOLS): {model}")
            success = True
            break
    
    # Phase 2: Test with direct search prompts
    if not success:
        print(Fore.CYAN + "\n=== PHASE 2: Testing with DIRECT search prompts ===")
        for model in MODELS_TO_TEST:
            if test_model_direct_with_search_prompt(model):
                print(Fore.GREEN + f"\n>>> WORKING MODEL FOUND (DIRECT): {model}")
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
