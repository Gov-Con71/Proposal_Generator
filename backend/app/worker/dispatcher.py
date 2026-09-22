"""Run with python -m app.worker.dispatcher (no broker required to start)."""
import logging
import signal
from threading import Event
from app.core.logging import configure_logging
from app.services.dispatch_service import dispatch_once


def main():
    configure_logging(service='dispatcher')
    stopped = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            dispatch_once()
        except Exception:
            logging.getLogger(__name__).exception('Dispatcher iteration failed; retrying')
        stopped.wait(2)


if __name__ == '__main__':
    main()
