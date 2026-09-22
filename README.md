# SenaSaarthi AI

Private LAN chat and document correction backed by Ollama.

Requirements: Python 3.11–3.14 and Ollama running locally.

The application provides one general chat window. Users can ask normal questions,
write code, rewrite text, analyze files, and request grammar correction. DOCX/PDF
correction requests produce a temporary corrected DOCX download.

## Prerequisite: install Ollama

Install Ollama on the computer that will run SenaSaarthi AI. Ollama must be
running locally at `http://127.0.0.1:11434`.

### Windows

Open PowerShell and run the official installer command:

```powershell
irm https://ollama.com/install.ps1 | iex
```

You can also download and run the installer from
<https://ollama.com/download/windows>. After installation, open a new
PowerShell window and pull the default model:

```powershell
ollama --version
ollama pull qwen3.5:9b
ollama list
```

### Ubuntu

Open a terminal and run the official Linux installer:

```bash
sudo apt update
sudo apt install -y curl
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
ollama pull qwen3.5:9b
ollama list
```

If Ubuntu reports that Ollama is not running, start it in another terminal:

```bash
ollama serve
```

The official Linux instructions are available at
<https://ollama.com/download/linux>.

## Quick local test

These instructions are for macOS. The defaults are already set for the model
currently being used: `qwen3.5:9b`.

### 1. Install and verify Ollama

Install Ollama, start it, and pull the model:

```bash
ollama pull qwen3.5:9b
ollama list
```

The model should appear as `qwen3.5:9b`.

### 2. Create the Python environment

From the project directory:

```bash
cd /Users/kanchan/Desktop/Local-LLM
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[test]'
```

If `.env` does not already exist, create it once:

```bash
cp .env.example .env
```

If `.env` already exists, keep it and edit it; do not overwrite it.

### 3. Configure login accounts

Edit `.env` and set these values. Use strong passwords of at least 10
characters:

```text
APP_SECRET_KEY=<long-random-secret>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<admin-password>
USER_USERNAME=user
USER_PASSWORD=<user-password>
```

Generate a secret with:

```bash
openssl rand -hex 32
```

Accounts are created automatically only when their usernames do not already
exist. Existing passwords are never overwritten. Do not commit `.env`.

If an account already exists and you need another one, use:

```bash
python -m scripts.create_user --username another-user
python -m scripts.create_user --username another-admin --admin
```

### 4. Start the website

```bash
python -m scripts.start_server
```

Open <http://127.0.0.1:8080> and sign in.

## Default configuration

These values come from `.env.example`. Values in your `.env` take priority.

| Setting | Default |
|---|---|
| Model | `qwen3.5:9b` |
| Ollama address | `http://127.0.0.1:11434` |
| Thinking | Enabled |
| Context window | `auto` — detected from the model |
| Website address | `http://127.0.0.1:8080` |
| Upload limit | 25 MB |
| PDF limit | 50 pages |
| DOCX limit | About 200,000 extracted characters |
| Temporary file retention | 30 minutes |
| Simultaneous generations | 2; additional requests wait in a queue |

`MAX_CONCURRENT_JOBS` is a generation limit, not a user-account limit. Increase
it only if the server GPU can handle more simultaneous model requests.

## Basic test checklist

1. Ask a normal question and confirm tokens appear while the model is generating.
2. Start a response, then press **Stop**. The partial response should remain.
3. Press **New chat** and confirm the temporary conversation is cleared.
4. Attach a selectable-text PDF or DOCX and ask for a summary. Answers may include
   references such as `[SOURCE: Page 3]` or `[SOURCE: Paragraph 00012]`.
5. Ask to correct the attached document. A corrected DOCX should be downloadable.

Scanned/image-only PDFs are not supported yet. PDF layout is not preserved
exactly; PDF correction creates a new editable DOCX.

## LAN deployment

On Windows Server, set these environment values before starting:

```text
APP_SECRET_KEY=<long-random-secret>
LOCAL_LLM_DATA_DIR=D:\LocalLLM\data
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:9b
OLLAMA_THINKING=true
OLLAMA_NUM_CTX=auto
APP_HOST=0.0.0.0
ACTIVE_USER_WINDOW_SECONDS=300
APP_PORT=8080
```

Create accounts manually with `scripts.create_user`, then open:

```text
http://SERVER_LAN_IP:8080
```

Allow inbound TCP 8080 only from the approved LAN subnet in Windows Firewall.
Do not add router port forwarding and do not expose port 11434.

The pilot uses manual startup. A later hardening phase can register Ollama and
the web application as Windows services.

`OLLAMA_NUM_CTX=auto` reads the selected model's advertised maximum context
window from Ollama. If that maximum causes GPU-memory pressure, replace `auto`
with a safe numeric value such as `8192` or `16384`.

Administrators can manage accounts at `/admin`. The admin console shows active
users, Ollama/model health, detected context size, and running/queued generation
jobs. An account is considered active when it has sent activity within
`ACTIVE_USER_WINDOW_SECONDS` (five minutes by default). Administrators can create,
disable, reset, and revoke sessions for accounts. Public self-registration remains
disabled.

For the Windows pilot, after installing dependencies and creating an account:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\scripts\start_windows.ps1
```

The script checks whether Ollama is already reachable on localhost, starts it
when necessary, and then starts the web application on the LAN interface.

## File behavior

- DOCX and selectable-text PDF files are accepted.
- DOCX output preserves basic paragraphs, styles, lists, and simple tables.
- PDF input becomes a new structured DOCX; original PDF layout is not preserved.
- Scanned PDFs require OCR and are rejected in this version.
- Uploads and generated files expire after 30 minutes.
- Conversation history is held in memory and disappears after restart.
- User accounts persist in SQLite.
- The chat UI supports stopping a generation and starting a new temporary chat.
- Uploaded document context is labeled with PDF page, DOCX paragraph/table, or text
  line sources so the model can cite where an answer came from.
- `MAX_CONCURRENT_JOBS` controls simultaneous model generations; extra requests are
  queued, not rejected.

## Automated tests

```bash
source .venv/bin/activate
python -m pytest -q
```

The tests do not require a running Ollama server. Live testing uses the selected
model and should be performed on the target machine/GPU.
