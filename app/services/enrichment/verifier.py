"""Free email verification: syntax -> MX -> SMTP RCPT handshake.

Levels of confidence (EmailStatus):
  verified    SMTP server accepted RCPT for this mailbox AND rejected a random
              mailbox (so it is not a catch-all) -> safe to send
  accept_all  domain accepts every RCPT (catch-all) -> deliverable, unproven
  mx_valid    MX exists but SMTP could not be completed (port 25 blocked etc.)
  risky       pattern-guessed address on an MX-valid domain
  invalid     bad syntax / no MX / SMTP rejected the mailbox
  not_found   nothing to verify

No paid APIs. Note: most residential ISPs block outbound port 25 — in that
case results degrade to mx_valid/risky automatically.
"""
import asyncio
import logging
import secrets
import smtplib
import socket

import dns.asyncresolver
import dns.exception
from email_validator import EmailNotValidError, validate_email

from app.config import get_settings
from app.models import EmailStatus

log = logging.getLogger(__name__)

_SMTP_TIMEOUT = 10
_mx_cache: dict[str, list[str]] = {}
_smtp_reachable: bool | None = None  # None = untested


async def get_mx_hosts(domain: str) -> list[str]:
    """Resolve MX hosts for a domain (cached), best-preference first."""
    domain = domain.lower().strip()
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        resolver = dns.asyncresolver.Resolver()
        resolver.lifetime = 6
        answers = await resolver.resolve(domain, "MX")
        hosts = [str(r.exchange).rstrip(".") for r in sorted(answers, key=lambda r: r.preference)]
    except (dns.exception.DNSException, OSError):
        hosts = []
    _mx_cache[domain] = hosts
    return hosts


def _smtp_rcpt_check(mx_host: str, email: str, helo_domain: str, from_address: str) -> bool | None:
    """RCPT TO probe. True=accepted, False=rejected, None=inconclusive."""
    try:
        with smtplib.SMTP(mx_host, 25, timeout=_SMTP_TIMEOUT) as smtp:
            smtp.helo(helo_domain)
            smtp.mail(from_address)
            code, _ = smtp.rcpt(email)
        if code in (250, 251):
            return True
        if code in (550, 551, 553):
            return False
        return None  # greylisting / 4xx / policy responses are inconclusive
    except (smtplib.SMTPException, OSError, socket.timeout):
        return None


async def _smtp_check(mx_host: str, email: str) -> bool | None:
    settings = get_settings()
    return await asyncio.to_thread(
        _smtp_rcpt_check, mx_host, email, settings.smtp_helo_domain, settings.smtp_from_address
    )


async def verify_email(email: str, *, is_guess: bool = False) -> EmailStatus:
    """Full verification pipeline for one address."""
    global _smtp_reachable
    email = (email or "").strip().lower()
    if not email:
        return EmailStatus.not_found

    # 1. Syntax
    try:
        validated = validate_email(email, check_deliverability=False)
        email = validated.normalized
        domain = validated.domain
    except EmailNotValidError:
        return EmailStatus.invalid

    # 2. MX
    mx_hosts = await get_mx_hosts(domain)
    if not mx_hosts:
        return EmailStatus.invalid

    mx_only_status = EmailStatus.risky if is_guess else EmailStatus.mx_valid

    # 3. SMTP handshake (skip if disabled or previously found unreachable)
    if not get_settings().smtp_verify_enabled or _smtp_reachable is False:
        return mx_only_status

    result = await _smtp_check(mx_hosts[0], email)
    if result is None:
        if _smtp_reachable is None:
            # Probe whether outbound port 25 works at all; if not, stop trying.
            probe = await asyncio.to_thread(_port25_open, mx_hosts[0])
            _smtp_reachable = probe
            if not probe:
                log.info("outbound port 25 appears blocked — SMTP verification disabled for this run")
        return mx_only_status
    _smtp_reachable = True
    if result is False:
        return EmailStatus.invalid

    # 4. Catch-all detection: a random mailbox should NOT be accepted
    random_addr = f"zz-{secrets.token_hex(8)}@{domain}"
    catch_all = await _smtp_check(mx_hosts[0], random_addr)
    if catch_all is True:
        return EmailStatus.accept_all
    return EmailStatus.verified


def _port25_open(host: str) -> bool:
    try:
        with socket.create_connection((host, 25), timeout=6):
            return True
    except OSError:
        return False


async def find_best_verified(candidates: list[str], *, guesses_from: int | None = None) -> tuple[str, EmailStatus, list]:
    """Verify candidates in order; return the first sendable one.

    guesses_from: index at which candidates switch from found emails to
    pattern guesses (affects the risky/mx_valid status).
    Returns (email, status, audit_trail).
    """
    audit = []
    best: tuple[str, EmailStatus] | None = None
    order = [EmailStatus.verified, EmailStatus.accept_all, EmailStatus.mx_valid, EmailStatus.risky]

    for i, candidate in enumerate(candidates):
        is_guess = guesses_from is not None and i >= guesses_from
        status = await verify_email(candidate, is_guess=is_guess)
        audit.append({"email": candidate, "status": status.value})
        if status == EmailStatus.verified:
            return candidate, status, audit
        if status in order and (best is None or order.index(status) < order.index(best[1])):
            best = (candidate, status)

    if best:
        return best[0], best[1], audit
    return "", EmailStatus.not_found, audit
