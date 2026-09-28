import urllib.request

try:
    urllib.request.urlopen("http://127.0.0.1:11434", timeout=2)
    print("ollama_up")
except Exception as exc:  # noqa: BLE001
    print(f"ollama_down:{exc}")
