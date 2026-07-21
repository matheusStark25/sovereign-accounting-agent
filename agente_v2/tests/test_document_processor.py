import asyncio

from agente_v2.document_processor import DocumentProcessor


def test_process_plain_text():
    dp = DocumentProcessor()
    data = "Nome: João da Silva\nCPF: 123.456.789-00".encode("utf-8")
    res = asyncio.get_event_loop().run_until_complete(dp.process(data, "test.txt"))
    assert res["filename"] == "test.txt"
    assert "chunks" in res
    assert isinstance(res.get("entities"), list)
