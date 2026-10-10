"""Bubble Reader plugin: reads a comic's speech bubbles aloud in reading order (Kokoro voices).

Runs as a helper process started by the reader (worker.py); see comicreader/core/bubbles.py for
the protocol. Shares detection and OCR code with the Manga Translator (plugins/common).
"""
__version__ = "0.1.0"
