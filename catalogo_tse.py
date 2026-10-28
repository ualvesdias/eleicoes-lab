
import sqlite3
import requests
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path.home() / "EleicoesLab"
DB = ROOT / "eleicoes.sqlite"
API = "https://dadosabertos.tse.jus.br/api/3/action"

YEARS = (2018, 2022, 2026)
KEYWORDS = (
    "resultado", "boletim de urna", "totalizacao",
    "totalização", "correspondenc", "log",
    "arquivos transmitidos", "gedai",
    "comparecimento", "absten", "eleitorado",
    "candidato"
)

ROOT.mkdir(parents=True, exist_ok=True)

def get_json(url, params=None):
    response = requests.get(
        url, params=params, timeout=90
    )
    response.raise_for_status()
    data = response.json()
    if not data["success"]:
        raise RuntimeError(f"API error: {data}")
    return data["result"]

def discover():
    datasets = {}
    for year in YEARS:
        start = 0
        while True:
            result = get_json(
                f"{API}/package_search",
                {"q": str(year), "rows": 100, "start": start}
            )
            for item in result["results"]:
                blob = " ".join([
                    item.get("title", ""),
                    item.get("notes", ""),
                    item.get("name", "")
                ]).lower()
                if any(k in blob for k in KEYWORDS):
                    datasets[item["id"]] = item
            start += len(result["results"])
            if start >= result["count"] or not result["results"]:
                break
    return datasets.values()

def main():
    with sqlite3.connect(DB) as con:
        con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS datasets (
            id TEXT PRIMARY KEY,
            title TEXT,
            metadata_json TEXT NOT NULL,
            discovered_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS resources (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            name TEXT,
            format TEXT,
            url TEXT,
            metadata_json TEXT NOT NULL,
            download_status TEXT DEFAULT 'pending',
            local_path TEXT,
            sha256 TEXT,
            FOREIGN KEY(dataset_id) REFERENCES datasets(id)
        );
        """)

        now = datetime.now(timezone.utc).isoformat()
        total = 0

        for dataset in discover():
            con.execute(
                """INSERT OR REPLACE INTO datasets
                   VALUES (?, ?, ?, ?)""",
                (
                    dataset["id"],
                    dataset["title"],
                    json.dumps(dataset, ensure_ascii=False),
                    now
                )
            )

            for resource in dataset.get("resources", []):
                con.execute(
                    """INSERT INTO resources
                       (id, dataset_id, name, format, url,
                        metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         name=excluded.name,
                         format=excluded.format,
                         url=excluded.url,
                         metadata_json=excluded.metadata_json""",
                    (
                        resource["id"],
                        dataset["id"],
                        resource.get("name"),
                        resource.get("format"),
                        resource.get("url"),
                        json.dumps(resource, ensure_ascii=False)
                    )
                )
                total += 1

        print(f"Recursos catalogados: {total}")
        print(f"Banco: {DB}")

if __name__ == "__main__":
    main()

