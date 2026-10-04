#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ENDPOINTS = [
    "/",
    "/translate",
    "/advisor-queue",
    "/estimate-conversion",
    "/management",
    "/manage",
    "/bg",
    "/cases",
    "/api/health",
    "/api/stats",
    "/api/release",
]


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def request_once(url: str, timeout: float = 5.0) -> dict:
    start = time.perf_counter()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(128)
            ms = (time.perf_counter() - start) * 1000
            return {
                "ok": 200 <= resp.status < 400,
                "status": resp.status,
                "latency_ms": round(ms, 2),
                "error": "",
                "sample": body.decode("utf-8", errors="ignore"),
            }
    except urllib.error.HTTPError as exc:
        ms = (time.perf_counter() - start) * 1000
        return {
            "ok": False,
            "status": exc.code,
            "latency_ms": round(ms, 2),
            "error": f"HTTP {exc.code}",
            "sample": "",
        }
    except Exception as exc:  # noqa: BLE001
        ms = (time.perf_counter() - start) * 1000
        return {
            "ok": False,
            "status": None,
            "latency_ms": round(ms, 2),
            "error": str(exc),
            "sample": "",
        }


def summarize(latencies: list[float], failures: int) -> dict:
    if not latencies:
        return {
            "count": 0,
            "failures": failures,
            "min_ms": None,
            "avg_ms": None,
            "p95_ms": None,
            "max_ms": None,
        }
    values = sorted(latencies)
    p95_index = max(0, min(len(values) - 1, int(round(0.95 * (len(values) - 1)))))
    return {
        "count": len(values),
        "failures": failures,
        "min_ms": round(values[0], 2),
        "avg_ms": round(mean(values), 2),
        "p95_ms": round(values[p95_index], 2),
        "max_ms": round(values[-1], 2),
    }


def run_health_check() -> dict:
    cmd = [sys.executable, str(ROOT / "dev_tools" / "autoro_health_check.py")]
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    return {
        "exit_code": p.returncode,
        "ok": p.returncode == 0,
        "stdout": p.stdout,
        "stderr": p.stderr,
    }


def detect_live_endpoints(base_url: str, endpoints: list[str]) -> tuple[list[str], list[dict]]:
    live: list[str] = []
    probe: list[dict] = []
    for ep in endpoints:
        r = request_once(f"{base_url}{ep}")
        probe.append({"endpoint": ep, **r})
        if r["ok"]:
            live.append(ep)
    return live, probe


def main() -> int:
    parser = argparse.ArgumentParser(description="Overnight cycle test for AutoRO user experience")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--iterations", type=int, default=20, help="Requests per endpoint per cycle")
    parser.add_argument("--cycle-minutes", type=float, default=30, help="Minutes between cycle starts")
    parser.add_argument("--duration-hours", type=float, default=8, help="Total run duration")
    parser.add_argument("--output-dir", default=str(ROOT / "runtime" / "logs" / "overnight_tests"))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = output_dir / f"overnight_cycle_{stamp}.jsonl"
    summary_path = output_dir / f"overnight_cycle_{stamp}_summary.md"

    live_endpoints, probe = detect_live_endpoints(args.base_url, DEFAULT_ENDPOINTS)
    endpoints = live_endpoints if live_endpoints else DEFAULT_ENDPOINTS

    started = time.time()
    deadline = started + (args.duration_hours * 3600)
    cycle = 0
    all_cycle_records: list[dict] = []

    print(f"Start: {now_utc()}")
    print(f"Testing endpoints ({len(endpoints)}): {', '.join(endpoints)}")
    print(f"Output JSONL: {jsonl_path}")

    while time.time() < deadline:
        cycle += 1
        cycle_start = time.time()
        cycle_ts = now_utc()

        health = run_health_check()
        endpoint_results: dict[str, dict] = {}

        for ep in endpoints:
            latencies: list[float] = []
            failures = 0
            statuses: dict[str, int] = {}

            for _ in range(args.iterations):
                r = request_once(f"{args.base_url}{ep}")
                key = str(r["status"])
                statuses[key] = statuses.get(key, 0) + 1
                if r["ok"]:
                    latencies.append(r["latency_ms"])
                else:
                    failures += 1

            endpoint_results[ep] = {
                **summarize(latencies, failures),
                "status_counts": statuses,
            }

        record = {
            "cycle": cycle,
            "timestamp_utc": cycle_ts,
            "iterations_per_endpoint": args.iterations,
            "health_check": {
                "ok": health["ok"],
                "exit_code": health["exit_code"],
            },
            "endpoint_results": endpoint_results,
        }
        all_cycle_records.append(record)

        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        failed_eps = [ep for ep, v in endpoint_results.items() if v["failures"] > 0]
        print(
            f"Cycle {cycle} @ {cycle_ts}: health={'PASS' if health['ok'] else 'FAIL'}, "
            f"endpoint_failures={len(failed_eps)}"
        )

        if time.time() >= deadline:
            break

        cycle_interval = args.cycle_minutes * 60
        sleep_seconds = max(0.0, cycle_interval - (time.time() - cycle_start))
        remaining = max(0.0, deadline - time.time())
        time.sleep(min(sleep_seconds, remaining))

    # aggregate summary
    aggregate: dict[str, dict] = {}
    health_fails = 0
    for rec in all_cycle_records:
        if not rec["health_check"]["ok"]:
            health_fails += 1
        for ep, stats in rec["endpoint_results"].items():
            agg = aggregate.setdefault(ep, {"latencies": [], "failures": 0, "requests": 0})
            agg["failures"] += stats["failures"]
            agg["requests"] += args.iterations
            if stats["avg_ms"] is not None:
                agg["latencies"].append(stats["avg_ms"])

    lines = [
        "# Overnight Cycle Test Summary",
        "",
        f"- Started: {dt.datetime.fromtimestamp(started, tz=dt.timezone.utc).isoformat()}",
        f"- Ended: {now_utc()}",
        f"- Cycles: {len(all_cycle_records)}",
        f"- Iterations per endpoint per cycle: {args.iterations}",
        f"- Endpoints tested: {', '.join(endpoints)}",
        f"- Health check failures: {health_fails}/{len(all_cycle_records)}",
        "",
        "## User Experience View",
        "",
        "| Endpoint | Total Requests | Failures | Avg Response (ms) |",
        "|---|---:|---:|---:|",
    ]

    for ep in endpoints:
        agg = aggregate.get(ep, {"latencies": [], "failures": 0, "requests": 0})
        avg = round(mean(agg["latencies"]), 2) if agg["latencies"] else None
        lines.append(f"| {ep} | {agg['requests']} | {agg['failures']} | {avg if avg is not None else '-'} |")

    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Done: {now_utc()}")
    print(f"Summary: {summary_path}")
    print(f"Raw cycles: {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
