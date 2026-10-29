"""Sincronização conservadora do catálogo CKAN do TSE.

Princípios:
- dados de votação/downloads nunca são alterados por este módulo;
- metadados incongruentes são bloqueados (fail closed);
- correções manuais explícitas e justificadas são auditadas;
- recursos baixados com URL diferente não são sobrescritos silenciosamente;
- prévia é padrão, --aplicar altera somente tabelas de catálogo.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "eleicoes.sqlite"
API = "https://dadosabertos.tse.jus.br/api/3/action"
ANOS = (2018, 2022, 2026)
UF = set("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO ZZ".split())
ZIP_MAGIC = {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}


def agora():
    return datetime.now(timezone.utc).isoformat()


def sessao():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.0,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET"}))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": "EleicoesLab/0.3 (pesquisa em dados publicos)",
                      "Cache-Control": "no-cache", "Accept-Encoding": "identity"})
    return s


def api(s, action, params):
    r = s.get(f"{API}/{action}", params=params, timeout=(20, 90))
    r.raise_for_status()
    body = r.json()
    if body.get("success") is not True:
        raise ValueError(f"API CKAN retornou erro para {action}: {body.get('error')}")
    return body["result"]


def url_oficial(url):
    if not isinstance(url, str):
        return False
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    try:
        porta = p.port
    except ValueError:
        return False
    return (p.scheme == "https" and (host == "tse.jus.br" or host.endswith(".tse.jus.br"))
            and not p.username and not p.password and porta in (None, 443) and bool(p.path))


def tipo_recurso(nome):
    n = re.sub(r"\s+", " ", str(nome or "")).casefold()
    if "hash sha2" in n or "hash sha-2" in n or "hash sha512" in n:
        return "hash"
    if "boletim de urna" in n:
        return "boletim"
    return "outro"


def eh_dataset_bu(titulo):
    return "boletim de urna" in str(titulo or "").casefold()


def validar_metadados(recurso, dataset_bu):
    """Devolve lista de problemas. Não inventa/reescreve URLs suspeitas."""
    erros = []
    rid = recurso.get("id")
    if not isinstance(rid, str) or not rid.strip():
        erros.append("ID de recurso ausente")
    url = recurso.get("url")
    if not url_oficial(url):
        erros.append("URL não é HTTPS em domínio oficial do TSE")
        return erros
    caminho = urlsplit(url).path.lower()
    if dataset_bu:
        tipo = tipo_recurso(recurso.get("name"))
        if tipo == "boletim" and not caminho.endswith(".zip"):
            erros.append("Boletim aponta para arquivo que não termina em .zip")
        if tipo == "hash" and not caminho.endswith((".sha256", ".sha512")):
            erros.append("Hash aponta para arquivo que não termina em .sha256/.sha512")
        if tipo == "boletim" and caminho.endswith((".sha512", ".sha256")):
            erros.append("Boletim aponta para checksum, não para o ZIP")
        # Validação cruzada UF/turno para boletins do ciclo presidencial.
        if tipo in {"boletim", "hash"}:
            n = re.sub(r"\s+", " ", str(recurso.get("name") or "")).upper()
            m = re.match(r"^([A-Z]{2})\s*-", n)
            if not m or m.group(1) not in UF:
                erros.append("UF não reconhecida no nome do recurso")
            if "PRIMEIRO TURNO" not in n and "SEGUNDO TURNO" not in n:
                erros.append("Turno não reconhecido no nome do recurso")
    return list(dict.fromkeys(erros))


def verificar_conteudo(s, url, tipo):
    """Lê apenas prefixo, sem baixar ZIP inteiro. Exige resposta coerente."""
    with s.get(url, stream=True, headers={"Range": "bytes=0-255", "Accept-Encoding": "identity"},
               timeout=(20, 90), allow_redirects=True) as r:
        r.raise_for_status()
        if r.status_code not in (200, 206) or not url_oficial(r.url):
            raise ValueError(f"Resposta HTTP/redirecionamento não oficial: {r.status_code} {r.url}")
        if r.status_code == 206 and not r.headers.get("Content-Range", "").startswith("bytes 0-"):
            raise ValueError("Content-Range inconsistente para leitura inicial")
        dados = bytearray()
        for pedaco in r.iter_content(chunk_size=256):
            if pedaco:
                dados.extend(pedaco)
            if len(dados) >= 256:
                break
    if tipo == "boletim" and bytes(dados[:4]) not in ZIP_MAGIC:
        raise ValueError(f"Conteúdo não tem assinatura ZIP: {dados[:8].hex()}")
    if tipo == "hash":
        try:
            texto = dados.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("Conteúdo do hash não é texto ASCII") from exc
        if not re.search(r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{128}|[0-9a-fA-F]{64})(?![0-9a-fA-F])", texto):
            raise ValueError("Resposta não contém digest SHA-256/SHA-512 reconhecível")
    return len(dados)


def carregar_overrides(arquivo):
    if not arquivo:
        return {}
    data = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Arquivo de overrides deve ser um objeto JSON")
    for rid, item in data.items():
        if not isinstance(item, dict) or not all(item.get(x) for x in ("url", "justificativa", "fonte")):
            raise ValueError(f"Override {rid}: requer url, justificativa e fonte")
        if not url_oficial(item["url"]):
            raise ValueError(f"Override {rid}: URL não oficial")
    return data


def selecionar_datasets(con, anos, categoria):
    rows = con.execute("SELECT id,title,metadata_json FROM datasets ORDER BY title").fetchall()
    selecionados = []
    for did, title, meta in rows:
        if not any(re.search(rf"(?<!\d){ano}(?!\d)", title) for ano in anos):
            continue
        if categoria == "boletins" and not eh_dataset_bu(title):
            continue
        selecionados.append((did, title, json.loads(meta)))
    return selecionados


def descobrir(s, anos, categoria):
    novos = {}
    for ano in anos:
        offset = 0
        while True:
            resultado = api(s, "package_search", {"q": str(ano), "rows": 100, "start": offset})
            items = resultado.get("results", [])
            for item in items:
                title = item.get("title", "")
                if not re.search(rf"(?<!\d){ano}(?!\d)", title):
                    continue
                if categoria == "boletins" and not eh_dataset_bu(title):
                    continue
                if categoria == "todos" and not any(t in title.casefold() for t in
                    ("resultado", "boletim", "correspond", "gedai", "eleitorado", "comparecimento", "candidato")):
                    continue
                if "suplementar" in title.casefold():
                    continue
                novos[item["id"]] = (item["id"], title, item)
            offset += len(items)
            if not items or offset >= resultado.get("count", 0):
                break
    return list(novos.values())


def plano_atualizacao(con, pacotes, s, overrides, probe, incluir_novos_datasets=True):
    """Monta plano sem alterar banco. Usa resource_show nos recursos novos/alterados."""
    plano = []
    problemas = []
    for dataset in pacotes:
        did = dataset.get("id")
        title = dataset.get("title", "")
        local = con.execute("SELECT id FROM datasets WHERE id=?", (did,)).fetchone()
        if local is None and not incluir_novos_datasets:
            problemas.append({"dataset": did, "erro": "dataset ausente localmente"})
            continue
        recursos = dataset.get("resources")
        if not isinstance(recursos, list):
            problemas.append({"dataset": did, "erro": "lista de recursos inválida"})
            continue
        tipo_bu = eh_dataset_bu(title)
        for resource in recursos:
            rid = resource.get("id") if isinstance(resource, dict) else None
            if not rid:
                problemas.append({"dataset": did, "erro": "recurso sem ID"})
                continue
            if resource.get("package_id") not in (None, did):
                problemas.append({"resource_id": rid, "erro": "package_id divergente"})
                continue
            old = con.execute("SELECT name,url,format,metadata_json FROM resources WHERE id=?", (rid,)).fetchone()
            override = overrides.get(rid)
            candidato = dict(resource)
            if override:
                candidato["url"] = override["url"]
            erros = validar_metadados(candidato, tipo_bu)
            if erros:
                problemas.append({"resource_id": rid, "nome": resource.get("name"), "erro": "; ".join(erros)})
                continue
            if old and old[1] == candidato["url"] and old[0] == candidato.get("name") \
                    and old[2] == candidato.get("format") and json.loads(old[3]) == resource:
                continue
            # Resource_show independente detecta divergências entre endpoints.
            try:
                individual = api(s, "resource_show", {"id": rid})
                if individual.get("id") != rid or individual.get("package_id") != did:
                    raise ValueError("resource_show não corresponde ao dataset/recurso")
                if individual.get("url") != resource.get("url"):
                    raise ValueError("package_show e resource_show divergem na URL")
                if probe and tipo_bu:
                    verificar_conteudo(s, candidato["url"], tipo_recurso(candidato.get("name")))
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                problemas.append({"resource_id": rid, "nome": resource.get("name"), "erro": f"verificação remota falhou: {exc}"})
                continue
            if old is not None and old[1] != candidato["url"]:
                download = (con.execute(
                    "SELECT status,url FROM downloads WHERE resource_id=?", (rid,)
                ).fetchone() if tabela_existe(con, "downloads") else None)
                if download and download[0] in ("downloaded", "verified"):
                    problemas.append({"resource_id": rid, "nome": resource.get("name"),
                                      "erro": "URL mudou mas recurso já foi baixado: revisão manual necessária"})
                    continue
            plano.append({"acao": "inserir" if old is None else "atualizar", "dataset_id": did,
                          "resource_id": rid, "nome": candidato.get("name", ""),
                          "url_antiga": old[1] if old else None, "url_nova": candidato["url"],
                          "metadados": candidato, "oficial": resource,
                          "override": override})
    return plano, problemas


def aplicar(con, pacotes, plano):
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS catalogo_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_utc TEXT NOT NULL, acao TEXT NOT NULL,
            dataset_id TEXT NOT NULL, resource_id TEXT,
            url_anterior TEXT, url_nova TEXT,
            metadados_json TEXT NOT NULL
        )""")
        for pkg in pacotes:
            did = pkg["id"]
            registro = con.execute("SELECT 1 FROM datasets WHERE id=?", (did,)).fetchone()
            if registro:
                con.execute("UPDATE datasets SET title=?,metadata_json=? WHERE id=?",
                            (pkg.get("title", ""), json.dumps(pkg, ensure_ascii=False), did))
            else:
                con.execute("INSERT INTO datasets (id,title,metadata_json,discovered_at) VALUES (?,?,?,?)",
                            (did, pkg.get("title", ""), json.dumps(pkg, ensure_ascii=False), agora()))
        for item in plano:
            rid = item["resource_id"]
            info = item["metadados"]
            if item["acao"] == "inserir":
                con.execute("""INSERT INTO resources
                    (id,dataset_id,name,format,url,metadata_json)
                    VALUES (?,?,?,?,?,?)""",
                    (rid, item["dataset_id"], info.get("name"), info.get("format"),
                     item["url_nova"], json.dumps(item["oficial"], ensure_ascii=False)))
            else:
                con.execute("""UPDATE resources SET name=?,format=?,url=?,metadata_json=? WHERE id=?""",
                            (info.get("name"), info.get("format"), item["url_nova"],
                             json.dumps(item["oficial"], ensure_ascii=False), rid))
            con.execute("""INSERT INTO catalogo_historico
                (data_utc,acao,dataset_id,resource_id,url_anterior,url_nova,metadados_json)
                VALUES (?,?,?,?,?,?,?)""",
                (agora(), item["acao"], item["dataset_id"], rid, item["url_antiga"],
                 item["url_nova"], json.dumps({"override": item["override"],
                                               "origem": "CKAN TSE"}, ensure_ascii=False)))
        con.commit()
    except Exception:
        con.rollback()
        raise


def tabela_existe(con, nome):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)
    ).fetchone() is not None


def iniciar_esquema_catalogo(con):
    """Bootstrap de novo clone: cria somente as tabelas base do catálogo."""
    con.executescript("""
        CREATE TABLE IF NOT EXISTS datasets (
            id TEXT PRIMARY KEY, title TEXT,
            metadata_json TEXT NOT NULL, discovered_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS resources (
            id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, name TEXT,
            format TEXT, url TEXT, metadata_json TEXT NOT NULL,
            download_status TEXT DEFAULT 'pending', local_path TEXT, sha256 TEXT,
            FOREIGN KEY(dataset_id) REFERENCES datasets(id)
        );
    """)


def auditar_local(con, anos, categoria):
    problemas = []
    for did, title, meta in selecionar_datasets(con, anos, categoria):
        for rid, name, url in con.execute(
            "SELECT id,name,url FROM resources WHERE dataset_id=?", (did,)):
            erros = validar_metadados({"id": rid, "name": name, "url": url}, eh_dataset_bu(title))
            for erro in erros:
                problemas.append({"dataset": title, "id": rid, "recurso": name, "problema": erro})
            download = (con.execute("SELECT url,status FROM downloads WHERE resource_id=?", (rid,)).fetchone()
                        if tabela_existe(con, "downloads") else None)
            if download and download[0] != url:
                problemas.append({"dataset": title, "id": rid, "recurso": name,
                                  "problema": f"URL do catálogo diverge da origem registrada em downloads ({download[1]})"})
    return problemas


def cli(argv=None, *, root=None, client=None):
    root = Path(root or ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ano", type=int, choices=ANOS)
    parser.add_argument("--categoria", choices=("todos", "boletins"), default="todos")
    parser.add_argument("--descobrir", action="store_true", help="Pesquisar datasets novos por ano")
    parser.add_argument("--auditar-local", action="store_true", help="Sem rede, detecta URLs suspeitas")
    parser.add_argument("--aplicar", action="store_true", help="Grava apenas alterações aprovadas")
    parser.add_argument("--overrides", type=Path, help="Correções explícitas e justificadas em JSON")
    args = parser.parse_args(argv)
    db = root / "eleicoes.sqlite"
    inicializando = not db.exists()
    if inicializando and not (args.descobrir and args.aplicar):
        parser.error(f"Banco não encontrado: {db}. Para recriá-lo use --descobrir --aplicar")
    anos = [args.ano] if args.ano else list(ANOS)
    with closing(sqlite3.connect(db, timeout=120)) as con:
        con.execute("PRAGMA busy_timeout=120000")
        if inicializando:
            iniciar_esquema_catalogo(con)
        if args.auditar_local:
            problemas = auditar_local(con, anos, args.categoria)
            print(f"RECURSOS SUSPEITOS: {len(problemas)}")
            for item in problemas:
                print(f"  - {item['recurso']}: {item['problema']}")
            return 0 if not problemas else 2
        overrides = carregar_overrides(args.overrides)
        s = client or sessao()
        try:
            candidatos = {d[0]: d for d in selecionar_datasets(con, anos, args.categoria)}
            if args.descobrir:
                for item in descobrir(s, anos, args.categoria):
                    candidatos[item[0]] = item
            if not candidatos:
                raise RuntimeError("Nenhum dataset candidato; use --descobrir")
            pacotes = []
            for did, title, meta in candidatos.values():
                pkg = api(s, "package_show", {"id": meta.get("name") or did})
                if pkg.get("id") != did:
                    raise ValueError(f"Dataset divergente: esperado {did}, recebido {pkg.get('id')}")
                pacotes.append(pkg)
            plano, problemas = plano_atualizacao(con, pacotes, s, overrides, probe=args.aplicar)
            contagens = Counter(x["acao"] for x in plano)
            print(f"Datasets consultados: {len(pacotes)}")
            print(f"Mudanças válidas: {len(plano)} (novos={contagens['inserir']}, atualizações={contagens['atualizar']})")
            print(f"Anomalias bloqueadas: {len(problemas)}")
            for item in plano[:30]:
                print(f"  {item['acao'].upper()}: {item['nome']} | {item['url_nova']}")
            for item in problemas[:30]:
                print(f"  BLOQUEADO: {item.get('nome') or item.get('resource_id') or item.get('dataset')}: {item['erro']}")
            manifests = root / "manifests"
            manifests.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            destino = manifests / f"catalogo_sync_{stamp}.json"
            destino.write_text(json.dumps({"gerado_em": agora(), "aplicado": args.aplicar,
                "datasets": [p["id"] for p in pacotes], "plano": plano,
                "anomalias": problemas}, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
            print(f"Manifesto: {destino}")
            if args.aplicar:
                aplicar(con, pacotes, plano)
                print(f"Aplicadas {len(plano)} alterações seguras no catálogo. Nenhum voto/download foi modificado.")
            return 0 if not problemas else 2
        finally:
            if client is None:
                s.close()


if __name__ == "__main__":
    sys.exit(cli())
