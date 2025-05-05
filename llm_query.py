import os
import openai

class LLMAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("ROUTER_API_KEY")
        if not self.api_key:
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

    def analyze(self, classified_keywords, prompt, abstract, model_name="gpt-4.1-mini-2025-04-14"):
        # Prepare the input text for the model
        input_text = "Keyword Counts:\n"
        for enabler, keyword_counter in classified_keywords.items():
            input_text += f"{enabler}:\n"
            for keyword, count in keyword_counter.items():
                input_text += f"Keyword: {keyword}, Count: {count}\n"
            input_text += "\n"

        # Combine prompt and input text
        full_prompt = prompt + "\n\n" + "\n\n" + input_text

        print("\nFull Prompt:")
        print(full_prompt)

        # Call the chat completion endpoint
        system_message = (
            "You are an expert assistant specialized in analyzing scientific articles. "
            "Provide precise, objective, and context-aware responses based on the input. "
            "Focus on understanding the content and relevance of keywords and the text provided."
        )
        response = self.client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": full_prompt}
            ]
        )

        if not response.choices:
            raise Exception("No response choices found.")

        llm_response = response.choices[0].message.content.strip()
        print("\nPrompt to be sent to LLM:")
        print(f"\t{full_prompt}")

        # Ask user to continue or not
        while True:
            user_input = input("Continue with this? (y/n): ").strip().lower()
            if user_input == 'y':
                break
            elif user_input == 'n':
                print("Occurrence discarded by user.")
                return None
            else:
                print("Please enter 'y' or 'n'.")

        return llm_response

    def analyze_single_occurrence(self, prompt_text, model_name="gpt-4.1-mini-2025-04-14"):
        system_message = (
            "You are an expert assistant specialized in analyzing scientific articles. "
            "Provide precise, objective, and context-aware responses based on the input. "
            "Focus on understanding the content and relevance of keywords and the text provided."
        )
        response = self.client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt_text}
            ]
        )

        if not response.choices:
            raise Exception("No response choices found.")

        llm_response = response.choices[0].message.content.strip()
        print("\nPrompt to be sent to LLM:")
        print(f"\t{prompt_text}")

        # Ask user to continue or not
        while True:
            user_input = input("Continue with this? (y/n): ").strip().lower()
            if user_input == 'y':
                break
            elif user_input == 'n':
                print("Occurrence discarded by user.")
                return None
            else:
                print("Please enter 'y' or 'n'.")

        return llm_response
