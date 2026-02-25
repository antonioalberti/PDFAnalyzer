
import os
import random
from openai import OpenAI
from colorama import init, Fore, Style

init(autoreset=True)

class LLMAnalyzer:
    def __init__(self, api_key=None, models_file="models.txt"):
        self.api_key = api_key or os.getenv("ROUTER_API_KEY")
        if not self.api_key:
            print(Fore.RED + "Error: ROUTER_API_KEY not found in environment variables.")
            raise ValueError("ROUTER_API_KEY not found in environment variables.")
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.models = self._load_models(models_file)
        if not self.models:
            print(Fore.YELLOW + f"Warning: No models loaded from {models_file}. Using default model." + Style.RESET_ALL)
            self.models = ["openai/gpt-4.1-mini-2025-04-14"]
        
        # Token usage tracking
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost = 0.0  # in USD
        
        # Model pricing (USD per 1M tokens) - updated with correct prices
        self.model_pricing = {
            # Qwen models
            "qwen/qwen-turbo": {"prompt": 0.04, "completion": 0.16},
            "qwen/qwen-plus": {"prompt": 0.40, "completion": 1.20},
            "qwen/qwen-max": {"prompt": 1.60, "completion": 6.40},
            "qwen/qwen2.5-coder-7b-instruct": {"prompt": 0.03, "completion": 0.09},
            # Google models
            "google/gemini-2.0-flash-lite-001": {"prompt": 0.075, "completion": 0.30},
            "google/gemini-2.0-flash-001": {"prompt": 0.10, "completion": 0.40},
            "google/gemini-3-flash-preview": {"prompt": 0.10, "completion": 0.50},
            "google/gemma-3-4b-it": {"prompt": 0.04, "completion": 0.08},
            "google/gemma-3-12b-it": {"prompt": 0.04, "completion": 0.13},
            "google/gemma-2-9b-it": {"prompt": 0.03, "completion": 0.09},
            # OpenAI models
            "openai/gpt-4.1-nano": {"prompt": 0.10, "completion": 0.40},
            "openai/gpt-4.1-mini": {"prompt": 0.40, "completion": 1.60},
            "openai/gpt-4.1": {"prompt": 2.00, "completion": 8.00},
            "openai/gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
            "openai/gpt-4o": {"prompt": 2.50, "completion": 10.00},
            "openai/gpt-5-nano": {"prompt": 0.05, "completion": 0.40},
            "openai/gpt-5-mini": {"prompt": 0.05, "completion": 0.40},
            # xAI models
            "x-ai/grok-4-fast": {"prompt": 0.20, "completion": 0.50},
            "x-ai/grok-4.1-fast": {"prompt": 0.20, "completion": 0.50},
            "x-ai/grok-4": {"prompt": 3.00, "completion": 15.00},
            # Meta/Llama models
            "meta-llama/llama-3.1-8b-instruct": {"prompt": 0.02, "completion": 0.05},
            "meta-llama/llama-3-8b-instruct": {"prompt": 0.03, "completion": 0.04},
            "meta-llama/llama-3.2-3b-instruct": {"prompt": 0.02, "completion": 0.02},
            # Anthropic models
            "anthropic/claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
            "anthropic/claude-3.5-sonnet": {"prompt": 6.00, "completion": 30.00},
        }
    
    def _get_model_price(self, model_name: str) -> tuple[float, float]:
        """Get prompt and completion prices for a model."""
        model_lower = model_name.lower()
        for key, prices in self.model_pricing.items():
            if key in model_lower:
                return prices["prompt"], prices["completion"]
        # Default prices if model not found - use a reasonable estimate
        print(Fore.YELLOW + f"Warning: No pricing found for model '{model_name}', using default estimate." + Style.RESET_ALL)
        return 0.10, 0.40
    
    def _track_usage(self, model_name: str, usage: dict):
        """Track token usage and cost from API response."""
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        prompt_price, completion_price = self._get_model_price(model_name)
        
        prompt_cost = (prompt_tokens / 1_000_000) * prompt_price
        completion_cost = (completion_tokens / 1_000_000) * completion_price
        total_call_cost = prompt_cost + completion_cost
        
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cost += total_call_cost
    
    def get_usage_summary(self) -> dict:
        """Get a summary of token usage."""
        total_tokens = self.total_prompt_tokens + self.total_completion_tokens
        return {
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": total_tokens,
            "total_cost_usd": self.total_cost
        }
    
    def print_usage_summary(self, output_file=None):
        """Print token usage summary to console and optionally save to file."""
        summary = self.get_usage_summary()
        
        # Format cost string - always show at least 4 decimal places
        cost_str = f"${summary['total_cost_usd']:.6f} USD"
        
        # Print to console
        print(Fore.CYAN + "\n" + "="*60)
        print(Fore.CYAN + "TOKEN USAGE SUMMARY")
        print(Fore.CYAN + "="*60)
        print(f"Prompt tokens:     {summary['prompt_tokens']:,}")
        print(f"Completion tokens: {summary['completion_tokens']:,}")
        print(f"Total tokens:      {summary['total_tokens']:,}")
        print(Fore.GREEN + f"Total cost:        {cost_str}")
        print(Fore.CYAN + "="*60 + Style.RESET_ALL)
        
        # Save to file if path provided
        if output_file:
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write("TOKEN USAGE SUMMARY\n")
                    f.write("="*60 + "\n")
                    f.write(f"Prompt tokens:     {summary['prompt_tokens']:,}\n")
                    f.write(f"Completion tokens: {summary['completion_tokens']:,}\n")
                    f.write(f"Total tokens:      {summary['total_tokens']:,}\n")
                    f.write(f"Total cost:        {cost_str}\n")
                    f.write("="*60 + "\n")
                print(Fore.GREEN + f"Saved cost summary to {output_file}" + Style.RESET_ALL)
            except Exception as e:
                print(Fore.RED + f"Error saving cost summary: {e}" + Style.RESET_ALL)

    def _load_models(self, models_file):
        """Load model names from a text file, ignoring comments and empty lines."""
        models = []
        try:
            with open(models_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        models.append(line)
            print(Fore.CYAN + f"Loaded {len(models)} models from {models_file}: {', '.join(models)}" + Style.RESET_ALL)
        except FileNotFoundError:
            print(Fore.YELLOW + f"Warning: Models file '{models_file}' not found. Using default model." + Style.RESET_ALL)
        except Exception as e:
            print(Fore.RED + f"Error loading models file: {e}. Using default model." + Style.RESET_ALL)
        return models

    def get_random_model(self):
        """Select a random model from the loaded list."""
        selected_model = random.choice(self.models)
        print(Fore.CYAN + f"Selected model: {selected_model}" + Style.RESET_ALL)
        return selected_model

    @staticmethod
    def load_prompt(prompt_path):
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()

    def analyze(self, classified_keywords, prompt, abstract=None, model_name=None):
        # Use random model if none specified
        if model_name is None:
            model_name = self.get_random_model()
        else:
            print(Fore.CYAN + f"Using specified model: {model_name}" + Style.RESET_ALL)

        # Use the prompt as is, since keyword counts are already included
        full_prompt = prompt

        # Call the chat completion endpoint
        system_message = (
            "You are an expert assistant specialized in analyzing scientific articles."
        )
        response = self.client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": full_prompt}
            ]
        )

        # Track token usage
        if hasattr(response, 'usage') and response.usage:
            self._track_usage(model_name, {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens
            })

        if not response.choices:
            print(Fore.RED + "Error: No response choices found." + Style.RESET_ALL)
            raise Exception("No response choices found.")

        llm_response = response.choices[0].message.content.strip()
        print(Fore.GREEN + "\nLLM response:")
        print(Style.RESET_ALL + f"\t{llm_response}")

        return llm_response

    def analyze_single_occurrence(self, prompt_text, model_name=None):
        # Use random model if none specified
        if model_name is None:
            model_name = self.get_random_model()
        else:
            print(Fore.CYAN + f"Using specified model: {model_name}" + Style.RESET_ALL)

        # Send prompt to LLM automatically without user approval
        system_message = (
            "You are an expert assistant specialized in analyzing scientific articles."
        )
        response = self.client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt_text}
            ]
        )

        # Track token usage
        if hasattr(response, 'usage') and response.usage:
            self._track_usage(model_name, {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens
            })

        if not response.choices:
            print(Fore.RED + "Error: No response choices found." + Style.RESET_ALL)
            raise Exception("No response choices found.")

        llm_response = response.choices[0].message.content.strip()
        return llm_response

    # List of models that support web search - tried in order of cost-effectiveness
    # Sorted by price (cheapest first)
    WEB_SEARCH_MODELS = [
        "qwen/qwen-turbo",              # $0.04/1M prompt
        "google/gemini-2.0-flash-lite-001",  # $0.075/1M prompt
        "openai/gpt-4.1-nano",          # $0.10/1M prompt
        "google/gemini-2.0-flash-001",  # $0.10/1M prompt
        "openai/gpt-4o-mini",           # $0.15/1M prompt
        "x-ai/grok-4-fast",             # $0.20/1M prompt
    ]

    def fetch_article_summary(self, article_title: str, model_name: str | None = None) -> str | None:
        """Fetch a summary of the article from the internet using multiple LLMs.
        
        Tries multiple models and returns all successfully obtained summaries.
        
        Args:
            article_title: The title of the article to summarize
            model_name: Optional model name to use (uses all web search models if None)
            
        Returns:
            A string with all summaries combined, or None if no summary found
        """
        prompt_template = self.load_prompt("summary_prompt.txt")
        prompt = prompt_template.replace("{article_title}", article_title)
        
        print(Fore.CYAN + f"Fetching article summary for: {article_title}" + Style.RESET_ALL)
        
        # Determine which models to use
        if model_name:
            models_to_try = [model_name]
        else:
            models_to_try = self.WEB_SEARCH_MODELS
        
        system_message = (
            "You are a research assistant with web browsing capabilities. "
            "Always search the web when asked about articles or papers."
        )
        
        all_summaries = []
        
        for search_model in models_to_try:
            print(Fore.CYAN + f"Trying model: {search_model}" + Style.RESET_ALL)
            
            try:
                response = self.client.chat.completions.create(
                    model=search_model,
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt}
                    ]
                )
                
                if not response.choices:
                    print(Fore.YELLOW + f"No response choices from {search_model}" + Style.RESET_ALL)
                    continue

                llm_response = response.choices[0].message.content.strip()
                
                # Check if response indicates not found
                if llm_response == "SUMMARY_NOT_FOUND":
                    print(Fore.YELLOW + f"{search_model}: SUMMARY_NOT_FOUND" + Style.RESET_ALL)
                    continue
                
                # Check for various "not found" patterns
                lower_response = llm_response.lower()
                not_found_patterns = ["could not find", "cannot find", "not found", "no information", 
                                      "does not appear", "unable to find", "search failed", 
                                      "no results", "i cannot find", "i could not find",
                                      "i couldn't find", "don't have information"]
                if any(pattern in lower_response for pattern in not_found_patterns):
                    print(Fore.YELLOW + f"{search_model}: Article not found" + Style.RESET_ALL)
                    continue
                
                if not llm_response or len(llm_response.strip()) == 0:
                    print(Fore.YELLOW + f"{search_model}: Empty response" + Style.RESET_ALL)
                    continue
                
                # Track token usage
                if hasattr(response, 'usage') and response.usage:
                    self._track_usage(search_model, {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens
                    })
                
                # Success! Add to summaries
                print(Fore.GREEN + f"{search_model}: Found summary!" + Style.RESET_ALL)
                all_summaries.append(f"[{search_model}]\n{llm_response}")
                
            except Exception as e:
                error_msg = str(e)
                print(Fore.RED + f"{search_model}: Error - {error_msg[:100]}..." + Style.RESET_ALL)
                continue
        
        if not all_summaries:
            print(Fore.RED + "No summaries obtained from any model." + Style.RESET_ALL)
            return None
        
        # Combine all summaries
        combined = "\n\n---\n\n".join(all_summaries)
        print(Fore.GREEN + f"Obtained {len(all_summaries)} summary(s) from {len(models_to_try)} models." + Style.RESET_ALL)
        return combined
