from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit

from runtime_paths import runtime_path

ROOT = Path(__file__).resolve().parents[1]
_CREDENTIAL_NAME = re.compile(
    r"(?:^|_)(?:API_KEY|PASSWORD|AUTHORIZATION_CODE|TOKEN)(?:_|$)",
    re.IGNORECASE,
)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def credential_values(values: dict[str, str]) -> list[str]:
    return [
        value
        for key, value in values.items()
        if value and _CREDENTIAL_NAME.search(key)
    ]


def endpoint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def sanitize(value: object, secrets: list[str]) -> str:
    text = str(value)
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    text = re.sub(
        r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+",
        r"\1[redacted]",
        text,
    )
    text = re.sub(
        r"(?i)((?:api[_ -]?key|token|password)\s*[:=]\s*)[^\s,;]+",
        r"\1[redacted]",
        text,
    )
    return text[:500]


@dataclass(frozen=True)
class ProbeTarget:
    provider_id: str
    provider_group: str
    model: str
    base_url: str
    key_slot: str
    api_key: str


@dataclass(frozen=True)
class ProbeResult:
    provider_id: str
    provider_group: str
    model: str
    base_url: str
    key_slot: str
    ok: bool
    status: int | None
    latency_ms: int
    error_type: str
    detail: str


def build_targets(env: dict[str, str]) -> list[ProbeTarget]:
    raw_registry = env.get("BOT_MODEL_REGISTRY", "{}").strip() or "{}"
    registry = json.loads(raw_registry)
    if not isinstance(registry, dict):
        raise TypeError("BOT_MODEL_REGISTRY must be a JSON object")
    targets: list[ProbeTarget] = []
    ordered = sorted(
        registry.items(),
        key=lambda pair: (int(pair[1].get("priority", 100)), pair[0])
        if isinstance(pair[1], dict)
        else (100, pair[0]),
    )
    for provider_id, item in ordered:
        if not isinstance(item, dict):
            continue
        key_ref = str(item.get("api_key", ""))
        key_name = key_ref.removeprefix("env:").strip() if key_ref.startswith("env:") else "inline"
        api_key = env.get(key_name, "") if key_name != "inline" else key_ref
        base_url = str(item.get("base_url", "")).strip()
        targets.append(
            ProbeTarget(
                provider_id=str(provider_id),
                provider_group=urlsplit(base_url).hostname or base_url,
                model=str(item.get("model", "")).strip(),
                base_url=base_url,
                key_slot=key_name,
                api_key=api_key,
            )
        )

    return targets


def probe_target(
    target: ProbeTarget,
    *,
    opener: Any,
    secrets: list[str],
    timeout: float,
    max_tokens: int,
) -> ProbeResult:
    if not target.api_key:
        return ProbeResult(
            provider_id=target.provider_id,
            provider_group=target.provider_group,
            model=target.model,
            base_url=target.base_url,
            key_slot=target.key_slot,
            ok=False,
            status=None,
            latency_ms=0,
            error_type="config_missing",
            detail="api key is not configured",
        )
    started = time.perf_counter()
    body = json.dumps(
        {
            "model": target.model,
            "messages": [{"role": "user", "content": "Reply exactly: OK"}],
            "temperature": 0,
            "max_tokens": max(1, int(max_tokens)),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = request.Request(
        endpoint(target.base_url),
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {target.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 provider-health-probe/1.0",
        },
    )
    status: int | None = None
    try:
        with opener.open(req, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read(1024 * 1024).decode("utf-8", errors="replace")
        data = json.loads(raw)
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ValueError("response missing choices[0]")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ValueError("response missing choices[0].message")  # noqa: TRY004
        if not any(
            [
                str(message.get("content") or "").strip(),
                str(message.get("reasoning_content") or "").strip(),
                message.get("tool_calls"),
            ]
        ):
            raise ValueError("response message contains no content")
        ok = True
        error_type = ""
        detail = "response_schema_ok"
    except error.HTTPError as exc:
        status = exc.code
        try:
            detail = exc.read(8192).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - malformed provider error bodies are optional.
            detail = str(exc.reason)
        ok = False
        error_type = f"http_{exc.code}"
    except error.URLError as exc:
        detail = str(exc.reason)
        ok = False
        error_type = "network"
    except TimeoutError as exc:
        detail = str(exc)
        ok = False
        error_type = "timeout"
    except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
        detail = str(exc)
        ok = False
        error_type = "schema"
    except Exception as exc:  # noqa: BLE001 - diagnostics classify heterogeneous SDK/transport failures.
        detail = f"{type(exc).__name__}: {exc}"
        ok = False
        error_type = "provider_error"
    return ProbeResult(
        provider_id=target.provider_id,
        provider_group=target.provider_group,
        model=target.model,
        base_url=target.base_url,
        key_slot=target.key_slot,
        ok=ok,
        status=status,
        latency_ms=int((time.perf_counter() - started) * 1000),
        error_type=error_type,
        detail=sanitize(detail, secrets),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe every configured LLM model once without deleting configuration."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output", default=str(runtime_path("data/provider_probe_latest.json")))
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--max-tokens", type=int, default=32)
    args = parser.parse_args(argv)

    env = load_env(Path(args.env_file))
    secrets = credential_values(env)
    proxy = env.get("BOT_DOWNLOAD_PROXY", "").strip()
    handlers: list[Any] = []
    if proxy:
        handlers.append(request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = request.build_opener(*handlers)
    targets = build_targets(env)
    results = [
        probe_target(
            target,
            opener=opener,
            secrets=secrets,
            timeout=max(1.0, args.timeout),
            max_tokens=max(1, args.max_tokens),
        )
        for target in targets
    ]
    payload = {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "request_policy": {
            "prompt": "fixed health probe",
            "max_tokens": max(1, args.max_tokens),
            "one_request_per_model_and_key": True,
            "deletes_configuration": False,
        },
        "results": [asdict(item) for item in results],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in results:
        mark = "PASS" if item.ok else "FAIL"
        status = item.status if item.status is not None else "-"
        print(
            f"{mark:4} {item.provider_id:42} model={item.model:30} "
            f"status={status!s:3} latency={item.latency_ms:5}ms "
            f"error={item.error_type or '-'} detail={item.detail}"
        )
    print(f"REPORT={output.resolve()}")
    return 1 if any(not item.ok for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
