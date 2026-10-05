from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path


class MigrationError(Exception):
    pass


RESERVED = set("abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while var record sealed permits yield true false null constructor prototype __proto__ name length arguments await delete export function let typeof with from get set".split())
RESERVED -= {"name", "length", "from", "get", "set"}


def name(value: str, style: str = "camel") -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", ascii_value)
    words = [w.lower() for w in words] or ["field"]
    result = words[0] + "".join(w.title() for w in words[1:])
    if result[0].isdigit():
        result = "n" + result
    if result in RESERVED:
        result += "Value"
    if style == "pascal":
        return result[0].upper() + result[1:]
    if style == "kebab":
        return "-".join(words) if not words[0][0].isdigit() else "n-" + "-".join(words)
    return result


def unique_names(values: list[str], style: str = "camel") -> dict[str, str]:
    result: dict[str, str] = {}
    used: set[str] = set()
    for value in values:
        if value in result:
            raise MigrationError(f"Ismétlődő Oracle objektumnév: {value}")
        base = name(value, style)
        candidate = base
        count = 2
        while candidate.lower() in used:
            candidate = base + str(count)
            count += 1
        used.add(candidate.lower())
        result[value] = candidate
    return result


def identifier(value: str, qualified: bool = False) -> str:
    pattern = r"[A-Za-z][A-Za-z0-9_$#]*(?:\.[A-Za-z][A-Za-z0-9_$#]*)?" if qualified else r"[A-Za-z][A-Za-z0-9_$#]*"
    if not re.fullmatch(pattern, value):
        raise MigrationError(f"Nem támogatott SQL azonosító: {value!r}; idézett/dinamikus SQL-hez adapter kell.")
    return value


def jstr(value: str) -> str:
    # ASCII escapes also keep Java and JavaScript source safe for unusual labels.
    return json.dumps(value, ensure_ascii=True)


def java_text_block(value: str, indent: str = '                ') -> str:
    """Readable Java 11 string literal (no text block): one concatenated line per source line."""
    lines = value.split('\n')
    parts = [jstr(line + ('\n' if i < len(lines) - 1 else '')) for i, line in enumerate(lines)]
    return ('\n' + indent + '+ ').join(parts) if parts else '""'


def read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        raise MigrationError(f"Nem olvasható JSON: {path}: {exc}") from exc
    if not isinstance(obj, dict):
        raise MigrationError(f"JSON objektum szükséges: {path}")
    return obj


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()


# Forms2XML escapes its own character references: a line break in TriggerText,
# WhereClause or ProgramUnitText arrives as the literal text "&#10;" after XML
# parsing. Only whitespace references are restored; anything else stays as is.
LINE_ESCAPE = re.compile(r"&#([xX][0-9a-fA-F]{1,8}|[0-9]{1,8});")


def decode_line_escapes(text: str) -> str:
    def replace(match):
        value = match.group(1)
        number = int(value[1:], 16) if value[:1] in "xX" else int(value)
        return chr(number) if number in (9, 10, 13) else match.group()
    return LINE_ESCAPE.sub(replace, text or "")
