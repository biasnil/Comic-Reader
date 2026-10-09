"""Manga Translator plugin: Koharu-style Japanese -> English page translation.

Runs as a helper process started by the reader (worker.py); see comicreader/core/translation.py
for the protocol and the cache it writes. Nothing here imports tkinter.
"""
__version__ = "0.1.0"
