"""Linha de comando de administração.

    python -m agente_v2.cli criar-usuario --usuario maria --tenant empresa_a --papeis accountant
    python -m agente_v2.cli gerar-chaves-rpa --saida ./chaves
    python -m agente_v2.cli verificar-auditoria --tenant empresa_a
    python -m agente_v2.cli gerar-segredo
    python -m agente_v2.cli gerar-chave-governanca
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
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
