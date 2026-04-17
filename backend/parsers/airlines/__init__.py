"""
Per-airline flight extractors.

Each airline module exposes an ``extract(email_msg, rule) -> list[dict]``
function.  The engine calls ``rule.extractor`` directly — this package is
a plain namespace; no dispatch table is needed here.
"""
