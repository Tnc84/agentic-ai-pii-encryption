from pathlib import Path

from crypto.keys import derive_key
from crypto.vault import decrypt_alias_map, encrypt_alias_map
from db.migrate import ensure_migrated, upgrade_head
from pii.regex_detect import detect_regex

upgrade_head()
ensure_migrated()
print("db_migrated")

assert len(derive_key("pass", b"0123456789abcdef")) == 32
print("keys_ok")

text = Path("examples/sample.txt").read_text(encoding="utf-8")
spans = detect_regex(text)
print("spans", [(s.entity_type, s.value) for s in spans])

try:
    from pii.presidio_detect import detect_presidio

    p_spans = detect_presidio(text)
    print("presidio", len(p_spans))
except Exception as exc:
    print("presidio_skip", exc)

salt, nonce, ciphertext = encrypt_alias_map({"a@b.com": "TOKEN_EMAIL_1"}, "test-pass")
assert decrypt_alias_map(salt, nonce, ciphertext, "test-pass") == {"a@b.com": "TOKEN_EMAIL_1"}
print("crypto_ok")

from agents.graph import build_graph, get_checkpointer

build_graph(checkpointer=get_checkpointer())
print("graph_ok")
