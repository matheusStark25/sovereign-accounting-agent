"""Robô da consulta pública de NF-e, CT-e e NFC-e (SEFAZ): chave de acesso, captcha resolvido por uma pessoa e o resumo.

Mesmas garantias dos outros robôs: só navega nos hosts permitidos, registra cada passo na trilha WORM (a chave só como
hash) e **para para uma pessoa resolver o hCaptcha** (nunca resolve, nunca esconde que é automação). O resultado dessa
consulta não é PDF: é uma tela com os dados da nota, que o robô lê e grava em JSON (``consulta_nfe_<sha>.json``).
CPF que apareça na tela (destinatário pessoa física) é mascarado antes de gravar.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from contabil_agente.documentos.validadores import mascarar_cpf, validar_chave_acesso, validar_cpf
from contabil_agente.security.worm_audit import WormAudit

from .config import ConfigPortalCTe, ConfigPortalNFCe, ConfigPortalNFe
from .humano import PortaDoHumano, RequerAcaoHumana, hcaptcha_resolvido
from .robo_fgts import ErroDoRobo, ResultadoExtrato, RoboExtratoFGTS, so_digitos

# Pares "rótulo -> valor" da tela, na ordem do documento, com o título da seção em que cada um está.
JS_PARES = r"""() => {
  const limpar = s => (s || "").replace(/\s+/g, " ").trim();
  const visivel = el => el.getClientRects().length > 0;
  const valorDe = el => {
    if (!el) return "";
    if (el.value !== undefined && el.tagName !== "LI") return limpar(el.value);
    return limpar(el.innerText || el.textContent);
  };
  const saida = [];
  let secao = "";
  const alvos = document.querySelectorAll("legend, h1, h2, h3, h4, h5, caption, [class*='titulo' i], label, dt, th");
  for (const el of alvos) {
    if (!visivel(el)) continue;
    const tag = el.tagName.toLowerCase();
    const texto = limpar(el.innerText || el.textContent);
    if (!texto) continue;
    if (tag === "label" || tag === "dt" || tag === "th") {
      let valor = "";
      if (tag === "label" && el.htmlFor && document.getElementById(el.htmlFor)) valor = valorDe(document.getElementById(el.htmlFor));
      if (!valor) {
        let prox = el.nextElementSibling;
        if (tag === "th" && prox && prox.tagName.toLowerCase() !== "td") prox = null;
        valor = valorDe(prox);
      }
      if (valor && valor.length <= 300 && texto.length <= 80) saida.push({secao, rotulo: texto.replace(/:$/, ""), valor});
    } else if (texto.length <= 80) {
      secao = texto;
    }
  }
  return saida.slice(0, 400);
}"""

_ROTULO_LINHA = re.compile(r"^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 /().-]{2,48}):\s*(\S.{0,200})$")
_CPF_FORMATADO = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_CPF_SOLTO = re.compile(r"(?<![\d./-])\d{11}(?![\d./-])")

# rótulo normalizado -> campo do resumo, por seção. O que não casar continua em "campos", sem perder nada.
_CAMPOS_DA_NOTA: Tuple[Tuple[str, str], ...] = (
    ("chave", r"^chave( de acesso)?$"), ("numero", r"^n[uú]mero( da nf-?e)?$"), ("serie", r"^s[eé]rie$"), ("modelo", r"^modelo$"),
    ("data_emissao", r"data de emiss[aã]o|^emiss[aã]o$"), ("valor_total", r"valor total"), ("situacao", r"situa[cç][aã]o"),
    ("protocolo", r"protocolo"),
)
_CAMPOS_DE_PARTE: Tuple[Tuple[str, str], ...] = (
    ("documento", r"^(cnpj|cpf)(/(cnpj|cpf))?$"), ("nome", r"nome|raz[aã]o social"), ("inscricao_estadual", r"inscri[cç][aã]o estadual"),
    ("uf", r"^uf$"), ("municipio", r"munic[ií]pio"),
)


@dataclass
class ResultadoNFe(ResultadoExtrato):
    dados: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {**super().to_dict(), "dados": self.dados}


def _mascarar_cpfs(texto: str) -> str:
    """CPF (pessoa física, p.ex. destinatário) nunca vai para o arquivo; CNPJ de empresa fica."""
    texto = _CPF_FORMATADO.sub(lambda m: mascarar_cpf(m.group(0)), texto)
    return _CPF_SOLTO.sub(lambda m: mascarar_cpf(m.group(0)) if validar_cpf(m.group(0)) else m.group(0), texto)


def _decimal_br(valor: str) -> Optional[str]:
    """``R$ 1.234,56`` -> ``1234.56`` (ou ``None`` se não for número)."""
    limpo = re.sub(r"[^\d,.-]", "", valor or "")
    if not limpo or not re.search(r"\d", limpo):
        return None
    limpo = limpo.replace(".", "").replace(",", ".") if "," in limpo else limpo
    try:
        return str(Decimal(limpo))
    except InvalidOperation:
        return None


def _parte_da_secao(secao: str) -> str:
    s = secao.lower()
    for trecho, parte in (("emitente", "emitente"), ("destinat", "destinatario"), ("remetente", "remetente"), ("tomador", "tomador")):
        if trecho in s:
            return parte
    return ""


MODELOS = {"55": "NF-e", "57": "CT-e", "65": "NFC-e"}


def modelo_da_chave(chave: str) -> str:
    """Modelo do documento, gravado nas posições 21-22 da chave: 55 NF-e, 57 CT-e, 65 NFC-e."""
    return so_digitos(chave)[20:22]


def config_para_chave(chave: str, nfe: ConfigPortalNFe, cte: ConfigPortalCTe, nfce: ConfigPortalNFCe) -> ConfigPortalNFe:
    """Qual portal consulta esta chave. NFC-e é estadual: só a UF configurada (padrão SP)."""
    digitos, modelo = so_digitos(chave), modelo_da_chave(chave)
    if len(digitos) != 44 or not validar_chave_acesso(digitos):
        raise ErroDoRobo("chave_invalida", "informe os 44 dígitos da chave de acesso, com o dígito verificador correto")
    if modelo == "65":
        if nfce.uf and digitos[:2] != nfce.uf:
            raise ErroDoRobo("nfce_de_outra_uf", f"esta NFC-e é da UF {digitos[:2]}; configure a consulta da SEFAZ dela em NFCE_PORTAL_CONFIG (url e uf)")
        return nfce
    escolhido = {"55": nfe, "57": cte}.get(modelo)
    if escolhido is None:
        raise ErroDoRobo("modelo_nao_suportado", f"modelo {modelo} na chave; o robô consulta NF-e (55), CT-e (57) e NFC-e (65)")
    return escolhido


def montar_resumo(pares: List[Dict[str, str]]) -> Dict[str, Any]:
    """Organiza os pares rótulo/valor: dados da nota, emitente e destinatário. Só entra o que a tela realmente trouxe."""
    resumo: Dict[str, Any] = {}
    for par in pares:
        rotulo, valor = par["rotulo"].strip().lower(), par["valor"]
        parte = _parte_da_secao(par.get("secao", ""))
        tabela = _CAMPOS_DE_PARTE if parte else _CAMPOS_DA_NOTA
        alvo = resumo.setdefault(parte, {}) if parte else resumo
        for campo, padrao in tabela:
            if campo not in alvo and re.search(padrao, rotulo):
                alvo[campo] = valor
                break
    if "valor_total" in resumo and (numero := _decimal_br(resumo["valor_total"])) is not None:
        resumo["valor_total_decimal"] = numero
    return resumo


def pares_do_texto(texto: str) -> List[Dict[str, str]]:
    """Reserva para telas sem rótulos marcados: linhas no formato ``Rótulo: valor``."""
    achados = []
    for linha in (texto or "").splitlines():
        m = _ROTULO_LINHA.match(linha.strip())
        if m:
            achados.append({"secao": "", "rotulo": m.group(1).strip(), "valor": m.group(2).strip()})
    return achados[:200]


class RoboConsultaNFe(RoboExtratoFGTS):
    PREFIXO = "rpa.nfe"

    def __init__(
        self,
        config: ConfigPortalNFe,
        pasta_de_trabalho,
        audit: Optional[WormAudit] = None,
        tenant: str = "SYSTEM",
        ator: str = "rpa",
        notificar_humano: Optional[Callable[[str, str, Any], None]] = None,
        chave_hash: Optional[str] = None,
    ):
        super().__init__(config, pasta_de_trabalho, audit, tenant, ator, notificar_humano, chave_hash)
        # o hCaptcha continua na tela depois de resolvido: o sinal de "terminou" é o token de resposta preenchido
        self.porta = PortaDoHumano(config.seletores_desafio, config.timeout_humano_s, notificar_humano, resolvido=hcaptcha_resolvido)

    def executar(self, chave: str) -> ResultadoNFe:  # type: ignore[override]
        digitos = so_digitos(chave)
        if len(digitos) != 44 or not validar_chave_acesso(digitos):
            raise ErroDoRobo("chave_invalida", "informe os 44 dígitos da chave de acesso, com o dígito verificador correto")
        if modelo_da_chave(digitos) not in self.config.modelos:
            raise ErroDoRobo("modelo_errado", f"a chave é de {MODELOS.get(modelo_da_chave(digitos), 'outro modelo')}; este portal consulta "
                                              f"{', '.join(MODELOS.get(m, m) for m in self.config.modelos)}")
        self._passos = []
        self._passo("inicio", titular=self._id_do_titular(digitos), modelo=modelo_da_chave(digitos))
        try:
            base = self.resiliencia.chamar(self._rodar, digitos)
        except RequerAcaoHumana:
            raise
        except Exception as exc:
            self._passo("falha", motivo=getattr(exc, "motivo", type(exc).__name__))
            raise
        self._passo("fim", sha256=base.sha256, tamanho=base.tamanho)
        dados = json.loads(Path(base.caminho).read_text(encoding="utf-8"))
        return ResultadoNFe(base.caminho, base.sha256, base.tamanho, list(self._passos), base.segundos_com_humano, dados)

    # --------------------------------------------------------------------- fluxo
    def _fluxo(self, page, chave: str) -> tuple:  # type: ignore[override]
        cfg = self.config
        humano_s = 0.0
        self._checar_host(page)
        self._preencher_cpf(page, chave)  # o campo de identificação é a chave de acesso
        for rodada in range(1, cfg.tentativas_captcha + 1):
            if rodada > 1:
                self._preencher_cpf(page, chave)  # o formulário devolvido pelo portal pode vir sem a chave
            humano_s += self._pausar_se_desafio(page, f"hCaptcha da consulta de {MODELOS.get(cfg.modelos[0], 'documento fiscal')}")
            humano_s += self._codigo_da_imagem(page)
            self._clicar_primeiro(page, cfg.seletores_envio, "envio")
            if self._aguardar_resultado(page, chave):
                break
            self._passo("consulta_nao_concluida", rodada=rodada)
        else:
            raise ErroDoRobo("resultado_nao_apareceu", f"o portal não mostrou a nota em {cfg.tentativas_captcha} tentativas")
        return self._ler_e_guardar(page, chave), humano_s + self._humano_extra

    def _codigo_da_imagem(self, page) -> float:
        """Captcha de imagem (o código que a pessoa lê e digita): aviso na janela e espera o "Terminei esta etapa"."""
        for seletor in self.config.seletores_captcha_imagem:
            try:
                visivel = page.locator(seletor).count() and page.locator(seletor).first.is_visible()
            except Exception:  # noqa: BLE001 - página navegando
                visivel = False
            if visivel:
                segundos = self.porta.assistir(page, "captcha_imagem", "Digite o código da imagem no campo e clique em 'Terminei esta etapa'.")
                self._passo("humano_digitou_o_codigo", segundos=round(segundos, 1))
                return segundos
        return 0.0

    def _aguardar_resultado(self, page, chave: str) -> bool:
        """Espera a tela da nota. ``True`` = apareceu; ``False`` = o portal devolveu o formulário (captcha vencido ou recusado)."""
        cfg = self.config
        limite = time.monotonic() + cfg.espera_resultado_s
        rx_nota = re.compile(cfg.padrao_resultado, re.IGNORECASE)
        rx_recusa = re.compile(cfg.padrao_nota_inexistente, re.IGNORECASE)
        while time.monotonic() < limite:
            page.wait_for_timeout(500)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                self._checar_host(page)
                texto = page.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 20000)") or ""
            except ErroDoRobo:
                raise
            except Exception:  # noqa: BLE001 - página navegando; olha de novo no próximo ciclo
                continue
            self._checar_bloqueio(page)
            if rx_recusa.search(texto):
                self._passo("nota_nao_encontrada")
                raise ErroDoRobo("nota_nao_encontrada", "o portal diz que não há NF-e com essa chave")
            if chave in re.sub(r"\D", "", texto) or rx_nota.search(texto):
                self._passo("resultado_na_tela")
                return True
        return False

    def _ler_e_guardar(self, page, chave: str) -> str:
        pares: List[Dict[str, str]] = []
        for frame in self._frames(page):
            try:
                pares += frame.evaluate(JS_PARES)
            except Exception:  # noqa: BLE001 - quadro de outro domínio ou já fechado
                continue
        if not pares:
            try:
                pares = pares_do_texto(page.evaluate("() => document.body.innerText.slice(0, 20000)"))
            except Exception:  # noqa: BLE001
                pares = []
        if not pares:
            self._salvar_diagnostico(page, "resumo_nfe")
            raise ErroDoRobo("resumo_nao_interpretado", "a tela da nota apareceu, mas não achei rótulos e valores; diagnóstico salvo para ajustar")
        campos = [{"secao": _mascarar_cpfs(p.get("secao", "")), "rotulo": _mascarar_cpfs(p["rotulo"]), "valor": _mascarar_cpfs(p["valor"])} for p in pares]
        dados = {
            "chave": chave,
            "consultado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "modelo": MODELOS.get(modelo_da_chave(chave), modelo_da_chave(chave)),
            "fonte": self.config.nome_portal,
            "resumo": montar_resumo(campos),
            "campos": campos,
        }
        conteudo = json.dumps(dados, ensure_ascii=False, indent=1).encode("utf-8")
        sha = hashlib.sha256(conteudo).hexdigest()
        tipo = MODELOS.get(modelo_da_chave(chave), "doc").lower().replace("-", "")
        destino = self.pasta / "downloads" / f"consulta_{tipo}_{sha[:16]}.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)
        try:
            os.chmod(destino, 0o600)
        except OSError:
            pass
        self._passo("resumo_salvo", sha256=sha, tamanho=len(conteudo), campos=len(campos))
        return str(destino)
