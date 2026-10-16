import os
import sys
import requests


def main():
    url = "http://127.0.0.1:5000/api/generate"
    payload = {
        "mensagem": (
            "GERE O DOCUMENTO: Aditivo de transferencia para Ramino de Souza Lopes; "
            "CPF 000.000.000-00; salario R$3000; posto anterior: Posto X; "
            "novo posto: Posto Sao Jose; data: 01/02/2026"
        ),
        "session_id": "test-session",
        "force_generate": True,
    }

    print("POSTing to", url)
    try:
        r = requests.post(url, json=payload, timeout=30)
    except Exception as e:
        print("Request failed:", e)
        sys.exit(2)

    print("Status:", r.status_code)
    print("Response:", r.text)

    try:
        data = r.json()
    except Exception:
        print("Response is not JSON; aborting")
        sys.exit(0)

    pdf_url = data.get("pdf_url") or data.get("download_link")
    if not pdf_url:
        print("No pdf_url returned.")
        sys.exit(0)

    # Normalize URL
    if pdf_url.startswith("/"):
        download_url = "http://127.0.0.1:5000" + pdf_url
    else:
        download_url = pdf_url

    print("Attempting to download PDF from", download_url)
    try:
        resp = requests.get(download_url, stream=True, timeout=30)
    except Exception as e:
        print("Download request failed:", e)
        sys.exit(3)

    if resp.status_code != 200:
        print("Download failed, status", resp.status_code)
        sys.exit(4)

    out_path = os.path.join(os.getcwd(), "generated_document.pd")
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(1024 * 8):
            if chunk:
                f.write(chunk)

    print("Saved PDF to", out_path)


if __name__ == "__main__":
    main()
