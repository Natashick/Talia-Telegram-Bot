# handlers.py

import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from vector_store import vector_store
from llm_client import ask_ollama
import json
import logging
from pdf2image import convert_from_path
from PIL import Image
import asyncio
from pdf_parser import pdf_parser
import re

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Globale Variablen (keine globale Dokument-/Modus-Auswahl mehr)
pdf_files = []

USER_STATE_FILE = "user_state.json"

def load_user_state():
    try:
        with open(USER_STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_user_state(state):
    with open(USER_STATE_FILE, "w") as f:
        json.dump(state, f)

# User-zu-Dokument-Mapping
user_selected_doc = load_user_state()

user_screenshot_state = {}
user_last_context = {}

async def show_typing_while_processing(update, duration_seconds=25):
    """
    ZEIGT KONTINUIERLICHES "TIPPT..." WÄHREND LLM ARBEITET
    """
    try:
        for _ in range(duration_seconds // 4):  # Alle 4 Sekunden erneuern
            if update.message:
                await update.message.reply_chat_action(action="typing")
            await asyncio.sleep(4)
    except:
        pass  # Ignoriere Fehler falls Chat geschlossen wurde

# Hilfsfunktion: Erkenne typische Folgefragen
FOLLOW_UP_KEYWORDS = [
    "more details", "explain this", "tell me more", "erkläre das", "mehr details", "explain", "details"
]

# NEUE FUNKTION: Erkenne Figure/Table/Image Anfragen
VISUAL_CONTENT_KEYWORDS = [
    "figure", "table", "image", "chart", "diagram", "graph", "bild", "abbildung", "tabelle", "grafik"
]

def extract_figure_table_request(user_question):
    text = user_question.lower()
    import re
    patterns = [
        r'(?:figure|fig\.?)\s+([a-z]*\.?\d+(?:\.\d+)?)',
        r'(?:table|tab\.?)\s+([a-z]*\.?\d+(?:\.\d+)?)',
        r'(?:image|img)\s+([a-z]*\.?\d+(?:\.\d+)?)',
        r'(?:abbildung|abb\.?)\s+([a-z]*\.?\d+(?:\.\d+)?)',
        r'(?:tabelle)\s+([a-z]*\.?\d+(?:\.\d+)?)'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            if any(word in text for word in ['figure', 'fig', 'abbildung', 'abb']):
                return ("figure", match.group(1))
            elif any(word in text for word in ['table', 'tab', 'tabelle']):
                return ("table", match.group(1))
            elif any(word in text for word in ['image', 'img', 'bild']):
                return ("image", match.group(1))
    return None

def is_follow_up(update, user_question):
    if update.message and update.message.reply_to_message and update.message.reply_to_message.from_user.is_bot:
        return True
    uq = user_question.lower()
    return any(kw in uq for kw in FOLLOW_UP_KEYWORDS)

def get_pdf_files():
    return [f for f in os.listdir() if f.lower().endswith('.pdf')]

def get_file_display_name(fname):
    return os.path.splitext(os.path.basename(fname))[0]

def get_callback_maps(pdf_files):
    callback_to_file = {f"doc{i}": fname for i, fname in enumerate(pdf_files)}
    file_to_callback = {fname: cb for cb, fname in callback_to_file.items()}
    file_display_name = {fname: get_file_display_name(fname) for fname in pdf_files}
    return callback_to_file, file_to_callback, file_display_name

async def greet_on_new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.my_chat_member and update.my_chat_member.new_chat_member.status == "member":
        chat = update.effective_chat
        if chat.type == "private":
            pass  # Begrüßungsnachricht entfernt

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pdf_files
    pdf_files = [f for f in os.listdir('.') if f.endswith('.pdf')]
    context.bot_data['pdf_files'] = pdf_files[:]
    if not pdf_files:
        await update.message.reply_text("Keine PDF-Dateien gefunden. Bitte laden Sie zuerst PDFs hoch.")
        return
    keyboard = []
    keyboard.append([InlineKeyboardButton("Alle Dokumente durchsuchen", callback_data="global_search")])
    keyboard.append([InlineKeyboardButton("Dokument auswählen:", callback_data="separator")])
    for i, pdf in enumerate(pdf_files):
        short_id = f"doc_{i}"
        keyboard.append([InlineKeyboardButton(f"{pdf}", callback_data=short_id)])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Willkommen beim intelligenten PDF-Bot!\n\n"
        "Globale Suche ist aktiv – ich durchsuche alle verfügbaren Dokumente.\n\n"
        "Verfügbare PDFs:\n" + "\n".join([f"• {pdf}" for pdf in pdf_files]) + "\n\n"
        "Stellen Sie Ihre Frage oder wählen Sie ein Dokument aus.",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Per-User Modus: keine globalen Zustände
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Callback konnte nicht bestätigt werden (evtl. zu alt/duplicated): {e}")
    global pdf_files
    if not pdf_files:
        cached = context.bot_data.get('pdf_files')
        if isinstance(cached, list) and cached:
            pdf_files = cached[:]
        else:
            pdf_files = [f for f in os.listdir('.') if f.endswith('.pdf')]
    if query.data == "global_search":
        # Per-User Auswahl zurücksetzen
        user_id = update.effective_user.id
        if user_id is not None:
            user_selected_doc.pop(str(user_id), None)
            save_user_state(user_selected_doc)
        await query.edit_message_text(
            "Globale Suche aktiviert!\n\n"
            "Ich durchsuche jetzt alle verfügbaren PDFs gleichzeitig:\n\n" +
            "\n".join([f"• {pdf}" for pdf in pdf_files]) + "\n\n"
            "Tipp: Für spezifische Fragen können Sie ein einzelnes Dokument auswählen."
        )
        keyboard = []
        keyboard.append([InlineKeyboardButton("🔍 Alle Dokumente durchsuchen", callback_data="global_search")])
        keyboard.append([InlineKeyboardButton("📚 Dokument auswählen:", callback_data="separator")])
        for i, pdf in enumerate(pdf_files):
            short_id = f"doc_{i}"
            keyboard.append([InlineKeyboardButton(f"{pdf}", callback_data=short_id)])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Verfügbare Optionen:", reply_markup=reply_markup)
    elif query.data == "separator":
        await query.message.reply_text("Wählen Sie ein Dokument aus:")
    elif query.data.startswith("doc_"):
        doc_index = int(query.data[4:])
        if 0 <= doc_index < len(pdf_files):
            selected_document = pdf_files[doc_index]
            # Per-User Auswahl speichern
            user_id = update.effective_user.id
            user_selected_doc[str(user_id)] = selected_document
            save_user_state(user_selected_doc)
            needs_index = not vector_store.has_document(selected_document)
            try:
                await query.edit_message_text(
                    (
                        "Spezifische Suche aktiviert!\n\n"
                        f"Ausgewähltes Dokument: {selected_document}\n\n"
                        + ("Indexiere das Dokument im Hintergrund – bitte kurz warten...\n\n" if needs_index else "")
                        + "Ich durchsuche nur dieses Dokument für Ihre Fragen.\n\n"
                        "Tipp: Drücken Sie 'Alle Dokumente durchsuchen' für die globale Suche."
                    )
                )
            except Exception as e:
                logger.warning(f"Konnte Auswahltext nicht senden: {e}")
            if needs_index:
                asyncio.create_task(_ensure_document_indexed(selected_document))
            keyboard = []
            keyboard.append([InlineKeyboardButton("Alle Dokumente durchsuchen", callback_data="global_search")])
            keyboard.append([InlineKeyboardButton("Dokument auswählen:", callback_data="separator")])
            for i, pdf in enumerate(pdf_files):
                short_id = f"doc_{i}"
                keyboard.append([InlineKeyboardButton(f"{pdf}", callback_data=short_id)])
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await query.message.reply_text("Verfügbare Optionen:", reply_markup=reply_markup)
            except Exception as e:
                logger.warning(f"Konnte Optionen nicht senden: {e}")
        else:
            pdf_files = [f for f in os.listdir('.') if f.endswith('.pdf')]
            context.bot_data['pdf_files'] = pdf_files[:]
            await query.message.reply_text("Ungültiger Dokument-Index. Die Dokumentliste wurde aktualisiert – bitte erneut wählen.")
    elif query.data.startswith("screenshot_"):
        await _handle_screenshot_request(update, context, query.data[11:])

async def _ensure_document_indexed(document_name: str):
    try:
        if vector_store.has_document(document_name):
            logger.info(f"Dokument bereits indexiert: {document_name}")
            return
        logger.info(f"Indexiere Dokument: {document_name}")
        paragraphs = await pdf_parser.extract_paragraphs_from_pdf(document_name)
        if not paragraphs:
            logger.warning(f"Keine Paragraphen extrahiert: {document_name}")
            return
        full_text = "\n\n".join(paragraphs)
        success = vector_store.add_document(
            doc_id=document_name,
            text=full_text,
            metadata={"source": document_name, "type": "pdf"}
        )
        if success:
            logger.info(f"Dokument {document_name} erfolgreich indexiert: {len(paragraphs)} Absätze")
        else:
            logger.error(f"Fehler beim Indexieren von {document_name}")
    except Exception as e:
        logger.error(f"Fehler beim Indexieren: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pdf_files
    user_question = update.message.text
    user_id = update.effective_user.id
    logger.info(f"Frage von User {user_id}: {user_question}")
    try:
        selected = user_selected_doc.get(str(user_id))
        if selected:
            await _handle_specific_search(update, user_question, selected)
        else:
            await _handle_global_search(update, user_question)
    except Exception as e:
        logger.error(f"Fehler bei der Nachrichtenverarbeitung: {e}")
        await update.message.reply_text("Ein Fehler ist aufgetreten. Bitte versuchen Sie es erneut.")

async def _handle_global_search(update: Update, user_question: str):
    try:
        all_results = []
        # Ensure pdf_files is populated
        if not pdf_files:
            pdf_files.extend(get_pdf_files())
        for pdf_file in pdf_files:
            try:
                await _ensure_document_indexed(pdf_file)
                # Search inside this specific PDF
                context_text, chunks_info = vector_store.get_combined_context_for_document(user_question, pdf_file, max_chunks=2)
                if chunks_info:
                    for chunk in chunks_info[:2]:
                        # ensure source is known
                        chunk['source_pdf'] = pdf_file
                        all_results.append(chunk)
            except Exception as e:
                logger.warning(f"Fehler bei Suche in {pdf_file}: {e}")
                continue
        if not all_results:
            await update.message.reply_text(
                "Keine relevanten Informationen gefunden.\n\n"
                "Ich habe alle verfügbaren Dokumente durchsucht, aber nichts Relevantes gefunden.\n\n"
                "Tipps:\n"
                "• Versuchen Sie andere Suchbegriffe\n"
                "• Wählen Sie ein spezifisches Dokument aus\n"
                "• Formulieren Sie Ihre Frage anders"
            )
            return
        all_results.sort(key=lambda x: x["similarity_score"], reverse=True)
        best_results = all_results[:4]
        context_parts = []
        for i, result in enumerate(best_results):
            source_pdf = result.get('source_pdf', 'Unbekannt')
            context_parts.append(
                f"--- CHUNK {i+1} aus {source_pdf} (Score: {result['similarity_score']:.3f}) ---\n"
                f"{result['text']}\n"
                f"--- CHUNK_END ---"
            )
        combined_context = "\n\n".join(context_parts)
        logger.info(f"Globale Suche: Generiere Antwort mit {len(best_results)} Chunks aus verschiedenen PDFs")
        # Prüfe: ask_ollama signature in llm_client.py, passe ggf. die args an
        response = await ask_ollama(user_question, combined_context, best_results)
        if "INFORMATION NICHT GEFUNDEN" in response:
            await update.message.reply_text(
                "**Keine relevanten Informationen gefunden.**\n\n"
                "Ich habe alle verfügbaren Dokumente durchsucht, aber nichts Relevantes gefunden.\n\n"
                "**Tipps:**\n"
                "• Versuchen Sie andere Suchbegriffe\n"
                "• Wählen Sie ein spezifisches Dokument aus\n"
                "• Formulieren Sie Ihre Frage anders",
                parse_mode='Markdown'
            )
            return
        if _should_offer_screenshot(user_question):
            keyboard = [[InlineKeyboardButton("Screenshot generieren", callback_data=f"screenshot_{user_question[:50]}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(f"Globale Suche abgeschlossen!\n\n{response}", reply_markup=reply_markup)
        else:
            await update.message.reply_text(f"Globale Suche abgeschlossen!\n\n{response}")
    except Exception as e:
        logger.error(f"Fehler bei globaler Suche: {e}")
        await update.message.reply_text("Fehler bei der globalen Suche. Bitte versuchen Sie es erneut.")

async def _handle_specific_search(update: Update, user_question: str, selected_document: str):
    if not selected_document:
        await update.message.reply_text(
            "Kein Dokument ausgewählt!\n\nDrücken Sie 'Alle Dokumente durchsuchen' oder wählen Sie ein spezifisches Dokument aus."
        )
        return
    try:
        if not vector_store.has_document(selected_document):
            await _ensure_document_indexed(selected_document)
        context_text, chunks_info = vector_store.get_combined_context_for_document(user_question, selected_document)
        if not chunks_info:
            await update.message.reply_text(
                f"Keine relevanten Informationen in {selected_document} gefunden.\n\n"
                "Versuchen Sie es mit anderen Suchbegriffen oder aktivieren Sie die globale Suche."
            )
            return
        logger.info(f"Spezifische Suche in {selected_document}: Generiere Antwort mit {len(chunks_info)} relevanten Chunks")
        response = await ask_ollama(user_question, context_text, chunks_info)
        if "INFORMATION NICHT GEFUNDEN" in response:
            await update.message.reply_text(
                f"Die gesuchte Information wurde in {selected_document} nicht gefunden.\n\n"
                "Tipps:\n"
                "• Versuchen Sie andere Suchbegriffe\n"
                "• Aktivieren Sie die globale Suche\n"
                "• Formulieren Sie Ihre Frage anders"
            )
            return
        if _should_offer_screenshot(user_question):
            keyboard = [[InlineKeyboardButton("Screenshot generieren", callback_data=f"screenshot_{user_question[:50]}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(f"Suche in {selected_document} abgeschlossen!\n\n{response}", reply_markup=reply_markup)
        else:
            await update.message.reply_text(f"Suche in {selected_document} abgeschlossen!\n\n{response}")
    except Exception as e:
        logger.error(f"Fehler bei spezifischer Suche: {e}")
        await update.message.reply_text("Fehler bei der spezifischen Suche. Bitte versuchen Sie es erneut.")

def _should_offer_screenshot(question: str) -> bool:
    screenshot_keywords = [
        'figure', 'figur', 'table', 'tabelle', 'diagram', 'diagramm',
        'screenshot', 'bild', 'image', 'abbildung', 'chart', 'graph'
    ]
    question_lower = question.lower()
    return any(keyword in question_lower for keyword in screenshot_keywords)

async def _handle_screenshot_request(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str):
    try:
        await update.callback_query.edit_message_text(
            f"Screenshot-Anfrage für: {question}\n\n"
            "Screenshot-Funktionalität wird implementiert..."
        )
    except Exception as e:
        logger.error(f"Fehler bei Screenshot-Anfrage: {e}")
        await update.callback_query.edit_message_text("Fehler bei der Screenshot-Generierung")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
**BOT-HILFE - Intelligente PDF-Suche**

**Globale Suche (Standard):**
• Durchsucht **alle verfügbaren PDFs** gleichzeitig
• Findet die **besten Informationen** aus allen Dokumenten
• **Keine Dokument-Auswahl** nötig

**Spezifische Suche:**
• Wählen Sie ein **bestimmtes PDF** aus
• **Fokussierte Suche** in einem Dokument
• Für **gezielte Fragen**

**Befehle:**
/start - Dokumente anzeigen + globale Suche aktivieren
/help - Diese Hilfe anzeigen
/status - Aktueller Suchmodus anzeigen

**Verwendung:**
1. **Globale Suche:** Stellen Sie direkt Ihre Frage
2. **Spezifische Suche:** Wählen Sie ein PDF aus
3. **Wechseln:** Drücken Sie "Alle Dokumente durchsuchen"

**Tipps:**
• Verwenden Sie spezifische Suchbegriffe
• Fragen Sie nach Abschnitten, Figuren oder Tabellen
• Der Bot antwortet in Ihrer Sprache
"""
    await update.message.reply_text(help_text)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pdf_files
    store_info = vector_store.get_document_info()
    user_id = update.effective_user.id
    sel = user_selected_doc.get(str(user_id))
    mode_text = "Spezifische Suche" if sel else "Globale Suche"
    doc_text = sel or "Alle verfügbaren PDFs"
    status_text = (
        "BOT-STATUS\n\n"
        f"Aktueller Modus: {mode_text}\n"
        f"Aktuelles Dokument: {doc_text}\n"
        f"Verfügbare PDFs: {len(pdf_files)}\n"
        f"Indexierte Chunks: {store_info.get('total_chunks', 0)}\n"
        f"Vector Store: {store_info.get('persist_directory', 'Unbekannt')}\n"
        f"Batch-Größe: {store_info.get('batch_size', 'Unbekannt')}\n"
    )
    await update.message.reply_text(status_text)

async def screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_screenshot_state[user_id] = {'step': 'awaiting_page'}
    await update.message.reply_text("Enter page number for view-only screenshot (e.g., 12):")

async def handle_screenshot_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_screenshot_state.get(user_id)
    if not state:
        return
    if state['step'] == 'awaiting_page':
        try:
            page = int(update.message.text.strip())
            state['page'] = page
            state['step'] = 'awaiting_crop'
            await update.message.reply_text("Optional: Enter crop box as left,upper,right,lower (e.g., 100,200,400,600) or 'no' for full page:")
        except Exception:
            await update.message.reply_text("Invalid page number. Please enter a valid number:")
    elif state['step'] == 'awaiting_crop':
        crop_input = update.message.text.strip().lower()
        crop_box = None
        if crop_input != 'no':
            try:
                coords = [x.strip() for x in crop_input.split(',')]
                if len(coords) != 4:
                    raise ValueError("Need exactly 4 coordinates")
                crop_box = tuple(map(int, coords))
            except Exception as e:
                await update.message.reply_text("Invalid crop box. Please enter as left,upper,right,lower (e.g., 100,200,400,600) or 'no':")
                return
        pdf_files_local = get_pdf_files()
        selected_doc_local = user_selected_doc.get(str(user_id), pdf_files_local[0] if pdf_files_local else None)
        if not selected_doc_local:
            await update.message.reply_text("No document selected or available.")
            user_screenshot_state.pop(user_id, None)
            return
        try:
            images = convert_from_path(selected_doc_local, first_page=state['page'], last_page=state['page'])
            img = images[0]
            if crop_box:
                img = img.crop(crop_box)
            import io
            from telegram import InputMediaPhoto
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(img)
            watermark_text = "VIEW ONLY"
            try:
                font = ImageFont.truetype("arial.ttf", 24)
            except:
                font = ImageFont.load_default()
            img_width, img_height = img.size
            text_width = draw.textlength(watermark_text, font=font)
            draw.rectangle(
                [(img_width - text_width - 10, img_height - 35), (img_width - 5, img_height - 5)],
                fill=(0, 0, 0, 100)
            )
            draw.text(
                (img_width - text_width - 8, img_height - 30),
                watermark_text,
                fill=(255, 255, 255, 200),
                font=font
            )
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG', quality=85)
            img_buffer.seek(0)
            await update.message.reply_photo(
                photo=img_buffer,
                caption="Page screenshot - View only",
                has_spoiler=True,
                protect_content=True
            )
        except Exception as e:
            await update.message.reply_text(f"Error creating screenshot: {e}")
        user_screenshot_state.pop(user_id, None)

async def find_and_send_visual_content(update: Update, content_type: str, content_id: str):
    user_id = update.effective_user.id
    selected_doc_local = user_selected_doc.get(str(user_id))
    if not selected_doc_local:
        await update.message.reply_text("Please select a document first using /start")
        return
    await update.message.reply_chat_action(action="typing")
    try:
        chunks = await pdf_parser.extract_paragraphs_from_pdf(selected_doc_local)
        found_page = None
        found_context = ""
        escaped_id = content_id.replace('.', r'\.')
        search_patterns = [
            f"{content_type}\\s*{content_id}",
            f"{content_type}\\s*{escaped_id}",
            f"{content_id}",
            f"{content_type.capitalize()}\\s*{content_id}",
        ]
        import PyPDF2
        total_pages = 0
        try:
            with open(selected_doc_local, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                total_pages = len(reader.pages)
        except:
            total_pages = 100
        for i, chunk in enumerate(chunks):
            for pattern in search_patterns:
                if re.search(pattern, chunk, re.IGNORECASE):
                    estimated_page = max(1, min(total_pages, int((i / len(chunks)) * total_pages) + 1))
                    found_page = estimated_page
                    found_context = chunk[:300] + "..."
                    break
            if found_page:
                break
        if found_page:
            await update.message.reply_text(f"Found {content_type} {content_id} on page {found_page}. Generating screenshot...")
            from pdf2image import convert_from_path
            from PIL import ImageDraw, ImageFont
            import io
            images = convert_from_path(selected_doc_local, first_page=found_page, last_page=found_page)
            img = images[0]
            draw = ImageDraw.Draw(img)
            watermark_text = f"{content_type.upper()} {content_id} - VIEW ONLY"
            try:
                font = ImageFont.truetype("arial.ttf", 20)
            except:
                font = ImageFont.load_default()
            img_width, img_height = img.size
            text_width = draw.textlength(watermark_text, font=font)
            draw.rectangle(
                [(img_width - text_width - 10, img_height - 30), (img_width - 5, img_height - 5)],
                fill=(0, 0, 0, 120)
            )
            draw.text(
                (img_width - text_width - 8, img_height - 25),
                watermark_text,
                fill=(255, 255, 255, 200),
                font=font
            )
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG', quality=90)
            img_buffer.seek(0)
            await update.message.reply_photo(
                photo=img_buffer,
                caption=f"{content_type.capitalize()} {content_id} from page {found_page}\n\n{found_context}",
                has_spoiler=True,
                protect_content=True
            )
        else:
            await update.message.reply_text(
                f"Sorry, I couldn't find {content_type} {content_id} in the selected document. Try using /screenshot to manually browse pages."
            )
    except Exception as e:
        await update.message.reply_text(f"Error searching for {content_type} {content_id}: {e}")

async def main_message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_question = update.message.text or ""
    visual_request = extract_figure_table_request(user_question)
    if visual_request:
        content_type, content_id = visual_request
        await find_and_send_visual_content(update, content_type, content_id)
        return
    if user_id in user_screenshot_state:
        await handle_screenshot_dialog(update, context)
    elif is_follow_up(update, user_question):
        last_context = user_last_context.get(user_id)
        if last_context:
            typing_task = asyncio.create_task(show_typing_while_processing(update, 25))
            try:
                answer = await ask_ollama(user_question, last_context)
            finally:
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass
            max_length = 4096
            for i in range(0, len(answer), max_length):
                await update.message.reply_text(answer[i:i+max_length])
    else:
        await handle_message(update, context)