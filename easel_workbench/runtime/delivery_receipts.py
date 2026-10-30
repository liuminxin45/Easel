"""Read explicit final receipt objects from streamed assistant text.

Progress text may precede the final JSON object. Extra recognition is limited
to line-start objects with an explicit delivery/production receipt field; it
does not search arbitrary nested JSON, prose paths, or directories.
"""
import json
import re


def structured_receipts(reply):
    if not isinstance(reply, str):
        return
    seen = set()
    for block in [reply, *re.findall(r'```(?:json)?\s*\n(.*?)\n```', reply, re.S)]:
        try:
            value = json.loads(block)
        except (ValueError, TypeError):
            continue
        if isinstance(value, (dict, list)):
            marker = json.dumps(value, sort_keys=True, ensure_ascii=False)
            if marker not in seen:
                seen.add(marker)
                yield value
    decoder = json.JSONDecoder()
    for match in re.finditer(r'(?m)^[ \t]*(?=\{)', reply):
        try:
            value, end = decoder.raw_decode(reply, match.end())
        except ValueError:
            continue
        # The complete JSON must end its line, not be an inline prose sample.
        if reply[end:].split('\n', 1)[0].strip():
            continue
        if not isinstance(value, dict) or not ({'deliverables', 'production_result'} & value.keys()):
            continue
        value = {key: value[key] for key in ('deliverables', 'production_result') if key in value}
        marker = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if marker not in seen:
            seen.add(marker)
            yield value
