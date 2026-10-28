
import argparse
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests

ROOT = Path(__file__).resolve().parent
DB = ROOT / "eleicoes.sqlite"
RAW = ROOT / "raw"
MANIFESTS = ROOT / "manifests"

YEARS = (2018, 2022, 2026)

CATEGORIES = {
    "resultados",
    "boletins",
    "arquivos_urna",
    "correspondencias",
    "gedai",
    "comparecimento",
    "eleitorado",
}

def classify(title):
    t = title.casefold()
    if "suplementar" in t:
        return None
    if "arquivos transmitidos" in t:
        return "arquivos_urna"
    if "boletim de urna" in t:
        return "boletins"
    if "correspondências esperadas e efetivadas" in t:
        return "correspondencias"
    if "logs do sistema de preparação" in t:
        return "gedai"
    if t.startswith("resultados -") and "boletim" not in t:
        return "resultados"
    if "comparecimento e abstenção" in t:
        return "comparecimento"
    if t.startswith("eleitorado -"):
        return "eleitorado"
    return None

def year_from(title):
    found = re.findall(r"(?<!\d)(2018|2022|2026)(?!\d)", title)
    return int(found[0]) if len(set(found)) == 1 else None

def init_db(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            resource_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            year INTEGER NOT NULL,
            category TEXT NOT NULL,
            url TEXT NOT NULL,
            path TEXT NOT NULL,
            size_bytes INTEGER,
            sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            downloaded_at TEXT,
            error TEXT
        )
    """)
    con.commit()

def get_resources(con, years, categories):
    rows = con.execute("""
        SELECT d.id, d.title, d.metadata_json,
               r.id, r.name, r.format, r.url
        FROM datasets d
        JOIN resources r ON d.id = r.dataset_id
        ORDER BY d.title, r.name
    """).fetchall()

    selected = []
    for did, title, metadata, rid, name, fmt, url in rows:
        year = year_from(title)
        category = classify(title)
        if year not in years or category not in categories:
            continue
        if not url or not url.startswith(("https://", "http://")):
            continue

        # Evita arquivos de referência bibliográfica sem download.
        parsed = urlparse(url)
        basename = Path(unquote(parsed.path)).name
        suffix = Path(basename).suffix.lower()

        if not suffix:
            suffix = "." + re.sub(
                r"[^a-z0-9]", "", (fmt or "").lower()
            )[:10]

        if suffix in (".", ""):
            suffix = ".bin"

        # O ID evita colisões entre nomes semelhantes.
        filename = f"{rid}{suffix}"
        target = RAW / str(year) / category / did / filename

        selected.append({
            "resource_id": rid,
            "dataset_id": did,
            "year": year,
            "category": category,
            "name": name,
            "url": url,
            "path": target,
        })
    return selected

def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def download_one(session, con, item):
    rid = item["resource_id"]
    path = item["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")

    previous = con.execute(
        "SELECT sha256 FROM downloads WHERE resource_id = ?",
        (rid,)
    ).fetchone()

    if path.exists() and previous and previous[0]:
        current_hash = sha256_file(path)
        if current_hash == previous[0]:
            return "verified"

    con.execute("""
        INSERT INTO downloads
            (resource_id, dataset_id, year, category,
             url, path, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
        ON CONFLICT(resource_id) DO UPDATE SET
            dataset_id=excluded.dataset_id,
            year=excluded.year,
            category=excluded.category,
            url=excluded.url,
            path=excluded.path
    """, (
        rid, item["dataset_id"], item["year"],
        item["category"], item["url"], str(path)
    ))
    con.commit()

    for attempt in range(1, 5):
        try:
            existing = partial.stat().st_size if partial.exists() else 0
            headers = {"Range": f"bytes={existing}-"} if existing else {}

            with session.get(
                item["url"],
                headers=headers,
                stream=True,
                timeout=(30, 180),
                allow_redirects=True
            ) as response:

                # Retomada somente quando o servidor confirma
                # a faixa exata solicitada.
                append = False
                if existing and response.status_code == 206:
                    content_range = response.headers.get("Content-Range", "")
                    append = content_range.startswith(f"bytes {existing}-")
                    if not append:
                        raise RuntimeError(
                            f"Content-Range inesperado: {content_range}"
                        )

                elif response.status_code == 416:
                    partial.unlink(missing_ok=True)
                    raise RuntimeError("Range inválido; reiniciando download")

                response.raise_for_status()

                mode = "ab" if append else "wb"
                with partial.open(mode) as f:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)

                expected_length = response.headers.get("Content-Length")
                content_encoding = response.headers.get(
                    "Content-Encoding", "identity"
                ).lower()

                # Content-Length representa o tamanho da resposta HTTP
                # transmitida, que pode estar comprimida.
                # requests.iter_content() normalmente entrega bytes
                # já descompactados.
                if expected_length is not None and content_encoding == "identity":
                    expected_total = int(expected_length) + (
                        existing if append else 0
                    )

                    actual_total = partial.stat().st_size

                    if actual_total != expected_total:
                        raise RuntimeError(
                            f"Tamanho divergente: "
                            f"{actual_total}/{expected_total}"
                        )

            digest = sha256_file(partial)
            partial.replace(path)
            size = path.stat().st_size

            con.execute("""
                UPDATE downloads
                SET status='downloaded',
                    size_bytes=?,
                    sha256=?,
                    downloaded_at=datetime('now'),
                    error=NULL
                WHERE resource_id=?
            """, (size, digest, rid))
            con.commit()
            return "downloaded"

        except (requests.RequestException, OSError,
                RuntimeError, ValueError) as exc:
            con.execute("""
                UPDATE downloads
                SET status='error', error=?
                WHERE resource_id=?
            """, (str(exc), rid))
            con.commit()
            print(f"    Tentativa {attempt}/4: {exc}")
            if attempt < 4:
                time.sleep(min(2 ** attempt, 15))

    return "error"

def export_manifest(con):
    MANIFESTS.mkdir(exist_ok=True)
    rows = con.execute("""
        SELECT resource_id, year, category, url, path,
               size_bytes, sha256, status, downloaded_at, error
        FROM downloads
        ORDER BY year, category, resource_id
    """).fetchall()
    columns = [
        "resource_id", "year", "category", "url", "path",
        "size_bytes", "sha256", "status", "downloaded_at", "error"
    ]
    destination = MANIFESTS / "downloads.json"
    data = [dict(zip(columns, row)) for row in rows]
    destination.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"\nManifesto: {destination}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", type=int, choices=YEARS)
    parser.add_argument("--categoria", choices=sorted(CATEGORIES))
    parser.add_argument("--limite", type=int)
    parser.add_argument("--executar", action="store_true")
    args = parser.parse_args()

    if args.limite is not None and args.limite < 1:
        parser.error("--limite deve ser positivo")

    years = {args.ano} if args.ano else set(YEARS)
    categories = (
        {args.categoria} if args.categoria else CATEGORIES
    )

    if not DB.exists():
        raise SystemExit(f"Banco não encontrado: {DB}")

    with sqlite3.connect(DB, timeout=120) as con:
        con.execute("PRAGMA busy_timeout = 120000")
        con.execute("PRAGMA journal_mode=WAL")
        init_db(con)
        resources = get_resources(con, years, categories)

        print(f"\nRecursos selecionados: {len(resources)}")
        print(f"Anos: {sorted(years)}")
        print(f"Categorias: {sorted(categories)}")

        if not args.executar:
            print("\nPRÉVIA — nenhum arquivo será baixado.")
            for item in resources[:30]:
                print(
                    f"{item['year']} | {item['category']:<18} "
                    f"| {item['name']}"
                )
            print("\nUse --executar para iniciar.")
            return

        if args.limite:
            resources = resources[:args.limite]

        session = requests.Session()
        session.headers.update({
            "User-Agent": "EleicoesLab/0.1 (auditoria de dados publicos)",
            "Accept-Encoding": "identity"
        })

        summary = {"downloaded": 0, "verified": 0, "error": 0}

        try:
            for index, item in enumerate(resources, 1):
                print(
                    f"[{index}/{len(resources)}] "
                    f"{item['year']} {item['category']} "
                    f"{item['name']}"
                )
                result = download_one(session, con, item)
                summary[result] += 1
                print(f"    {result.upper()}")
        except KeyboardInterrupt:
            print("\nInterrompido pelo usuário. Progresso preservado.")
        finally:
            export_manifest(con)
            session.close()

        print("\nRESUMO")
        for status, count in summary.items():
            print(f"  {status}: {count}")

if __name__ == "__main__":
    main()

