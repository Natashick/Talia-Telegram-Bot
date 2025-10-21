# pdf_parser.py

import PyPDF2
import pdf2image
import pytesseract
import re
import logging
import asyncio
from typing import List, Dict, Optional, Tuple
from PIL import Image
import os

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OptimizedPDFParser:
    """Optimierter PDF-Parser mit intelligenter OCR und asynchroner Verarbeitung"""
    
    def __init__(self):
        # OCR-Konfiguration
        self.default_dpi = 200
        self.fallback_dpi = 300
        self.min_text_length = 120  # Mindestlänge für gültigen Text
        self.psm_modes = [6, 3, 8]  # Verschiedene PSM-Modi zum Testen
        
        # Sprach-Konfiguration
        self.languages = ['eng', 'deu']  # Englisch + Deutsch
        
        logger.info("Optimierter PDF-Parser initialisiert")
        logger.info(f"Standard DPI: {self.default_dpi}, Fallback DPI: {self.fallback_dpi}")
        logger.info(f"PSM-Modi: {self.psm_modes}")
        logger.info(f"Sprachen: {self.languages}")

    async def extract_paragraphs_from_pdf(self, pdf_path: str) -> List[str]:
        try:
            logger.info(f"Starte PDF-Verarbeitung: {pdf_path}")
            
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                total_pages = len(pdf_reader.pages)
                logger.info(f"PDF hat {total_pages} Seiten")
            
            tasks = []
            for page_num in range(total_pages):
                task = self._process_page_async(pdf_path, page_num, total_pages)
                tasks.append(task)
            
            page_texts = await asyncio.gather(*tasks, return_exceptions=True)
            
            paragraphs = []
            for i, result in enumerate(page_texts):
                if isinstance(result, Exception):
                    logger.error(f"Fehler bei Seite {i+1}: {result}")
                    continue
                if result and len(result.strip()) > 0:
                    paragraphs.append(result.strip())
            
            logger.info(f"Erfolgreich {len(paragraphs)} Absätze extrahiert")
            return paragraphs
            
        except Exception as e:
            logger.error(f"Fehler bei PDF-Verarbeitung: {e}")
            return []

    async def _process_page_async(self, pdf_path: str, page_num: int, total_pages: int) -> Optional[str]:
        try:
            logger.debug(f"Verarbeite Seite {page_num + 1}/{total_pages}")
            page_text = await self._extract_text_normal(pdf_path, page_num)
            
            if self._is_text_sufficient(page_text):
                logger.debug(f"Seite {page_num + 1}: Normaler Text ausreichend")
                return page_text
            
            logger.info(f"Seite {page_num + 1}: Starte OCR (Text zu kurz)")
            ocr_text = await self._extract_text_ocr(pdf_path, page_num)
            
            if self._is_text_sufficient(ocr_text):
                logger.debug(f"Seite {page_num + 1}: OCR erfolgreich")
                return ocr_text
            else:
                logger.warning(f"Seite {page_num + 1}: OCR lieferte unzureichenden Text")
                return page_text if page_text else ocr_text
                
        except Exception as e:
            logger.error(f"Fehler bei Seite {page_num + 1}: {e}")
            return None

    async def _extract_text_normal(self, pdf_path: str, page_num: int) -> str:
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                page = pdf_reader.pages[page_num]
                text = page.extract_text()
                return text or ""
        except Exception as e:
            logger.error(f"Fehler beim normalen Text-Extrakt: {e}")
            return ""

    async def _extract_text_ocr(self, pdf_path: str, page_num: int) -> str:
        """Extrahiert Text mit OCR; rendert für jede getestete DPI neu."""
        try:
            best_text = ""
            best_quality = 0.0
            
            # Teste mehrere DPI-Werte (rendere pro DPI)
            for dpi in [self.default_dpi, self.fallback_dpi]:
                try:
                    images = await asyncio.to_thread(
                        pdf2image.convert_from_path,
                        pdf_path,
                        first_page=page_num + 1,
                        last_page=page_num + 1,
                        dpi=dpi,
                        fmt='PNG'
                    )
                except Exception as e:
                    logger.debug(f"pdf2image convert failed for dpi {dpi}: {e}")
                    images = []
                
                if not images:
                    logger.warning(f"Keine Bilder für Seite {page_num + 1} bei DPI {dpi} generiert")
                    continue
                
                image = images[0]
                for psm in self.psm_modes:
                    try:
                        text = await asyncio.to_thread(
                            pytesseract.image_to_string,
                            image,
                            lang='+'.join(self.languages),
                            config=f'--psm {psm}'
                        )
                        quality = self._evaluate_ocr_quality(text)
                        if quality > best_quality:
                            best_quality = quality
                            best_text = text
                        logger.debug(f"PSM {psm}, DPI {dpi}: Qualität {quality:.2f}")
                    except Exception as e:
                        logger.debug(f"OCR fehlgeschlagen für PSM {psm}, DPI {dpi}: {e}")
                        continue
                
                image.close()
                del images
            
            return best_text
        except Exception as e:
            logger.error(f"Fehler bei OCR für Seite {page_num + 1}: {e}")
            return ""

    def _is_text_sufficient(self, text: str) -> bool:
        if not text:
            return False
        cleaned = re.sub(r'\s+', '', text)
        if len(cleaned) < self.min_text_length:
            return False
        alphanumeric = re.sub(r'[^A-Za-z0-9ÄÖÜäöüß]', '', cleaned)
        if len(alphanumeric) < self.min_text_length * 0.5:
            return False
        words = text.split()
        if len(words) < 20:
            return False
        return True

    def _evaluate_ocr_quality(self, text: str) -> float:
        if not text:
            return 0.0
        cleaned = re.sub(r'\s+', '', text)
        if len(cleaned) == 0:
            return 0.0
        alphanumeric = re.sub(r'[^A-Za-z0-9ÄÖÜäöüß]', '', cleaned)
        char_ratio = len(alphanumeric) / len(cleaned)
        words = text.split()
        avg_word_length = sum(len(word) for word in words) / len(words) if words else 0
        quality = (char_ratio * 0.4 + 
                  min(len(words) / 100, 1.0) * 0.3 + 
                  min(avg_word_length / 8, 1.0) * 0.3)
        return min(quality, 1.0)

    def extract_paragraphs_from_pdf_sync(self, pdf_path: str) -> List[str]:
        """Synchrone Version für Kompatibilität (versucht asyncio.run zuerst)."""
        try:
            return asyncio.run(self.extract_paragraphs_from_pdf(pdf_path))
        except RuntimeError:
            # Fallback: wenn bereits ein laufender Event Loop existiert
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.extract_paragraphs_from_pdf(pdf_path))

# Globale Instanz
pdf_parser = OptimizedPDFParser()

def extract_paragraphs_from_pdf(pdf_path: str) -> List[str]:
    return pdf_parser.extract_paragraphs_from_pdf_sync(pdf_path)