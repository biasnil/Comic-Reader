"""Translation backends. All blocks of a page go in one request, in reading order, for context.

  OpenAIBackend     any OpenAI-compatible chat server: Ollama, LM Studio, llama.cpp's
                    llama-server, or OpenAI itself. Plain urllib, no extra package.
  AnthropicBackend  Claude through the official `anthropic` package (pip install anthropic).
  LlamaCppBackend   a local GGUF model inside the worker (pip install llama-cpp-python). It can't
                    read images, so it needs the local OCR (ocr = "local" or "manga-ocr").

When `with_images` is set (OCR mode "llm") each block is sent as an image crop too and the
model reads the Japanese itself; otherwise only the OCR'd text is sent.
The answer is JSON: {"blocks": [{"id": 1, "source": "...", "translation": "..."}]}.
"""
import base64
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

try:
    import anthropic
except ImportError:
    anthropic = None

SYSTEM_PROMPT = (
    "You translate Japanese manga into natural, concise {target} that fits in speech bubbles.\n"
    "You get every text block of one page in reading order, numbered by id. Translate each "
    "block in the context of the whole page: keep each character's voice and tone, keep "
    "honorifics such as -san and -chan, and translate sound effects as short {target} sound "
    "effects. Keep translations about as short as the original.\n"
    "If a block has no readable text, give an empty translation.\n"
    'Answer with JSON only: {{"blocks": [{{"id": 1, "source": "<the Japanese text>", '
    '"translation": "<the {target} translation>"}}]}} with one entry per id.'
)

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "source": {"type": "string"},
                    "translation": {"type": "string"},
                },
                "required": ["id", "source", "translation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["blocks"],
    "additionalProperties": False,
}


class TranslationError(RuntimeError):
    pass


def _png_b64(img: Image.Image, max_side: int = 768) -> str:
    img = img.convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _parse(text: str) -> dict[int, tuple[str, str]]:
    """{id: (source, translation)} from the model's answer (tolerates code fences / chatter)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise TranslationError(f"The model didn't answer with JSON: {text[:200]!r}")
    try:
        data = json.loads(m.group(0))
    except ValueError as exc:
        raise TranslationError(f"The model's JSON is invalid: {exc}") from exc
    out = {}
    for item in data.get("blocks", []) if isinstance(data, dict) else []:
        try:
            out[int(item["id"])] = (str(item.get("source", "")), str(item.get("translation", "")))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _intro(items, target: str, with_images: bool) -> str:
    lines = [f"Translate this page's {len(items)} text blocks into {target}."]
    if with_images:
        lines.append("Each block's image follows its id; read the Japanese from the image.")
    for i, (text, _crop) in enumerate(items, 1):
        if not with_images:
            lines.append(f"{i}: {text}")
    return "\n".join(lines)


# ---- backends ------------------------------------------------------------------ #
class OpenAIBackend:
    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        host = urllib.parse.urlparse(self.url).hostname or ""
        # a local server (Ollama, LM Studio) must not go through a system-wide proxy
        local = host in ("localhost", "127.0.0.1", "::1")
        self.opener = urllib.request.build_opener(*([urllib.request.ProxyHandler({})] if local else []))

    def translate(self, items, target: str, with_images: bool) -> dict[int, tuple[str, str]]:
        content = [{"type": "text", "text": _intro(items, target, with_images)}]
        if with_images:
            for i, (_text, crop) in enumerate(items, 1):
                content.append({"type": "text", "text": f"Block {i}:"})
                content.append({"type": "image_url",
                                "image_url": {"url": "data:image/png;base64," + _png_b64(crop)}})
        body = {"model": self.model, "temperature": 0.2,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT.format(target=target)},
                             {"role": "user", "content": content}]}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"),
                                     headers=headers, method="POST")
        try:
            with self.opener.open(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise TranslationError(f"{self.url} answered {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TranslationError(f"Can't reach {self.url} ({exc.reason}). Is the server "
                                   "(Ollama / LM Studio) running?") from exc
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise TranslationError(f"Unexpected answer from {self.url}") from exc
        return _parse(text)


class AnthropicBackend:
    def __init__(self, model: str, api_key: str = ""):
        if anthropic is None:
            raise TranslationError("The Anthropic backend needs: pip install anthropic")
        # no key given: the SDK finds ANTHROPIC_API_KEY or an `ant auth login` profile
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model

    def translate(self, items, target: str, with_images: bool) -> dict[int, tuple[str, str]]:
        content = [{"type": "text", "text": _intro(items, target, with_images)}]
        if with_images:
            for i, (_text, crop) in enumerate(items, 1):
                content.append({"type": "text", "text": f"Block {i}:"})
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": _png_b64(crop)}})
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT.format(target=target),
                messages=[{"role": "user", "content": content}],
                output_config={"effort": "medium",
                               "format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
                # a declined request is re-run on Anthropic's recommended fallback model
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise TranslationError("Anthropic rejected the API key (Translation settings)") from exc
        except anthropic.RateLimitError as exc:
            raise TranslationError("Anthropic rate limit reached; try again shortly") from exc
        except anthropic.APIStatusError as exc:
            raise TranslationError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise TranslationError("Can't reach the Anthropic API (network)") from exc
        if response.stop_reason == "refusal":
            raise TranslationError("The model declined to translate this page")
        text = "".join(b.text for b in response.content if b.type == "text")
        return _parse(text)


class LlamaCppBackend:
    def __init__(self, gguf_path: str, use_gpu: bool = True):
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise TranslationError("The llama.cpp translator needs: pip install llama-cpp-python") from exc
        if not gguf_path or not os.path.isfile(gguf_path):
            raise TranslationError("Choose a .gguf model file in Translation Settings")
        self.llm = Llama(model_path=gguf_path, n_ctx=8192, n_gpu_layers=-1 if use_gpu else 0,
                         verbose=False)

    def translate(self, items, target: str, with_images: bool) -> dict[int, tuple[str, str]]:
        if with_images:
            raise TranslationError("The llama.cpp translator can't read images; use the local OCR")
        out = self.llm.create_chat_completion(
            messages=[{"role": "system", "content": SYSTEM_PROMPT.format(target=target)},
                      {"role": "user", "content": _intro(items, target, False)}],
            temperature=0.2, max_tokens=4096, response_format={"type": "json_object"})
        try:
            text = out["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise TranslationError("Unexpected answer from llama.cpp") from exc
        return _parse(text)


def make_backend(settings: dict):
    if settings.get("backend") == "llama-cpp":
        return LlamaCppBackend(settings.get("gguf_path", ""), settings.get("gpu", True))
    if settings.get("backend") == "anthropic":
        return AnthropicBackend(settings.get("anthropic_model") or "claude-opus-5-5",
                                settings.get("api_key", ""))
    return OpenAIBackend(settings.get("base_url", ""), settings.get("model", ""),
                         settings.get("api_key", ""))
