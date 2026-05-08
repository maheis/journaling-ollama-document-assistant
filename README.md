# Ollama Document Assistant (Debian, CPU-only)

Lokale Dokument-Automatisierung mit Ollama, OCR und Web-Review.

Wichtiges Prinzip:

- `organize.py` erzeugt immer nur Vorschlaege (Dry-Run)
- finales Umbenennen passiert ausschliesslich per Deploy in der Weboberflaeche

## Quickstart (Debian)

1) Repository klonen und in den Ordner wechseln

```bash
git clone https://github.com/maheis/ollama-document-assistant.git
cd ollama-document-assistant
```

2) Komplettsetup ausfuehren

```bash
bash ./install.sh --full-setup
```

3) Service starten (falls nicht schon durch Install-Skript gestartet)

```bash
systemctl --user restart ollama-document-assistant.service
```

4) Weboberflaeche oeffnen

```text
http://127.0.0.1:8449
```

5) Passwort auslesen

```bash
head -n 1 ./.review_web_password
```

## Was das Projekt macht

- Text aus PDF/TXT/MD/Bildern extrahieren (inkl. OCR-Fallback)
- Dokumente mit lokalem LLM klassifizieren
- saubere Zielnamen vorschlagen
- Vorschlaege im Browser pruefen/anpassen
- erst nach Freigabe deployen

## Workflow

1) Inbox fuellen (`./inbox`)
2) Dry-Run erzeugt Vorschlaege
3) Vorschlaege in der Web-UI pruefen
4) einzelne oder alle Eintraege deployen

## Dateinamenschema

`YYYY-MM-DD_ABSENDER_KATEGORIE_[KUNDENNUMMER]_TITEL.ext`

Beispiele:

- `2026-03-11_stadtwerke_RECHNUNG_123456_abschlag_april.pdf`
- `2026-03-11_stadtwerke_RECHNUNG_abschlag_april.pdf`

## Zentrale Konfiguration

Zentrale Defaults liegen in `assistant_config.json`.

Gesteuert werden u. a.:

- Host/Port der Weboberflaeche
- Login-Passwortdatei
- Scan-Intervall
- Modell und Inbox fuer den Dienst

Start mit Config:

```bash
python3 review_web.py --config-file ./assistant_config.json
python3 doc_assistant_service.py --config-file ./assistant_config.json
```

Prioritaet:

- CLI-Flag > `assistant_config.json` > Script-Default

Validierung:

- `review_web.py` und `doc_assistant_service.py` validieren die Config beim Start
- bei JSON- oder Schema-Fehlern: klare Meldung und Exit-Code `2`

## Installation per Script

Basis-Setup (venv, Python-Dependencies, Inbox, Passwortdatei, optionale user-systemd Unit):

```bash
bash ./install.sh
```

Vollsetup fuer Debian:

```bash
bash ./install.sh --full-setup
```

Optionen:

- `--no-systemd`: keine user-systemd Unit installieren
- `--no-start`: Unit installieren, aber nicht starten
- `--full-setup`: aktiviert `--install-system-deps`, `--install-ollama`, `--pull-models`
- `--install-system-deps`: apt-Pakete installieren (Debian/Ubuntu)
- `--install-ollama`: Ollama installieren und starten
- `--pull-models`: Modell(e) mit `ollama pull` laden
- `--model <name>`: Modell explizit setzen (mehrere per Komma)

Hinweise:

- kein `git clone`/Checkout im Skript
- fuer apt-Schritte sind root/sudo Rechte noetig

## Web-Review und Deploy

Start (manuell):

```bash
python3 review_web.py --config-file ./assistant_config.json
```

UI-Funktionen:

1. Spaltenweise bearbeiten (Sender, Kategorie, Kunden-Nr, Titel, Datum)
2. Dokument direkt aus der Zeile oeffnen
3. global oder pro Zeile speichern
4. global oder pro Zeile deployen
5. Status je Eintrag: `PENDING`, `SAVED`, `MISSING`, `DEPLOYED`
6. Status-Filter: `Alle`, `Offen`, `Pending`, `Saved`, `Missing`, `Deployed`
7. Lern-Haken pro Feld (Alias-Lernen)

Hinweis:

- deployte Dokumente bleiben sichtbar und sind filterbar

## Sicherheit

Login empfohlen:

```bash
printf '%s\n' 'DEIN_STARKES_PASSWORT' > ./.review_web_password
chmod 600 ./.review_web_password
```

Verhalten:

- mit `--auth-password` oder `--auth-password-file`: Login aktiv (Session-Cookie)
- Remote-Bind ohne Login wird blockiert

## Dienstbetrieb (auto scan + web host)

Der Dienst `doc_assistant_service.py`:

- startet `review_web.py` dauerhaft
- startet `organize.py` periodisch im Dry-Run
- restartet Web-Prozess bei Absturz

Manuell starten:

```bash
python3 doc_assistant_service.py --config-file ./assistant_config.json
```

User-systemd Unit:

- Datei: `systemd/ollama-document-assistant.service`

Installation:

```bash
mkdir -p ~/.config/systemd/user
cp ./systemd/ollama-document-assistant.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ollama-document-assistant.service
systemctl --user status ollama-document-assistant.service
```

## Modell-Empfehlung (CPU-only)

Testreihenfolge:

1. `qwen2.5:3b-instruct`
2. `qwen2.5:7b-instruct`
3. `llama3.1:8b`

Praxisprofil:

- Standard: `qwen2.5:7b-instruct`
- Fallback bei Last: `qwen2.5:3b-instruct`

## Wichtige organize.py Optionen

```bash
python3 organize.py \
  --input ./inbox \
  --dry-run \
  --model qwen2.5:7b-instruct \
  --min-confidence 0.85 \
  --max-text-chars 8000 \
  --ollama-timeout 1800 \
  --ollama-retries 0 \
  --field-aliases-file field_aliases.json
```

Wichtige Hinweise:

- `--apply` ist deaktiviert
- Logs landen in `/tmp` (mit Datums-Prefix)
- bei wenig PDF-Text greift OCR

## Troubleshooting

### Kein Text extrahiert

```bash
which pdftotext && pdftotext -v
which tesseract && tesseract --list-langs | grep -E 'deu|eng'
python3 -c "import pypdf,pdf2image,pytesseract; print('python deps ok')"
```

### Ollama Timeout

```bash
python3 organize.py --input ./inbox --dry-run --model qwen2.5:7b-instruct --ollama-timeout 1800 --ollama-retries 0
```

Wenn noetig:

1. auf `qwen2.5:3b-instruct` wechseln
2. `--max-text-chars` reduzieren
3. Ollama API pruefen: `curl http://127.0.0.1:11434/api/tags`

### CPU drosseln

```bash
python3 organize.py \
  --input ./inbox \
  --dry-run \
  --model qwen2.5:3b-instruct \
  --process-nice 8 \
  --max-cpu-threads 2 \
  --ollama-num-thread 2 \
  --sleep-between-files 0.5
```

## Lizenz

MIT, siehe `LICENSE`.

MIT, siehe [LICENSE](LICENSE).
