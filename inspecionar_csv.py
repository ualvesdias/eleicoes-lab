
import csv
import io
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "eleicoes.sqlite"

with sqlite3.connect(DB) as con:
    row = con.execute("""
        SELECT path FROM downloads
        WHERE year = 2018
          AND category = 'boletins'
          AND status = 'downloaded'
          AND path LIKE '%.zip'
        ORDER BY downloaded_at
        LIMIT 1
    """).fetchone()

if not row:
    raise SystemExit("Nenhum ZIP de boletins de 2018 encontrado.")

with zipfile.ZipFile(row[0]) as z:
    csv_name = next(
        name for name in z.namelist()
        if name.lower().endswith(".csv")
    )

    with z.open(csv_name) as source:
        sample = source.read(65536)

    try:
        decoded = sample.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        decoded = sample.decode("latin-1")
        encoding = "latin-1"

    first_line = decoded.splitlines()[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","

    print("Arquivo:", csv_name)
    print("Codificação:", encoding)
    print("Separador:", repr(delimiter))

    with z.open(csv_name) as source:
        with io.TextIOWrapper(source, encoding=encoding, newline="") as text:
            reader = csv.DictReader(text, delimiter=delimiter)

            print("\nCOLUNAS:")
            for i, name in enumerate(reader.fieldnames or [], 1):
                print(f"{i:02d}. {name}")

            print("\nPRIMEIRAS 3 LINHAS:")
            for _, record in zip(range(3), reader):
                print(record)

