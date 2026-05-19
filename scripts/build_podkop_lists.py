#!/usr/bin/env python3
from __future__ import annotations

import json
import ipaddress
import os
import re
import ssl
import sys
import time
from argparse import ArgumentParser
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

try:
    import certifi
except ImportError:  # pragma: no cover - optional dependency
    certifi = None


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "sources.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "src"
DEFAULT_TIMEOUT = 30
DEFAULT_FETCH_RETRIES = 3
USER_AGENT = "podkop-list-updater/1.0"
VALID_KINDS = {"domain", "subnet"}
VALID_DISCOVERY_PROVIDERS = {"crtsh", "certspotter", "urlscan", "wayback"}
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])$"
)


class BuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class OutputConfig:
    name: str
    kind: str
    remote_sources: tuple[str, ...]
    local_sources: tuple[Path, ...]
    remote_source_groups: tuple["RemoteSourceGroup", ...] = ()
    discovery: tuple["DiscoveryConfig", ...] = ()


@dataclass(frozen=True)
class RemoteSourceGroup:
    name: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryConfig:
    provider: str
    roots: tuple[str, ...]
    roots_files: tuple[Path, ...]
    limit_per_root: int = 200
    timeout_per_root: int = 8


@dataclass(frozen=True)
class DiscoveryReportItem:
    provider: str
    roots: tuple[str, ...]
    added_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class BuildResult:
    values: tuple[str, ...]
    remote_count: int
    local_count: int
    discovered_count: int
    discovery: tuple[DiscoveryReportItem, ...]


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description="Build Podkop remote domain lists.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    output_dir = args.output_dir.resolve()

    outputs = load_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "outputs": [],
    }

    for output in outputs:
        result = build_output_with_details(output, timeout=args.timeout)
        write_output_files(output_dir, output.name, list(result.values), output.kind)
        manifest["outputs"].append(
            {
                "name": output.name,
                "kind": output.kind,
                "domain_count": len(result.values),
                "remote_count": result.remote_count,
                "local_count": result.local_count,
                "discovered_count": result.discovered_count,
                "remote_sources": list(output.remote_sources),
                "local_sources": [str(path.relative_to(PROJECT_ROOT)) for path in output.local_sources],
                "discovery": [
                    {
                        "provider": item.provider,
                        "roots": list(item.roots),
                        "added_count": item.added_count,
                        "warnings": list(item.warnings),
                    }
                    for item in result.discovery
                ],
            }
        )

    write_json(output_dir / "manifest.json", manifest)
    return 0


def load_config(config_path: Path) -> list[OutputConfig]:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BuildError(f"Config file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise BuildError(f"Invalid JSON in {config_path}: {exc}") from exc

    outputs_data = data.get("outputs")
    if not isinstance(outputs_data, list) or not outputs_data:
        raise BuildError("Config must contain a non-empty 'outputs' array.")

    outputs: list[OutputConfig] = []
    for item in outputs_data:
        if not isinstance(item, dict):
            raise BuildError("Each item in 'outputs' must be an object.")

        name = item.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", name):
            raise BuildError(f"Invalid output name: {name!r}")

        kind = item.get("kind", "domain")
        if kind not in VALID_KINDS:
            raise BuildError(f"Invalid output kind for {name}: {kind!r}")

        remote_sources = ensure_string_list(item.get("remote_sources"), "remote_sources")
        remote_source_groups = load_remote_source_groups(item.get("remote_source_groups", []), name=name)
        local_source_strings = ensure_string_list(item.get("local_sources", []), "local_sources")
        local_sources = tuple((PROJECT_ROOT / source).resolve() for source in local_source_strings)
        discovery = load_discovery_configs(item.get("discovery", []), name=name, kind=kind)

        outputs.append(
            OutputConfig(
                name=name,
                kind=kind,
                remote_sources=tuple(remote_sources),
                remote_source_groups=tuple(remote_source_groups),
                local_sources=local_sources,
                discovery=tuple(discovery),
            )
        )

    return outputs


def load_remote_source_groups(value: object, *, name: str) -> list[RemoteSourceGroup]:
    if not isinstance(value, list):
        raise BuildError(f"'remote_source_groups' for {name} must be an array.")

    groups: list[RemoteSourceGroup] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise BuildError(f"Each remote source group for {name} must be an object.")
        group_name = item.get("name", f"group-{index}")
        if not isinstance(group_name, str) or not group_name.strip():
            raise BuildError(f"Invalid remote source group name for {name}: {group_name!r}")
        sources = ensure_string_list(item.get("sources", []), "sources")
        if not sources:
            raise BuildError(f"Remote source group {group_name!r} for {name} must include at least one source.")
        groups.append(RemoteSourceGroup(name=group_name.strip(), sources=tuple(sources)))
    return groups


def load_discovery_configs(value: object, *, name: str, kind: str) -> list[DiscoveryConfig]:
    if not isinstance(value, list):
        raise BuildError(f"'discovery' for {name} must be an array.")
    if kind != "domain" and value:
        raise BuildError(f"Discovery is only supported for domain outputs: {name}")

    configs: list[DiscoveryConfig] = []
    for item in value:
        if not isinstance(item, dict):
            raise BuildError(f"Each discovery item for {name} must be an object.")
        provider = item.get("provider")
        if provider not in VALID_DISCOVERY_PROVIDERS:
            raise BuildError(f"Unsupported discovery provider for {name}: {provider!r}")
        roots = tuple(ensure_string_list(item.get("roots", []), "roots"))
        roots_file_strings = ensure_string_list(item.get("roots_files", []), "roots_files")
        roots_files = tuple((PROJECT_ROOT / source).resolve() for source in roots_file_strings)
        limit_per_root = item.get("limit_per_root", 200)
        if not isinstance(limit_per_root, int) or limit_per_root < 1 or limit_per_root > 2000:
            raise BuildError(f"Invalid limit_per_root for {name}: {limit_per_root!r}")
        timeout_per_root = item.get("timeout_per_root", 8)
        if not isinstance(timeout_per_root, int) or timeout_per_root < 1 or timeout_per_root > 60:
            raise BuildError(f"Invalid timeout_per_root for {name}: {timeout_per_root!r}")
        configs.append(
            DiscoveryConfig(
                provider=provider,
                roots=roots,
                roots_files=roots_files,
                limit_per_root=limit_per_root,
                timeout_per_root=timeout_per_root,
            )
        )
    return configs


def ensure_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise BuildError(f"'{field_name}' must be an array.")

    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BuildError(f"'{field_name}' must contain only non-empty strings.")
        result.append(item.strip())
    return result


def build_output(config: OutputConfig, timeout: int) -> list[str]:
    return list(build_output_with_details(config, timeout=timeout).values)


def build_output_with_details(config: OutputConfig, timeout: int) -> BuildResult:
    values: set[str] = set()
    remote_values: set[str] = set()
    local_values: set[str] = set()
    discovery_reports: list[DiscoveryReportItem] = []

    for source in config.remote_sources:
        extracted = fetch_source_values(source, kind=config.kind, timeout=timeout)
        values.update(extracted)
        remote_values.update(extracted)

    for source_group in config.remote_source_groups:
        extracted = fetch_source_group_values(source_group, kind=config.kind, timeout=timeout)
        values.update(extracted)
        remote_values.update(extracted)

    for local_path in config.local_sources:
        if not local_path.is_file():
            raise BuildError(f"Local source not found: {local_path}")
        extracted = extract_values(local_path.read_text(encoding="utf-8"), str(local_path), config.kind)
        values.update(extracted)
        local_values.update(extracted)

    if config.kind == "domain":
        for discovery in config.discovery:
            discovered_values, warnings = discover_domains(discovery, timeout=timeout)
            added_values = discovered_values - values
            values.update(discovered_values)
            discovery_reports.append(
                DiscoveryReportItem(
                    provider=discovery.provider,
                    roots=tuple(sorted(load_discovery_roots(discovery))),
                    added_count=len(added_values),
                    warnings=tuple(warnings),
                )
            )

    discovered_count = sum(item.added_count for item in discovery_reports)
    return BuildResult(
        values=tuple(sorted(values)),
        remote_count=len(remote_values),
        local_count=len(local_values),
        discovered_count=discovered_count,
        discovery=tuple(discovery_reports),
    )


def fetch_source_values(source: str, *, kind: str, timeout: int) -> set[str]:
    text = fetch_remote_text(source, timeout=timeout)
    return extract_values(text, source, kind)


def fetch_source_group_values(source_group: RemoteSourceGroup, *, kind: str, timeout: int) -> set[str]:
    errors: list[str] = []
    for source in source_group.sources:
        try:
            return fetch_source_values(source, kind=kind, timeout=timeout)
        except BuildError as exc:
            errors.append(f"{source}: {exc}")
    raise BuildError(f"All sources failed in fallback group {source_group.name}: {'; '.join(errors)}")


def discover_domains(config: DiscoveryConfig, timeout: int) -> tuple[set[str], list[str]]:
    roots = load_discovery_roots(config)
    discovered: set[str] = set()
    warnings: list[str] = []
    for root in roots:
        if config.provider == "crtsh":
            domains, root_warnings = fetch_crtsh_domains(root, timeout=min(timeout, config.timeout_per_root), limit=config.limit_per_root)
            discovered.update(domains)
            warnings.extend(root_warnings)
        elif config.provider == "certspotter":
            domains, root_warnings = fetch_certspotter_domains(root, timeout=min(timeout, config.timeout_per_root), limit=config.limit_per_root)
            discovered.update(domains)
            warnings.extend(root_warnings)
        elif config.provider == "urlscan":
            domains, root_warnings = fetch_urlscan_domains(root, timeout=min(timeout, config.timeout_per_root), limit=config.limit_per_root)
            discovered.update(domains)
            warnings.extend(root_warnings)
        elif config.provider == "wayback":
            domains, root_warnings = fetch_wayback_domains(root, timeout=min(timeout, config.timeout_per_root), limit=config.limit_per_root)
            discovered.update(domains)
            warnings.extend(root_warnings)
    return discovered, warnings


def load_discovery_roots(config: DiscoveryConfig) -> set[str]:
    roots: set[str] = set()
    for root in config.roots:
        normalized = normalize_domain(root)
        if normalized:
            roots.add(normalized)

    for roots_file in config.roots_files:
        if not roots_file.is_file():
            raise BuildError(f"Discovery roots file not found: {roots_file}")
        for domain in extract_values_from_text(roots_file.read_text(encoding="utf-8"), str(roots_file), "domain"):
            roots.add(domain)

    return roots


def fetch_crtsh_domains(root: str, timeout: int, limit: int) -> tuple[set[str], list[str]]:
    url = f"https://crt.sh/?q={quote(f'%.{root}')}&output=json"
    try:
        text = fetch_remote_text(url, timeout=timeout, retries=1)
    except BuildError as exc:
        warning = f"discovery skipped for {root}: {exc}"
        print(f"WARN: {warning}", file=sys.stderr)
        return set(), [warning]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BuildError(f"Invalid crt.sh response for {root}: {exc}") from exc

    domains: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        for field in ("name_value", "common_name"):
            value = item.get(field)
            if not isinstance(value, str):
                continue
            for line in value.splitlines():
                normalized = normalize_domain(line)
                if not normalized:
                    continue
                if normalized != root and normalized.endswith(f".{root}"):
                    domains.add(normalized)
        if len(domains) >= limit:
            break
    return domains, []


def fetch_certspotter_domains(root: str, timeout: int, limit: int) -> tuple[set[str], list[str]]:
    base_url = "https://api.certspotter.com/v1/issuances"
    after: str | None = None
    domains: set[str] = set()
    warnings: list[str] = []

    while len(domains) < limit:
        params = [
            f"domain={quote(root)}",
            "include_subdomains=true",
            "expand=dns_names",
        ]
        if after:
            params.append(f"after={quote(after)}")
        url = f"{base_url}?{'&'.join(params)}"

        try:
            text = fetch_remote_text(url, timeout=timeout, retries=1)
        except BuildError as exc:
            warning = f"discovery skipped for {root}: {exc}"
            print(f"WARN: {warning}", file=sys.stderr)
            warnings.append(warning)
            return domains, warnings

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BuildError(f"Invalid Cert Spotter response for {root}: {exc}") from exc

        if not isinstance(payload, list) or not payload:
            break

        last_id: str | None = None
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if item_id is not None:
                last_id = str(item_id)
            dns_names = item.get("dns_names", [])
            if not isinstance(dns_names, list):
                continue
            for name in dns_names:
                if not isinstance(name, str):
                    continue
                normalized = normalize_domain(name)
                if not normalized:
                    continue
                if normalized != root and normalized.endswith(f".{root}"):
                    domains.add(normalized)
                    if len(domains) >= limit:
                        return domains, warnings

        if not last_id:
            break
        after = last_id

    return domains, warnings


def fetch_urlscan_domains(root: str, timeout: int, limit: int) -> tuple[set[str], list[str]]:
    domains: set[str] = set()
    search_after: str | None = None

    while len(domains) < limit:
        page_size = min(100, limit - len(domains))
        url = f"https://urlscan.io/api/v1/search/?q=page.apexDomain:{quote(root)}&size={page_size}"
        if search_after:
            url = f"{url}&search_after={quote(search_after)}"

        try:
            text = fetch_remote_text(url, timeout=timeout, retries=1)
        except BuildError as exc:
            warning = f"discovery skipped for {root}: {exc}"
            print(f"WARN: {warning}", file=sys.stderr)
            return domains, [warning]

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BuildError(f"Invalid urlscan response for {root}: {exc}") from exc

        results = payload.get("results", [])
        if not isinstance(results, list) or not results:
            break

        for item in results:
            if not isinstance(item, dict):
                continue
            page = item.get("page", {})
            if not isinstance(page, dict):
                continue
            candidate = page.get("domain")
            if not isinstance(candidate, str):
                continue
            normalized = normalize_domain(candidate)
            if not normalized:
                continue
            if normalized != root and normalized.endswith(f".{root}"):
                domains.add(normalized)
                if len(domains) >= limit:
                    return domains, []

        if limit <= 100 or not payload.get("has_more"):
            break
        last_result = results[-1]
        if not isinstance(last_result, dict):
            break
        sort_values = last_result.get("sort")
        if not isinstance(sort_values, list) or not sort_values:
            break
        search_after = ",".join(str(value) for value in sort_values)

    return domains, []


def fetch_wayback_domains(root: str, timeout: int, limit: int) -> tuple[set[str], list[str]]:
    url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url=*.{quote(root)}/*&output=json&fl=original&limit={limit}"
        "&filter=statuscode:200"
    )
    try:
        text = fetch_remote_text(url, timeout=timeout, retries=1)
    except BuildError as exc:
        warning = f"discovery skipped for {root}: {exc}"
        print(f"WARN: {warning}", file=sys.stderr)
        return set(), [warning]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BuildError(f"Invalid Wayback response for {root}: {exc}") from exc

    if not isinstance(payload, list):
        return set(), []

    domains: set[str] = set()
    for row in payload[1:]:
        if not isinstance(row, list) or not row:
            continue
        original = row[0]
        if not isinstance(original, str):
            continue
        parsed = urlparse(original)
        host = parsed.hostname
        if not host:
            continue
        normalized = normalize_domain(host)
        if not normalized:
            continue
        if normalized != root and normalized.endswith(f".{root}"):
            domains.add(normalized)
            if len(domains) >= limit:
                break

    return domains, []


def fetch_remote_text(url: str, timeout: int, retries: int = DEFAULT_FETCH_RETRIES) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise BuildError(f"Unsupported URL scheme for source: {url}")

    headers = {"User-Agent": USER_AGENT}
    if parsed.netloc == "api.certspotter.com":
        token = os.getenv("CERTSPOTTER_API_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    if parsed.netloc == "urlscan.io":
        token = os.getenv("URLSCAN_API_KEY", "").strip()
        if token:
            headers["API-Key"] = token

    request = Request(url, headers=headers)
    ssl_context = build_ssl_context()
    last_error: Exception | None = None
    retries = max(1, retries)
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=timeout, context=ssl_context) as response:
                return response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(min(2 ** (attempt - 1), 4))

    raise BuildError(f"Failed to fetch {url}: {last_error}") from last_error


def build_ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def extract_values(text: str, source_name: str, kind: str) -> set[str]:
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return extract_values_from_json(stripped, source_name, kind)
    return extract_values_from_text(text, source_name, kind)


def extract_values_from_json(text: str, source_name: str, kind: str) -> set[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BuildError(f"Invalid JSON source {source_name}: {exc}") from exc

    rules = payload.get("rules")
    if isinstance(rules, list):
        values: set[str] = set()
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_key = "domain_suffix" if kind == "domain" else "ip_cidr"
            items = rule.get(rule_key, [])
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, str):
                        continue
                    normalized = normalize_value(item, kind)
                    if normalized:
                        values.add(normalized)
        return values

    if kind == "subnet":
        values: set[str] = set()
        result = payload.get("result")
        candidate_lists: list[object] = []
        if isinstance(payload.get("ipv4_cidrs"), list):
            candidate_lists.append(payload.get("ipv4_cidrs"))
        if isinstance(result, dict) and isinstance(result.get("ipv4_cidrs"), list):
            candidate_lists.append(result.get("ipv4_cidrs"))
        for items in candidate_lists:
            for item in items:
                if not isinstance(item, str):
                    continue
                normalized = normalize_value(item, kind)
                if normalized:
                    values.add(normalized)
        if values:
            return values

    raise BuildError(f"JSON source {source_name} has no supported rules for kind {kind}.")


def extract_values_from_text(text: str, source_name: str, kind: str) -> set[str]:
    values: set[str] = set()
    had_meaningful_tokens = False
    for raw_line in text.splitlines():
        tokens = list(tokenize_line(raw_line))
        if tokens:
            had_meaningful_tokens = True
        for token in tokens:
            normalized = normalize_value(token, kind)
            if normalized:
                values.add(normalized)
    if had_meaningful_tokens and not values:
        expected = "domains" if kind == "domain" else "subnets"
        raise BuildError(f"No valid {expected} found in source {source_name}.")
    return values


def tokenize_line(line: str) -> Iterable[str]:
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("//") or cleaned.startswith("#"):
        return ()

    if "//" in cleaned:
        cleaned = cleaned.split("//", 1)[0].strip()
    if "#" in cleaned:
        cleaned = cleaned.split("#", 1)[0].strip()
    if not cleaned:
        return ()

    if cleaned.startswith("DOMAIN-SUFFIX,"):
        cleaned = cleaned.split(",", 1)[1]
    elif cleaned.startswith("full:"):
        cleaned = cleaned.split(":", 1)[1]

    return [part for chunk in cleaned.split(",") for part in chunk.split()]


def normalize_domain(value: str) -> str | None:
    candidate = value.strip().lower().rstrip(".")
    if not candidate:
        return None

    for prefix in ("*.", ".", "domain:"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):]

    if "/" in candidate or ":" in candidate or "_" in candidate:
        return None

    try:
        candidate = candidate.encode("idna").decode("ascii")
    except UnicodeError:
        return None

    if not DOMAIN_RE.fullmatch(candidate):
        return None
    return candidate


def normalize_subnet(value: str) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None

    try:
        if "/" in candidate:
            network = ipaddress.ip_network(candidate, strict=False)
            return str(network)
        address = ipaddress.ip_address(candidate)
        return str(address)
    except ValueError:
        return None


def normalize_value(value: str, kind: str) -> str | None:
    if kind == "domain":
        return normalize_domain(value)
    if kind == "subnet":
        return normalize_subnet(value)
    raise BuildError(f"Unsupported kind: {kind}")


def write_output_files(output_dir: Path, name: str, values: list[str], kind: str) -> None:
    lst_path = output_dir / f"{name}.lst"
    json_path = output_dir / f"{name}.json"

    lst_body = "\n".join(values)
    if lst_body:
        lst_body += "\n"
    lst_path.write_text(lst_body, encoding="utf-8")

    rule_key = "domain_suffix" if kind == "domain" else "ip_cidr"
    ruleset = {
        "version": 3,
        "rules": [{rule_key: values}],
    }
    write_json(json_path, ruleset)


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
