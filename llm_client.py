# llm_client.py

import aiohttp
import os
import json
import logging
from typing import Dict, List, Optional, Tuple

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Konfiguration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# Optimierte LLM-Parameter
TEMPERATURE = 0.1  # Niedrige Temperatur für konsistente Antworten
TOP_P = 0.9
MAX_TOKENS = 1024  # Mehr Tokens für vollständige Sätze
TOP_K = 40
REPEAT_PENALTY = 1.1

# Timeout erhöht
TIMEOUT = aiohttp.ClientTimeout(total=180)  # 3 Minuten

async def ask_ollama(question: str, context: str, chunks_info: List[Dict] = None) -> str:
    """
    Verbesserte Ollama-Anfrage mit strukturierten Prompts
    
    Args:
        question: Benutzerfrage
        context: Gefundener Dokumentenkontext
        chunks_info: Informationen über die gefundenen Chunks
        
    Returns:
        Antwort des LLMs
    """
    try:
        # Sprache erkennen
        language_instruction = _detect_language(question)
        
        # Strukturierten Prompt erstellen
        system_prompt, user_prompt = _create_structured_prompts(
            question, context, chunks_info, language_instruction
        )
        
        # Ollama API aufrufen
        response = await _call_ollama_api(system_prompt, user_prompt)
        
        # Antwort parsen und validieren
        parsed_response = _parse_and_validate_response(response, question)
        
        return parsed_response
        
    except Exception as e:
        logger.error(f"Fehler bei Ollama-Anfrage: {e}")
        return f"[System Error] An unexpected error occurred: {e}"

def _detect_language(question: str) -> str:
    """Erkennt die Sprache der Frage und gibt entsprechende Anweisungen"""
    question_lower = question.lower()
    
    german_keywords = [
        'was', 'wie', 'wo', 'wann', 'wer', 'welche', 'welcher', 'welches',
        'erkläre', 'beschreibe', 'definiere', 'was ist', 'was bedeutet'
    ]
    
    if any(keyword in question_lower for keyword in german_keywords):
        return (
            "Antworte auf Deutsch. Verwende eine klare, professionelle Sprache. "
            "Beende alle Sätze vollständig. Wenn du eine Information nicht findest, "
            "sage das klar und deutlich."
        )
    else:
        return (
            "Respond in English. Use clear, professional language. "
            "Complete all sentences properly. If you cannot find information, "
            "state this clearly and directly."
        )

def _create_structured_prompts(
    question: str, 
    context: str, 
    chunks_info: List[Dict], 
    language_instruction: str
) -> Tuple[str, str]:
    """Erstellt strukturierte Prompts für bessere Antworten"""
    
    # System Prompt mit klaren Regeln
    system_prompt = f"""Du bist ein Experten-Assistent für die Beantwortung von Fragen basierend auf bereitgestellten Dokumenten.

WICHTIGE REGELN:
1. Verwende NUR die bereitgestellten KONTEXTE. Erfinde KEINE Fakten.
2. Wenn eine Antwort NICHT in den Kontexten gefunden wird, antworte mit: "INFORMATION NICHT GEFUNDEN"
3. Beende alle Sätze vollständig und logisch.
4. Gib immer mindestens eine kurze, wörtliche Zitat aus dem Kontext an.
5. {language_instruction}

ANTWORTFORMAT:
- Wenn Information gefunden: Gib eine klare, vollständige Antwort mit Zitat
- Wenn NICHT gefunden: "INFORMATION NICHT GEFUNDEN"
- Beende alle Sätze vollständig"""

    # User Prompt mit strukturiertem Kontext
    context_with_scores = ""
    if chunks_info:
        context_with_scores = "\n\n".join([
            f"--- CHUNK {i+1} (Ähnlichkeit: {chunk['similarity_score']:.3f}) ---\n{chunk['text']}"
            for i, chunk in enumerate(chunks_info)
        ])
    else:
        context_with_scores = context

    user_prompt = f"""KONTEXTE:
{context_with_scores}

FRAGE: {question}

Antworte basierend auf den obigen Kontexten. Verwende nur die bereitgestellten Informationen."""
    
    return system_prompt, user_prompt

async def _call_ollama_api(system_prompt: str, user_prompt: str) -> str:
    """Ruft die Ollama API auf"""
    
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"{system_prompt}\n\n{user_prompt}",
        "stream": False,
        "options": {
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "top_k": TOP_K,
            "num_predict": MAX_TOKENS,
            "repeat_penalty": REPEAT_PENALTY
        }
    }
    
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload
        ) as response:
            if response.status == 200:
                result = await response.json()
                return result.get("response", "")
            else:
                error_text = await response.text()
                raise Exception(f"Ollama API Error {response.status}: {error_text}")

def _parse_and_validate_response(response: str, question: str) -> str:
    """Parst und validiert die LLM-Antwort"""
    
    if not response or response.strip() == "":
        return "INFORMATION NICHT GEFUNDEN - Keine Antwort vom LLM erhalten."
    
    # Prüfe auf "Information nicht gefunden" Patterns
    not_found_patterns = [
        "information nicht gefunden",
        "information not found", 
        "keine informationen gefunden",
        "no information found",
        "nicht in den kontexten",
        "not in the contexts"
    ]
    
    response_lower = response.lower()
    if any(pattern in response_lower for pattern in not_found_patterns):
        return "INFORMATION NICHT GEFUNDEN"
    
    # Prüfe auf unvollständige Sätze am Ende
    if not response.strip().endswith(('.', '!', '?')):
        # Versuche den letzten Satz zu vervollständigen
        sentences = response.split('.')
        if len(sentences) > 1:
            last_sentence = sentences[-1].strip()
            if last_sentence and len(last_sentence) < 50:  # Kurzer unvollständiger Satz
                # Entferne den unvollständigen Teil
                response = '.'.join(sentences[:-1]) + '.'
    
    return response.strip()

async def test_ollama_connection() -> bool:
    """Testet die Verbindung zu Ollama"""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(f"{OLLAMA_URL}/api/tags") as response:
                return response.status == 200
    except Exception as e:
        logger.error(f"Ollama Verbindungstest fehlgeschlagen: {e}")
        return False

# Hilfsfunktion für Kompatibilität
async def ask_ollama_simple(question: str, context: str) -> str:
    """Einfache Kompatibilitätsfunktion"""
    return await ask_ollama(question, context)