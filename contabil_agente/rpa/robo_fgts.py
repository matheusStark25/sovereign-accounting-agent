"""Robô Playwright que baixa o extrato do FGTS (PDF) do portal configurado.

Garantias: só navega nos hosts permitidos; aceita só download que seja PDF de verdade e de tamanho
limitado; calcula o SHA-256 do arquivo; registra cada passo na trilha WORM (CPF só como hash); pausa para a
pessoa nos desafios (captcha/login); tenta de novo com backoff e para se o portal ficar instável (disjuntor).
"""

from __future__ import annotations

import hashlib
import json
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

from .calibracao import JS_ESTRUTURA
from .config import ConfigPortalFGTS
from .humano import HumanoNaoRespondeu, PortaDoHumano, RequerAcaoHumana

logger = logging.getLogger(__name__)


class ErroDoRobo(RuntimeError):
    def __init__(self, motivo: str, detalhe: str = ""):
        super().__init__(f"{motivo}: {detalhe}" if detalhe else motivo)
        self.motivo = motivo


class PortalBloqueouAutomacao(ErroDoRobo):
    """O portal reprovou o navegador automatizado (ex.: PGMEI, erro 13896). Repetir só piora, então não há nova tentativa:
    baixe o PDF no navegador normal e envie pelo sistema."""


SINAIS_DE_BLOQUEIO = re.compile(
    r"comportamento de rob|impedido por prote|access denied|acesso negado|unusual traffic|you have been blocked|shieldsquare",
    re.IGNORECASE,
)
JS_SUGESTAO = r'''el => el.id ? "#" + el.id : (el.getAttribute("name") ? el.tagName.toLowerCase() + "[name='" + el.getAttribute("name") + "']" : null)'''


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
    PREFIXO = "rpa.fgts"  # prefixo dos eventos na trilha de auditoria (as subclasses trocam)

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
        self.resiliencia = ChamadaResiliente(
            "portal_fgts", limite_falhas=3, janela_reset=300, timeout=None, tentativas=2, atraso_inicial=2.0,
            excecoes=(ErroDoRobo,), nao_repetir=(PortalBloqueouAutomacao,),
        )
        self._passos: List[Dict[str, Any]] = []
        self._humano_extra = 0.0  # segundos que a pessoa levou em etapas que o robô não achou sozinho
        self._download_da_pessoa: Any = None  # último download visto na janela (inclusive o que a pessoa iniciou)

    # --------------------------------------------------------------- registro
    def _passo(self, nome: str, **extra: Any) -> None:
        item = {"passo": nome, "em": round(time.time(), 3), **extra}
        self._passos.append(item)
        if self.audit is not None:
            self.audit.append(f"{self.PREFIXO}.{nome}", extra, tenant=self.tenant, ator=self.ator)

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

    def _rodar(self, identificador: str, *extra: Any) -> ResultadoExtrato:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            raise ErroDoRobo("playwright_indisponivel", str(exc)) from exc

        cfg = self.config
        perfil = cfg.user_data_dir or str(self.pasta / "perfil")
        self._humano_extra, self._download_da_pessoa = 0.0, None
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
                for aberta in contexto.pages:
                    self._observar_downloads(aberta)
                contexto.on("page", self._observar_downloads)  # abas novas (o portal pode abrir o PDF em outra)
                page = contexto.pages[0] if contexto.pages else contexto.new_page()
                self._passo("abrindo_portal", host=urlparse(cfg.url).hostname)
                try:
                    page.goto(cfg.url, wait_until="domcontentloaded", timeout=cfg.timeout_navegacao_s * 1000)
                except (PlaywrightTimeout, PlaywrightError) as exc:
                    raise ErroDoRobo("portal_inacessivel", str(exc).splitlines()[0]) from exc

                caminho, humano_s = self._fluxo(page, identificador, *extra)
            finally:
                contexto.close()
        dados = Path(caminho).read_bytes()
        resultado = ResultadoExtrato(caminho, hashlib.sha256(dados).hexdigest(), len(dados), segundos_com_humano=humano_s)
        return resultado

    def _fluxo(self, page, cpf: str) -> tuple:
        """Do portal aberto até o PDF salvo: devolve ``(caminho, segundos_com_humano)``. Cada portal tem o seu."""
        humano_s = 0.0
        self._checar_host(page)
        humano_s += self._pausar_se_desafio(page, "desafio ao abrir o portal")
        self._checar_host(page)
        self._preencher_cpf(page, cpf)
        self._clicar_primeiro(page, self.config.seletores_envio, "envio")
        page.wait_for_load_state("domcontentloaded")
        self._checar_host(page)
        self._checar_bloqueio(page)
        humano_s += self._pausar_se_desafio(page, "desafio após enviar o CPF")
        self._checar_host(page)
        return self._baixar_pdf(page), humano_s + self._humano_extra

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

    def _checar_bloqueio(self, page) -> None:
        """Se o portal reprovou o navegador automatizado, pedir ajuda não adianta: falha clara e sem nova tentativa."""
        try:
            texto = page.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 6000)")
        except Exception:  # noqa: BLE001 - página navegando
            return
        achado = SINAIS_DE_BLOQUEIO.search(texto or "")
        if achado:
            self._passo("portal_bloqueou_automacao", host=urlparse(page.url).hostname, sinal=achado.group(0)[:40])
            raise PortalBloqueouAutomacao(
                "portal_bloqueou_automacao",
                "o portal reprovou o navegador automatizado; baixe o PDF no seu navegador normal e envie pelo sistema",
            )

    # ------------------------------------------- localizar sem travar por bobeira
    @staticmethod
    def _frames(page) -> list:
        return [page.main_frame] + [f for f in page.frames if f != page.main_frame]

    @staticmethod
    def _palavras(expressao: str) -> List[str]:
        return [w for w in re.split(r"[^a-z0-9]+", expressao.lower()) if len(w) >= 3]

    def _candidatos(self, frame, seletores, tipo: Optional[str]):
        """Primeiro o que está configurado; depois alternativas pelo que o elemento *é* (rótulo, texto, papel)."""
        for seletor in seletores:
            yield seletor, frame.locator(seletor)
        cfg = self.config
        if tipo == "campo":
            rx = re.compile(cfg.rotulo_campo, re.IGNORECASE)
            yield "por rótulo", frame.get_by_label(rx)
            yield "por placeholder", frame.get_by_placeholder(rx)
            nomes = ", ".join(f"input[name*='{w}' i], input[id*='{w}' i]" for w in self._palavras(cfg.rotulo_campo))
            if nomes:
                yield "por nome ou id", frame.locator(nomes)
            yield "único campo de texto", frame.locator("input[type='text'], input:not([type])")
        elif tipo == "botao":
            rx = re.compile(cfg.rotulo_envio, re.IGNORECASE)
            yield "botão pelo texto", frame.get_by_role("button", name=rx)
            yield "link pelo texto", frame.get_by_role("link", name=rx)
            yield "botão de envio do formulário", frame.locator("input[type='submit'], button[type='submit']")
        elif tipo == "download":
            rx = re.compile(cfg.rotulo_download, re.IGNORECASE)
            yield "link para PDF", frame.locator("a[href*='.pdf' i]")
            yield "download pelo texto (botão)", frame.get_by_role("button", name=rx)
            yield "download pelo texto (link)", frame.get_by_role("link", name=rx)

    def _visiveis(self, page, seletores, tipo: Optional[str]) -> list:
        """Todos os candidatos visíveis agora, na ordem de confiança: [(como_achou, locator)]."""
        achados = []
        for frame in self._frames(page):
            for origem, loc in self._candidatos(frame, seletores, tipo):
                try:
                    n = loc.count()
                    if not n or (origem == "único campo de texto" and n != 1):
                        continue
                    if loc.first.is_visible():
                        achados.append((origem, loc.first))
                except Exception:  # noqa: BLE001 - a página mudou no meio da busca
                    continue
        return achados

    def _localizar(self, page, seletores, tipo: Optional[str], espera_s: Optional[float] = None):
        """Espera o elemento aparecer (portais lentos montam a tela por JavaScript) e procura em todos os quadros."""
        limite = time.monotonic() + (self.config.espera_elemento_s if espera_s is None else espera_s)
        while True:
            achados = self._visiveis(page, seletores, tipo)
            if achados:
                return achados[0][1], achados[0][0]
            if time.monotonic() >= limite:
                return None, ""
            page.wait_for_timeout(400)

    def _registrar_alternativa(self, etapa: str, origem: str, seletores, loc) -> None:
        """Se achou por outro caminho que não o configurado, anota e sugere o seletor para atualizar a configuração."""
        if origem in tuple(seletores):
            return
        try:
            sugestao = loc.evaluate(JS_SUGESTAO)
        except Exception:  # noqa: BLE001
            sugestao = None
        self._passo("seletor_alternativo", etapa=etapa, achou_por=origem, sugestao=sugestao)

    def _salvar_diagnostico(self, page, etapa: str) -> None:
        """Guarda a estrutura da página (botões, campos, links; números e e-mails mascarados) para ajustar a configuração."""
        try:
            elementos: list = []
            for frame in self._frames(page):
                try:
                    frame.evaluate(JS_ESTRUTURA)
                    elementos += frame.evaluate("window.__instantaneo ? window.__instantaneo() : []")
                except Exception:  # noqa: BLE001 - quadro de outro domínio ou já fechado
                    continue
            arquivo = self.pasta / f"diagnostico_{etapa}_{int(time.time())}.json"
            local = urlparse(page.url)
            arquivo.write_text(
                json.dumps({"etapa": etapa, "host": local.hostname, "caminho": local.path, "elementos": elementos[:150]}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            try:
                os.chmod(arquivo, 0o600)
            except OSError:
                pass
            if self.config.capturar_tela_na_falha:
                page.screenshot(path=str(arquivo.with_suffix(".png")))
            self._passo("diagnostico_salvo", etapa=etapa, arquivo=arquivo.name)
        except Exception:  # noqa: BLE001 - o diagnóstico nunca pode derrubar a execução
            logger.debug("Não consegui salvar o diagnóstico da etapa %s.", etapa)

    def _ajuda_ou_erro(self, page, etapa: str, instrucao: str, erro: ErroDoRobo, concluido: Optional[Callable[[], bool]] = None) -> None:
        """Não achou: salva o diagnóstico e, em vez de abortar, pede a pessoa na própria janela (se ``ajuda_humana``)."""
        self._checar_bloqueio(page)
        self._salvar_diagnostico(page, etapa)
        if not self.config.ajuda_humana:
            raise erro
        segundos = self.porta.assistir(page, etapa, instrucao, concluido)
        self._humano_extra += segundos
        self._passo("humano_fez_a_etapa", etapa=etapa, segundos=round(segundos, 1))
        self._checar_host(page)

    def _observar_downloads(self, pagina) -> None:
        pagina.on("download", self._guardar_download)

    def _guardar_download(self, download) -> None:
        self._download_da_pessoa = download

    # ----------------------------------------------------------------- passos
    def _preencher_cpf(self, page, cpf: str) -> None:
        loc, origem = self._localizar(page, self.config.seletores_cpf, "campo")
        if loc is None:
            self._ajuda_ou_erro(
                page, "campo_cpf", "Não achei o campo do CPF/CNPJ. Preencha-o e clique em 'Terminei esta etapa'.",
                ErroDoRobo("campo_cpf_nao_encontrado", "ajuste seletores_cpf para o portal"),
            )
            return
        self._registrar_alternativa("cpf", origem, self.config.seletores_cpf, loc)
        try:
            loc.fill(cpf)
        except Exception:  # noqa: BLE001 - campos com máscara por JavaScript às vezes recusam fill
            loc.click()
            page.keyboard.type(cpf)
        self._passo("cpf_preenchido")

    def _clicar_primeiro(self, page, seletores, nome: str) -> None:
        loc, origem = self._localizar(page, seletores, "botao" if nome == "envio" else None)
        if loc is None:
            self._ajuda_ou_erro(
                page, nome, f"Não achei o passo '{nome}'. Faça esse clique e depois clique em 'Terminei esta etapa'.",
                ErroDoRobo(f"botao_{nome}_nao_encontrado", f"ajuste seletores_{nome}"),
            )
            return
        self._registrar_alternativa(nome, origem, seletores, loc)
        loc.click()
        self._passo(f"{nome}_clicado")

    def _baixar_pdf(self, page) -> str:
        cfg = self.config
        self._download_da_pessoa = None
        ultimo: Optional[Exception] = None
        limite = time.monotonic() + cfg.espera_elemento_s
        while True:
            candidatos = self._visiveis(page, cfg.seletores_download, "download")
            if candidatos or time.monotonic() >= limite:
                break
            page.wait_for_timeout(400)
        for origem, loc in candidatos[:6]:
            try:
                with page.expect_download(timeout=cfg.timeout_download_s * 1000) as info:
                    loc.click()
                self._registrar_alternativa("download", origem, cfg.seletores_download, loc)
                temporario = self.pasta / f"baixando_{int(time.time() * 1000)}.tmp"
                info.value.save_as(str(temporario))
                return self._validar_e_guardar(temporario)
            except ErroDoRobo:
                raise
            except Exception as exc:  # noqa: BLE001 - esse candidato não baixou nada; tenta o próximo
                ultimo = exc
        erro = ErroDoRobo("download_nao_localizado", str(ultimo) if ultimo else "ajuste seletores_download")
        self._ajuda_ou_erro(
            page, "download", "Não consegui baixar o PDF sozinho. Clique no botão ou link que baixa o PDF; eu pego o arquivo.",
            erro, concluido=lambda: self._download_da_pessoa is not None,
        )
        baixado = self._download_da_pessoa
        if baixado is None:  # clicou em "Terminei" sem ter baixado nada
            raise erro
        temporario = self.pasta / f"baixando_{int(time.time() * 1000)}.tmp"
        baixado.save_as(str(temporario))
        return self._validar_e_guardar(temporario)

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
