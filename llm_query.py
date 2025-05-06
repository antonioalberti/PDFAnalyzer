import os
import openai
from colorama import init, Fore, Style

init(autoreset=True)

class LLMAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("ROUTER_API_KEY")
        if not self.api_key:
            print(Fore.RED + "Error: ROUTER_API_KEY not found in environment variables.")
            raise ValueError("ROUTER_API_KEY not found in environment variables.")
        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url="https://router.requesty.ai/v1",
            default_headers={"Authorization": f"Bearer {self.api_key}"}
        )

    @staticmethod
    def load_prompt(prompt_path):
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()

    def analyze(self, classified_keywords, prompt, abstract=None, model_name="gpt-4.1-mini-2025-04-14", prompt_approval=False):
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

    def analyze_single_occurrence(self, prompt_text, model_name="gpt-4.1-mini-2025-04-14", prompt_approval=True):
        #print(Fore.BLUE + "\nPrompt to be sent to LLM:")
        #print(Style.RESET_ALL + f"\t{prompt_text}")

        if prompt_approval:
            # Ask user to continue or not before calling LLM
            while True:
                user_input = input(Fore.MAGENTA + "Send this prompt to LLM? (y/n): " + Style.RESET_ALL).strip().lower()
                if user_input == 'y':
                    break
                elif user_input == 'n':
                    print(Fore.RED + "Prompt discarded by user." + Style.RESET_ALL)
                    return None
                else:
                    print(Fore.YELLOW + "Please enter 'y' or 'n'." + Style.RESET_ALL)

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
