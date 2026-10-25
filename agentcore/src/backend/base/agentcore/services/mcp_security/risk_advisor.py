"""Static rule engine that flags risky MCP server configurations.

Stateless and dependency-free. Public API:

    analyze(payload: dict, mode: str | None) -> RiskAnalysis

`payload` mirrors the shape sent by the Add/Request MCP modal: ``mode``,
``url``, ``command``, ``args``, ``env_vars``, ``headers``. Unknown keys are
ignored. ``mode`` may be passed explicitly or inferred from presence of
``command`` (stdio) vs ``url`` (sse).

Severity ladder: HIGH > MEDIUM > LOW.
Overall verdict:
  - ``high_risk`` if any HIGH finding
  - ``review_carefully`` if any MEDIUM finding
  - ``looks_ok`` otherwise (including all-LOW or no findings)
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlparse


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class Finding:
    category: str
    severity: Severity
    rule_id: str
    title: str
    detail: str
    recommendation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "severity": self.severity.value,
            "rule_id": self.rule_id,
            "title": self.title,
            "detail": self.detail,
            "recommendation": self.recommendation,
        }


@dataclass
class RiskAnalysis:
    findings: list[Finding] = field(default_factory=list)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.MEDIUM)

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.LOW)

    @property
    def overall(self) -> str:
        if self.high_count > 0:
            return "high_risk"
        if self.medium_count > 0:
            return "review_carefully"
        return "looks_ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "findings": [f.to_dict() for f in self.findings],
        }


# --- Rule data ---------------------------------------------------------------

_KNOWN_RUNTIMES = {"npx", "uvx", "node", "python", "python3"}

_DANGEROUS_EXECUTABLES = {
    "bash", "sh", "zsh", "ksh", "fish",
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    "curl", "wget", "nc", "ncat", "netcat",
    "rm", "dd", "eval", "ssh", "scp", "ftp", "tftp",
    "python -c", "perl", "ruby",
}

_TRUSTED_NPM_SCOPES = {
    "@modelcontextprotocol",
    "@drawio",
    "@antv",
    "@anthropic",
    "@cloudflare",
    "@github",
    "@notionhq",
    "@upstash",
    "@browserbase",
    "@stripe",
    "@elastic",
    "@pinecone-database",
}

_DANGEROUS_ENV_KEYS = {
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_FALLBACK_FRAMEWORK_PATH",
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "PYTHONINSPECT",
    "PERL5OPT", "PERL5LIB",
    "PATH",
}

_NODE_OPTIONS_LOADERS = (
    "--require",
    "--import",
    "--experimental-loader",
    "--loader",
    "--inspect-brk",
    "--inspect=",
    "--cpu-prof",
)

_SHELL_METACHARS = set(";|&<>`$()")
_CONTROL_CHARS = {"\x00", "\r", "\n"}

_SENSITIVE_PATHS = {
    "/", "/etc", "/root", "/var", "/boot", "/proc", "/sys", "/home", "~",
    "C:\\", "C:\\Windows", "C:\\Users",
}

_MAX_ARGS = 50
_MAX_ARG_LEN = 1024


# --- Helpers -----------------------------------------------------------------

def _norm_executable(command: str) -> str:
    """Strip path/extension and lowercase: '/usr/bin/Bash' -> 'bash'."""
    cmd = command.strip()
    # Take only the basename
    cmd = cmd.replace("\\", "/").rsplit("/", 1)[-1]
    # Drop common Windows extensions for matching
    lower = cmd.lower()
    for ext in (".exe", ".cmd", ".bat", ".ps1"):
        if lower.endswith(ext):
            lower = lower[: -len(ext)]
            break
    return lower


def _detect_npm_package(args: list[str]) -> str | None:
    """Find the first arg that looks like an npm package spec."""
    for a in args:
        if not a or a.startswith("-"):
            continue
        # Strip version suffix: '@scope/pkg@1.2' -> '@scope/pkg', 'pkg@1.0' -> 'pkg'
        candidate = a
        if candidate.startswith("@"):
            # Scoped: keep first '@', split version on second '@'
            parts = candidate.split("@")
            # parts looks like ['', 'scope/pkg', 'version'?]
            if len(parts) >= 2:
                candidate = "@" + parts[1]
        else:
            candidate = candidate.split("@", 1)[0]
        if "/" in candidate or candidate.startswith("@"):
            return candidate
        # Bare package name (unscoped)
        if candidate and all(c.isalnum() or c in "-_." for c in candidate):
            return candidate
    return None


def _is_private_ip(host: str) -> tuple[bool, str | None]:
    """Return (is_private, resolved_ip). Resolves DNS once."""
    try:
        info = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, None
    for entry in info:
        ip_str = entry[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True, ip_str
    return False, info[0][4][0] if info else None


# --- Rule families -----------------------------------------------------------

def _check_command(command: str | None, findings: list[Finding]) -> str | None:
    """Returns the normalised executable name (or None if empty/missing)."""
    if not command or not command.strip():
        findings.append(Finding(
            category="Command",
            severity=Severity.HIGH,
            rule_id="cmd.empty",
            title="Command is empty",
            detail="STDIO mode requires a command to spawn.",
            recommendation="Provide an executable like `npx`, `uvx`, `node`, or `python`.",
        ))
        return None

    raw = command.strip()
    if " " in raw:
        findings.append(Finding(
            category="Command",
            severity=Severity.MEDIUM,
            rule_id="cmd.contains_space",
            title="Command field contains spaces",
            detail=f"Got `{raw}`. The command field should be a single executable; "
                   "arguments belong in the args list.",
            recommendation="Move everything after the first token into the args list.",
        ))

    exe = _norm_executable(raw)
    if exe in _DANGEROUS_EXECUTABLES:
        findings.append(Finding(
            category="Command",
            severity=Severity.HIGH,
            rule_id="cmd.dangerous_executable",
            title=f"Dangerous executable: {exe}",
            detail=f"`{exe}` is a shell or system utility, not an MCP server runtime. "
                   "Spawning it as the MCP entrypoint is almost always a sign of misuse.",
            recommendation="Use a known MCP runtime such as `npx`, `uvx`, `node`, or `python`.",
        ))
    elif exe in _KNOWN_RUNTIMES:
        findings.append(Finding(
            category="Command",
            severity=Severity.LOW,
            rule_id="cmd.known_runtime",
            title=f"Known MCP runtime: {exe}",
            detail=f"`{exe}` is a recognised runtime for MCP servers.",
            recommendation="No action needed.",
        ))
    else:
        findings.append(Finding(
            category="Command",
            severity=Severity.MEDIUM,
            rule_id="cmd.unknown_executable",
            title=f"Unknown executable: {exe}",
            detail=f"`{exe}` is not in the standard set of MCP runtimes "
                   "(npx, uvx, node, python, python3). Verify it is intentional.",
            recommendation="Confirm the executable is installed in the runtime image and is the intended entrypoint.",
        ))
    return exe


def _check_package(exe: str | None, args: list[str], findings: list[Finding]) -> None:
    if exe != "npx":
        return
    pkg = _detect_npm_package(args)
    if pkg is None:
        findings.append(Finding(
            category="Package",
            severity=Severity.MEDIUM,
            rule_id="pkg.no_package",
            title="`npx` invoked without a detectable package name",
            detail="The args list does not contain anything that looks like an npm package spec.",
            recommendation="Add the npm package as the first non-flag argument (e.g. `@modelcontextprotocol/server-filesystem`).",
        ))
        return
    if pkg.startswith("@"):
        scope = pkg.split("/", 1)[0]
        if scope in _TRUSTED_NPM_SCOPES:
            findings.append(Finding(
                category="Package",
                severity=Severity.LOW,
                rule_id="pkg.trusted_publisher",
                title=f"Trusted npm publisher: {scope}",
                detail=f"`{pkg}` is published under a trusted scope.",
                recommendation="No action needed.",
            ))
        else:
            findings.append(Finding(
                category="Package",
                severity=Severity.MEDIUM,
                rule_id="pkg.unknown_scope",
                title=f"Unknown npm publisher: {scope}",
                detail=f"`{pkg}` is from a publisher not on the trusted list.",
                recommendation=f"Verify {scope} on npmjs.com before approving.",
            ))
    else:
        findings.append(Finding(
            category="Package",
            severity=Severity.MEDIUM,
            rule_id="pkg.unscoped",
            title=f"Unscoped npm package: {pkg}",
            detail=f"`{pkg}` is unscoped, which carries typosquatting risk.",
            recommendation=f"Verify {pkg} on npmjs.com (downloads, publisher, source).",
        ))


def _check_args(args: list[str], findings: list[Finding]) -> None:
    if len(args) > _MAX_ARGS:
        findings.append(Finding(
            category="Arguments",
            severity=Severity.MEDIUM,
            rule_id="args.too_many",
            title=f"Too many arguments ({len(args)})",
            detail=f"More than {_MAX_ARGS} args is unusual for an MCP server invocation.",
            recommendation="Trim the argument list or move config into env vars / a config file.",
        ))

    saw_metachars = False
    saw_control = False
    saw_too_long = False
    saw_sensitive: list[str] = []

    for arg in args:
        if not arg:
            continue
        if not saw_control and any(c in _CONTROL_CHARS for c in arg):
            findings.append(Finding(
                category="Arguments",
                severity=Severity.HIGH,
                rule_id="args.control_chars",
                title="Argument contains control characters",
                detail="An arg contains NUL / CR / LF, which can corrupt log output and indicate injection attempts.",
                recommendation="Strip control characters from the arg.",
            ))
            saw_control = True
        if not saw_metachars and any(c in _SHELL_METACHARS for c in arg):
            findings.append(Finding(
                category="Arguments",
                severity=Severity.HIGH,
                rule_id="args.shell_metachars",
                title="Argument contains shell metacharacters",
                detail=f"Arg `{arg[:80]}` contains one of `; | & < > $ ( ) \\`` . "
                       "These would be interpreted by a shell wrapper.",
                recommendation="Remove shell metacharacters. With safe-spawn enabled they are inert, but their presence is still a strong red flag.",
            ))
            saw_metachars = True
        if not saw_too_long and len(arg) > _MAX_ARG_LEN:
            findings.append(Finding(
                category="Arguments",
                severity=Severity.MEDIUM,
                rule_id="args.too_long",
                title="Overly long argument",
                detail=f"An arg is {len(arg)} chars (limit {_MAX_ARG_LEN}). Long args often hide payloads.",
                recommendation="Split the argument or move long values into env vars.",
            ))
            saw_too_long = True
        if arg in _SENSITIVE_PATHS and arg not in saw_sensitive:
            saw_sensitive.append(arg)

    for path in saw_sensitive:
        findings.append(Finding(
            category="Arguments",
            severity=Severity.MEDIUM,
            rule_id="args.sensitive_path",
            title=f"Sensitive filesystem path: {path}",
            detail=f"Arg `{path}` grants the server access to a privileged location.",
            recommendation="Scope the server to a narrower directory (e.g. `/srv/data`).",
        ))


def _check_env_vars(env_vars: dict[str, str] | None, findings: list[Finding]) -> None:
    if not env_vars:
        return
    for key, value in env_vars.items():
        if key in _DANGEROUS_ENV_KEYS or key.startswith("DYLD_"):
            findings.append(Finding(
                category="Environment",
                severity=Severity.HIGH,
                rule_id="env.dangerous_key",
                title=f"Dangerous environment variable: {key}",
                detail=f"`{key}` can hijack process loading or library resolution.",
                recommendation=f"Remove {key} from the env. There is no legitimate reason for an MCP server config to set it.",
            ))
        if key == "NODE_OPTIONS" and isinstance(value, str):
            lowered = value.lower()
            if any(loader in lowered for loader in _NODE_OPTIONS_LOADERS):
                findings.append(Finding(
                    category="Environment",
                    severity=Severity.HIGH,
                    rule_id="env.node_options_loader",
                    title="NODE_OPTIONS contains a code-loading flag",
                    detail=f"NODE_OPTIONS=`{value}` contains `--require`/`--import`/`--loader`/`--inspect`. "
                           "These execute arbitrary code at Node startup.",
                    recommendation="Strip the loader flag. Pass startup logic through args, not NODE_OPTIONS.",
                ))


def _check_url(url: str | None, findings: list[Finding]) -> None:
    if not url or not url.strip():
        findings.append(Finding(
            category="Network",
            severity=Severity.HIGH,
            rule_id="url.empty",
            title="SSE URL is empty",
            detail="SSE mode requires a URL.",
            recommendation="Provide an HTTPS URL for the SSE endpoint.",
        ))
        return

    try:
        parsed = urlparse(url.strip())
    except Exception:
        findings.append(Finding(
            category="Network",
            severity=Severity.HIGH,
            rule_id="url.invalid",
            title="URL failed to parse",
            detail=f"Could not parse `{url}` as a URL.",
            recommendation="Provide a well-formed HTTPS URL.",
        ))
        return

    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        findings.append(Finding(
            category="Network",
            severity=Severity.HIGH,
            rule_id="url.unsupported_scheme",
            title=f"Unsupported URL scheme: {scheme or '(none)'}",
            detail=f"Only http/https are supported. Got `{scheme}`.",
            recommendation="Use an https:// URL.",
        ))
        return

    if scheme == "http":
        findings.append(Finding(
            category="Network",
            severity=Severity.MEDIUM,
            rule_id="url.plain_http",
            title="Plain HTTP (no transport encryption)",
            detail="Traffic and headers (including auth) flow in cleartext.",
            recommendation="Use https:// instead.",
        ))

    if "@" in (parsed.netloc or "") and parsed.username is not None:
        findings.append(Finding(
            category="Network",
            severity=Severity.HIGH,
            rule_id="url.userinfo",
            title="URL contains embedded credentials",
            detail="`user:pass@host` style URLs leak credentials to logs and proxies.",
            recommendation="Move credentials into headers or env vars.",
        ))

    host = parsed.hostname
    if not host:
        findings.append(Finding(
            category="Network",
            severity=Severity.HIGH,
            rule_id="url.no_host",
            title="URL has no parseable hostname",
            detail=f"Could not extract a hostname from `{url}`.",
            recommendation="Provide a URL with an explicit host.",
        ))
        return

    is_ip = False
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False

    if is_ip:
        findings.append(Finding(
            category="Network",
            severity=Severity.MEDIUM,
            rule_id="url.ip_literal",
            title="URL host is a raw IP literal",
            detail=f"Got `{host}`. IP literals bypass DNS-based access control and TLS hostname checks.",
            recommendation="Use a DNS hostname covered by your TLS cert.",
        ))

    private, resolved_ip = _is_private_ip(host)
    if resolved_ip is None and not is_ip:
        findings.append(Finding(
            category="Network",
            severity=Severity.MEDIUM,
            rule_id="url.unresolvable",
            title=f"Hostname did not resolve: {host}",
            detail="DNS resolution failed at validation time. The server may be unreachable.",
            recommendation="Verify the hostname is correct and resolvable from the runtime environment.",
        ))
    elif private:
        findings.append(Finding(
            category="Network",
            severity=Severity.HIGH,
            rule_id="url.private_ip",
            title="URL points to a private/internal IP",
            detail=f"`{host}` resolves to `{resolved_ip}`, which is private/loopback/link-local. "
                   "This can be used to reach cloud metadata services (e.g. 169.254.169.254) or internal infra.",
            recommendation="Point the SSE URL at a public, dedicated MCP endpoint.",
        ))


def _check_headers(headers: dict[str, str] | None, findings: list[Finding]) -> None:
    if not headers:
        return
    for key, value in headers.items():
        if not isinstance(value, str):
            continue
        if "\r" in value or "\n" in value or "\r" in key or "\n" in key:
            findings.append(Finding(
                category="Headers",
                severity=Severity.HIGH,
                rule_id="hdr.crlf_injection",
                title=f"CRLF in header `{key}`",
                detail="Header value contains CR or LF, which enables HTTP header-injection.",
                recommendation="Strip CR/LF from the header value.",
            ))


# --- Public entry point ------------------------------------------------------

def _infer_mode(payload: dict, mode: str | None) -> str:
    if mode and mode.lower() in {"sse", "stdio"}:
        return mode.lower()
    if payload.get("command"):
        return "stdio"
    if payload.get("url"):
        return "sse"
    return "stdio"


def analyze(payload: dict[str, Any], mode: str | None = None) -> RiskAnalysis:
    """Run every applicable rule against `payload` and return a RiskAnalysis.

    Pure function. No subprocess. No DB writes. DNS resolution is the only
    side-effect (read-only, used for url.private_ip).
    """
    findings: list[Finding] = []
    resolved_mode = _infer_mode(payload or {}, mode)

    args_raw = payload.get("args") or []
    args: list[str] = [str(a) for a in args_raw if a is not None]
    env_vars = payload.get("env_vars") or None
    headers = payload.get("headers") or None

    if resolved_mode == "stdio":
        exe = _check_command(payload.get("command"), findings)
        _check_package(exe, args, findings)
        _check_args(args, findings)
        _check_env_vars(env_vars, findings)
    else:  # sse
        _check_url(payload.get("url"), findings)
        _check_headers(headers, findings)
        _check_env_vars(env_vars, findings)

    return RiskAnalysis(findings=findings)
