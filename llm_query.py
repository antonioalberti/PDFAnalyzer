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

    def analyze(self, classified_keywords, prompt, abstract):
        # Prepare the input text for the model
        input_text = "Keyword Counts:\n"
        for enabler, keyword_counter in classified_keywords.items():
            input_text += f"{enabler}:\n"
            for keyword, count in keyword_counter.items():
                input_text += f"Keyword: {keyword}, Count: {count}\n"
            input_text += "\n"

        # Combine prompt and input text
        full_prompt = prompt + "\n\n" + "Abstract:\n" + abstract + "\n\n" + input_text

        print("\nFull Prompt:")
        print(full_prompt)

        # Call the chat completion endpoint
        response = self.client.chat.completions.create(
            model="alibaba/qwen-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": full_prompt}
            ]
        )

        if not response.choices:
            raise Exception("No response choices found.")

        return response.choices[0].message.content.strip()
