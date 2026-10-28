
import sqlite3
import csv
import json
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent
DB = ROOT / "eleicoes.sqlite"
OUTPUT = ROOT / "auditoria_catalogo.csv"

YEARS = (2018, 2022, 2026)

def get_year(dataset):
    tags = " ".join(
        t.get("name", "") for t in dataset.get("tags", [])
    )
    text = f"{dataset.get('title', '')} {tags}"
    found = set(re.findall(r"\b(?:2018|2022|2026)\b", text))
    return int(next(iter(found))) if len(found) == 1 else None

def category(title):
    t = title.casefold()

    if "arquivos transmitidos" in t:
        return "ARQUIVOS_URNA"
    if "boletim de urna" in t:
        return "BOLETIM_URNA"
    if "correspond" in t:
        return "CORRESPONDENCIAS"
    if "gedai" in t or "preparação das urnas" in t:
        return "GEDAI"
    if "resultado" in t:
        return "RESULTADOS"
    if "comparecimento" in t or "abstenção" in t:
        return "COMPARECIMENTO"
    if "eleitorado" in t:
        return "ELEITORADO"
    if "candidato" in t:
        return "CANDIDATOS"
    return "OUTROS"

def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    datasets = con.execute("""
        SELECT id, title, metadata_json
        FROM datasets
        ORDER BY title
    """).fetchall()

    resource_counts = dict(con.execute("""
        SELECT dataset_id, COUNT(*)
        FROM resources
        GROUP BY dataset_id
    """).fetchall())

    report = []
    groups = defaultdict(list)

    for row in datasets:
        metadata = json.loads(row["metadata_json"])
        year = get_year(metadata)
        if year not in YEARS:
            continue

        cat = category(row["title"])
        count = resource_counts.get(row["id"], 0)

        record = {
            "ano": year,
            "categoria": cat,
            "dataset": row["title"],
            "recursos": count,
            "url": (
                "https://dadosabertos.tse.jus.br/dataset/"
                + metadata.get("name", "")
            ),
            "dataset_id": row["id"],
        }

        report.append(record)
        groups[(year, cat)].append(record)

    con.close()

    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "ano", "categoria", "dataset", "recursos",
            "url", "dataset_id"
        ])
        writer.writeheader()
        writer.writerows(report)

    relevant = [
        "RESULTADOS", "ARQUIVOS_URNA",
        "BOLETIM_URNA", "CORRESPONDENCIAS",
        "GEDAI", "COMPARECIMENTO", "ELEITORADO"
    ]

    print("\nAUDITORIA DO CATÁLOGO TSE")
    print("=" * 75)

    for year in YEARS:
        print(f"\n{'=' * 20} {year} {'=' * 20}")

        for cat in relevant:
            items = groups.get((year, cat), [])
            print(f"\n[{cat}] {len(items)} datasets")

            for item in items:
                print(
                    f"  ({item['recursos']:3d} recursos) "
                    f"{item['dataset']}"
                )

    print("\n" + "=" * 75)
    print(f"Datasets classificados: {len(report)}")
    print(f"Relatório completo: {OUTPUT}")

if __name__ == "__main__":
    main()

