"""Robô Playwright que baixa o extrato do FGTS (PDF) do portal configurado.

Garantias: só navega nos hosts permitidos; aceita só download que seja PDF de verdade e de tamanho
limitado; calcula o SHA-256 do arquivo; registra cada passo na trilha WORM (CPF só como hash); pausa para a
pessoa nos desafios (captcha/login); tenta de novo com backoff e para se o portal ficar instável (disjuntor).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from contabil_agente.lgpd.anonimizacao import PIIAnonymizer
from contabil_agente.resilience import ChamadaResiliente
from contabil_agente.security.worm_audit import WormAudit

from .config import ConfigPortalFGTS
from .humano import HumanoNaoRespondeu, PortaDoHumano, RequerAcaoHumana

logger = logging.getLogger(__name__)


class ErroDoRobo(RuntimeError):
    def __init__(self, motivo: str, detalhe: str = ""):
        super().__init__(f"{motivo}: {detalhe}" if detalhe else motivo)
        self.motivo = motivo


@dataclass
class ResultadoExtrato:
    caminho: str
    sha256: str
    tamanho: int
    passos: List[Dict[str, Any]] = field(default_factory=list)
    segundos_com_humano: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {"status": "success", "path": self.caminho, "sha256": self.sha256, "tamanho": self.tamanho,
                "passos": self.passos, "segundos_com_humano": round(self.segundos_com_humano, 1)}


def so_digitos(cpf: str) -> str:
    return re.sub(r"\D", "", str(cpf or ""))


class RoboExtratoFGTS:
    def __init__(
        self,
        config: ConfigPortalFGTS,
        pasta_de_trabalho: str | Path,
        audit: Optional[WormAudit] = None,
        tenant: str = "SYSTEM",
        ator: str = "rpa",
        notificar_humano: Optional[Callable[[str, str, Any], None]] = None,
        chave_hash: Optional[str] = None,
    ):
        self.config = config
        self.pasta = Path(pasta_de_trabalho)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.audit, self.tenant, self.ator = audit, tenant, ator
        self._chave_hash = chave_hash
        self.porta = PortaDoHumano(config.seletores_desafio, config.timeout_humano_s, notificar_humano)
        self.resiliencia = ChamadaResiliente("portal_fgts", limite_falhas=3, janela_reset=300, timeout=None, tentativas=2, atraso_inicial=2.0, excecoes=(ErroDoRobo,))
        self._passos: List[Dict[str, Any]] = []

    # --------------------------------------------------------------- registro
    def _passo(self, nome: str, **extra: Any) -> None:
        item = {"passo": nome, "em": round(time.time(), 3), **extra}
        self._passos.append(item)
        if self.audit is not None:
            self.audit.append(f"rpa.fgts.{nome}", extra, tenant=self.tenant, ator=self.ator)

    def _id_do_titular(self, cpf: str) -> str:
        return PIIAnonymizer.hash_pii(cpf, self._chave_hash) if self._chave_hash else "sem-chave"

    # ------------------------------------------------------------- execução
    def executar(self, cpf: str) -> ResultadoExtrato:
        digitos = so_digitos(cpf)
        if len(digitos) != 11:
            raise ErroDoRobo("cpf_invalido", "informe 11 dígitos")
        from contabil_agente.documentos.validadores import validar_cpf

        if not validar_cpf(digitos):
            raise ErroDoRobo("cpf_invalido", "dígito verificador não confere")
        self._passos = []
        self._passo("inicio", titular=self._id_do_titular(digitos))
        try:
            resultado = self.resiliencia.chamar(self._rodar, digitos)
        except RequerAcaoHumana:
            raise
        except Exception as exc:
            self._passo("falha", motivo=getattr(exc, "motivo", type(exc).__name__))
            raise
        self._passo("fim", sha256=resultado.sha256, tamanho=resultado.tamanho)
        resultado.passos = list(self._passos)
        return resultado

    def _rodar(self, cpf: str) -> ResultadoExtrato:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            raise ErroDoRobo("playwright_indisponivel", str(exc)) from exc

        cfg = self.config
        perfil = cfg.user_data_dir or str(self.pasta / "perfil")
        humano_s = 0.0
        with sync_playwright() as p:
            try:
                contexto = p.chromium.launch_persistent_context(
                    user_data_dir=perfil,
                    headless=cfg.headless,
                    channel=cfg.canal,
                    accept_downloads=True,
                    viewport={"width": 1366, "height": 900},
                )
            except PlaywrightError as exc:
                raise ErroDoRobo("navegador_indisponivel", str(exc).splitlines()[0]) from exc
            try:
                contexto.route("**/*", self._so_hosts_permitidos)
                page = contexto.pages[0] if contexto.pages else contexto.new_page()
                self._passo("abrindo_portal", host=urlparse(cfg.url).hostname)
                try:
                    page.goto(cfg.url, wait_until="domcontentloaded", timeout=cfg.timeout_navegacao_s * 1000)
                except (PlaywrightTimeout, PlaywrightError) as exc:
                    raise ErroDoRobo("portal_inacessivel", str(exc).splitlines()[0]) from exc

                self._checar_host(page)
                humano_s += self._pausar_se_desafio(page, "desafio ao abrir o portal")
                self._checar_host(page)
                self._preencher_cpf(page, cpf)
                self._clicar_primeiro(page, cfg.seletores_envio, "envio")
                page.wait_for_load_state("domcontentloaded")
                self._checar_host(page)
                humano_s += self._pausar_se_desafio(page, "desafio após enviar o CPF")
                self._checar_host(page)
                caminho = self._baixar_pdf(page)
            finally:
                contexto.close()
        dados = Path(caminho).read_bytes()
        resultado = ResultadoExtrato(caminho, hashlib.sha256(dados).hexdigest(), len(dados), segundos_com_humano=humano_s)
        return resultado

    # ----------------------------------------------------------------- passos
    def _so_hosts_permitidos(self, route) -> None:
        req = route.request
        host = urlparse(req.url).hostname or ""
        if req.is_navigation_request() and req.frame.parent_frame is None and host not in self.config.hosts:
            self._passo("navegacao_bloqueada", host=host)
            route.abort("blockedbyclient")
            return
        route.continue_()

    def _checar_host(self, page) -> None:
        """O Playwright não passa redirecionamentos pelo filtro de rotas: confere onde a página realmente está."""
        host = urlparse(page.url).hostname or ""
        if page.url not in ("about:blank", "") and host not in self.config.hosts:
            self._passo("dominio_nao_permitido", host=host)
            raise ErroDoRobo("dominio_nao_permitido", f"a página foi para {host}; o CPF não foi enviado")

    def _pausar_se_desafio(self, page, motivo: str) -> float:
        espera = self.porta.esperar(page, motivo)
        if espera > 0:
            self._passo("humano_resolveu", motivo=motivo, segundos=round(espera, 1))
        return espera

    def _preencher_cpf(self, page, cpf: str) -> None:
        for seletor in self.config.seletores_cpf:
            loc = page.locator(seletor)
            try:
                if loc.count() and loc.first.is_visible():
                    loc.first.fill(cpf)
                    self._passo("cpf_preenchido")
                    return
            except Exception:  # noqa: BLE001
                continue
        raise ErroDoRobo("campo_cpf_nao_encontrado", "ajuste seletores_cpf para o portal")

    def _clicar_primeiro(self, page, seletores, nome: str) -> None:
        for seletor in seletores:
            loc = page.locator(seletor)
            try:
                if loc.count() and loc.first.is_visible():
                    loc.first.click()
                    self._passo(f"{nome}_clicado")
                    return
            except Exception:  # noqa: BLE001
                continue
        raise ErroDoRobo(f"botao_{nome}_nao_encontrado", f"ajuste seletores_{nome}")

    def _baixar_pdf(self, page) -> str:
        cfg = self.config
        ultimo: Optional[Exception] = None
        for seletor in cfg.seletores_download:
            loc = page.locator(seletor)
            try:
                if not (loc.count() and loc.first.is_visible()):
                    continue
                with page.expect_download(timeout=cfg.timeout_download_s * 1000) as info:
                    loc.first.click()
                download = info.value
                temporario = self.pasta / f"baixando_{int(time.time() * 1000)}.tmp"
                download.save_as(str(temporario))
                return self._validar_e_guardar(temporario)
            except ErroDoRobo:
                raise
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                continue
        raise ErroDoRobo("download_nao_localizado", str(ultimo) if ultimo else "ajuste seletores_download")

    def _validar_e_guardar(self, temporario: Path) -> str:
        tamanho = temporario.stat().st_size
        if tamanho == 0 or tamanho > self.config.tamanho_maximo_pdf:
            temporario.unlink(missing_ok=True)
            raise ErroDoRobo("pdf_invalido", f"tamanho {tamanho} fora do limite")
        with open(temporario, "rb") as f:
            cabecalho = f.read(5)
        if cabecalho != b"%PDF-":
            temporario.unlink(missing_ok=True)
            raise ErroDoRobo("download_nao_e_pdf", "o arquivo baixado não tem assinatura de PDF")
        sha = hashlib.sha256(temporario.read_bytes()).hexdigest()
        destino = self.pasta / "downloads" / f"extrato_fgts_{sha[:16]}.pdf"
        destino.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporario, destino)
        try:
            os.chmod(destino, 0o600)
        except OSError:
            pass
        self._passo("pdf_salvo", sha256=sha, tamanho=tamanho)
        return str(destino)


class SovereignRPAWorker:
    """Interface antiga: ``SovereignRPAWorker(...).executar("extrato_fgts", {"cpf": ...})``."""

    def __init__(self, session_id: str, work_dir: str | Path, config: Optional[Dict[str, Any]] = None, audit: Optional[WormAudit] = None, **_: Any):
        self.session_id = session_id
        self._robo = RoboExtratoFGTS(ConfigPortalFGTS.carregar(config or {}), work_dir, audit)

    def __enter__(self) -> "SovereignRPAWorker":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def executar(self, tarefa: str, dados: Dict[str, Any]) -> Dict[str, Any]:
        if str(tarefa).strip().lower() != "extrato_fgts":
            return {"status": "error", "reason": f"tarefa_nao_suportada:{tarefa}"}
        try:
            return self._robo.executar(dados.get("cpf", "")).to_dict()
        except ErroDoRobo as exc:
            return {"status": "error", "reason": exc.motivo, "detalhe": str(exc)}
        except HumanoNaoRespondeu as exc:
            return {"status": "error", "reason": "captcha_nao_resolvido", "detalhe": str(exc)}
