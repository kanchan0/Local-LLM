# SenaSaarthi AI

Private LAN chat and document correction backed by Ollama.

The application provides one general chat window. Users can ask normal questions,
write code, rewrite text, analyze files, and request grammar correction. DOCX/PDF
correction requests produce a temporary corrected DOCX download.

## Requirements

- Python 3.11–3.14.
- Ollama installed and running locally.
- `fonttools` is installed automatically for better PDF font decoding.
- A model pulled into Ollama.
- macOS for development or Windows Server 2022 for deployment.

Ollama must remain local to the application:

```text
http://127.0.0.1:11434
```

Do not expose Ollama's port to the LAN. Expose only the application port.

## Development setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[test]'
cp .env.example .env
```

Set a real `APP_SECRET_KEY` and the model you want to test in `.env`.

Start Ollama and pull a model, for example:

```bash
ollama pull llama3.3
```

You can provision accounts either from `.env` or with the CLI. For automatic
startup provisioning, add these values to `.env`:

```text
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong-admin-password>
USER_USERNAME=user
USER_PASSWORD=<strong-user-password>
```

Each configured account is created only if that username does not already exist;
restarting the application never overwrites an existing password. Passwords must
be at least 10 characters. Do not commit `.env`.

Alternatively, create the first administrator manually:

```bash
python -m scripts.create_user --username admin --admin
```

Start the website:

```bash
python -m scripts.start_server
```

Open http://127.0.0.1:8080.

## LAN deployment

On Windows Server, set these environment values before starting:

```text
APP_SECRET_KEY=<long-random-secret>
LOCAL_LLM_DATA_DIR=D:\LocalLLM\data
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=<benchmarked-model-tag>
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

## Testing

```bash
pytest
```

The tests do not require a running Ollama server. Live model benchmarking is a
separate step and should be run on the target Windows GPU with the exact model
tags being considered.
