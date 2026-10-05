"""In-process metrics with a Prometheus text endpoint.

No metrics backend is required to run this service — counters and histograms live in memory
and are exposed at /api/metrics in Prometheus exposition format, which is enough to scrape in
a real deployment and enough to inspect by curl in a demo. Deliberately not a dependency on
prometheus_client: a few counters do not justify one.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock

# Buckets in milliseconds — chosen around the latencies this system actually exhibits
# (sub-100 ms retrieval, 1–20 s LLM round-trips).
LATENCY_BUCKETS = (50, 100, 250, 500, 1000, 2500, 5000, 10000, 20000, 60000)


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[int]] = defaultdict(list)

    def increment(self, name: str, value: int = 1, **labels: str) -> None:
        with self._lock:
            self._counters[(name, self._key(labels))] += value

    def observe(self, name: str, value_ms: float, **labels: str) -> None:
        with self._lock:
            self._histograms[(name, self._key(labels))].append(int(value_ms))

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()

    @staticmethod
    def _key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((k, str(v)) for k, v in labels.items()))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            counters = {
                self._render_name(name, labels): count for (name, labels), count in self._counters.items()
            }
            histograms = {}
            for (name, labels), values in self._histograms.items():
                if not values:
                    continue
                ordered = sorted(values)
                histograms[self._render_name(name, labels)] = {
                    "count": len(ordered),
                    "sum_ms": sum(ordered),
                    "p50_ms": ordered[len(ordered) // 2],
                    "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
                    "max_ms": ordered[-1],
                }
        return {"counters": counters, "histograms": histograms}

    @staticmethod
    def _render_name(name: str, labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return name
        rendered = ",".join(f'{k}="{v}"' for k, v in labels)
        return f"{name}{{{rendered}}}"

    def render_prometheus(self) -> str:
        """Prometheus text exposition format."""
        lines: list[str] = []
        with self._lock:
            seen: set[str] = set()
            for (name, labels), count in sorted(self._counters.items()):
                if name not in seen:
                    lines.append(f"# TYPE {name} counter")
                    seen.add(name)
                lines.append(f"{self._render_name(name, labels)} {count}")

            for (name, labels), values in sorted(self._histograms.items()):
                if not values:
                    continue
                base = f"{name}_ms"
                if base not in seen:
                    lines.append(f"# TYPE {base} histogram")
                    seen.add(base)
                label_pairs = list(labels)
                cumulative = 0
                ordered = sorted(values)
                for bucket in LATENCY_BUCKETS:
                    cumulative = sum(1 for v in ordered if v <= bucket)
                    bucket_labels = (*label_pairs, ("le", str(bucket)))
                    lines.append(f"{self._render_name(base + '_bucket', bucket_labels)} {cumulative}")
                inf_labels = (*label_pairs, ("le", "+Inf"))
                lines.append(f"{self._render_name(base + '_bucket', inf_labels)} {len(ordered)}")
                lines.append(f"{self._render_name(base + '_sum', labels)} {sum(ordered)}")
                lines.append(f"{self._render_name(base + '_count', labels)} {len(ordered)}")

        return "\n".join(lines) + "\n"


metrics = Metrics()
