"""Constrained editing experiment. Model output is untrusted text, never code.

Plans can replace only a literal earlier span with a literal correction stated
later in the same source. Ordinary no-correction text never enters this path.
This checks structural evidence; it does not guarantee semantic equivalence.
"""
import re

WORD = re.compile(r"[\w]+(?::[\d]{0,2})?", re.UNICODE)
CUE = re.compile(r"\b(?:(?:ой|о|а)\s*,?\s*(?:нет|не)|нет|точнее|поправка|хотя\s+давай)\b", re.I)


def tokens(text):
    return [(m.group().casefold().replace("ё", "е"), m.start(), m.end()) for m in WORD.finditer(text)]


def occurrences(text, needle):
    haystack, target = tokens(text), tokens(needle)
    if not target:
        return []
    wanted = [w[0] for w in target]
    n = len(wanted)
    return [(haystack[i][1], haystack[i+n-1][2]) for i in range(len(haystack)-n+1)
            if [w[0] for w in haystack[i:i+n]] == wanted]


def inside_quote(text, position):
    # Protect explicit quoted spans. ASR may omit quotes: that limitation remains.
    stack = []
    for char in text[:position]:
        if char in '«“': stack.append(char)
        elif char in '»”' and stack: stack.pop()
        elif char == '"':
            if stack and stack[-1] == '"': stack.pop()
            else: stack.append(char)
    return bool(stack)


def has_correction(text):
    return any(not inside_quote(text, m.start()) for m in CUE.finditer(text))


def apply_plan(source, plan):
    edits = plan.get("edits") if isinstance(plan, dict) else None
    if not isinstance(edits, list) or len(edits) > 8:
        return source, [{"status":"rejected", "reason":"invalid_plan"}]
    current, audit = source, []
    # Cue order is taken from source evidence, not invented numeric offsets.
    def cue_order(edit):
        if not isinstance(edit, dict) or not isinstance(edit.get("cue"), str): return len(source)
        found = occurrences(source, edit["cue"])
        return found[0][0] if found else len(source)
    for edit in sorted(edits, key=cue_order):
        if not isinstance(edit, dict) or any(not isinstance(edit.get(k), str) for k in ["old", "new", "cue"]):
            audit.append({"status":"rejected", "reason":"invalid_edit"}); continue
        old, new, cue = (edit[k].strip() for k in ["old", "new", "cue"])
        if not old or not new or len(tokens(old)) > 4 or len(tokens(new)) > 4:
            audit.append({"status":"rejected", "reason":"span_size", "edit":edit}); continue
        cues = occurrences(current, cue)
        if len(cues) != 1:
            audit.append({"status":"rejected", "reason":"cue_not_unique_literal", "edit":edit}); continue
        cue_start, cue_end = cues[0]
        cue_source = current[cue_start:cue_end]
        if not CUE.match(cue_source) or inside_quote(current, cue_start):
            audit.append({"status":"rejected", "reason":"not_explicit_cue", "edit":edit}); continue
        new_matches = occurrences(cue_source, new)
        old_matches = occurrences(current[:cue_start], old)
        if not new_matches or not old_matches:
            audit.append({"status":"rejected", "reason":"missing_source_evidence", "edit":edit}); continue
        if new_matches[-1][1] != tokens(cue_source)[-1][2]:
            audit.append({"status":"rejected", "reason":"cue_contains_unrelated_tail", "edit":edit}); continue
        if any(t[0] in ["не", "нет", "отправь", "передай", "создай", "проверь", "давай", "нужно", "я"] for t in tokens(old)):
            audit.append({"status":"rejected", "reason":"protected_statement_in_anchor", "edit":edit}); continue
        old_start, old_end = old_matches[-1]
        if inside_quote(current, old_start) or len(tokens(current[old_end:cue_start])) > 32:
            audit.append({"status":"rejected", "reason":"anchor_too_far_or_quoted", "edit":edit}); continue
        # Copy replacement spelling from the source; do not trust generated spelling.
        new_start, new_end = new_matches[-1]
        replacement = cue_source[new_start:new_end]
        gap = current[old_end:cue_start]
        if all(c.isspace() or c in '.,' for c in gap) and current[cue_end:cue_end+1] in [',', '.', ';', ':']:
            gap = ''
        current = current[:old_start] + replacement + gap + current[cue_end:]
        current = re.sub(r"\s+([,.!?;:])", r"\1", current)
        current = re.sub(r"([.!?])\s*\1", r"\1", current)
        current = re.sub(r"\s{2,}", " ", current).strip()
        audit.append({"status":"applied", "edit":edit})
    # A partially applied plan can leave a different meaning. Treat the entire
    # proposal as one transaction; a rejection always preserves the source.
    if any(item["status"] == "rejected" for item in audit):
        for item in audit:
            if item["status"] == "applied": item["status"] = "rolled_back"
        return source, audit
    return current, audit


def normalize_explicit_time(text):
    def time_value(match):
        hour = int(match[1]); period = match[2].casefold()
        if (period in ["дня", "вечера"] and 7 <= hour <= 11) or (period == "утра" and hour >= 12):
            return match[0]
        if period in ["дня", "вечера"] and 1 <= hour <= 6: hour += 12
        return f"в {hour:02d}:00"
    return re.sub(r"\bв\s+([01]?\d|2[0-3]):?\s+(дня|вечера|утра|час|часа|часов)\b", time_value, text, flags=re.I)


def conservative_surface(text):
    # ASR already supplies punctuation; only tidy whitespace and initial case.
    text = normalize_explicit_time(text.strip())
    return text[:1].upper() + text[1:] if text else ""


SCHEMA = {
    "type":"object", "properties":{"edits":{"type":"array", "maxItems":8,
        "items":{"type":"object", "properties":{k:{"type":"string"} for k in ["old", "new", "cue"]},
                 "required":["old", "new", "cue"], "additionalProperties":False}}},
    "required":["edits"], "additionalProperties":False,
}
