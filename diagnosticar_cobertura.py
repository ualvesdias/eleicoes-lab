#!/usr/bin/env python3
"""Diagnostica cobertura dos recursos de boletins presidenciais catalogados.

Uso (a partir da pasta do projeto):
    python diagnosticar_cobertura.py
    python diagnosticar_cobertura.py --db snapshots/arquivo.sqlite

Este script abre o SQLite exclusivamente em modo leitura e não modifica dados.
"""

import argparse
import csv
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
ANOS = (2018, 2022, 2026)
UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
    "RS", "RO", "RR", "SC", "SP", "SE", "TO", "ZZ",
}


def normalizar(texto):
    return re.sub(r"\s+", " ", (texto or "").casefold()).strip()


def identificar_turno(*textos):
    """Só classifica turno quando ele é explícito no nome do recurso."""
    texto = " ".join(normalizar(t) for t in textos)
    primeiro = bool(re.search(r"(?:primeiro|1\s*[º°o]?|1t)\s*(?:turno|t\b)", texto))
    segundo = bool(re.search(r"(?:segundo|2\s*[º°o]?|2t)\s*(?:turno|t\b)", texto))
    if primeiro == segundo:
        return None
    return 1 if primeiro else 2


def identificar_uf(nome):
    match = re.match(r"^\s*([A-Za-z]{2})\s*[-–—]", nome or "")
    if match and match.group(1).upper() in UFS:
        return match.group(1).upper()
    if re.match(r"^\s*exterior\b", nome or "", re.IGNORECASE):
        return "ZZ"
    return None


def parece_hash(nome, formato, url):
    texto = normalizar(nome)
    extensao = Path(urlparse(url or "").path).suffix.lower()
    return ("hash" in texto or extensao in {".sha256", ".sha512", ".md5"}
            or normalizar(formato).lstrip(".") in {"sha256", "sha512", "md5"})


def consulta_recursos(con):
    return con.execute("""
        SELECT d.title, r.id, r.name, r.format, r.url,
               COALESCE(dl.status, 'sem_download') AS status,
               dl.path,
               CASE WHEN ib.resource_id IS NULL THEN 0 ELSE 1 END AS importado
        FROM resources AS r
        JOIN datasets AS d ON d.id = r.dataset_id
        LEFT JOIN downloads AS dl ON dl.resource_id = r.id
        LEFT JOIN importacoes_bu AS ib ON ib.resource_id = r.id
        WHERE LOWER(d.title) LIKE '%boletim de urna%'
        ORDER BY d.title, r.name
    """).fetchall()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "eleicoes.sqlite",
                        help="Banco SQLite a inspecionar (padrão: pasta do script)")
    parser.add_argument("--exportar", action="store_true",
                        help="Salvar detalhamento CSV em resultados_analises/")
    args = parser.parse_args()
    db = args.db.expanduser().resolve()
    if not db.is_file():
        parser.error(f"Banco não encontrado: {db}")

    con = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA query_only=ON")
    try:
        registros = consulta_recursos(con)
    except sqlite3.OperationalError as exc:
        raise SystemExit(f"Erro ao consultar tabelas: {exc}") from exc
    finally:
        con.close()

    grupos = defaultdict(list)
    nao_classificados = []
    hashes = 0
    detalhes = []

    for titulo, resource_id, nome, formato, url, status, path, importado in registros:
        ano_match = re.search(r"(?<!\d)(2018|2022|2026)(?!\d)", titulo or "")
        if not ano_match:
            nao_classificados.append(("Ano não reconhecido", titulo, nome, status))
            continue
        ano = int(ano_match.group(1))
        if parece_hash(nome, formato, url):
            hashes += 1
            continue

        uf = identificar_uf(nome)
        turno = identificar_turno(nome)
        if not uf or turno is None:
            motivo = ("UF" if not uf else "turno") + " não identificado"
            nao_classificados.append((motivo, titulo, nome, status))
            continue

        item = {"ano": ano, "turno": turno, "uf": uf, "recurso": nome,
                "resource_id": resource_id, "status": status, "importado": bool(importado),
                "arquivo_local": path or ""}
        grupos[(ano, turno)].append(item)
        detalhes.append(item)

    print("\nDIAGNÓSTICO DOS BOLETINS — INVENTÁRIO LOCAL")
    print("=" * 70)
    print("Banco:", db)
    print("Arquivos de hash excluídos da contagem:", hashes)

    for ano in ANOS:
        for turno in (1, 2):
            itens = grupos[(ano, turno)]
            catalogadas = {it["uf"] for it in itens}
            baixadas = {it["uf"] for it in itens if it["status"] == "downloaded"}
            importadas = {it["uf"] for it in itens if it["importado"]}
            print(f"\n{ano} — TURNO {turno}")
            print(f"  Recursos classificados:     {len(itens)}")
            print(f"  UFs catalogadas:            {len(catalogadas)}/28")
            print(f"  UFs com download concluído: {len(baixadas)}/28")
            print(f"  UFs com importação marcada: {len(importadas)}/28")
            print("  UFs ausentes do catálogo:   ", ", ".join(sorted(UFS - catalogadas)) or "nenhuma")
            print("  UFs não baixadas:           ", ", ".join(sorted(catalogadas - baixadas)) or "nenhuma")
            print("  UFs baixadas não importadas:", ", ".join(sorted(baixadas - importadas)) or "nenhuma")
            problemas = [it for it in itens if it["status"] != "downloaded"]
            for it in problemas[:10]:
                print(f"    {it['uf']}: status={it['status']} | {it['recurso']}")
            if len(problemas) > 10:
                print(f"    ... mais {len(problemas) - 10} recurso(s)")

    print("\nRECURSOS SEM CLASSIFICAÇÃO:", len(nao_classificados))
    for motivo, titulo, nome, status in nao_classificados:
        print(f"  [{motivo}] {titulo} | {nome} | {status}")

    if args.exportar:
        destino = ROOT / "resultados_analises" / "diagnostico_cobertura.csv"
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("w", newline="", encoding="utf-8-sig") as f:
            campos = ["ano", "turno", "uf", "recurso", "resource_id", "status", "importado", "arquivo_local"]
            writer = csv.DictWriter(f, fieldnames=campos)
            writer.writeheader()
            writer.writerows(detalhes)
        print("\nRelatório CSV:", destino)

    print("\nOBS.: Este diagnóstico não comprova cobertura de todas as seções;")
    print("      apenas compara recursos catalogados, baixados e importados.")


if __name__ == "__main__":
    main()

