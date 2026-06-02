#!/usr/bin/env python3
"""Email notification helpers for completed scans."""

from __future__ import annotations

import json
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any


@dataclass
class EmailNotificationSettings:
    enabled: bool
    recipient: str
    sender: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_starttls: bool
    smtp_ssl: bool
    subject_prefix: str


@dataclass
class EmailNotificationResult:
    sent: bool
    reason: str = ""


def load_email_notification_settings(config: dict[str, Any]) -> EmailNotificationSettings:
    notifications = config.get("notifications", {})
    if not isinstance(notifications, dict):
        notifications = {}

    email = notifications.get("email", {})
    if not isinstance(email, dict):
        email = {}

    return EmailNotificationSettings(
        enabled=bool(email.get("enabled", False)),
        recipient=str(email.get("to", "")).strip(),
        sender=str(email.get("from", "")).strip(),
        smtp_host=str(email.get("smtp_host", "")).strip(),
        smtp_port=int(email.get("smtp_port", 587) or 587),
        smtp_username=str(email.get("smtp_username", "")).strip(),
        smtp_password=str(email.get("smtp_password", "")),
        smtp_starttls=bool(email.get("smtp_starttls", True)),
        smtp_ssl=bool(email.get("smtp_ssl", False)),
        subject_prefix=str(email.get("subject_prefix", "[ODA]")).strip() or "[ODA]",
    )


def _send_email(settings: EmailNotificationSettings, *, subject: str, body: str) -> EmailNotificationResult:
    missing = []
    if not settings.recipient:
        missing.append("notifications.email.to")
    if not settings.sender:
        missing.append("notifications.email.from")
    if not settings.smtp_host:
        missing.append("notifications.email.smtp_host")
    if settings.smtp_port < 1:
        missing.append("notifications.email.smtp_port")
    if missing:
        return EmailNotificationResult(sent=False, reason="missing:" + ",".join(missing))

    recipients = [part.strip() for part in settings.recipient.split(",") if part.strip()]
    if not recipients:
        return EmailNotificationResult(sent=False, reason="missing:notifications.email.to")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    try:
        if settings.smtp_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(msg, to_addrs=recipients)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.ehlo()
                if settings.smtp_starttls:
                    smtp.starttls()
                    smtp.ehlo()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(msg, to_addrs=recipients)
    except Exception as exc:
        return EmailNotificationResult(sent=False, reason=str(exc))

    return EmailNotificationResult(sent=True)


def notification_debug_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    settings = load_email_notification_settings(config)
    return {
        "enabled": settings.enabled,
        "recipient_configured": bool(settings.recipient.strip()),
        "sender_configured": bool(settings.sender.strip()),
        "smtp_host_configured": bool(settings.smtp_host.strip()),
        "smtp_port": settings.smtp_port,
        "smtp_username_configured": bool(settings.smtp_username.strip()),
        "smtp_password_configured": bool(settings.smtp_password),
        "smtp_starttls": settings.smtp_starttls,
        "smtp_ssl": settings.smtp_ssl,
        "subject_prefix": settings.subject_prefix,
    }


def append_notification_debug_log(log_path: Path, payload: dict[str, Any]) -> None:
    record = {"timestamp": datetime.now().isoformat(timespec="seconds"), **payload}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def send_test_email(config: dict[str, Any], *, review_url: str, input_path: str) -> EmailNotificationResult:
    settings = load_email_notification_settings(config)
    subject = f"{settings.subject_prefix} Testmail"
    body = "\n".join(
        [
            "Dies ist eine Testmail des Ollama Document Assistant.",
            "",
            f"Zeitpunkt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Inbox: {input_path}",
            f"Weboberfläche: {review_url}",
            "",
            "Wenn diese Mail ankommt, funktioniert die aktuelle SMTP-Konfiguration.",
        ]
    )
    # Testmails sollen auch dann möglich sein, wenn der automatische Versand deaktiviert ist.
    settings.enabled = True
    return _send_email(settings, subject=subject, body=body)


def send_review_notification(
    config: dict[str, Any],
    *,
    new_review_count: int,
    error_count: int,
    scan_source: str,
    review_url: str,
    input_path: str,
) -> EmailNotificationResult:
    if new_review_count <= 0 and error_count <= 0:
        return EmailNotificationResult(sent=False, reason="no_new_review_entries_or_errors")

    settings = load_email_notification_settings(config)
    if not settings.enabled:
        return EmailNotificationResult(sent=False, reason="disabled")

    if error_count > 0 and new_review_count > 0:
        subject = f"{settings.subject_prefix} {new_review_count} neue Prüfdokumente, {error_count} Fehler"
        body_lines = [
            "Ein Scan wurde mit Fehlern abgeschlossen.",
            "",
            f"Neue Dokumente zur Prüfung: {new_review_count}",
            f"Fehler: {error_count}",
            f"Scan-Quelle: {scan_source}",
            f"Inbox: {input_path}",
            f"Weboberfläche: {review_url}",
            "",
            "Bitte die neuen Vorschläge prüfen und die Fehlerursache kontrollieren.",
        ]
    elif error_count > 0:
        subject = f"{settings.subject_prefix} Scan mit {error_count} Fehlern"
        body_lines = [
            "Ein Scan wurde mit Fehlern abgeschlossen.",
            "",
            f"Neue Dokumente zur Prüfung: {new_review_count}",
            f"Fehler: {error_count}",
            f"Scan-Quelle: {scan_source}",
            f"Inbox: {input_path}",
            f"Weboberfläche: {review_url}",
            "",
            "Bitte die Fehlerursache prüfen.",
        ]
    else:
        subject = f"{settings.subject_prefix} {new_review_count} neue Dokumente zur Prüfung"
        body_lines = [
            "Ein Scan wurde abgeschlossen.",
            "",
            f"Neue Dokumente zur Prüfung: {new_review_count}",
            f"Fehler: {error_count}",
            f"Scan-Quelle: {scan_source}",
            f"Inbox: {input_path}",
            f"Weboberfläche: {review_url}",
            "",
            "Bitte die neuen Vorschläge in der Weboberfläche prüfen.",
        ]
    body = "\n".join(body_lines)
    return _send_email(settings, subject=subject, body=body)
