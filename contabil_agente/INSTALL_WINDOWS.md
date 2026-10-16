Instalação de dependências de áudio no Windows

Resumo rápido
- O pacote `pyaudio` frequentemente requer ferramentas de compilação no Windows. Recomendo instalar via `pipwin` (instala wheels pré-compilados) ou usar uma wheel pré-compilada.

Opção 1 — pipwin (recomendada para Windows):
1) Instale pipwin:

```powershell
pip install pipwin
```

2) Use pipwin para instalar pyaudio:

```powershell
pipwin install pyaudio
```

3) Instale SpeechRecognition e pyttsx3 (se ainda não estiverem):

```powershell
pip install SpeechRecognition pyttsx3
```

Opção 2 — wheel pré-compilada (quando pipwin não funcionar):
1) Abra https://www.lfd.uci.edu/~gohlke/pythonlibs/ e pesquise por "PyAudio". Baixe o arquivo .whl compatível com sua versão do Python (por ex. `PyAudio‑0.2.11‑cp39‑cp39‑win_amd64.whl`).
2) Instale com pip apontando para o arquivo:

```powershell
pip install C:\caminho\para\PyAudio‑0.2.11‑cp39‑cp39‑win_amd64.whl
```

Opção 3 — Build Tools (quando você precisa compilar)
- Instale o "Build Tools for Visual Studio" (C++). Link: https://visualstudio.microsoft.com/visual-cpp-build-tools/
- Depois, tente `pip install pyaudio` novamente.

Observações e dicas
- Se você usa apenas o frontend do navegador (Web Speech API) e envia o áudio ao backend como arquivo, normalmente não precisa de `pyaudio` no servidor (ele é necessário principalmente para captura de microfone local via Python). O backend já faz STT a partir de arquivos de áudio com `SpeechRecognition` usando `AudioFile`.
- O nosso servidor também suporta TTS via `pyttsx3`. Se quiser áudio gerado no servidor, instale `pyttsx3` normalmente. Em alguns ambientes Windows, `pyttsx3` funciona sem pyaudio.
- Alternativa moderna para captura/streaming: usar o navegador para captura (já implementado no `index.html`) e enviar o arquivo ao endpoint `/api/voice` — isso evita precisar instalar `pyaudio` no servidor.

Comandos de verificação rápida

```powershell
python -c "import speech_recognition; print('SpeechRecognition OK')"
python -c "import pyttsx3; print('pyttsx3 OK')"
python -c "import pyaudio; print('pyaudio OK')"
```

Se precisar, eu posso adicionar um script PowerShell para automatizar a instalação via `pipwin` e checar as versões do Python e wheels compatíveis.
