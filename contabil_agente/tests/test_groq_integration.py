import importlib
import sys
import types
import unittest


def make_fake_groq_module(success=True):
    mod = types.ModuleType("groq")

    class APIConnectionError(Exception):
        pass

    class APIError(Exception):
        pass

    class RateLimitError(Exception):
        pass

    class MockResponseChoice:
        def __init__(self, content):
            class Msg:
                def __init__(self, c):
                    self.content = c

            self.message = Msg(content)

    class MockResponse:
        def __init__(self, content):
            self.choices = [MockResponseChoice(content)]

    class Groq:
        def __init__(self, api_key=None):
            pass

        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    if success:
                        return MockResponse("Resposta simulada do LLM")
                    raise APIConnectionError("simulated")

    mod.Groq = Groq
    mod.APIConnectionError = APIConnectionError
    mod.APIError = APIError
    mod.RateLimitError = RateLimitError
    return mod


class GroqHelperTests(unittest.TestCase):
    def test_chamar_groq_success(self):
        # inject fake groq module that returns success
        sys.modules["groq"] = make_fake_groq_module(success=True)
        # Force reload to pick up the injected groq module
        if "contabil_agente.groq_helper" in sys.modules:
            del sys.modules["contabil_agente.groq_helper"]
        gh = importlib.import_module("contabil_agente.groq_helper")
        resp = gh.chamar_groq("teste", api_key="k", model="m", max_retries=0)
        self.assertIn("Resposta simulada do LLM", resp)

    def test_chamar_groq_failure_returns_fallback(self):
        # inject fake groq module that fails
        sys.modules["groq"] = make_fake_groq_module(success=False)
        # Force reload to pick up the injected groq module
        if "contabil_agente.groq_helper" in sys.modules:
            del sys.modules["contabil_agente.groq_helper"]
        gh = importlib.import_module("contabil_agente.groq_helper")
        resp = gh.chamar_groq(
            "teste", api_key="k", model="m", max_retries=0, fallback_text="MEU_FALLBACK"
        )
        self.assertEqual(resp, "MEU_FALLBACK")


if __name__ == "__main__":
    unittest.main()
