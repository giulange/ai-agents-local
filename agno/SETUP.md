# Agno — Setup ambiente VM

Documento riproducibile dell'ambiente installato sulla VM CentOS 7.
Aggiornare questa sezione ogni volta che si aggiunge un nuovo componente.

**VM:** CentOS Linux 7 (Core)  
**Utente:** `giuliano.langella` (gruppo `wheel`, NOPASSWD configurato)  
**Data setup iniziale:** 2026-05-12

---

## 0. Prerequisiti sudo

Abilitare sudo senza password per l'utente corrente (richiede accesso root iniziale):

```bash
sudo visudo
# Aggiungere in fondo:
# giuliano.langella ALL=(ALL) NOPASSWD: ALL
```

---

## 1. Aggiornamento sistema

> CentOS 7 usa `yum`, non `dnf`.
> I pacchetti nvidia vengono esclusi perché firmati con una chiave GPG non presente.

```bash
sudo yum update -y --exclude=nvidia* --exclude=libnvidia* --exclude=cuda*
```

---

## 2. Dipendenze di sistema

```bash
# Pacchetti già presenti su questa VM (verificare con --version prima di installare)
# git-1.8.3.1, python3-3.6.8, python3-pip-9.0.3, curl-7.29.0
sudo yum install -y git python3 python3-pip curl

# Dipendenze per compilare Python 3.12 da sorgente (via pyenv)
sudo yum install -y \
    gcc gcc-c++ make \
    zlib-devel bzip2 bzip2-devel \
    readline-devel sqlite sqlite-devel \
    openssl-devel tk-devel libffi-devel xz-devel

# OpenSSL 1.1.1 — necessario per Python 3.12 (CentOS 7 ha OpenSSL 1.0.2, troppo vecchio)
sudo yum install -y openssl11 openssl11-devel

# zstd — richiesto dall'installer di Ollama nativo (non usato, ma installato)
sudo yum install -y zstd
```

---

## 3. Git — configurazione e SSH

```bash
# Configurazione identità
git config --global user.name "giulange"
git config --global user.email "gyuliano@libero.it"

# Generazione chiave SSH (ED25519)
ssh-keygen -t ed25519 -C "giuliano.langella@vm-engineering-copilot" \
    -f ~/.ssh/id_ed25519 -N ""

# Mostrare la chiave pubblica da aggiungere su GitHub
cat ~/.ssh/id_ed25519.pub
```

> Aggiungere la chiave su **GitHub → Settings → SSH and GPG keys → New SSH key**  
> Titolo suggerito: `VM Engineering Copilot`

```bash
# Aggiornare known_hosts e verificare autenticazione
ssh-keygen -R github.com
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts
ssh -T git@github.com   # atteso: "Hi giulange! You've successfully authenticated"
```

---

## 4. Struttura cartelle e repository

```bash
# Cartella radice per tutti i repo
mkdir -p ~/git

# Clonare il repo principale
cd ~/git
git clone git@github.com:giulange/ai-agents-local.git

# Creare struttura agno/ e spostarsi sul branch di sviluppo
cd ~/git/ai-agents-local
git checkout -b feature/agno-setup

mkdir -p agno/{config,agents,knowledge,logs,state,workflows,docker,scripts}
touch agno/README.md agno/requirements.txt agno/.env.example
touch agno/agents/.gitkeep agno/config/.gitkeep agno/knowledge/.gitkeep \
      agno/logs/.gitkeep agno/state/.gitkeep agno/workflows/.gitkeep
```

---

## 5. Python 3.12 via pyenv

> Python 3.6 (default CentOS 7) non supporta `agno` (richiede 3.10+).
> OpenSSL 1.1.1 deve essere installato prima (sezione 2) altrimenti la compilazione fallisce.

```bash
# Installare pyenv
curl https://pyenv.run | bash

# Aggiungere pyenv al profilo shell (aggiunto in ~/.bashrc)
cat >> ~/.bashrc << 'EOF'

# pyenv
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - bash)"
EOF

# Caricare pyenv nella sessione corrente
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - bash)"

# Compilare Python 3.12.9 contro OpenSSL 1.1.1
CPPFLAGS="-I/usr/include/openssl11" \
LDFLAGS="-L/usr/lib64/openssl11 -Wl,-rpath,/usr/lib64/openssl11" \
pyenv install 3.12.9

# Impostare come versione globale
pyenv global 3.12.9

# Verifica
python --version          # Python 3.12.9
python -c "import ssl; print(ssl.OPENSSL_VERSION)"  # OpenSSL 1.1.1k
```

---

## 6. Virtualenv e dipendenze Python

```bash
cd ~/git/ai-agents-local/agno

# Creare virtualenv con Python 3.12
python -m venv .venv

# Installare dipendenze
.venv/bin/pip install agno anthropic ollama
```

Il file `requirements.txt` corrente:

```
agno
anthropic
ollama
```

Attivazione ambiente:

```bash
# Da ~/git/ai-agents-local/agno/
source scripts/activate.sh

# Oppure direttamente:
source ~/git/ai-agents-local/agno/.venv/bin/activate
```

---

## 7. Ollama via Docker

> Ollama nativo non funziona su CentOS 7: richiede GLIBC 2.27+, disponibile solo da CentOS 8.  
> Le GPU presenti (2x Tesla C2075, Compute Capability 2.0) non sono supportate da Ollama moderno (richiede CC 5.0+).  
> Ollama gira in **CPU-only mode** via Docker.

```bash
# Creare il volume persistente per i modelli (operazione una tantum)
docker volume create ollama_models

# Avviare il container (oppure usare lo script docker/up.sh)
bash ~/git/ai-agents-local/agno/docker/up.sh

# Verificare che il servizio risponda
curl -s http://localhost:11434/api/tags
```

Il container è configurato con `restart: unless-stopped` e si riavvia automaticamente al boot di Docker.

Gestione:

```bash
# Avvio
bash ~/git/ai-agents-local/agno/docker/up.sh

# Stop
bash ~/git/ai-agents-local/agno/docker/down.sh
```

---

## 8. Modelli Ollama

```bash
# Scaricare i modelli (richiede container Ollama attivo)
docker exec ollama ollama pull nomic-embed-text   # ~274 MB — embedding
docker exec ollama ollama pull qwen2.5:7b          # ~4.7 GB — LLM principale

# Verificare i modelli installati
docker exec ollama ollama list
```

---

## 9. Clonazione repository AgriMetSupport

Tutti i repo vengono clonati in `~/git/` con `--no-single-branch` per includere tutti i branch remoti.

```bash
cd ~/git

git clone --no-single-branch git@github.com:giulange/ETL_WeatherProg.git
git clone --no-single-branch git@github.com:giulange/PYDBAPI.git
git clone --no-single-branch git@github.com:giulange/agrimetsupport_cps.git
git clone --no-single-branch git@github.com:giulange/ams-keycloak.git
git clone --no-single-branch git@github.com:giulange/ams-meteo-mobile-app.git
git clone --no-single-branch git@github.com:giulange/MapStore2-C035.git
git clone --no-single-branch git@github.com:giulange/irrigation-eye.git
git clone --no-single-branch git@github.com:giulange/weatherprog.git
```

Verificare che tutti i branch remoti siano tracciati:

```bash
for repo in ETL_WeatherProg PYDBAPI agrimetsupport_cps ams-keycloak \
            ams-meteo-mobile-app MapStore2-C035 irrigation-eye weatherprog; do
    echo "=== $repo ==="
    (cd ~/git/$repo && git fetch --all && echo "  branch remoti: $(git branch -r | wc -l)")
done
```

Branch remoti confermati al momento del clone:

| Repository            | Branch remoti |
|-----------------------|:-------------:|
| ETL_WeatherProg       | 4             |
| PYDBAPI               | 3             |
| agrimetsupport_cps    | 4             |
| ams-keycloak          | 2             |
| ams-meteo-mobile-app  | 3             |
| MapStore2-C035        | 3             |
| irrigation-eye        | 21            |
| weatherprog           | 13            |

> Nota: git 1.8.3.1 (CentOS 7) non supporta `git -C <path>`. Usare subshell `(cd <path> && git ...)`.

---

## 10. Verifica ambiente (smoke test)

Il test verifica l'intera catena: agno → Ollama container → modello `qwen2.5:7b`.

### Dipendenza aggiuntiva

Il modello Ollama di agno richiede il pacchetto `openai` (usato internamente):

```bash
.venv/bin/pip install openai
```

Aggiornare anche `requirements.txt`:

```
agno
anthropic
ollama
openai
```

### Esecuzione

```bash
# Da ~/git/ai-agents-local/
source agno/scripts/activate.sh
python agno/tests/test_smoke.py
```

### Output atteso

```
Modello : qwen2.5:7b
Prompt  : Dimmi ciao
----------------------------------------
Risposta: Ciao! Come posso aiutarti oggi?
----------------------------------------
SMOKE TEST PASSATO
```

### Esito

| Data       | Modello      | Prompt        | Risposta                        | Esito  |
|------------|--------------|---------------|---------------------------------|--------|
| 2026-05-12 | qwen2.5:7b   | Dimmi ciao    | Ciao! Come posso aiutarti oggi? | PASS   |

---

## 11. Fondazione da agents-ai

Porting e adattamento dei servizi core da `~/git/agents-ai` al nuovo sistema multi-agente.

### Repo di origine

```bash
cd ~/git
git clone --no-single-branch git@github.com:giulange/agents-ai.git
```

### File creati in `agno/`

| File | Origine | Modifiche principali |
|---|---|---|
| `config.py` | `agents-ai/src/agents_ai/config.py` | Rimosso OpenAI come primario; aggiunti `OLLAMA_*`, `ANTHROPIC_API_KEY`, `REPOS_BASE_DIR`; OpenAI conservato opzionale per audio |
| `agno_service.py` | `agents-ai/src/agents_ai/agno_service.py` | Modello → Ollama qwen2.5:7b; include `AgentInput`/`build_agent_input` (erano in `agent.py`); classe rinominata `ChiefOrchestratorGateway`; step 1: sarà wrappato in `agno.team.Team` |
| `telegram_service.py` | `agents-ai/src/agents_ai/telegram_service.py` | Rimossa dipendenza da `agent.py`; importa da `agno_service`; messaggi adattati in italiano |

> `agent.py` e `main.py` non sono portati: saranno riscritti con l'architettura multi-agente.

### Nota PYTHONPATH

La cartella `agno/` ha lo stesso nome del pacchetto `agno` installato nel venv.
Per evitare conflitti, i moduli usano import assoluti e il loader aggiunge `agno/` al `PYTHONPATH`:

```bash
# Già incluso in scripts/activate.sh
export PYTHONPATH="~/git/ai-agents-local/agno:$PYTHONPATH"
```

### Dipendenze aggiuntive

Rispetto a agents-ai, aggiunte a `requirements.txt`:

```bash
# Wheel precompilata necessaria su CentOS 7 (gcc 4.8 non supporta C++20 per greenlet)
.venv/bin/pip install greenlet --only-binary=:all:

.venv/bin/pip install "python-telegram-bot==21.11.1" "sqlalchemy>=2.0.0,<3.0.0" httpx ddgs
```

### Verifica import

```bash
PYTHONPATH=~/git/ai-agents-local/agno \
.venv/bin/python -c "
from config import load_settings
from agno_service import ChiefOrchestratorGateway, AgentInput, build_agent_input
from telegram_service import TelegramIntakeService
print('config           OK')
print('agno_service     OK')
print('telegram_service OK')
"
```

---

## Verifica finale

```bash
# Git
git --version
ssh -T git@github.com

# Python
python --version
python -c "import agno; import anthropic; import ollama; print('OK')"

# Ollama
curl -s http://localhost:11434/api/tags | python -m json.tool
docker exec ollama ollama list

# Smoke test
python agno/tests/test_smoke.py
```
