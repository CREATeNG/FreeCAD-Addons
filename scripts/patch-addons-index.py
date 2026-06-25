#!/usr/bin/env python3
"""Patch Data/Index.json for a freecad-mcp-bridge release. Internal CI helper.

Writes minimal hunks: only the target entry block is added or field values replaced.
The rest of Index.json is left byte-for-byte unchanged.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


META_KEYS = {"$schema", "_meta"}


def target_fields(*, tag: str, repo_url: str) -> dict[str, object]:
    return {
        "repository": repo_url,
        "git_ref": tag,
        "branch_display_name": tag,
        "zip_url": f"{repo_url}/archive/refs/tags/{tag}.zip",
        "curated": True,
    }


def json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def entry_block(entry_id: str, fields: dict[str, object], indent: str = "  ") -> str:
    item_indent = indent * 2
    field_indent = indent * 3
    lines = [
        f'{indent}"{entry_id}": [',
        f"{item_indent}{{",
        f'{field_indent}"repository": {json_string(str(fields["repository"]))},',
        f'{field_indent}"git_ref": {json_string(str(fields["git_ref"]))},',
        f'{field_indent}"branch_display_name": {json_string(str(fields["branch_display_name"]))},',
        f'{field_indent}"zip_url": {json_string(str(fields["zip_url"]))},',
        f'{field_indent}"curated": true',
        f"{item_indent}}}",
        f"{indent}],",
    ]
    return "\n".join(lines)


def find_entry_block(text: str, entry_id: str) -> tuple[int, int] | None:
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)"{re.escape(entry_id)}"\s*:\s*\[(?:.|\n)*?^\1\],',
    )
    match = pattern.search(text)
    if not match:
        return None
    return match.start(), match.end()


def replace_json_string_field(block: str, field: str, value: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)"{re.escape(field)}"\s*:\s*(?P<quote>")(?P<val>(?:\\.|[^"\\])*)(?P=quote)\s*,?\s*$'
    )
    match = pattern.search(block)
    if not match:
        return block, False
    replacement = (
        f'{match.group("indent")}"{field}": {json_string(value)},'
    )
    return block[: match.start()] + replacement + block[match.end() :], True


def replace_curated_field(block: str, value: bool) -> tuple[str, bool]:
    pattern = re.compile(
        r'(?m)^(?P<indent>[ \t]*)"curated"\s*:\s*(?P<val>true|false)\s*,?\s*$'
    )
    match = pattern.search(block)
    if not match:
        return block, False
    literal = "true" if value else "false"
    if match.group("val") == literal:
        return block, False
    replacement = f'{match.group("indent")}"curated": {literal}'
    return block[: match.start()] + replacement + block[match.end() :], True


def patch_existing_block(block: str, fields: dict[str, object]) -> tuple[str, bool]:
    updated = block
    changed = False
    for key in ("repository", "git_ref", "branch_display_name", "zip_url"):
        updated, field_changed = replace_json_string_field(updated, key, str(fields[key]))
        changed = changed or field_changed
    updated, curated_changed = replace_curated_field(updated, bool(fields["curated"]))
    return updated, changed or curated_changed


def insert_position(text: str, entry_id: str) -> int:
    key_pattern = re.compile(r'(?m)^[ \t]*"([^"]+)"\s*:\s*\[')
    for match in key_pattern.finditer(text):
        key = match.group(1)
        if key in META_KEYS:
            continue
        if entry_id < key:
            return match.start()
    last_key = None
    for match in key_pattern.finditer(text):
        key = match.group(1)
        if key not in META_KEYS:
            last_key = match
    if last_key is None:
        raise ValueError("could not find insertion point in Index.json")
    # Insert after the closing ], of the last entry block.
    block_end = find_entry_block(text, last_key.group(1))
    if block_end is None:
        raise ValueError(f"could not locate block for {last_key.group(1)!r}")
    return block_end[1]


def patch_index_text(
    text: str,
    *,
    entry_id: str,
    tag: str,
    repo_url: str,
    allow_add: bool,
) -> tuple[str, bool]:
    fields = target_fields(tag=tag, repo_url=repo_url)
    span = find_entry_block(text, entry_id)
    if span is not None:
        start, end = span
        block = text[start:end]
        updated_block, changed = patch_existing_block(block, fields)
        if not changed:
            return text, False
        if not text.endswith("\n"):
            text += "\n"
        return text[:start] + updated_block + text[end:], True

    if not allow_add:
        raise ValueError(f"entry not found: {entry_id}")

    insert_at = insert_position(text, entry_id)
    block = entry_block(entry_id, fields)
    prefix = text[:insert_at]
    suffix = text[insert_at:]
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    updated = prefix + block + "\n" + suffix
    return updated, True


def main() -> int:
    if len(sys.argv) != 6:
        print(
            "usage: patch-addons-index.py <index.json> <entry_id> <tag> <repo_url> <allow_add>",
            file=sys.stderr,
        )
        return 2

    path = Path(sys.argv[1])
    entry_id = sys.argv[2]
    tag = sys.argv[3]
    repo_url = sys.argv[4].rstrip("/")
    allow_add = sys.argv[5].lower() == "true"

    original = path.read_text(encoding="utf-8")
    updated, changed = patch_index_text(
        original,
        entry_id=entry_id,
        tag=tag,
        repo_url=repo_url,
        allow_add=allow_add,
    )

    if changed:
        # Preserve upstream newline style (LF on FreeCAD/Addons; avoids noisy diffs).
        if "\r\n" in original and "\r\n" not in updated:
            updated = updated.replace("\n", "\r\n")
        path.write_text(updated, encoding="utf-8", newline="")
        print(f"Patched {entry_id} for {tag}")
    else:
        print(f"No changes needed for {entry_id} ({tag})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())