"""Inventário de cobertura documental dos boletins presidenciais.

A cobertura aqui é de *recursos*, não de seções eleitorais.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import PurePosixPath
from urllib.parse import urlparse, unquote

UFS = (
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
    "RS", "RO", "RR", "SC", "SP", "SE", "TO", "ZZ"
)
ANOS = (2018, 2022, 2026)


def normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "")
                   if not unicodedata.combining(c)).casefold()


def identificar(nome: str, titulo: str):
    ano = re.findall(r"(?<!\d)(2018|2022|2026)(?!\d)", titulo)
    if len(set(ano)) != 1:
        return None
    nome_normalizado = normalizar(nome)
    uf = re.match(r"^\s*([A-Z]{2})\s*-", nome or "")
    if not uf or uf.group(1) not in UFS:
        return None
    turno = (1 if re.search(r"\b(primeiro|1o|1)\s*turno\b", nome_normalizado)
             else 2 if re.search(r"\b(segundo|2o|2)\s*turno\b", nome_normalizado)
             else None)
    return (int(ano[0]), turno, uf.group(1)) if turno else None


def categoria(titulo: str) -> str:
    n = normalizar(titulo)
    if "arquivos transmitidos" in n:
        return "arquivos_urna"
    if "boletim de urna" in n:
        return "boletins"
    if "correspond" in n:
        return "correspondencias"
    if "gedai" in n or "preparacao das urnas" in n:
        return "gedai"
    if "comparecimento" in n or "abstencao" in n:
        return "comparecimento"
    if "eleitorado" in n:
        return "eleitorado"
    if "resultad" in n:
        return "resultados"
    return "outros"


def auditar(con: sqlite3.Connection, profundo: bool = False) -> dict:
    nomes = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    requeridas = {"datasets", "resources", "downloads", "importacoes_bu"}
    faltantes = sorted(requeridas - nomes)
    agora = datetime.now(timezone.utc).isoformat()
    if faltantes:
        return {"schema_version": 1, "gerado_em": agora,
                "estado": "indisponivel", "tabelas_ausentes": faltantes,
                "resumo": [], "segmentos": [], "nao_classificados": []}

    linhas = con.execute("""
        SELECT d.title, r.id, r.name, r.format, r.url,
               dl.status, dl.sha256, ib.sha256, ib.linhas_presidente
        FROM resources AS r
        JOIN datasets AS d ON d.id = r.dataset_id
        LEFT JOIN downloads AS dl ON dl.resource_id = r.id
        LEFT JOIN importacoes_bu AS ib ON ib.resource_id = r.id
        ORDER BY d.title, r.name
    """).fetchall()
    por_segmento = {}
    nao_classificados = []
    inventario_recursos = []
    resumo_recursos = defaultdict(lambda: {"catalogados": 0, "baixados": 0})
    for titulo, rid, nome, formato, url, status, sha_download, sha_import, qt in linhas:
        anos = set(re.findall(r"(?<!\d)(2018|2022|2026)(?!\d)", titulo or ""))
        if len(anos) == 1 and "suplementar" not in normalizar(titulo):
            ano_inventario = int(next(iter(anos)))
            tipo = categoria(titulo)
            par = (ano_inventario, tipo)
            resumo_recursos[par]["catalogados"] += 1
            if status == "downloaded":
                resumo_recursos[par]["baixados"] += 1
            inventario_recursos.append({
                "ano": ano_inventario, "categoria": tipo,
                "recurso_id": rid, "dataset": titulo,
                "nome": nome, "formato": formato, "url": url,
                "status_download": status or "nao_registrado",
                "sha256_local_registrado": sha_download,
            })
        if "boletim de urna" not in normalizar(titulo):
            continue
        caminho_url = PurePosixPath(unquote(urlparse(url or "").path))
        if caminho_url.suffix.lower() != ".zip" and (formato or "").lower() != "zip":
            continue  # hashes SHA-512 e recursos auxiliares não são boletins CSV
        chave = identificar(nome or "", titulo or "")
        if chave is None:
            nao_classificados.append({"recurso_id": rid, "nome": nome, "dataset": titulo})
            continue
        valido = (status == "downloaded" and bool(sha_download)
                  and sha_import == sha_download and (qt or 0) > 0)
        por_segmento.setdefault(chave, []).append({
            "resource_id": rid, "nome": nome,
            "baixado": status == "downloaded", "importado": valido,
            "linhas_presidente_declaradas": qt or 0,
            "hashes_registrados_coincidem": bool(sha_download) and sha_import == sha_download,
        })

    segmentos, resumo = [], []
    for ano in ANOS:
        for turno in (1, 2):
            contadores = {"ok": 0, "nao_catalogado": 0,
                          "nao_baixado": 0, "nao_importado": 0, "ambiguo": 0}
            for uf in UFS:
                recursos = por_segmento.get((ano, turno, uf), [])
                if not recursos:
                    estado = "nao_catalogado"
                elif len(recursos) > 1:
                    estado = "ambiguo"
                elif not recursos[0]["baixado"]:
                    estado = "nao_baixado"
                elif not recursos[0]["importado"]:
                    estado = "nao_importado"
                else:
                    estado = "ok"
                contadores[estado] += 1
                segmentos.append({"ano": ano, "turno": turno, "uf": uf,
                                  "estado": estado, "recursos": recursos})
            resumo.append({"ano": ano, "turno": turno, "ufs_esperadas": len(UFS),
                           "ufs_com_arquivos_importados": contadores["ok"],
                           "situacoes": contadores,
                           "estado": ("cobertura_de_arquivos_ok" if contadores["ok"] == len(UFS)
                                      else "parcial")})
    secoes = {"estado": "nao_executada", "motivo": "Use --profundo para contar seções observadas"}
    if profundo:
        if "votos_bu" not in nomes:
            secoes = {"estado": "indisponivel", "motivo": "Tabela votos_bu ausente"}
        else:
            contagens = con.execute("""
                SELECT ano, turno, uf, COUNT(*) AS linhas_votacao,
                       COUNT(DISTINCT municipio || ':' || zona || ':' || secao)
                           AS secoes_observadas,
                       COUNT(DISTINCT resource_id) AS recursos_com_registros
                FROM votos_bu
                GROUP BY ano, turno, uf
                ORDER BY ano, turno, uf
            """).fetchall()
            secoes = {
                "estado": "observada_sem_reconciliacao_independente",
                "aviso": "Seções esperadas ainda não foram derivadas das correspondências do TSE.",
                "por_uf": [
                    {"ano": a, "turno": t, "uf": u, "linhas_votacao": linhas,
                     "secoes_observadas": qtd, "recursos_com_registros": recursos,
                     "secoes_esperadas": None}
                    for a, t, u, linhas, qtd, recursos in contagens
                ],
            }

    return {
        "schema_version": 1,
        "gerado_em": agora,
        "estado": "avaliada",
        "alcance": "Presenca e importacao de ZIPs por UF/turno; NAO comprova total de secoes, votos ou autenticidade oficial.",
        "resumo": resumo, "segmentos": segmentos, "secoes": secoes,
        "inventario_recursos": inventario_recursos,
        "resumo_recursos": [
            {"ano": ano, "categoria": tipo, **dados}
            for (ano, tipo), dados in sorted(resumo_recursos.items())
        ],
        "nao_classificados": nao_classificados,
    }


def verificar_escopo(auditoria: dict, escopo: dict) -> tuple[bool, list[dict]]:
    if auditoria.get("estado") != "avaliada":
        return False, [{"motivo": "auditoria_indisponivel"}]
    anos = escopo.get("anos")
    turnos = escopo.get("turnos")
    ufs = escopo.get("ufs")
    if not (isinstance(anos, list) and anos and
            isinstance(turnos, list) and turnos and
            isinstance(ufs, list) and ufs):
        raise ValueError("Escopo precisa declarar listas não vazias: anos, turnos, ufs")
    if any(a not in ANOS for a in anos) or any(t not in (1, 2) for t in turnos):
        raise ValueError("Ano ou turno fora do universo suportado")
    if any(u not in UFS for u in ufs):
        raise ValueError("UF inválida no escopo")
    selecionados = [s for s in auditoria["segmentos"]
                    if s["ano"] in anos and s["turno"] in turnos and s["uf"] in ufs]
    pendencias = [s for s in selecionados if s["estado"] != "ok"]
    return not pendencias and len(selecionados) == len(set(anos)) * len(set(turnos)) * len(set(ufs)), pendencias
