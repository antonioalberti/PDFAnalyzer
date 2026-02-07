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

        if not response.choices:
            print(Fore.RED + "Error: No response choices found." + Style.RESET_ALL)
            raise Exception("No response choices found.")

        llm_response = response.choices[0].message.content.strip()
        return llm_response
