"""Swappable AI model providers. Each returns the reply as a dict matching REPLY_SCHEMA.

- anthropic: Claude (default), using a forced tool call so the output is always structured.
- openai_compatible: any provider with an OpenAI-style /chat/completions API and JSON mode,
  e.g. DeepSeek (https://api.deepseek.com), OpenAI, OpenRouter. Set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.
"""
import json

import httpx

PRESETS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-flash"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": ""},
}


class AnthropicLLM:
    def __init__(self, client, model: str):
        self.client, self.model = client, model

    async def complete_json(self, system: str, messages: list[dict], schema: dict) -> dict:
        tool = {"name": "send_reply", "description": "Send the reply to the customer.", "input_schema": schema}
        resp = await self.client.messages.create(
            model=self.model, max_tokens=1024, system=system, messages=messages,
            tools=[tool], tool_choice={"type": "tool", "name": "send_reply"},
        )
        block = next(b for b in resp.content if getattr(b, "type", "") == "tool_use")
        return dict(block.input)


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, api_key: str, model: str, http: httpx.AsyncClient | None = None):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.http = http or httpx.AsyncClient(timeout=60)

    async def complete_json(self, system: str, messages: list[dict], schema: dict) -> dict:
        fields = ", ".join(f'"{k}"' for k in schema["properties"])
        system = (system + "\n\nRespond with a single json object only, with these keys: " + fields + ".\n"
                  "JSON schema: " + json.dumps(schema))
        r = await self.http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "max_tokens": 1024, "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system}, *messages]},
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise ValueError("empty model response")
        return json.loads(content)


def build_llm(s, anthropic_client=None):
    if s.llm_provider == "anthropic":
        if anthropic_client is None:
            import anthropic

            anthropic_client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key)
        return AnthropicLLM(anthropic_client, s.model)
    preset = PRESETS.get(s.llm_provider, {})
    base = s.llm_base_url or preset.get("base_url", "")
    model = s.llm_model or preset.get("model", "")
    if not (base and model and s.llm_api_key):
        raise RuntimeError(f"LLM_PROVIDER={s.llm_provider} needs LLM_API_KEY, and LLM_BASE_URL/LLM_MODEL if not preset")
    return OpenAICompatibleLLM(base, s.llm_api_key, model)
