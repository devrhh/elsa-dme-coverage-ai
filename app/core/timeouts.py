"""Hard timeout enforcement for blocking, potentially-unsafe operations.

Coverage PDFs are untrusted input: a malformed or adversarial file (e.g. a
decompression bomb, or a pathological table layout) could otherwise make
`pdfplumber` hang or run for a very long time. We run such work in a
separate process and forcibly kill it if it exceeds its time budget, so a
single bad upload can never hang the API server.
"""

import multiprocessing as mp
from typing import Any, Callable


class TimeoutExceededError(Exception):
    pass


def _run_and_send(conn, func: Callable, args: tuple, kwargs: dict) -> None:
    try:
        result = func(*args, **kwargs)
        conn.send(("ok", result))
    except Exception as exc:  # noqa: BLE001 - propagate any failure to the parent
        conn.send(("error", str(exc)))
    finally:
        conn.close()


def run_with_timeout(
    func: Callable,
    args: tuple = (),
    kwargs: dict | None = None,
    timeout_seconds: float = 60,
) -> Any:
    """Run `func(*args, **kwargs)` in a subprocess, killing it if it exceeds
    `timeout_seconds`. Raises TimeoutExceededError on timeout, or re-raises
    the worker's exception message on failure."""

    kwargs = kwargs or {}
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_run_and_send, args=(child_conn, func, args, kwargs))
    process.start()
    child_conn.close()

    try:
        if parent_conn.poll(timeout_seconds):
            status, payload = parent_conn.recv()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
            if status == "error":
                raise RuntimeError(f"Worker failed: {payload}")
            return payload

        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
        raise TimeoutExceededError(f"Operation exceeded {timeout_seconds}s timeout")
    finally:
        parent_conn.close()
