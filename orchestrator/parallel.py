"""Run named tasks concurrently; a failed task is reported and left out of the result."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

T = TypeVar("T")


def run_parallel(tasks: dict[str, Callable[[], T]], workers: int) -> dict[str, T]:
    results: dict[str, T] = {}
    if not tasks:
        return results
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(tasks)))) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    return results
