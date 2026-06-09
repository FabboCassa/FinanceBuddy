"""Dev-only orchestration: auto-start/stop the Docker Compose stack with runserver.

Wired into ``manage.py`` so that launching ``python manage.py runserver`` (e.g. the
standard PyCharm "Django" run configuration) brings the full Compose stack up via
``docker compose up -d``, and stops it again with ``docker compose stop`` when the
server process exits.

The Compose ``web`` service is mapped to host port 8001 (see docker-compose.yml), so it
never collides with the local runserver on 8000 — the two coexist. The local runserver
talks to the containers via the localhost ports declared in ``.env`` (db on 5435, redis
on 6379).

Stdlib-only and side-effect-free on import: nothing happens unless ``maybe_autostart_docker``
is called for a ``runserver`` invocation.

Caveat: clean stop relies on Python ``atexit``/signal handlers. PyCharm's "soft kill"
(Ctrl+C / SIGINT) triggers them; a hard kill (TerminateProcess) on Windows may not, in
which case the containers keep running and are reused on the next launch. Enable
"Kill process softly" in the PyCharm run configuration for reliable teardown.
"""
import atexit
import os
import signal
import subprocess
import sys

# Repo root (directory that holds docker-compose.yml) = parent of this package dir.
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COMPOSE = ["docker", "compose"]

_started = False  # guards teardown so we only stop what we started


def _is_runserver(argv):
    return len(argv) > 1 and argv[1] == "runserver"


def _is_reload_child():
    # Django's autoreloader re-execs an inner worker with RUN_MAIN=true; the outer
    # (manager) process owns the container lifecycle so start/stop happen once.
    return os.environ.get("RUN_MAIN") == "true"


def maybe_autostart_docker(argv):
    """Start the Compose stack when launching runserver; register teardown on exit."""
    global _started
    if _is_reload_child() or not _is_runserver(argv):
        return

    print("[docker-boot] Avvio dei container Docker (docker compose up -d)...", flush=True)
    try:
        subprocess.run(_COMPOSE + ["up", "-d"], cwd=_PROJECT_DIR, check=True)
    except FileNotFoundError:
        print(
            "[docker-boot] 'docker' non trovato nel PATH: salto l'avvio dei container. "
            "runserver continua comunque.",
            flush=True,
        )
        return
    except subprocess.CalledProcessError as exc:
        print(
            f"[docker-boot] Avvio container fallito (exit {exc.returncode}). "
            "Docker Desktop è in esecuzione? runserver continua comunque.",
            flush=True,
        )
        return

    _started = True
    _install_teardown()


def _stop_containers(*_args):
    global _started
    if not _started:
        return
    _started = False
    print("\n[docker-boot] Stop dei container Docker (docker compose stop)...", flush=True)
    try:
        subprocess.run(_COMPOSE + ["stop"], cwd=_PROJECT_DIR, check=False)
    except Exception as exc:  # best-effort cleanup; never mask the real exit
        print(f"[docker-boot] Stop container non riuscito: {exc}", flush=True)


def _install_teardown():
    atexit.register(_stop_containers)
    # Also intercept termination signals so an interrupt/stop triggers the same cleanup.
    sigs = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):  # Windows Ctrl+Break / some PyCharm stop modes
        sigs.append(signal.SIGBREAK)
    for sig in sigs:
        try:
            previous = signal.getsignal(sig)

            def handler(signum, frame, _previous=previous):
                _stop_containers()
                if callable(_previous) and _previous not in (signal.SIG_DFL, signal.SIG_IGN):
                    _previous(signum, frame)
                else:
                    raise SystemExit(0)

            signal.signal(sig, handler)
        except (ValueError, OSError):
            # signal.signal fails off the main thread or for unsupported signals; atexit covers it.
            pass
