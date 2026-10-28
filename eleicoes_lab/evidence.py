"""Persistência verificável dos resultados de consultas (JSON Lines)."""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from pathlib import Path

MAX_LINHAS = 50000


def converter(valor):
    if isinstance(valor, bytes):
        return {"base64": base64.b64encode(valor).decode("ascii")}
    return valor


def gravar_consulta(
    con: sqlite3.Connection,
    sql: str,
    parametros,
    destino: Path,
    eventos: list,
    max_linhas: int = MAX_LINHAS,
) -> list[dict]:
    if max_linhas < 1:
        raise ValueError("max_linhas deve ser positivo")
    cursor = con.execute(sql, parametros)
    if cursor.description is None:
        raise ValueError("A consulta deve retornar linhas")
    colunas = [c[0] for c in cursor.description]
    if len(set(colunas)) != len(colunas):
        raise ValueError("A consulta tem colunas com nomes duplicados; utilize AS")

    destino.mkdir(parents=True, exist_ok=True)
    identificador = f"consulta_{1 + sum(e.get('tipo') == 'consulta_sql' for e in eventos):04d}"
    arquivo = destino / f"{identificador}.jsonl"
    temporario = destino / f"{identificador}.jsonl.part"
    linhas = []
    resumo_hash = hashlib.sha256()
    try:
        with temporario.open("wb") as out:
            for idx, registro in enumerate(cursor, start=1):
                if idx > max_linhas:
                    raise ValueError(
                        f"Consulta excedeu o limite de {max_linhas} linhas; "
                        "faça uma agregação SQL ou altere o limite explicitamente"
                    )
                linha = {nome: converter(valor) for nome, valor in zip(colunas, registro)}
                conteudo = (json.dumps(linha, ensure_ascii=False, sort_keys=True,
                                       allow_nan=False) + "\n").encode("utf-8")
                out.write(conteudo)
                resumo_hash.update(conteudo)
                linhas.append(linha)
        temporario.replace(arquivo)
    except Exception:
        temporario.unlink(missing_ok=True)
        raise

    try:
        params_serializaveis = json.loads(json.dumps(parametros, default=str))
    except (TypeError, ValueError) as exc:
        arquivo.unlink(missing_ok=True)
        raise ValueError(f"Parâmetros não serializáveis: {exc}") from exc

    eventos.append({
        "tipo": "consulta_sql", "id": identificador,
        "sql": sql, "parametros": params_serializaveis,
        "colunas": colunas, "quantidade_linhas": len(linhas),
        "arquivo_local": f"consultas/{arquivo.name}",
        "sha256_resultado": resumo_hash.hexdigest(),
        "truncado": False,
    })
    return linhas
