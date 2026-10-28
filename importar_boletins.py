import hashlib
import argparse
import csv
import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "eleicoes.sqlite"

BATCH_SIZE = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS votos_bu (
    resource_id TEXT NOT NULL,
    arquivo_csv TEXT NOT NULL,
    linha_csv INTEGER NOT NULL,
    ano INTEGER NOT NULL,
    turno INTEGER NOT NULL,
    pleito TEXT,
    eleicao TEXT,
    uf TEXT NOT NULL,
    municipio TEXT NOT NULL,
    nome_municipio TEXT,
    zona INTEGER NOT NULL,
    secao INTEGER NOT NULL,
    local_votacao TEXT,
    tipo_votavel TEXT,
    numero_votavel TEXT,
    nome_votavel TEXT,
    votos INTEGER NOT NULL,
    aptos INTEGER,
    comparecimento INTEGER,
    abstencoes INTEGER,
    urna TEXT,
    abertura TEXT,
    encerramento TEXT,
    dados_originais TEXT NOT NULL,
    PRIMARY KEY (resource_id, arquivo_csv, linha_csv)
);

CREATE TABLE IF NOT EXISTS importacoes_bu (
    resource_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    linhas_presidente INTEGER NOT NULL,
    arquivos_csv INTEGER NOT NULL,
    importado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bu_local
ON votos_bu(ano, turno, uf, municipio, zona, secao);

CREATE INDEX IF NOT EXISTS idx_bu_votavel
ON votos_bu(ano, turno, tipo_votavel, numero_votavel);

CREATE INDEX IF NOT EXISTS idx_bu_urna
ON votos_bu(ano, turno, urna);

CREATE INDEX IF NOT EXISTS idx_bu_encerramento
ON votos_bu(ano, turno, encerramento);
"""

def normalize(column):
    return re.sub(r"\s+", "", column.lstrip("\ufeff")).upper()

def as_int(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value or value == "#NULO#":
        return None
    return int(value)

def clean(value):
    if value is None:
        return None
    value = str(value).strip()
    if value in ("", "#NULO#"):
        return None
    return value

def is_president(row):
    cargo = clean(row.get("CD_CARGO_PERGUNTA"))
    descricao = (row.get("DS_CARGO_PERGUNTA") or "").strip().casefold()

    # Identificador oficial usado no layout inspecionado.
    if cargo == "1":
        return True

    return descricao in ("presidente", "presidente da república",
                         "presidente da republica")

def get_value(row, field):
    return clean(row.get(field))

def convert(row, resource_id, csv_name, line):
    required = (
        "ANO_ELEICAO", "NR_TURNO", "SG_UF",
        "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
        "QT_VOTOS"
    )
    missing = [k for k in required if not get_value(row, k)]
    if missing:
        raise ValueError(
            f"{csv_name}:{line}: campos ausentes: {missing}"
        )

    return (
        resource_id,
        csv_name,
        line,
        as_int(row["ANO_ELEICAO"]),
        as_int(row["NR_TURNO"]),
        get_value(row, "CD_PLEITO"),
        get_value(row, "CD_ELEICAO"),
        get_value(row, "SG_UF"),
        get_value(row, "CD_MUNICIPIO"),
        get_value(row, "NM_MUNICIPIO"),
        as_int(row["NR_ZONA"]),
        as_int(row["NR_SECAO"]),
        get_value(row, "NR_LOCAL_VOTACAO"),
        get_value(row, "CD_TIPO_VOTAVEL"),
        get_value(row, "NR_VOTAVEL"),
        get_value(row, "NM_VOTAVEL"),
        as_int(row["QT_VOTOS"]),
        as_int(row.get("QT_APTOS")),
        as_int(row.get("QT_COMPARECIMENTO")),
        as_int(row.get("QT_ABSTENCOES")),
        get_value(row, "NR_URNA_EFETIVADA"),
        get_value(row, "DT_ABERTURA"),
        get_value(row, "DT_ENCERRAMENTO"),
        json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    )

INSERT_SQL = """
INSERT INTO votos_bu VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?, ?
)
"""

def import_zip(con, resource_id, path, digest):
    count = 0
    processed_csv = 0
    cargo_columns_found = False

    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError(f"ZIP corrompido: {path.name}")

        con.execute(
            "DELETE FROM votos_bu WHERE resource_id = ?",
            (resource_id,)
        )

        for member in z.infolist():
            if member.is_dir() or not member.filename.lower().endswith(".csv"):
                continue

            # Os arquivos CSV do TSE podem utilizar diferentes
            # codificações entre as eleições.
            with z.open(member) as source:
                head = source.read(65536)

            try:
                head.decode("utf-8-sig")
                encoding = "utf-8-sig"
            except UnicodeDecodeError:
                encoding = "latin-1"

            first_line = head.decode(encoding).splitlines()[0]
            delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","

            batch = []
            with z.open(member) as source:
                with io.TextIOWrapper(
                    source, encoding=encoding, newline=""
                ) as text:
                    reader = csv.DictReader(text, delimiter=delimiter)

                    fieldnames = [
                        normalize(k) for k in (reader.fieldnames or [])
                    ]
                    if len(fieldnames) != len(set(fieldnames)):
                        raise ValueError(
                            f"Colunas duplicadas após normalização: "
                            f"{member.filename}"
                        )
                    reader.fieldnames = fieldnames

                    if not {"CD_CARGO_PERGUNTA",
                            "DS_CARGO_PERGUNTA"}.intersection(fieldnames):
                        raise ValueError(
                            f"CSV sem identificação do cargo: {member.filename}"
                        )

                    cargo_columns_found = True
                    processed_csv += 1

                    for line, record in enumerate(reader, start=2):
                        if not is_president(record):
                            continue

                        batch.append(convert(
                            record, resource_id, member.filename, line
                        ))

                        if len(batch) >= BATCH_SIZE:
                            con.executemany(INSERT_SQL, batch)
                            count += len(batch)
                            batch.clear()

                    if batch:
                        con.executemany(INSERT_SQL, batch)
                        count += len(batch)

    if not cargo_columns_found:
        raise ValueError(f"Nenhum CSV de boletim identificado: {path.name}")

    con.execute("""
        INSERT INTO importacoes_bu
            (resource_id, path, sha256,
             linhas_presidente, arquivos_csv, importado_em)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(resource_id) DO UPDATE SET
            path=excluded.path,
            sha256=excluded.sha256,
            linhas_presidente=excluded.linhas_presidente,
            arquivos_csv=excluded.arquivos_csv,
            importado_em=CURRENT_TIMESTAMP
    """, (resource_id, str(path), digest, count, processed_csv))

    return count, processed_csv

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", type=int, choices=(2018, 2022, 2026))
    parser.add_argument("--limite", type=int)
    args = parser.parse_args()

    if args.limite is not None and args.limite < 1:
        parser.error("--limite deve ser positivo")

    with sqlite3.connect(DB) as con:
        con.executescript(SCHEMA)

        sql = """
            SELECT resource_id, path, sha256
            FROM downloads
            WHERE category = 'boletins'
              AND status = 'downloaded'
              AND sha256 IS NOT NULL
              AND LOWER(path) LIKE '%.zip'
        """
        
        parameters = []
        if args.ano:
            sql += " AND year = ?"
            parameters.append(args.ano)
        sql += " ORDER BY year, resource_id"

        files = con.execute(sql, parameters).fetchall()

        if args.limite:
            files = files[:args.limite]

        print(f"Arquivos elegíveis: {len(files)}")

        for index, (rid, filename, digest) in enumerate(files, 1):
            path = Path(filename)
            print(f"[{index}/{len(files)}] {path.name}")

            if not path.is_file():
                print("  AUSENTE")
                continue
            if not zipfile.is_zipfile(path):
                print(f"  IGNORADO: não é um ZIP válido: {path.name}")
                continue
            with path.open("rb") as f:
                actual_hash = hashlib.file_digest(f, "sha256").hexdigest()

            if actual_hash != digest:
                print("  ERRO: SHA-256 diferente do manifesto")
                continue

            previous = con.execute("""
                SELECT sha256 FROM importacoes_bu
                WHERE resource_id = ?
            """, (rid,)).fetchone()

            if previous and previous[0] == digest:
                print("  JÁ IMPORTADO")
                continue

            try:
                # Transação independente por arquivo.
                con.execute("BEGIN")
                rows, csv_count = import_zip(
                    con, rid, path, digest
                )
                con.commit()
                print(
                    f"  OK: {rows:,} registros presidenciais "
                    f"em {csv_count} CSV(s)"
                )
            except Exception as exc:
                con.rollback()
                print(f"  ERRO: {exc}")

        print("\nTOTAL DE REGISTROS PRESIDENCIAIS")
        for ano, turno, total in con.execute("""
            SELECT ano, turno, COUNT(*)
            FROM votos_bu
            GROUP BY ano, turno
            ORDER BY ano, turno
        """):
            print(f"{ano} | Turno {turno}: {total:,} linhas")

if __name__ == "__main__":
    main()

