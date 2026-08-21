from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree


SUPPORTED_CHARACTER_DOCUMENT_SUFFIXES = {".md", ".txt", ".docx"}
_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def load_character_document(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"character context file not found: {path}")
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8-sig")
    if suffix == ".docx":
        return _read_docx_text(path)
    raise ValueError(f"unsupported character context file type: {path.suffix}")


def _read_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
    except KeyError as exc:
        raise ValueError(f"docx missing word/document.xml: {path}") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError(f"invalid docx file: {path}") from exc

    root = ElementTree.fromstring(document_xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{_WORD_NAMESPACE}p"):
        text_parts = [
            text_node.text or ""
            for text_node in paragraph.iter(f"{_WORD_NAMESPACE}t")
            if text_node.text
        ]
        paragraph_text = "".join(text_parts).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)
    return "\n".join(paragraphs)
