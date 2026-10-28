
import sqlite3
import csv
import json
import re
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
DB = ROOT / "eleicoes.sqlite"
OUTPUT = ROOT / "inventario_tse.csv"

YEARS = (2018, 2022, 2026)

def identify_year(text):
    years = re.findall(r"(?<!\d)20(?:18|22|26)(?!\d)", text)
    return sorted(set(int(y) for y in years))

def classify(text):
    text = text.lower()
    rules = [
        ("ARQUIVOS_URNA", ["arquivos transmitidos", "logjez", ".rdv"]),
        ("GEDAI", ["gedai", "preparação das urnas"]),
        ("CORRESPONDENCIAS", ["correspondência", "correspondencia"]),
        ("BOLETIM_URNA", ["boletim de urna"]),
        ("TOTALIZACAO", ["totalização", "totalizacao"]),
        ("RESULTADOS", ["resultado", "votação", "votacao"]),
        ("ELEITORADO", ["eleitorado", "comparecimento"]),
        ("CANDIDATOS", ["candidato"]),
    ]
    for category, keywords in rules:
        if any(word in text for word in keywords):
            return category
    return "OUTROS"

def main():
    if not DB.exists():
        raise SystemExit(f"Banco não encontrado: {DB}")

    con = sqlite3.connect(DB)
    rows = con.execute("""
        SELECT
            d.id,
            d.title,
            d.metadata_json,
            r.id,
            r.name,
            r.format,
            r.url
        FROM datasets d
        LEFT JOIN resources r ON r.dataset_id = d.id
        ORDER BY d.title, r.name
    """).fetchall()

    inventory = []
    counts = Counter()

    for dataset_id, title, metadata, rid, name, fmt, url in rows:
        meta = json.loads(metadata)
        description = meta.get("notes") or ""
        tags = " ".join(
            t.get("name", "") for t in meta.get("tags", [])
        )
        year_text = f"{title} {tags}"
        years = identify_year(year_text)
        category = classify(f"{title} {description} {name or ''}")
        year = years[0] if len(years) == 1 else None

        record = {
            "ano": year or "",
            "categoria": category,
            "dataset": title,
            "recurso": name or "",
            "formato": fmt or "",
            "url": url or "",
            "dataset_id": dataset_id,
            "resource_id": rid or "",
        }
        inventory.append(record)

        if year in YEARS and rid:
            counts[(year, category)] += 1

    con.close()

    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=inventory[0].keys())
        writer.writeheader()
        writer.writerows(inventory)

    categories = [
        "RESULTADOS", "BOLETIM_URNA", "ARQUIVOS_URNA",
        "CORRESPONDENCIAS", "GEDAI", "TOTALIZACAO",
        "ELEITORADO", "CANDIDATOS"
    ]

    print("\nINVENTÁRIO TSE")
    print("=" * 65)
    print(f"{'CATEGORIA':<24} {'2018':>8} {'2022':>8} {'2026':>8}")
    print("-" * 65)

    for category in categories:
        values = [counts[(y, category)] for y in YEARS]
        print(f"{category:<24} {values[0]:>8} {values[1]:>8} {values[2]:>8}")

    print("-" * 65)
    print(f"Total de registros no inventário: {len(inventory)}")
    print(f"Relatório: {OUTPUT}")
    print("\nATENÇÃO: zeros significam não descoberto/classificado,")
    print("não necessariamente indisponível no TSE.")

if __name__ == "__main__":
    main()

