"""Leitura segura de arquivos (PDF, XML, TXT/CSV) para o texto que as regras de extração usam.

Limites: 25 MB por arquivo e 300 páginas de PDF. XML é lido com ``defusedxml`` (sem entidades externas,
sem expansão de entidades). PDF sem camada de texto (escaneado) é sinalizado: não há OCR embutido,
e nada é inventado no lugar do texto que falta.
"""

from __future__ import annotations

import codecs
import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from pypdf import PdfReader
from pypdf.errors import PyPdfError

TAMANHO_MAXIMO = 25 * 1024 * 1024
PAGINAS_MAXIMAS = 300


class ArquivoInvalido(ValueError):
    """Arquivo ausente, grande demais, corrompido ou de formato não suportado."""


@dataclass
class Conteudo:
    formato: str  # pdf | xml | texto
    texto: str
    paginas: int = 0
    xml: Optional[Element] = None
    avisos: List[str] = field(default_factory=list)
    sha256: str = ""

    @property
    def linhas(self) -> List[str]:
        return self.texto.splitlines()


def _decodificar(dados: bytes) -> str:
    for codificacao in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return dados.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1", errors="replace")


def _ler_pdf(dados: bytes) -> Conteudo:
    try:
        leitor = PdfReader(io.BytesIO(dados))
        if leitor.is_encrypted:
            raise ArquivoInvalido("PDF protegido por senha: não consigo ler.")
        if len(leitor.pages) > PAGINAS_MAXIMAS:
            raise ArquivoInvalido(f"PDF com {len(leitor.pages)} páginas (máximo {PAGINAS_MAXIMAS}).")
        partes = [(pagina.extract_text() or "") for pagina in leitor.pages]
    except ArquivoInvalido:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        raise ArquivoInvalido(f"PDF ilegível: {exc}") from exc
    texto = "\n".join(partes)
    avisos = []
    if not texto.strip():
        avisos.append("PDF sem camada de texto (provavelmente escaneado): é preciso OCR; nada foi extraído.")
    return Conteudo("pdf", texto, paginas=len(partes), avisos=avisos)


def _ler_xml(dados: bytes) -> Conteudo:
    try:
        raiz = SafeET.fromstring(dados)
    except (DefusedXmlException, SafeET.ParseError, ValueError) as exc:
        raise ArquivoInvalido(f"XML inválido ou inseguro: {exc}") from exc
    texto = "\n".join(f"{_nome(el.tag)}: {(el.text or '').strip()}" for el in raiz.iter() if (el.text or "").strip())
    return Conteudo("xml", texto, xml=raiz)


def _nome(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ler(origem: Union[str, Path, bytes], nome: Optional[str] = None) -> tuple:
    if isinstance(origem, (str, Path)):
        caminho = Path(origem)
        if not caminho.is_file():
            raise ArquivoInvalido(f"Arquivo não encontrado: {caminho.name}")
        if caminho.stat().st_size > TAMANHO_MAXIMO:
            raise ArquivoInvalido(f"Arquivo maior que {TAMANHO_MAXIMO // (1024 * 1024)} MB.")
        dados = caminho.read_bytes()
        nome = nome or caminho.name
    else:
        dados = bytes(origem)
        if len(dados) > TAMANHO_MAXIMO:
            raise ArquivoInvalido(f"Arquivo maior que {TAMANHO_MAXIMO // (1024 * 1024)} MB.")
    if not dados.strip():
        raise ArquivoInvalido("Arquivo vazio.")

    inicio = dados.lstrip()[:8]
    extensao = Path(nome or "").suffix.lower()
    if dados.startswith(b"%PDF-"):
        return dados, _ler_pdf(dados)
    if inicio.startswith(b"<") or inicio.startswith(codecs.BOM_UTF8 + b"<"):
        return dados, _ler_xml(dados)
    if extensao == ".pdf":
        raise ArquivoInvalido("O arquivo diz ser PDF, mas não tem a assinatura de um PDF.")
    return dados, Conteudo("texto", _decodificar(dados))


def ler_documento(origem: Union[str, Path, bytes], nome: Optional[str] = None) -> Conteudo:
    """Lê um caminho ou os bytes de um arquivo. ``nome`` ajuda a decidir o formato de bytes sem assinatura."""
    dados, conteudo = _ler(origem, nome)
    conteudo.sha256 = hashlib.sha256(dados).hexdigest()
    return conteudo
