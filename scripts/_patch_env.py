from pathlib import Path

p = Path(".env")
text = p.read_text(encoding="utf-8") if p.exists() else ""
additions = {
    "CURSOR_RUNTIME": "auto",
    "CURSOR_SSL_VERIFY": "true",
    "CURSOR_GITHUB_REPO": "",
    "CURSOR_GITHUB_REF": "master",
    "CURSOR_CLOUD_TIMEOUT_SEC": "180",
    "VISION_AGENT_PROVIDER": "cursor",
}
force = {
    "CURSOR_RUNTIME",
    "CURSOR_SSL_VERIFY",
    "CURSOR_CLOUD_TIMEOUT_SEC",
    "VISION_AGENT_PROVIDER",
}
lines = text.splitlines()
keys_present = set()
out = []
for line in lines:
    if "=" in line and not line.strip().startswith("#"):
        k = line.split("=", 1)[0].strip()
        keys_present.add(k)
        if k in force:
            out.append(f"{k}={additions[k]}")
            continue
        out.append(line)
    else:
        out.append(line)
for k, v in additions.items():
    if k not in keys_present:
        out.append(f"{k}={v}")
p.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print("env updated")
