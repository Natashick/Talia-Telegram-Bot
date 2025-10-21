# README
# Telegram PDF Chatbot (mit ChromaDB & Ollama)

## Features
- Fragt PDFs im Ordner per Telegram-Bot ab (semantische Suche)
- Inline-Buttons für Dokumentauswahl
- Lokale LLM-Antworten (Ollama, z.B. Mistral)
- OCR für gescannte PDFs
- Persistente Vektor-Datenbank (ChromaDB)
- Webhook-Deployment (FastAPI)

## Setup

1. **Python-Pakete installieren**
   ```
   pip install -r requirements.txt
   ```

2. **Poppler & Tesseract installieren**
   - Poppler: [Download für Windows](http://blog.alivate.com.au/poppler-windows/)
   - Tesseract: [Download für Windows](https://github.com/tesseract-ocr/tesseract)

3. **Ollama installieren & Modell laden**
   ```
   ollama pull mistral
   ollama serve
   ```

4. **Umgebungsvariablen setzen**
   - `TELEGRAM_TOKEN` (dein Bot-Token)
   - `WEBHOOK_URL` (z.B. von ngrok oder deinem Server)

5. **Bot starten**
   ```
   python bot.py
   ```

6. **Webhook setzen**
   - Stelle sicher, dass dein Server/PC von Telegram erreichbar ist (z.B. mit ngrok).

## Hinweise
- PDFs einfach in den Projektordner legen.
- Der Bot indexiert alle PDFs beim Start.
- Inline-Buttons zeigen Dateinamen ohne `.pdf`.
- Antworten kommen vom lokalen LLM (Ollama).

## Fehlerbehebung
- Bei OCR-Problemen: Poppler- und Tesseract-Pfade prüfen.
- Bei LLM-Problemen: Läuft Ollama? Modell geladen?
- Bei Webhook-Problemen: Ist der Server von Telegram erreichbar?
