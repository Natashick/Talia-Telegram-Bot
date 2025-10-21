# vector_store.py

import chromadb
from chromadb.config import Settings
import os
import logging
import hashlib
import time
from typing import List, Dict, Optional, Tuple

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VectorStore:
    """Optimierter Vector Store für ChromaDB mit Batch-Verarbeitung"""
    
    def __init__(self, persist_directory: str = "./chroma_db", chunk_size: int = 1000, chunk_overlap: int = 200, batch_size: int = 256):
        """
        Initialisiert den Vector Store
        
        Args:
            persist_directory: Verzeichnis für persistente Speicherung
            chunk_size: Größe der Text-Chunks
            chunk_overlap: Überlappung zwischen Chunks
            batch_size: Größe der Batch-Verarbeitung
        """
        self.persist_directory = persist_directory
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.batch_size = batch_size
        self.seen_hashes = set()
        
        # ChromaDB-Client initialisieren
        try:
            self.client = chromadb.PersistentClient(
                path=persist_directory,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            self.collection = self.client.get_or_create_collection(
                name="pdf_chunks",
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"Vector Store initialisiert in: {persist_directory}")
            logger.info(f"Chunk-Größe: {chunk_size}, Overlap: {chunk_overlap}")
            logger.info(f"Batch-Größe: {batch_size}")
        except Exception as e:
            logger.error(f"Fehler bei der Initialisierung des Vector Stores: {e}")
            raise

    def add_document(self, doc_id: str, text: str, metadata: Optional[Dict] = None) -> bool:
        """
        Fügt ein Dokument zum Vector Store hinzu (Batch-Verarbeitung)
        
        Args:
            doc_id: Eindeutige Dokument-ID
            text: Dokumententext
            metadata: Zusätzliche Metadaten
            
        Returns:
            True wenn erfolgreich hinzugefügt
        """
        try:
            # Dokument in Chunks aufteilen
            chunks = self._split_text_into_chunks(text)
            
            # Batch-Verarbeitung vorbereiten
            doc_batch = []
            meta_batch = []
            id_batch = []
            
            total_added = 0
            
            for i, chunk in enumerate(chunks):
                # Qualitätsprüfung
                if not self._passes_quality_check(chunk):
                    logger.debug(f"Chunk {i} von {doc_id} hat Qualitätsprüfung nicht bestanden")
                    continue
                
                # Duplikatprüfung
                chunk_hash = self._calculate_chunk_hash(chunk)
                if chunk_hash in self.seen_hashes:
                    logger.debug(f"Chunk {i} von {doc_id} ist ein Duplikat")
                    continue
                
                # Eindeutige ID mit SHA1-Hash des Pfads
                unique_id = self._generate_unique_id(doc_id, i)
                
                # Chunk zum Batch hinzufügen
                doc_batch.append(chunk)
                meta_batch.append({
                    "doc_id": doc_id,
                    "chunk_id": unique_id,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "chunk_hash": chunk_hash,
                    **(metadata or {})
                })
                id_batch.append(unique_id)
                
                # Hash als gesehen markieren
                self.seen_hashes.add(chunk_hash)
                
                # Batch voll - füge hinzu
                if len(doc_batch) >= self.batch_size:
                    success = self._add_batch(doc_batch, meta_batch, id_batch)
                    if success:
                        total_added += len(doc_batch)
                        logger.info(f"Batch hinzugefügt: {len(doc_batch)} Chunks")
                    else:
                        logger.error(f"Fehler beim Hinzufügen des Batches")
                        return False
                    
                    # Batches leeren
                    doc_batch, meta_batch, id_batch = [], [], []
            
            # Verbleibende Chunks hinzufügen
            if doc_batch:
                success = self._add_batch(doc_batch, meta_batch, id_batch)
                if success:
                    total_added += len(doc_batch)
                    logger.info(f"Letzten Batch hinzugefügt: {len(doc_batch)} Chunks")
                else:
                    logger.error(f"Fehler beim Hinzufügen des letzten Batches")
                    return False
            
            logger.info(f"Dokument {doc_id} erfolgreich hinzugefügt: {total_added} Chunks von {len(chunks)}")
            return True
            
        except Exception as e:
            logger.error(f"Fehler beim Hinzufügen von Dokument {doc_id}: {e}")
            return False

    def _add_batch(self, documents: List[str], metadatas: List[Dict], ids: List[str]) -> bool:
        """
        Fügt einen Batch von Chunks hinzu mit Retry-Mechanismus
        
        Args:
            documents: Liste der Dokumente
            metadatas: Liste der Metadaten
            ids: Liste der IDs
            
        Returns:
            True wenn erfolgreich hinzugefügt
        """
        max_retries = 3
        backoff_time = 1
        
        for attempt in range(max_retries):
            try:
                self.collection.add(
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids
                )
                return True
                
            except Exception as e:
                logger.warning(f"Batch-Add fehlgeschlagen (Versuch {attempt + 1}/{max_retries}): {e}")
                
                if attempt < max_retries - 1:
                    # Warte und versuche es erneut
                    time.sleep(backoff_time)
                    backoff_time *= 2
                    
                    # Versuche Reconnect
                    try:
                        self._reconnect_client()
                    except Exception as reconnect_error:
                        logger.error(f"Reconnect fehlgeschlagen: {reconnect_error}")
                else:
                    logger.error(f"Alle Versuche fehlgeschlagen")
                    return False
        
        return False

    def _reconnect_client(self):
        """Versucht eine neue Verbindung zum ChromaDB-Client herzustellen"""
        try:
            logger.info("Versuche ChromaDB-Client neu zu verbinden...")
            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            self.collection = self.client.get_or_create_collection(
                name="pdf_chunks",
                metadata={"hnsw:space": "cosine"}
            )
            logger.info("ChromaDB-Client erfolgreich neu verbunden")
        except Exception as e:
            logger.error(f"Reconnect fehlgeschlagen: {e}")
            raise

    def _generate_unique_id(self, doc_id: str, chunk_index: int) -> str:
        """
        Generiert eine eindeutige ID mit SHA1-Hash des vollständigen Pfads
        
        Args:
            doc_id: Dokument-ID
            chunk_index: Chunk-Index
            
        Returns:
            Eindeutige ID
        """
        try:
            # Vollständigen Pfad verwenden
            full_path = os.path.abspath(doc_id)
            path_hash = hashlib.sha1(full_path.encode()).hexdigest()[:8]
            return f"{path_hash}_chunk_{chunk_index}"
        except Exception:
            # Fallback auf einfache ID
            return f"{doc_id}_chunk_{chunk_index}"

    def _calculate_chunk_hash(self, chunk: str) -> str:
        """
        Berechnet SHA1-Hash eines Chunks für Duplikatprüfung
        
        Args:
            chunk: Chunk-Text
            
        Returns:
            SHA1-Hash
        """
        return hashlib.sha1(chunk.encode('utf-8')).hexdigest()

    def _passes_quality_check(self, chunk: str) -> bool:
        """
        Erweiterte Qualitätsprüfung für Chunks
        
        Args:
            chunk: Zu prüfender Chunk
            
        Returns:
            True wenn Chunk Qualitätsprüfung bestanden hat
        """
        if not chunk or len(chunk.strip()) == 0:
            return False
        
        # Mindestlänge (Zeichen)
        if len(chunk.strip()) < 100:
            return False
        
        # Wortanzahl
        words = chunk.split()
        if len(words) < 10:
            return False
        
        # Alphabetischer Anteil
        alpha_chars = sum(c.isalpha() for c in chunk)
        total_chars = len(chunk)
        if total_chars > 0 and alpha_chars / total_chars < 0.3:
            return False
        
        # Durchschnittliche Wortlänge
        if words:
            avg_word_length = sum(len(word) for word in words) / len(words)
            if avg_word_length < 2.0:
                return False
        
        return True

    def _split_text_into_chunks(self, text: str) -> List[str]:
        """
        Teilt Text in Chunks mit Overlap auf
        
        Args:
            text: Zu teilender Text
            
        Returns:
            Liste der Text-Chunks
        """
        words = text.split()
        chunks = []
        
        if len(words) <= self.chunk_size:
            chunks.append(text)
        else:
            start = 0
            while start < len(words):
                end = min(start + self.chunk_size, len(words))
                chunk = " ".join(words[start:end])
                chunks.append(chunk)
                
                # Overlap für nächsten Chunk
                start = end - self.chunk_overlap
                if start >= len(words):
                    break
        
        return chunks

    def search(self, query: str, n_results: int = 5, similarity_threshold: float = 0.15) -> List[Dict]:
        """
        Sucht nach relevanten Dokumententeilen
        
        Args:
            query: Suchanfrage
            n_results: Anzahl der Ergebnisse
            similarity_threshold: Mindest-Ähnlichkeit (0.0-1.0)
            
        Returns:
            Liste der relevanten Chunks mit Metadaten
        """
        try:
            # Suche in ChromaDB
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results * 2,  # Mehr Ergebnisse für Filterung
                include=["metadatas", "distances", "documents"]
            )
            
            # Ergebnisse filtern und formatieren
            filtered_results = []
            
            for i, (metadata, distance, document) in enumerate(zip(
                results['metadatas'][0],
                results['distances'][0],
                results['documents'][0]
            )):
                # Distance zu Similarity Score konvertieren (ChromaDB verwendet L2-Distanz)
                similarity_score = 1.0 / (1.0 + distance)
                
                # Nur Ergebnisse über dem Threshold
                if similarity_score >= similarity_threshold:
                    filtered_results.append({
                        "doc_id": metadata.get("doc_id", ""),
                        "chunk_id": metadata.get("chunk_id", ""),
                        "chunk_index": metadata.get("chunk_index", 0),
                        "text": document,
                        "similarity_score": similarity_score,
                        "metadata": metadata
                    })
            
            # Nach Similarity Score sortieren
            filtered_results.sort(key=lambda x: x["similarity_score"], reverse=True)
            
            # Nur die besten Ergebnisse zurückgeben
            final_results = filtered_results[:n_results]
            
            logger.info(f"Suche nach '{query}': {len(final_results)} relevante Chunks gefunden")
            scores = [f"{r['similarity_score']:.3f}" for r in final_results[:3]]
            logger.info(f"Beste Similarity Scores: {scores}")
            
            return final_results
            
        except Exception as e:
            logger.error(f"Fehler bei der Suche: {e}")
            return []

    def get_combined_context(self, query: str, max_chunks: int = 4) -> Tuple[str, List[Dict]]:
        """
        Kombiniert mehrere relevante Chunks zu einem Kontext
        
        Args:
            query: Suchanfrage
            max_chunks: Maximale Anzahl Chunks
            
        Returns:
            Tuple aus (kombinierter Kontext, Chunk-Informationen)
        """
        chunks = self.search(query, n_results=max_chunks)
        
        if not chunks:
            return "Keine relevanten Informationen gefunden.", []
        
        # Kontext aus Chunks zusammenbauen
        context_parts = []
        for chunk in chunks:
            context_parts.append(
                f"--- CHUNK_START (Score: {chunk['similarity_score']:.3f}) ---\n"
                f"{chunk['text']}\n"
                f"--- CHUNK_END ---"
            )
        
        combined_context = "\n\n".join(context_parts)
        
        return combined_context, chunks

    def has_document(self, doc_id: str) -> bool:
        """
        Prüft, ob es bereits Chunks für ein bestimmtes Dokument gibt
        """
        try:
            result = self.collection.get(where={"doc_id": doc_id}, limit=1, include=["metadatas"])
            return bool(result and result.get("ids"))
        except Exception as e:
            logger.error(f"Fehler bei has_document({doc_id}): {e}")
            return False

    def search_in_document(self, query: str, doc_id: str, n_results: int = 5, similarity_threshold: float = 0.15) -> List[Dict]:
        """
        Sucht nach relevanten Chunks innerhalb eines spezifischen Dokuments
        """
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results * 2,
                where={"doc_id": doc_id},
                include=["metadatas", "distances", "documents"]
            )

            filtered_results = []
            for metadata, distance, document in zip(
                results.get('metadatas', [[]])[0],
                results.get('distances', [[]])[0],
                results.get('documents', [[]])[0]
            ):
                similarity_score = 1.0 / (1.0 + distance)
                if similarity_score >= similarity_threshold:
                    filtered_results.append({
                        "doc_id": metadata.get("doc_id", ""),
                        "chunk_id": metadata.get("chunk_id", ""),
                        "chunk_index": metadata.get("chunk_index", 0),
                        "text": document,
                        "similarity_score": similarity_score,
                        "metadata": metadata
                    })

            filtered_results.sort(key=lambda x: x["similarity_score"], reverse=True)
            final_results = filtered_results[:n_results]
            logger.info(f"Dokument '{doc_id}': {len(final_results)} relevante Chunks gefunden")
            return final_results
        except Exception as e:
            logger.error(f"Fehler bei der Dokument-Suche ({doc_id}): {e}")
            return []

    def get_combined_context_for_document(self, query: str, doc_id: str, max_chunks: int = 4) -> Tuple[str, List[Dict]]:
        """
        Kombiniert relevante Chunks eines bestimmten Dokuments zu einem Kontext
        """
        chunks = self.search_in_document(query, doc_id, n_results=max_chunks)
        if not chunks:
            return "Keine relevanten Informationen gefunden.", []

        context_parts = []
        for chunk in chunks:
            context_parts.append(
                f"--- CHUNK_START (Score: {chunk['similarity_score']:.3f}) ---\n"
                f"{chunk['text']}\n"
                f"--- CHUNK_END ---"
            )
        combined_context = "\n\n".join(context_parts)
        return combined_context, chunks

    def get_document_info(self) -> Dict:
        """
        Gibt Informationen über den Vector Store zurück
        
        Returns:
            Dictionary mit Store-Informationen
        """
        try:
            count = self.collection.count()
            return {
                "total_chunks": count,
                "persist_directory": self.persist_directory,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
                "batch_size": self.batch_size,
                "unique_hashes": len(self.seen_hashes)
            }
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Store-Informationen: {e}")
            return {}

    def clear_all(self) -> bool:
        """
        Löscht alle Dokumente aus dem Vector Store
        
        Returns:
            True wenn erfolgreich gelöscht
        """
        try:
            self.client.reset()
            self.seen_hashes.clear()  # Hash-Cache leeren
            logger.info("Vector Store erfolgreich geleert")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Leeren des Vector Stores: {e}")
            return False

# Globale Instanz
vector_store = VectorStore()