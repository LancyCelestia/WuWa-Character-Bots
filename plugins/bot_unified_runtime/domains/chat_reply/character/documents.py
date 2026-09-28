from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

SUPPORTED_CHARACTER_DOCUMENT_SUFFIXES = {".md", ".txt", ".docx"}
_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# F-D（S-FIX-PERSONA-R2）：docx 解压炸弹体积闸。**常量硬编码、零新配置键**
# （config.py 本票禁碰，也不留无声旋钮）：
# * 源文件 8 MiB——角色文档合理上限的保守放大（正常人格资料 docx 实测远小于此；
#   既有真身 leg 只读单条目 document.xml，8 MiB 的容器已远超任何合理设定文档）；
# * 条目 32 MiB——document.xml 纯文本的极限宽余量（约千万字级，再大即拒）；
# * 两腿配合：先按中央目录**声明**尺寸在解压前拒（炸弹第一形态），读回后按
#   **实际**字节复核（声明可说谎）。改值须走裁定波，禁止就地放宽。
_DOCX_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_DOCX_MAX_ENTRY_BYTES = 32 * 1024 * 1024


def load_character_document(path: Path) -> str:
    # 异常消息只留文件名（F-B 同口径）：全路径不外泄进日志/回执。
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"character context file not found: {path.name}")
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8-sig")
    if suffix == ".docx":
        return _read_docx_text(path)
    raise ValueError(f"unsupported character context file type: {path.suffix}")


def _read_docx_text(path: Path) -> str:
    try:
        source_size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"character context file unreadable: {path.name}") from exc
    if source_size > _DOCX_MAX_SOURCE_BYTES:
        raise ValueError(f"docx source file too large: {path.name}")
    try:
        with zipfile.ZipFile(path) as archive:
            # 声明尺寸从**中央目录**（infolist）读、在 ``open()`` 的 lied-size 校正
            # 之前——解压炸弹的虚报形态正住在中央目录声明里；真实字节由读后复核兜底。
            infos = archive.infolist()
            declared = next(
                (i.file_size for i in infos if i.filename == "word/document.xml"),
                None,
            )
            if declared is None:
                raise ValueError(f"docx missing word/document.xml: {path.name}")
            if declared > _DOCX_MAX_ENTRY_BYTES:
                # 解压前按声明尺寸拒（炸弹形态：小容器解出巨型条目）。
                raise ValueError(f"docx entry too large: {path.name}")
            document_xml = archive.read("word/document.xml")
            if len(document_xml) > _DOCX_MAX_ENTRY_BYTES:
                raise ValueError(f"docx entry too large: {path.name}")
    except KeyError as exc:
        raise ValueError(f"docx missing word/document.xml: {path.name}") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError(f"invalid docx file: {path.name}") from exc

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
