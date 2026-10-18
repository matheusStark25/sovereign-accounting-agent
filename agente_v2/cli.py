"""Linha de comando de administração.

    python -m agente_v2.cli criar-usuario --usuario maria --tenant empresa_a --papeis accountant
    python -m agente_v2.cli gerar-chaves-rpa --saida ./chaves
    python -m agente_v2.cli verificar-auditoria --tenant empresa_a
    python -m agente_v2.cli gerar-segredo
    python -m agente_v2.cli gerar-chave-governanca
    python -m agente_v2.cli verificar-ia --env-file .env
    python -m agente_v2.cli calibrar-fgts --canal msedge --saida ./calibragem
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import sys
from pathlib import Path


def _auth():
    from contabil_agente.security.auth import AuthService

    return AuthService()


def criar_usuario(args: argparse.Namespace) -> int:
    senha = os.environ.get("NOVA_SENHA") or getpass.getpass("Senha (mín. 10, misture maiúsculas, minúsculas, números ou símbolos): ")
    try:
        u = _auth().criar_usuario(args.usuario, senha, args.tenant, args.papeis.split(","))
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(u.to_dict(), ensure_ascii=False))
    return 0


def gerar_chaves_rpa(args: argparse.Namespace) -> int:
    from contabil_agente.security import pqc

    chaves = pqc.gerar_chaves_hibridas()
    pasta = Path(args.saida)
    pasta.mkdir(parents=True, exist_ok=True)
    pub, priv = pasta / "rpa_publica.json", pasta / "rpa_privada.json"
    pub.write_text(json.dumps(chaves.publica()), encoding="utf-8")
    priv.write_text(json.dumps(chaves.privada()), encoding="utf-8")
    try:
        os.chmod(priv, 0o600)
    except OSError:
        pass
    print(f"Chave pública:  {pub}\nChave privada:  {priv}  (guarde no Vault ou no worker; nunca versione)")
    print("RPA_PQC_PUBLIC_KEY=" + json.dumps(chaves.publica()))
    return 0


def verificar_auditoria(args: argparse.Namespace) -> int:
    from agente_v2.config import settings
    from contabil_agente.security.worm_audit import WormAudit

    worm = WormAudit.do_ambiente(settings.AUDIT_DIR)
    tenants = [args.tenant] if args.tenant else worm.tenants()
    ruim = 0
    for t in tenants:
        v = worm.verificar(t)
        print(json.dumps(v.to_dict(), ensure_ascii=False))
        ruim += 0 if v.ok else 1
    return 1 if ruim else 0


def gerar_chave_governanca(_: argparse.Namespace) -> int:
    import base64

    from contabil_agente.security import pqc

    par = pqc.DilithiumAssinatura.gerar_par()
    valor = json.dumps({"pub": base64.b64encode(par.publica).decode(), "priv": base64.b64encode(par.privada).decode()})
    print("Guarde no Vault (campo governanca_dsa_key) ou no ambiente do servidor; nunca versione:")
    print("GOVERNANCA_DSA_KEY=" + valor)
    return 0


def gerar_segredo(_: argparse.Namespace) -> int:
    print(secrets.token_urlsafe(48))
    return 0


def carregar_env(caminho: str) -> dict:
    """Lê um arquivo ``CHAVE=valor`` (comentários com #, aspas opcionais) sem exportar nada para o ambiente."""
    valores = {}
    for linha in Path(caminho).read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valores[chave.strip()] = valor.strip().strip("\"'")
    return valores


def calibrar_fgts(args: argparse.Namespace) -> int:
    """Abre o portal em um navegador de verdade; uma pessoa faz o caminho normal e o gravador anota só a estrutura."""
    from contabil_agente.rpa.calibracao import calibrar

    print("Vai abrir um navegador. Faça o caminho normal até baixar o extrato (login, captcha, menus, download).")
    print("Nada do que você digitar é gravado. Feche a janela quando terminar.")
    rel = calibrar(args.url, args.saida, canal=args.canal, user_data_dir=args.perfil)
    print(json.dumps({"hosts": rel["hosts"], "cliques": rel["cliques"], "downloads": len(rel["downloads"]),
                      "relatorio": str(Path(args.saida) / "calibragem.json")}, ensure_ascii=False))
    return 0


def verificar_ia(args: argparse.Namespace) -> int:
    """Chama de verdade cada provedor de IA configurado: a chave vale, o modelo existe e uma chamada mínima funciona."""
    from contabil_agente.chat.llm import GroqLLM, llm_do_ambiente
    from contabil_agente.pipeline.provedores import provedores_do_ambiente

    env = dict(os.environ)
    if args.env_file:
        env.update(carregar_env(args.env_file))
    verificados = []
    for p in provedores_do_ambiente(env).values():
        if p is not None:
            verificados.append(p.verificar())
    groq = llm_do_ambiente(env)
    if isinstance(groq, GroqLLM):
        verificados.append(groq.verificar())
    if not verificados:
        print("Nenhuma chave de IA configurada (GROQ_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY).", file=sys.stderr)
        if args.env_file:
            em_branco = [n for n in ("GROQ_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY") if n in env and not env[n].strip()]
            if em_branco:
                print(f"No arquivo {args.env_file} estas chaves existem mas estão em branco: {', '.join(em_branco)}. "
                      "Cole o valor depois do '=' e salve (Ctrl+S).", file=sys.stderr)
        return 2
    for v in verificados:
        print(json.dumps(v, ensure_ascii=False))
    return 0 if all(v["chamada_ok"] for v in verificados) else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="agente_v2.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("criar-usuario")
    c.add_argument("--usuario", required=True)
    c.add_argument("--tenant", required=True)
    c.add_argument("--papeis", required=True, help="separados por vírgula: super_admin,tenant_admin,accountant,auditor,viewer")
    c.set_defaults(func=criar_usuario)
    k = sub.add_parser("gerar-chaves-rpa")
    k.add_argument("--saida", default="./chaves")
    k.set_defaults(func=gerar_chaves_rpa)
    a = sub.add_parser("verificar-auditoria")
    a.add_argument("--tenant")
    a.set_defaults(func=verificar_auditoria)
    s = sub.add_parser("gerar-segredo")
    s.set_defaults(func=gerar_segredo)
    g = sub.add_parser("gerar-chave-governanca")
    g.set_defaults(func=gerar_chave_governanca)
    v = sub.add_parser("verificar-ia", help="testa de verdade as chaves e os modelos de IA configurados")
    v.add_argument("--env-file", help="arquivo CHAVE=valor com as chaves (ex.: .env)")
    v.set_defaults(func=verificar_ia)
    f = sub.add_parser("calibrar-fgts", help="grava a estrutura do portal do FGTS enquanto uma pessoa o percorre")
    f.add_argument("--url", default="https://www.caixa.gov.br", help="página inicial do caminho")
    f.add_argument("--saida", default="./calibragem")
    f.add_argument("--canal", help="msedge ou chrome (navegador já instalado); padrão: Chromium do Playwright")
    f.add_argument("--perfil", help="pasta do perfil do navegador (a sessão logada fica guardada nela)")
    f.set_defaults(func=calibrar_fgts)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
