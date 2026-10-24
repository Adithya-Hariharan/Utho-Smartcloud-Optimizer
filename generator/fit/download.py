"""CP1: download public trace mirrors into data/external/ (gitignored) and write MANIFEST.json.

python -m generator.fit.download
"""
import hashlib
import json
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EXTERNAL = Path(__file__).resolve().parents[2] / "data" / "external"
HF = "https://huggingface.co"

# key -> (dataset repo, path inside repo)
SOURCES = {
    "bitbrains_5T": ("Salesforce/GiftEval", "bitbrains_fast_storage/5T/data-00000-of-00001.arrow"),
    "bitbrains_H": ("Salesforce/GiftEval", "bitbrains_fast_storage/H/data-00000-of-00001.arrow"),
    "azure_2017": ("Salesforce/lotsa_data", "azure_vm_traces_2017/data-00000-of-00022.arrow"),
    "alibaba_2018": ("Salesforce/lotsa_data", "alibaba_cluster_trace_2018/data-00000-of-00010.arrow"),
    "borg_2011": ("Salesforce/lotsa_data", "borg_cluster_data_2011/data-00005-of-00031.arrow"),
}
LICENSES = {
    "Salesforce/GiftEval": "GIFT-Eval mirror, Apache-2.0; original Bitbrains GWA-T-12 terms apply (research use)",
    "Salesforce/lotsa_data": "LOTSA mirror (CloudOps-TSF preprocessing); original Azure/Alibaba/Google trace terms apply",
}


def url_for(repo, path):
    return f"{HF}/datasets/{repo}/resolve/main/{path}"


def expected_size(repo, path):
    folder = path.rsplit("/", 1)[0]
    with urllib.request.urlopen(f"{HF}/api/datasets/{repo}/tree/main/{folder}", timeout=60) as r:
        for item in json.load(r):
            if item["path"] == path:
                return int(item["size"])
    raise RuntimeError(f"{path} not listed in {repo}")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def local_path(key):
    return EXTERNAL / f"{key}.arrow"


def main():
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for key, (repo, path) in SOURCES.items():
        size = expected_size(repo, path)
        dest = local_path(key)
        if not dest.exists() or dest.stat().st_size != size:
            subprocess.run(["curl", "-L", "--fail", "--retry", "5", "--retry-delay", "5", "-C", "-",
                            "-s", "-S", "-o", str(dest), url_for(repo, path)], check=True)
        manifest[key] = {
            "file": dest.name, "url": url_for(repo, path), "expected_size": size,
            "size": dest.stat().st_size, "sha256": sha256(dest), "license": LICENSES[repo],
            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        print(f"{key}: {dest.stat().st_size:,} bytes")
    (EXTERNAL / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
