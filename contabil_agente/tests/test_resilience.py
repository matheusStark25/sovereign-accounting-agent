"""Disjuntor, backoff exponencial, timeout e degradação elegante, com relógio e sleep falsos."""

import asyncio
import threading
import time

import pytest

from contabil_agente.resilience import (
    ChamadaResiliente,
    CircuitBreaker,
    CircuitoAberto,
    Estado,
    TimeoutExcedido,
    calcular_atraso,
    com_retry,
    com_retry_async,
    com_timeout,
)


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def falha():
    raise ConnectionError("fora")


# ------------------------------------------------------------------ disjuntor
def test_abre_depois_do_limite_de_falhas_e_recusa_sem_chamar():
    rel = Relogio()
    cb = CircuitBreaker("api", limite_falhas=3, janela_reset=30, relogio=rel)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            cb.chamar(falha)
    assert cb.estado is Estado.ABERTO
    chamadas = []
    with pytest.raises(CircuitoAberto):
        cb.chamar(lambda: chamadas.append(1))
    assert chamadas == [] and cb.total_recusadas == 1


def test_limiares_sao_configuraveis():
    cb = CircuitBreaker("x", limite_falhas=1)
    with pytest.raises(ConnectionError):
        cb.chamar(falha)
    assert cb.estado is Estado.ABERTO
    with pytest.raises(ValueError):
        CircuitBreaker("x", limite_falhas=0)


def test_meio_aberto_deixa_passar_so_uma_chamada_de_teste():
    rel = Relogio()
    cb = CircuitBreaker("api", limite_falhas=1, janela_reset=10, relogio=rel)
    with pytest.raises(ConnectionError):
        cb.chamar(falha)
    rel.t += 11
    assert cb.estado is Estado.MEIO_ABERTO
    resultados = []

    def teste_lento():
        # enquanto o teste roda, outra chamada é recusada
        with pytest.raises(CircuitoAberto):
            cb.chamar(lambda: None)
        resultados.append("recusada durante o teste")
        return "ok"

    assert cb.chamar(teste_lento) == "ok"
    assert resultados and cb.estado is Estado.FECHADO


def test_teste_que_falha_reabre_o_disjuntor():
    rel = Relogio()
    cb = CircuitBreaker("api", limite_falhas=1, janela_reset=10, relogio=rel)
    with pytest.raises(ConnectionError):
        cb.chamar(falha)
    rel.t += 11
    with pytest.raises(ConnectionError):
        cb.chamar(falha)
    assert cb.estado is Estado.ABERTO
    rel.t += 5
    assert cb.estado is Estado.ABERTO  # a janela recomeçou


def test_sucesso_zera_as_falhas_seguidas():
    cb = CircuitBreaker("api", limite_falhas=3)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            cb.chamar(falha)
    cb.chamar(lambda: 1)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            cb.chamar(falha)
    assert cb.estado is Estado.FECHADO


def test_so_as_excecoes_configuradas_contam():
    cb = CircuitBreaker("api", limite_falhas=1, excecoes=(ConnectionError,))
    with pytest.raises(ValueError):
        cb.chamar(lambda: (_ for _ in ()).throw(ValueError("bug do chamador")))
    assert cb.estado is Estado.FECHADO


def test_como_decorador_e_estatisticas():
    cb = CircuitBreaker("dec", limite_falhas=2)

    @cb
    def soma(a, b):
        return a + b

    assert soma(1, 2) == 3 and soma.__name__ == "soma"
    assert cb.estatisticas()["chamadas"] == 1


def test_thread_safety_um_unico_teste_em_meio_aberto():
    rel = Relogio()
    cb = CircuitBreaker("api", limite_falhas=1, janela_reset=1, relogio=rel)
    with pytest.raises(ConnectionError):
        cb.chamar(falha)
    rel.t += 2
    liberar, entrou = threading.Event(), threading.Event()
    executadas, recusadas = [], []

    def lenta():
        executadas.append(1)
        entrou.set()
        liberar.wait(2)

    def tenta():
        try:
            cb.chamar(lenta)
        except CircuitoAberto:
            recusadas.append(1)

    primeira = threading.Thread(target=tenta)
    primeira.start()
    entrou.wait(2)
    outras = [threading.Thread(target=tenta) for _ in range(5)]
    [t.start() for t in outras]
    [t.join() for t in outras]
    liberar.set()
    primeira.join()
    assert len(executadas) == 1 and len(recusadas) == 5


# ---------------------------------------------------------------------- retry
def test_backoff_exponencial_sem_jitter():
    assert [calcular_atraso(n, 0.5, 2.0, 8.0, 0) for n in (1, 2, 3, 4, 5, 6)] == [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]


def test_jitter_fica_dentro_da_faixa():
    for _ in range(50):
        assert 0.8 <= calcular_atraso(1, 1.0, 2.0, 8.0, 0.2) <= 1.2


def test_retry_dorme_com_backoff_e_devolve_o_sucesso():
    pausas, tentativas = [], []

    def instavel():
        tentativas.append(1)
        if len(tentativas) < 3:
            raise ConnectionError("x")
        return "ok"

    r = com_retry(instavel, tentativas=4, atraso_inicial=1.0, jitter=0, dormir=pausas.append)
    assert r == "ok" and pausas == [1.0, 2.0]


def test_retry_esgota_e_levanta_o_ultimo_erro():
    pausas = []
    with pytest.raises(ConnectionError):
        com_retry(falha, tentativas=3, atraso_inicial=1.0, jitter=0, dormir=pausas.append)
    assert pausas == [1.0, 2.0]  # 3 tentativas, 2 esperas


def test_retry_nao_repete_o_que_nao_deve():
    chamadas = []

    def erro_de_dado():
        chamadas.append(1)
        raise ValueError("dado inválido")

    with pytest.raises(ValueError):
        com_retry(erro_de_dado, tentativas=5, nao_repetir=(ValueError,), dormir=lambda s: None)
    assert len(chamadas) == 1


def test_retry_assincrono():
    pausas, n = [], []

    async def instavel():
        n.append(1)
        if len(n) < 2:
            raise ConnectionError("x")
        return "ok"

    async def dorme(s):
        pausas.append(s)

    assert asyncio.run(com_retry_async(instavel, tentativas=3, atraso_inicial=0.25, jitter=0, dormir=dorme)) == "ok"
    assert pausas == [0.25]


# -------------------------------------------------------------------- timeout
def test_timeout_estoura_e_nao_atrapalha_quem_termina_a_tempo():
    assert com_timeout(lambda: "rapido", 1) == "rapido"
    with pytest.raises(TimeoutExcedido):
        com_timeout(lambda: time.sleep(0.5), 0.05)


def test_excecao_da_funcao_passa_pelo_timeout():
    with pytest.raises(ConnectionError):
        com_timeout(falha, 1)


# ------------------------------------------------------------------ degradação
def test_chamada_resiliente_faz_retry_e_recupera():
    n = []

    def instavel():
        n.append(1)
        if len(n) < 3:
            raise ConnectionError("x")
        return "ok"

    c = ChamadaResiliente("api", tentativas=3, timeout=1, dormir=lambda s: None)
    assert c.chamar(instavel) == "ok" and len(n) == 3


def test_degrada_para_a_alternativa_quando_tudo_falha():
    c = ChamadaResiliente("llm", tentativas=2, timeout=1, dormir=lambda s: None)
    assert c.chamar(falha, fallback=lambda exc: f"resposta padrão ({type(exc).__name__})") == "resposta padrão (ConnectionError)"


def test_sem_fallback_a_falha_aparece():
    c = ChamadaResiliente("llm", tentativas=2, timeout=1, dormir=lambda s: None)
    with pytest.raises(ConnectionError):
        c.chamar(falha)


def test_com_circuito_aberto_nao_chama_nem_repete_e_usa_o_fallback():
    c = ChamadaResiliente("llm", limite_falhas=2, tentativas=2, timeout=1, dormir=lambda s: None)
    c.chamar(falha, fallback=lambda e: None)  # 2 falhas abrem o circuito
    chamadas = []
    resposta = c.chamar(lambda: chamadas.append(1), fallback=lambda e: "degradado")
    assert resposta == "degradado" and chamadas == []


def test_erro_do_chamador_nao_e_mascarado_pelo_fallback():
    c = ChamadaResiliente("x", tentativas=1, timeout=1, excecoes=(ConnectionError,), dormir=lambda s: None)
    with pytest.raises(KeyError):
        c.chamar(lambda: {}["x"], fallback=lambda e: "não deveria")
