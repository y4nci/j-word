from __future__ import annotations

import html
import re
import unicodedata

from bs4 import BeautifulSoup

_WORD_RE = re.compile(r"[a-z0-9äöüß+#]+")
_WS_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_BLOCK_TAGS = ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"]

_GERMAN_MARKERS = {
    "und", "die", "der", "das", "wir", "sie", "mit", "für", "ihre", "deine",
    "bei", "eine", "einen", "unser", "unsere", "aufgaben", "profil", "kenntnisse",
}
_ENGLISH_MARKERS = {
    "and", "the", "we", "you", "with", "for", "your", "our", "team",
    "experience", "skills", "requirements", "responsibilities",
}


def tokens(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def normalize_key(text: str) -> str:
    """Lowercase, strip accents/punctuation; used for dedupe keys."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", folded.lower()))


def html_to_text(raw_html: str) -> str:
    """Convert (possibly HTML-escaped) job description HTML into readable plain text."""
    if not raw_html:
        return ""
    unescaped = html.unescape(raw_html)
    soup = BeautifulSoup(unescaped, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert(0, "- ")
    # Only block elements break lines; inline tags (<b>, <a>, <span>) stay within the sentence.
    for block in soup.find_all(_BLOCK_TAGS):
        block.insert_before("\n")
        block.insert_after("\n")
    text = soup.get_text()
    text = _WS_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def detect_language(text: str) -> str | None:
    """Very small heuristic: 'de' or 'en' based on stopword counts."""
    words = tokens(text[:4000])
    if len(words) < 20:
        return None
    de = sum(w in _GERMAN_MARKERS for w in words)
    en = sum(w in _ENGLISH_MARKERS for w in words)
    if de == en == 0:
        return None
    return "de" if de > en else "en"


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + " …[truncated]"
