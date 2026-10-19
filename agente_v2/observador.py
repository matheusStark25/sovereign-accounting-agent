"""Pasta observada: o PDF que você baixa no seu navegador de sempre (extrato do FGTS, DAS do PGMEI…) entra sozinho no sistema.

Os portais da Caixa e da Receita recusam navegador controlado por automação, mas aceitam o seu navegador normal. Este
observador olha uma pasta (a de Downloads, por exemplo), espera cada PDF novo terminar de ser gravado e o envia a
``POST /api/v1/documentos``, que classifica, extrai, confere e arquiva. Ele não toca no navegador nem no portal.

Garantias: só PDF de verdade (assinatura ``%PDF-``) e até 25 MB; o mesmo conteúdo nunca é enviado duas vezes (SHA-256,
guardado em ``.observador_enviados.json`` dentro da pasta); arquivo que ainda está crescendo espera a próxima volta; falha
temporária (rede, API fora do ar) tenta de novo, recusa definitiva (422, 413…) não.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import httpx

TAMANHO_MAXIMO = 25 * 1024 * 1024
ARQUIVO_ESTADO = ".observador_enviados.json"


class ErroDeEnvio(RuntimeError):
    def __init__(self, mensagem: str, definitivo: bool):
        super().__init__(mensagem)
        self.definitivo = definitivo


@dataclass
class ObservadorDePasta:
    pasta: Path
    enviar: Callable[[Path], Dict[str, Any]]
    desde: Optional[float] = None  # só arquivos modificados depois disto; None = agora (o que já estava na pasta fica de fora)
    padrao: str = "*.pdf"
    _vistos: Dict[str, Tuple[int, float]] = field(default_factory=dict, init=False)
    _tratados: Set[str] = field(default_factory=set, init=False)
    _enviados: Set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        self.pasta = Path(self.pasta)
        if not self.pasta.is_dir():
            raise ValueError(f"A pasta {self.pasta} não existe.")
        if self.desde is None:
            self.desde = time.time()
        try:
            self._enviados = set(json.loads((self.pasta / ARQUIVO_ESTADO).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            self._enviados = set()

    def _guardar_estado(self) -> None:
        arquivo = self.pasta / ARQUIVO_ESTADO
        temporario = arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(sorted(self._enviados)), encoding="utf-8")
        os.replace(temporario, arquivo)

    def varrer(self) -> List[Dict[str, Any]]:
        """Uma volta pela pasta. Devolve o que aconteceu com cada arquivo que ficou pronto nesta volta."""
        resultados: List[Dict[str, Any]] = []
        for caminho in sorted(self.pasta.glob(self.padrao)):
            chave = str(caminho)
            try:
                info = caminho.stat()
            except OSError:  # apagado ou renomeado no meio da volta
                continue
            if not caminho.is_file() or chave in self._tratados or info.st_mtime < (self.desde or 0) - 2:  # 2 s: relógio de arquivo grosso
                continue
            assinatura = (info.st_size, info.st_mtime)
            if self._vistos.get(chave) != assinatura:  # novo ou ainda crescendo: confere de novo na próxima volta
                self._vistos[chave] = assinatura
                continue
            resultados.append(self._tratar(caminho))
        return resultados

    def _tratar(self, caminho: Path) -> Dict[str, Any]:
        chave = str(caminho)
        base = {"arquivo": caminho.name}
        dados = caminho.read_bytes()
        if len(dados) > TAMANHO_MAXIMO or not dados.startswith(b"%PDF-"):
            self._tratados.add(chave)
            return {**base, "status": "ignorado", "motivo": "não é PDF" if not dados.startswith(b"%PDF-") else "maior que 25 MB"}
        sha = hashlib.sha256(dados).hexdigest()
        if sha in self._enviados:
            self._tratados.add(chave)
            return {**base, "status": "ignorado", "motivo": "já enviado antes", "sha256": sha}
        try:
            resposta = self.enviar(caminho)
        except ErroDeEnvio as exc:
            if exc.definitivo:
                self._tratados.add(chave)
                return {**base, "status": "recusado", "motivo": str(exc), "sha256": sha}
            self._vistos.pop(chave, None)  # tenta de novo nas próximas voltas
            return {**base, "status": "tentar_de_novo", "motivo": str(exc)}
        self._tratados.add(chave)
        self._enviados.add(sha)
        self._guardar_estado()
        return {**base, "status": "enviado", "sha256": sha, "tipo": resposta.get("tipo"), "estado": resposta.get("estado"),
                "requer_revisao": resposta.get("requer_revisao"), "alertas": [a.get("codigo") for a in resposta.get("alertas", []) if isinstance(a, dict)]}


class ClienteAPI:
    """Envia o arquivo para a API do sistema, com login por usuário e senha (o token é renovado se vencer)."""

    def __init__(self, base_url: str, usuario: str, senha: str, cliente: Optional[httpx.Client] = None, timeout: float = 120.0):
        self.base, self._usuario, self._senha = base_url.rstrip("/"), usuario, senha
        self._http = cliente or httpx.Client(timeout=timeout)
        self._token: Optional[str] = None

    def _entrar(self) -> None:
        try:
            r = self._http.post(f"{self.base}/token", data={"username": self._usuario, "password": self._senha})
        except httpx.HTTPError as exc:
            raise ErroDeEnvio(f"API inacessível: {type(exc).__name__}", definitivo=False) from exc
        if r.status_code != 200:
            raise ErroDeEnvio(f"login recusado ({r.status_code})", definitivo=r.status_code in (401, 423))
        self._token = r.json()["access_token"]

    def __call__(self, caminho: Path) -> Dict[str, Any]:
        for tentativa in (1, 2):
            if self._token is None:
                self._entrar()
            try:
                with open(caminho, "rb") as f:
                    tipo = "application/xml" if caminho.suffix.lower() == ".xml" else "application/pdf"
                    r = self._http.post(f"{self.base}/api/v1/documentos", files={"arquivo": (caminho.name, f, tipo)},
                                        headers={"Authorization": f"Bearer {self._token}"})
            except httpx.HTTPError as exc:
                raise ErroDeEnvio(f"API inacessível: {type(exc).__name__}", definitivo=False) from exc
            if r.status_code == 401 and tentativa == 1:  # token venceu: entra de novo e repete uma vez
                self._token = None
                continue
            if r.status_code == 200:
                return r.json()
            try:
                detalhe = r.json().get("detail") or r.json().get("falha") or ""
            except ValueError:
                detalhe = ""
            raise ErroDeEnvio(f"{r.status_code} {detalhe}".strip(), definitivo=r.status_code < 500 and r.status_code not in (408, 429))
        raise ErroDeEnvio("login recusado", definitivo=True)
