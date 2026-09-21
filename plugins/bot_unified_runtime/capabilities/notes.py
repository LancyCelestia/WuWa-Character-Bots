"""Compat shim: moved to domains/notes/capabilities/notes.py (v21r2 reorg W9)."""

from plugins.bot_unified_runtime.domains.notes.capabilities.notes import *
from plugins.bot_unified_runtime.domains.notes.capabilities.notes import (  # noqa: F401
    _NOTES_ADD_RE,
    _NOTES_BARE_RE,
    _NOTES_DELETE_RE,
    _NOTES_DONE_RE,
    _NOTES_LIST_RE,
    _NOTES_UNDO_EXPLICIT_RE,
    _NOTES_UNDO_NATURAL_RE,
    _NOTES_VIEW_RE,
    __all__,
    _images_root,
)
