# 🚀 Piano di Deploy & Hardening — FinanceBuddy

> **Stato: PROPOSTA — in attesa di conferma.** Nessuna modifica è ancora stata applicata.
> Redatto il 2026-06-10 dopo audit del repo (compose, settings, cronologia git, log).
>
> Obiettivo: hostare la piattaforma **gratis**, con **rilascio da GitHub**, accessibile
> **solo a Fabio**, con aggiornamento dati automatico 24/7 e **zero segreti in giro**.

---

## 0. TL;DR — decisioni proposte

| Tema | Proposta |
|---|---|
| Dove | **Oracle Cloud "Always Free"** (VM ARM Ampere, fino a 4 core / 24 GB RAM — gratuita per sempre) |
| Accesso solo tuo | **Tailscale** (gratis): l'app NON viene esposta su internet, è raggiungibile solo dai tuoi dispositivi |
| Rilascio | **GitHub Actions**: a ogni push su `main` (o release) → SSH sulla VM → `git pull` → `docker compose up -d --build` |
| Segreti | Solo nel `.env` **sul server** + GitHub Secrets per la chiave SSH del deploy. Mai nel repo (verificato: oggi è già così) |
| Piano B | Se Oracle non ha capacità ARM nella tua region: VPS Hetzner CX22 (~4,5 €/mese) — identico setup, non gratis |

---

## 1. Dove hostare — analisi delle opzioni

Lo stack richiede: 5 container (web ASGI, Postgres, Redis, Celery worker, Celery beat) e
**~3–4 GB di RAM** quando FinBERT è caricato (`USE_REAL_NLP=True`). Questo squalifica
quasi tutti i "free tier" PaaS:

| Opzione | Gratis? | Verdetto |
|---|---|---|
| **Oracle Cloud Always Free (ARM A1)** | ✅ per sempre | **⭐ Scelta consigliata.** 4 OCPU / 24 GB / 200 GB disco: lo stack ci gira largo, Docker Compose identico a ora. PyTorch ha wheel ARM64 → FinBERT ok su CPU ARM. Contro: serve carta per la verifica account; la capacità ARM a volte è esaurita (riprovare o cambiare availability domain); region consigliata: EU (es. Milano/Francoforte) |
| PC/mini-PC a casa + Tailscale | ✅ | Funziona già oggi; ma serve una macchina sempre accesa (consumo, rumore). Buon piano C |
| Render free | ⚠️ | Web "dorme" dopo 15 min, **niente background worker gratuiti** (Celery escluso), Postgres free a scadenza → non adatto |
| Railway / Fly.io | ❌ | Solo crediti di prova, poi a pagamento |
| PythonAnywhere free | ❌ | Niente Docker, niente Celery/Redis |
| Hetzner CX22 (piano B) | ❌ ~4,5 €/m | x86, 4 GB RAM (sufficiente, FinBERT entra appena; CX32 8 GB più comodo). Setup identico |

**Perché Tailscale invece di un login pubblico:** vuoi accesso solo tu → la soluzione più
sicura non è proteggere la porta pubblica, è **non avere una porta pubblica**. Con
Tailscale la VM entra nella tua rete privata (tailnet); dashboard e API sono visibili solo
dai dispositivi loggati col tuo account. Zero codice di autenticazione da scrivere oggi,
superficie d'attacco ≈ 0. (Il login Django multi-utente resta l'evoluzione futura se un
giorno vorrai accesso pubblico — è già annotato come deferred di Fase 5.)

---

## 2. Audit di sicurezza (eseguito 2026-06-10)

### 2.1 Cosa è risultato PULITO ✅

- **`.env` mai committato** in tutta la cronologia git (`git log --all -- .env` → vuoto) ed è in `.gitignore`.
- **Nessun token/chiave reale nella cronologia**: l'unico match per "TELEGRAM_BOT_TOKEN" sono fixture di test (`'tok'`, `'123'`) e default vuoti.
- **Nessuna stringa-segreto nel tree attuale** (scan pattern token Telegram/chiavi su .py/.yml/.md/.html → vuoto).
- `docker-compose.yml` usa interpolazione `${VAR:-default}` → il file committato non contiene credenziali reali.
- `.env.example` contiene solo placeholder.

→ **Il repo può restare su GitHub senza bonifiche della history.** (Consiglio comunque: repo **privato**, costo zero.)

### 2.2 Problemi da sistemare PRIMA del deploy 🔴

| # | Problema | Dove | Severità (su VPS pubblico) |
|---|---|---|---|
| A | **Postgres esposto sull'host** (`5435:5432`) e **Redis esposto** (`6379:6379`) — su una VM con IP pubblico chiunque può connettersi; Redis è senza password e Postgres ha password debole di default | `docker-compose.yml` | 🔴 Critica |
| B | **`runserver` come server di produzione** — è il dev-server Django: single-thread, niente hardening, e per di più i WebSocket richiedono ASGI vero | `docker-compose.yml` (`command:`) | 🔴 Alta |
| C | **`DEBUG` default `True`** — in caso di errore espone stack trace, settings e percorsi | `settings.py` + compose | 🔴 Alta |
| D | **`SECRET_KEY` con fallback insicuro committato** (`django-insecure-…`) — firma sessioni/cookie | `settings.py` + compose | 🔴 Alta |
| E | **`DB_PASSWORD` default `postgres_pwd`** | compose | 🟠 Media (critica se combinata con A) |
| F | **`ALLOWED_HOSTS = ['*']`** hardcoded | `settings.py` | 🟠 Media |
| G | **Nessuna autenticazione applicativa** (dashboard, API DRF e `/admin/` aperti) | app | 🟠 Media — **mitigata dal modello Tailscale** (nessuna esposizione pubblica) |
| H | **Nessuna `restart` policy** — se la VM riavvia, i container restano giù | compose | 🟠 Media |
| I | Backup del DB assenti — lo storico prezzi+news+sentiment è il valore della piattaforma (serve ~1 anno di accumulo per la Fase 4) | — | 🟠 Media |
| J | `CSRF_TRUSTED_ORIGINS` / cookie secure non configurati | `settings.py` | 🟡 Bassa (dietro tailnet) |

---

## 3. Fix proposti (change-set, in ordine)

### 3.1 `docker-compose.yml` — hardening (fix A, B, E, H)

- **Rimuovere** il mapping porte di `db` e `redis` (i container si parlano già sulla rete
  interna di Compose; il mapping serve solo al tuo PyCharm locale → spostarlo in un
  override solo-dev, vedi sotto).
- `web`: comando di produzione **Daphne** (già nei requirements, ASGI già configurato):
  `daphne -b 0.0.0.0 -p 8000 finance_buddy.asgi:application`
- `restart: unless-stopped` su tutti e 5 i servizi.
- Healthcheck su `db` (pg_isready) e `redis` (redis-cli ping) + `depends_on: condition: service_healthy`.
- Struttura proposta: `docker-compose.yml` = produzione sicura;
  **`docker-compose.override.yml` (gitignorato o committato come dev)** = runserver,
  porte 5435/6379 sull'host, DEBUG=True. Docker Compose applica l'override
  automaticamente in locale; sul server si usa `docker compose -f docker-compose.yml up -d`.
  → Lo sviluppo locale resta identico a oggi, zero attrito.

### 3.2 `finance_buddy/settings.py` — default sicuri (fix C, D, F, J)

- `DEBUG = os.environ.get('DEBUG', 'False') == 'True'` → **default False** (il dev override lo rimette True).
- `SECRET_KEY`: **niente fallback** quando `DEBUG=False` → `raise ImproperlyConfigured`
  se mancante. Il fallback dev resta solo con DEBUG=True.
- `ALLOWED_HOSTS` da env (`ALLOWED_HOSTS=fb-vm.tailnet-xyz.ts.net,localhost`), default `localhost,127.0.0.1`.
- `CSRF_TRUSTED_ORIGINS` da env; `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` attivi quando si usa HTTPS (vedi 3.5).
- Aggiornare `.env.example` con le nuove chiavi documentate.

### 3.3 `.env` del server — segreti (fix D, E)

Generati sulla VM, **mai** nel repo né in chat:

```bash
SECRET_KEY  → python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
DB_PASSWORD → openssl rand -base64 24
```

Più: `DEBUG=False`, `USE_REAL_NLP=True`, `ALLOWED_HOSTS=<hostname tailscale>`,
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (ricopiati a mano dal tuo `.env` locale).
⚠️ Nota: cambiare `DB_PASSWORD` vale solo per il **nuovo** volume Postgres della VM
(regola già nota: la password deve combaciare con quella di inizializzazione del volume).

### 3.4 GitHub Actions — rilascio da GitHub

Nuovo file `.github/workflows/deploy.yml`:

- Trigger: `push` su `main` (oppure `release: published`, a tua scelta).
- Step: checkout → `appleboy/ssh-action` → sulla VM: `cd ~/FinanceBuddy && git pull && docker compose -f docker-compose.yml up -d --build && docker system prune -f`.
- **GitHub Secrets** richiesti (Settings → Secrets → Actions): `DEPLOY_HOST` (IP tailscale della VM), `DEPLOY_USER`, `DEPLOY_SSH_KEY` (chiave ed25519 dedicata solo al deploy, creata ad hoc — non la tua personale).
- Nota: per raggiungere la VM via tailnet dalla Action serve un **tailscale ephemeral node** nella Action (azione ufficiale `tailscale/github-action` + auth key effimera in un secret) — incluso nel piano. Alternativa più semplice: aprire SSH (solo porta 22, solo chiave, niente password) sull'IP pubblico della VM e tenere chiuso tutto il resto.

### 3.5 VM Oracle + Tailscale — accesso "solo io" (fix G)

1. Creare VM `VM.Standard.A1.Flex` (4 OCPU / 24 GB), Ubuntu 22.04 ARM64, region EU.
2. Firewall OCI (Security List): **nessuna porta aperta** tranne 22 (e pure quella chiudibile dopo, usando SSH-over-tailscale).
3. `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up` → la VM appare nel tuo tailnet.
4. Installare Docker + Compose plugin, clonare il repo, creare `.env`, `docker compose -f docker-compose.yml up -d --build`.
5. Accesso: `http://fb-vm:8001` **solo** dai tuoi dispositivi con Tailscale attivo (PC, telefono).
6. *(Opzionale, consigliato)* `tailscale serve --bg 8001` → HTTPS automatico con certificato valido (`https://fb-vm.<tailnet>.ts.net`), e a quel punto attivare i cookie secure del punto 3.2. La porta 8001 può allora essere bindata su localhost soltanto.

### 3.6 Backup (fix I)

- Cron giornaliero sulla VM: `docker compose exec -T db pg_dump -U $DB_USER $DB_NAME | gzip > backup/fb_$(date +%F).sql.gz` + rotazione 14 giorni.
- *(Opzionale)* copia off-site settimanale (es. rclone verso un cloud storage gratuito o scp verso il tuo PC via tailnet).
- Il volume `hf_cache` non si backuppa (è solo cache modelli, si riscarica).

### 3.7 Verifica Telegram

Il test di ieri è fallito solo perché **lo stack era spento** (`service "web" is not running`). Procedura corretta:

```bash
docker compose up -d           # prima avvia lo stack
docker compose exec web python manage.py shell -c "from core.alerts import _send_telegram; _send_telegram('Test FinanceBuddy OK')"
```

Da rifare anche sulla VM a fine deploy (stessa coppia token/chat id → ti arriverà sul telefono identico).

### 3.8 Documentazione (regola architecture-sync)

Nello stesso change-set: aggiornare `ARCHITECTURE.md` (§2 runtime Daphne in produzione,
§5 componenti, §7 convenzioni: niente porte DB/Redis esposte in prod, file override per il dev)
e `.env.example`. Eventuale `DEPLOYMENT.md` operativo al posto di questo piano una volta eseguito.

---

## 4. Cosa NON fare (regole permanenti)

- ❌ Mai committare `.env`, dump del DB, o chiavi SSH nel repo (anche se privato).
- ❌ Mai incollare il token Telegram in issue/commit/chat; se dovesse trapelare → rigenerarlo subito con @BotFather (`/revoke`).
- ❌ Non esporre 5432/6379/8001 sull'IP pubblico della VM; il firewall OCI deve restare chiuso.
- ❌ Non usare `docker compose down -v` sul server (cancella il volume Postgres = tutto lo storico).
- ❌ Non riutilizzare la tua chiave SSH personale per la GitHub Action: chiave dedicata, revocabile.

---

## 5. Risposta alla domanda "si aggiorna da sola?"

**Sì, nessun riavvio necessario.** Sul server i container restano su 24/7: Celery beat
lancia da solo prezzi ogni 15 min e news/sentiment/alert/ranking/paper-trading ogni 30 min.
Dopo un'eventuale interruzione, `startup_catch_up` recupera il buco al riavvio (con
`restart: unless-stopped` il riavvio è automatico). Bonus dell'hosting 24/7: spariscono i
buchi di copertura news di yfinance e lo storico per la Fase 4 (gradino 3) matura molto più in fretta.

---

## 6. Checklist esecutiva (dopo la tua conferma)

1. ☑ **FATTO (2026-06-11)** — compose prod-safe (no porte DB/Redis, Daphne, restart, healthcheck, DB_PASSWORD obbligatoria) + `docker-compose.override.yml` dev + collectstatic/WhiteNoise
2. ☑ **FATTO (2026-06-11)** — settings.py hardened (DEBUG default False, SECRET_KEY obbligatoria in prod, ALLOWED_HOSTS/CSRF/SECURE_COOKIES da env, niente default DB password) + `.env.example` aggiornato
3. ☑ **FATTO (2026-06-11)** — 182/182 test OK in locale (hardening + wiki + monitoring + category impact + grid search + earnings)
4. ☑ **FATTO (2026-06-11)** — `.github/workflows/deploy.yml` creato. ☐ Restano a te: repo privato + i 4 GitHub Secrets (`TAILSCALE_AUTHKEY`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`)
5. ☐ Provisioning VM Oracle (o piano B Hetzner) + Tailscale + Docker — insieme
6. ☐ `.env` di produzione generato sulla VM (chiavi nuove) — insieme
7. ☐ Primo deploy + bootstrap + verifica dashboard via tailnet
8. ☐ Test Telegram dal server (§3.7) — ☑ già verificato **in locale** il 2026-06-11: invio reale riuscito, bot + chat id corretti
9. ☐ Cron backup + prova di restore di un dump
10. ☑ **FATTO (2026-06-11)** — ARCHITECTURE.md aggiornato (runtime, struttura, startup, convenzione #9)

**Tempo stimato:** 1–2 ore di lavoro mio sui file (1–2 + 4 + 10) + ~1 ora tua guidata per account Oracle/Tailscale e segreti (5–8), che richiedono mani tue per privacy delle credenziali.

---

## 7. Migliorie pre-pubblicazione aggiunte il 2026-06-11 ✅

Implementate dopo la revisione "c'è altro da fare prima di pubblicare?":

- **Ops server:** `/healthz` (DB+Redis, per uptime monitor esterno) · errori dei task Celery → **Telegram** con cooldown 60 min · **report salute dati settimanale** su Telegram (lun 08:00) · `mem_limit` per container (worker 8g) · `scripts/backup_db.sh` (pg_dump giornaliero, rotazione 14gg, cartella `backup/` gitignorata — punto 9 della checklist: resta solo da installare il cron sulla VM).
- **Analisi:** card **"Quali temi muovono i prezzi"** in home (`/api/category-impact/`) · bottone **"Ottimizza"** nella Strategy Sandbox (grid search con split train/test anti-overfitting, `/api/backtest/optimize/`).
- **Dati:** **calendario earnings** (campo su Asset + task giornaliero a rotazione + badge "Earnings tra Xg"). EDGAR/SEC e Reddit valutati e rimandati con motivazione (vedi ROADMAP Fase 4).
- ⚠️ Nuova **migration 0007**: al prossimo avvio `docker compose up` la applica da solo (entrypoint). Rilanciare poi `manage.py test` per la suite completa.
