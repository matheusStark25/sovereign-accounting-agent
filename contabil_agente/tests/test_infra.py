"""Consistência da infraestrutura (Docker, compose, nginx, CI, dependências, segredos), sem precisar do Docker."""

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]


def ler(rel):
    return (RAIZ / rel).read_text(encoding="utf-8")


def versionados():
    saida = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True)
    if saida.returncode != 0:
        pytest.skip("fora de um repositório git")
    return [RAIZ / p for p in saida.stdout.splitlines() if (RAIZ / p).is_file()]


# ----------------------------------------------------------------------------- compose
def test_compose_so_referencia_arquivos_que_existem():
    compose = yaml.safe_load(ler("docker-compose.yml"))
    for nome, srv in compose["services"].items():
        if "build" in srv and isinstance(srv["build"], str):
            assert (RAIZ / srv["build"] / "Dockerfile").is_file(), nome
        for vol in srv.get("volumes", []):
            origem = vol.split(":")[0]
            if origem.startswith("./"):
                assert (RAIZ / origem).exists() or origem == "./certs", f"{nome}: volume {origem} não existe"
    assert (RAIZ / "Dockerfile").is_file()


def test_compose_nao_tem_segredo_fixo_e_exige_os_obrigatorios():
    texto = ler("docker-compose.yml")
    for obrigatorio in ("JWT_SECRET", "AUDIT_HMAC_KEY", "GOVERNANCA_DSA_KEY", "REDIS_PASSWORD"):
        assert re.search(rf"\$\{{{obrigatorio}:\?", texto), f"{obrigatorio} precisa ser obrigatório (sem valor padrão)"
    assert not re.search(r"(?i)password\s*[:=]\s*[\"']?(admin|changeme|secret|password|contabil_pwd|123)", texto)
    assert "latest" not in texto  # nada de imagem sem versão
    compose = yaml.safe_load(texto)
    assert compose["services"]["vault"]["profiles"] == ["dev"]  # Vault em modo dev nunca sobe por padrão


def test_compose_endurece_os_containers_da_aplicacao():
    api = yaml.safe_load(ler("docker-compose.yml"))["services"]["api"]
    assert "no-new-privileges:true" in api["security_opt"] and api["cap_drop"] == ["ALL"]


def test_compose_filas_do_worker_batem_com_o_roteamento_do_celery():
    from contabil_agente.tarefas import celery_app

    worker = yaml.safe_load(ler("docker-compose.yml"))["services"]["worker-documentos"]["command"]
    assert "-Q" in worker and worker[worker.index("-Q") + 1] == "documentos"
    assert celery_app.conf.task_routes["documentos.*"]["queue"] == "documentos" and celery_app.conf.task_routes["rpa.*"]["queue"] == "rpa"


# ----------------------------------------------------------------------------- Dockerfile
def test_dockerfile_copia_so_o_que_existe_roda_como_nao_root_e_sobe_a_api_certa():
    d = ler("Dockerfile")
    for origem in re.findall(r"^COPY\s+(\S+)\s+\S+", d, re.M):
        assert (RAIZ / origem).exists(), origem
    assert d.startswith("# API") or "FROM python:3.12" in d
    assert re.search(r"^USER app", d, re.M) and "HEALTHCHECK" in d
    assert 'CMD ["uvicorn", "agente_v2.main:app"' in d
    import agente_v2.main as m

    assert hasattr(m, "create_app")  # o alvo do CMD existe (``app`` é criado sob demanda)


def test_dockerignore_deixa_de_fora_segredos_e_dados():
    ign = ler(".dockerignore")
    for item in (".env", "*.db", "certs/", "chaves/", ".git"):
        assert item in ign


# ----------------------------------------------------------------------------- nginx
def test_nginx_exige_certificado_de_cliente_na_porta_mtls_e_nao_repassa_identidade():
    conf = ler("nginx/nginx.conf")
    bloco = conf[conf.index("listen 8443"):]
    assert "ssl_verify_client       on" in bloco and "ssl_client_certificate" in bloco
    assert "TLSv1.2 TLSv1.3" in conf and "SSLv3" not in conf
    publico = conf[:conf.index("listen 8443")]
    assert re.search(r"location = /metrics\s*\{\s*return 404;", publico), "/metrics não pode ficar aberto na porta pública"
    assert (RAIZ / "nginx" / "proxy.inc").is_file()
    proxy = ler("nginx/proxy.inc")
    for cab in ("X-User-ID", "X-Tenant-ID", "X-User-Roles"):
        assert f'proxy_set_header {cab} ""' in proxy


# ----------------------------------------------------------------------------- CI
def test_ci_roda_o_que_existe_e_nao_aponta_para_arquivos_inexistentes():
    ci = yaml.safe_load(ler(".github/workflows/ci.yml"))
    passos = " ".join(str(p.get("run", "")) for j in ci["jobs"].values() for p in j["steps"])
    assert "pytest" in passos and "flake8 agente_v2 contabil_agente" in passos and "docker build" in passos
    for arq in re.findall(r"-r (\S+\.txt)", passos) + ["requirements-dev.txt"]:
        assert (RAIZ / arq).is_file(), arq
    assert not list((RAIZ / ".github" / "workflows").glob("ci-*.yml"))  # os workflows antigos foram embora
    assert "testpaths = agente_v2 contabil_agente" in ler("pytest.ini")


# ----------------------------------------------------------------------------- dependências
MODULO_PARA_PACOTE = {
    "jwt": "PyJWT", "yaml": "PyYAML", "kyber_py": "kyber-py", "dilithium_py": "dilithium-py", "prometheus_client": "prometheus-client",
}


def test_requirements_cobre_tudo_que_o_codigo_importa():
    req = {re.split(r"[<>=\[ ]", linha.strip())[0].lower().replace("_", "-") for linha in ler("requirements.txt").splitlines()
           if linha.strip() and not linha.startswith("#")}
    padrao = set(sys.stdlib_module_names) | {"agente_v2", "contabil_agente"}
    faltando = set()
    for arq in list((RAIZ / "agente_v2").rglob("*.py")) + list((RAIZ / "contabil_agente").rglob("*.py")):
        if "tests" in arq.parts:
            continue
        for n in ast.walk(ast.parse(arq.read_text(encoding="utf-8"))):
            nomes = [a.name.split(".")[0] for a in n.names] if isinstance(n, ast.Import) else (
                [n.module.split(".")[0]] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else [])
            for nome in nomes:
                if nome not in padrao and MODULO_PARA_PACOTE.get(nome, nome).lower().replace("_", "-") not in req:
                    faltando.add(nome)
    assert not faltando, f"faltam no requirements.txt: {sorted(faltando)}"


def test_requirements_nao_traz_o_que_foi_removido():
    req = ler("requirements.txt").lower()
    for removido in ("flask", "passlib", "python-jose", "gunicorn", "selenium", "pyautogui", "pywinauto"):
        assert removido not in req


# ----------------------------------------------------------------------------- .env.example
def test_env_example_lista_os_segredos_obrigatorios_e_nao_traz_valores():
    linhas = {l.split("=")[0]: l.split("=", 1)[1] for l in ler(".env.example").splitlines() if "=" in l and not l.startswith("#")}
    for chave in ("JWT_SECRET", "AUDIT_HMAC_KEY", "GOVERNANCA_DSA_KEY", "REDIS_PASSWORD", "ADMIN_USERNAME", "ADMIN_PASSWORD"):
        assert chave in linhas and linhas[chave] == ""
    # toda variável de segredo que o compose exige está no .env.example
    for var in re.findall(r"\$\{([A-Z_]+):\?", ler("docker-compose.yml")):
        assert var in linhas, var


# ----------------------------------------------------------------------------- segredos
PADROES_PROIBIDOS = [
    (r"gsk_[A-Za-z0-9]{20,}", "chave da Groq"),
    (r"sk-[A-Za-z0-9]{30,}", "chave de API estilo OpenAI/DeepSeek"),
    (r"AKIA[0-9A-Z]{16}", "chave da AWS"),
    (r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----", "chave privada"),
    (r"AIza[0-9A-Za-z_\-]{35}", "chave do Google"),
    (r"(?i)(api[_-]?key|secret|password|token)\s*=\s*[\"'][A-Za-z0-9_\-/+]{24,}[\"']", "segredo no código"),
]


def test_nenhum_segredo_versionado():
    achados = []
    for arq in versionados():
        if arq.suffix in (".pdf", ".png", ".jpg", ".db", ".zip", ".ico") or arq.name == "test_infra.py":
            continue
        try:
            texto = arq.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for padrao, nome in PADROES_PROIBIDOS:
            for m in re.finditer(padrao, texto):
                if arq.suffix == ".py" and "tests" in arq.parts:
                    continue  # chaves falsas de teste ("k" * 40 etc.) não casam; cabeçalhos PEM de teste são gerados em tempo de execução
                achados.append(f"{arq.relative_to(RAIZ)}: {nome}")
    assert not achados, achados


def test_nenhum_dado_de_execucao_versionado():
    ruins = [p.relative_to(RAIZ).as_posix() for p in versionados() if p.suffix in (".db", ".sqlite", ".sqlite3", ".jsonl", ".log", ".pem", ".key") or ".db-" in p.name]
    assert not ruins, ruins


def test_licenca_mit_presente():
    assert ler("LICENSE").startswith("MIT License")


def test_lock_cobre_todas_as_dependencias_diretas():
    lock = {re.split(r"==", l.strip())[0].lower().replace("_", "-") for l in ler("requirements.lock").splitlines() if "==" in l}
    diretas = {re.split(r"[<>=\[ ]", l.strip())[0].lower().replace("_", "-") for l in ler("requirements.txt").splitlines()
               if l.strip() and not l.startswith("#")}
    assert diretas <= lock, sorted(diretas - lock)
