#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finance_buddy.settings')

    # Dev convenience: starting runserver brings the Docker Compose stack up (and stops
    # it on exit). No-op for any other command. See finance_buddy/docker_boot.py.
    from finance_buddy.docker_boot import maybe_autostart_docker
    maybe_autostart_docker(sys.argv)

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
