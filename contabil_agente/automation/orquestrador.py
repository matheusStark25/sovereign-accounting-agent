from typing import Any, Dict, List, Optional
import os

# Ensure a stable `Style.RESET` value is available across environments/tests.
try:
    from colorama import Style
except Exception:

    class _FallbackStyle:
        RESET_ALL = "\033[0m"
        RESET = "\033[0m"

    Style = _FallbackStyle()
else:
    if not hasattr(Style, "RESET"):
        Style.RESET = getattr(Style, "RESET_ALL", "\033[0m")


class AuditRecord:
    def __init__(self, step: str, data: Any = None):
        self.step = step
        self.data = data


class Audit:
    def __init__(self):
        self.records: List[AuditRecord] = []

    def add(self, step: str, data: Any = None):
        self.records.append(AuditRecord(step, data))


class ExternalToolStub:
    def __init__(self, name: str = "tool"):
        self.name = name

    def executar(self, payload):
        return {"status": "success", "payload": payload}


class OrquestradorStark:
    """Minimal compatibility shim for automation tests.

    This file intentionally avoids terminal styling APIs that may differ
    between environments (e.g., `Style.RESET`). It mirrors the behaviour
    used by the test-suite's error-path checks.
    """

    def __init__(
        self, audit_path: Optional[str] = None, rng_seed: Optional[int] = None
    ):
        self.audit = Audit()
        self._last_sefip_payload: Optional[Dict[str, Any]] = None
        self.sefip = ExternalToolStub("sefip")
        self.ted = ExternalToolStub("ted")
        self.sintegra = ExternalToolStub("sintegra")
        self.audit_path = audit_path
        self.rng_seed = rng_seed

    def press_button_1(self, files: List[str]):
        # print minimal message without relying on colorama Style.RESET
        print("[Botão 1] Coleta e Preparo (1-15)")
        return self.botao1_coleta_preparo(files, auto_continue=False)

    def botao1_coleta_preparo(self, files: List[str], auto_continue: bool = False):
        res = self.sefip.executar(files)
        self._last_sefip_payload = res.get("payload") if isinstance(res, dict) else res
        self.audit.add("1.final.sefip_import", res)
        return res

    def botao2_processamento_transmissao(
        self, payloads: List[Dict[str, Any]], auto_continue: bool = False
    ):
        results = []
        for p in payloads:
            r = self.ted.executar(p)
            self.audit.add("2.transmissao.ted", r)
            results.append(r)
        return results

    def botao3_finalizacao_blindagem(
        self, files: List[str], output_dir: Optional[str] = None
    ):
        res = self.sintegra.executar(files)
        self.audit.add("3.final.sintegra", res)
        try:
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                out = os.path.join(output_dir, "evidence.txt")
                with open(out, "w", encoding="utf-8") as f:
                    f.write("evidence placeholder\n")
            self.audit.add(
                "evidence.pdf.generated", {"files": files, "out_dir": output_dir}
            )
        except Exception as e:
            self.audit.add("evidence.pdf.failed", {"error": str(e)})
        return res
