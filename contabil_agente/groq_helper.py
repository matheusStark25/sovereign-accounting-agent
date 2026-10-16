import logging
import time
from typing import Optional

try:
    from groq import APIConnectionError, APIError, Groq, RateLimitError
except Exception:  # pragma: no cover - during tests we may inject a fake module
    Groq = None
    APIConnectionError = Exception
    APIError = Exception
    RateLimitError = Exception


def chamar_groq(
    prompt: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_retries: int = 2,
    fallback_text: Optional[str] = None,
) -> str:
    """Chamada robusta ao Groq (encapsulada para testes)."""
    if Groq is None:
        raise RuntimeError("Groq client not available")

    client = Groq(api_key=api_key)
    backoff = [0, 1.5, 3.0]

    for attempt in range(max_retries + 1):
        try:
            resposta = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.45,
                max_tokens=600,
                timeout=25,
            )
            return resposta.choices[0].message.content.strip()

        except (APIConnectionError, APIError, RateLimitError) as api_err:
            logging.warning(f"Groq tentativa {attempt + 1} falhou: {api_err}")
            if attempt == max_retries:
                logging.error(
                    f"Groq esgotou {max_retries + 1} tentativas → usando fallback"
                )
                if fallback_text:
                    return fallback_text
                return "Tive uma instabilidade agora. Pode repetir a mensagem?"

            time.sleep(backoff[attempt])

        except Exception:
            logging.exception("Erro crítico inesperado na chamada Groq")
            if attempt == max_retries:
                return "Desculpe o transtorno. Ocorreu uma falha interna. Pode me dizer novamente o que precisa?"

    return "Tive uma instabilidade agora. Pode repetir a mensagem?"
