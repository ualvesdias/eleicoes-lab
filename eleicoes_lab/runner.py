"""Executor versionado; somente código Python confiável deve ser carregado."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import coverage, engine, evidence, reporting

CONCLUSOES = {"sim", "nao", "inconclusivo"}
ID_RE = re.compile(r"^A[0-9]{3,}$")
EXEC_RE = re.compile(r"\d{8}T\d{6}_\d{6}Z_[0-9a-f]{8}")


def agora():
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def salvar_json(path: Path, dados: dict):
    path.write_text(json.dumps(dados, ensure_ascii=False, indent=2,
                               sort_keys=True, default=str) + "\n", encoding="utf-8")


def git_info(root: Path) -> dict:
    def git(*args):
        processo = subprocess.run(["git", *args], cwd=root, capture_output=True,
                                 text=True, timeout=15, check=False)
        return processo.stdout.strip() if processo.returncode == 0 else None
    return {"commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


@dataclass
class Contexto:
    conexao: sqlite3.Connection
    snapshot: Path
    protocolo: dict
    evidencias: list[dict]
    pasta: Path

    def consulta(self, sql: str, parametros=(), max_linhas: int = evidence.MAX_LINHAS):
        return evidence.gravar_consulta(self.conexao, sql, parametros,
                                       self.pasta / "consultas", self.evidencias,
                                       max_linhas=max_linhas)

    def evidencia(self, nome: str, valor: Any, fonte: str, procedimento: str):
        if not all([nome, fonte, procedimento]):
            raise ValueError("Evidência sem identificação completa")
        # Rejeita valores não serializáveis antes de criar evidências publicáveis.
        json.dumps(valor, ensure_ascii=False, allow_nan=False)
        self.evidencias.append({"tipo": "evidencia", "nome": nome, "valor": valor,
                                "fonte": fonte, "procedimento": procedimento})


def carregar_protocolo(root: Path, identificador: str):
    if not ID_RE.fullmatch(identificador):
        raise ValueError("ID inválido")
    caminho = root / "analises" / identificador / "pergunta.yaml"
    if not caminho.is_file():
        raise FileNotFoundError(caminho)
    protocolo = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    if not isinstance(protocolo, dict) or protocolo.get("id") != identificador:
        raise ValueError("Protocolo inválido ou ID divergente")
    if protocolo.get("status") != "aprovado":
        raise ValueError("Protocolo não aprovado")
    for campo in ("titulo", "pergunta", "versao", "hipoteses", "fontes",
                  "metodologia", "criterios_decisao"):
        if campo not in protocolo:
            raise ValueError(f"Campo ausente: {campo}")
    if not isinstance(protocolo["fontes"], list):
        raise ValueError("Fontes deve ser uma lista")
    hs = protocolo["hipoteses"]
    cs = protocolo["criterios_decisao"]
    if not isinstance(hs, dict) or not {"h0", "h1"} <= hs.keys():
        raise ValueError("Hipóteses incompletas")
    if not isinstance(cs, dict) or not CONCLUSOES <= cs.keys():
        raise ValueError("Critérios incompletos")

    def pendente(obj):
        if isinstance(obj, dict):
            return any(pendente(v) for v in obj.values())
        if isinstance(obj, list):
            return any(pendente(v) for v in obj)
        return isinstance(obj, str) and obj.strip() == "A DEFINIR"

    if pendente(protocolo):
        raise ValueError("Protocolo contém campos A DEFINIR")
    return protocolo


def carregar_modulo(path: Path):
    nome = f"eleicoes_lab_analise_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(nome, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Não foi possível carregar o módulo")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo
    spec.loader.exec_module(modulo)
    if not callable(getattr(modulo, "executar", None)):
        raise ValueError("Módulo precisa definir executar(contexto)")
    return modulo


def validar_resultado(resultado):
    if not isinstance(resultado, dict):
        raise ValueError("A análise deve retornar dicionário")
    for campo in ("conclusao", "justificativa", "resultados", "limitacoes"):
        if campo not in resultado:
            raise ValueError(f"Resultado sem campo: {campo}")
    if resultado["conclusao"] not in CONCLUSOES:
        raise ValueError("Conclusão inválida")
    if not isinstance(resultado["justificativa"], str) or not resultado["justificativa"].strip():
        raise ValueError("Justificativa obrigatória")
    if not isinstance(resultado["resultados"], dict):
        raise ValueError("Resultados deve ser um dicionário")
    if not isinstance(resultado["limitacoes"], list):
        raise ValueError("Limitações deve ser uma lista")
    for opcional in ("tabelas", "graficos", "incertezas", "referencias"):
        if opcional in resultado and not isinstance(resultado[opcional], list):
            raise ValueError(f"{opcional} deve ser uma lista")
    json.dumps(resultado, ensure_ascii=False, allow_nan=False)


def graficos_validos(pasta: Path, resultado: dict):
    for item in resultado.get("graficos", []):
        if not isinstance(item, dict) or not item.get("titulo"):
            raise ValueError("Gráfico precisa de título")
        relativo = item.get("arquivo")
        if not isinstance(relativo, str):
            raise ValueError("Gráfico precisa de caminho relativo")
        caminho = Path(relativo)
        if (caminho.is_absolute() or len(caminho.parts) != 2
                or caminho.parts[0] != "graficos"
                or caminho.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")):
            raise ValueError(f"Caminho de gráfico inválido: {relativo}")
        origem = pasta / caminho
        if origem.is_symlink() or not origem.is_file():
            raise FileNotFoundError(origem)
        if origem.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Gráfico excede 10 MB")


def executar(identificador: str, snapshot: Path, root: Path | None = None):
    root = Path(root or engine.ROOT).resolve()
    snapshot = Path(snapshot).resolve()
    protocolo = carregar_protocolo(root, identificador)
    if not snapshot.is_file():
        raise FileNotFoundError(snapshot)
    if snapshot == (root / "eleicoes.sqlite").resolve():
        raise ValueError("Use um snapshot, nunca o banco principal")
    script = root / "analises" / identificador / "analise.py"
    if not script.is_file():
        raise FileNotFoundError(script)
    protocolo_path = root / "analises" / identificador / "pergunta.yaml"

    exec_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
               + "_" + uuid.uuid4().hex[:8])
    pasta = root / "resultados_analises" / identificador / exec_id
    pasta.mkdir(parents=True, exist_ok=False)
    try:
        uri = snapshot.as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=120)) as con:
            con.execute("PRAGMA query_only=ON")
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Integridade SQLite inválida")
            cobertura_snapshot = coverage.auditar(con)
            if protocolo.get("exigir_cobertura_arquivos", False):
                ok, pendencias = coverage.verificar_escopo(
                    cobertura_snapshot, protocolo.get("escopo", {}))
                if not ok:
                    raise ValueError(f"Cobertura de arquivos insuficiente: {len(pendencias)} pendências")
            contexto = Contexto(con, snapshot, protocolo, [], pasta)
            resultado = carregar_modulo(script).executar(contexto)
            validar_resultado(resultado)
            graficos_validos(pasta, resultado)

        ambiente = {"python": sys.version.split()[0],
                    "sistema": platform.platform(),
                    "sqlite": sqlite3.sqlite_version,
                    "pyyaml": yaml.__version__}
        manifest = {
            "schema_version": 2, "id": exec_id, "analise_id": identificador,
            "criado_em": agora(), "conclusao": resultado["conclusao"],
            "snapshot_sha256": sha256(snapshot),
            "protocolo_sha256": sha256(protocolo_path),
            "codigo_analise_sha256": sha256(script),
            "codigo": git_info(root), "ambiente": ambiente,
        }
        salvar_json(pasta / "cobertura.json", cobertura_snapshot)
        salvar_json(pasta / "evidencias.json", {
            "eventos": contexto.evidencias, "resultado": resultado})
        (pasta / "relatorio.md").write_text(
            reporting.construir(protocolo, resultado, manifest,
                                cobertura_snapshot, contexto.evidencias),
            encoding="utf-8")
        manifest["cobertura_sha256"] = sha256(pasta / "cobertura.json")
        manifest["evidencias_sha256"] = sha256(pasta / "evidencias.json")
        salvar_json(pasta / "execucao.json", manifest)
    except Exception:
        shutil.rmtree(pasta, ignore_errors=True)
        raise
    print("Execução concluída:", exec_id)
    print("Conclusão declarada:", resultado["conclusao"])
    print("Relatório provisório:", pasta / "relatorio.md")
    return pasta


def verificar_commit(root: Path, commit: str, relativo: str, hash_esperado: str):
    processo = subprocess.run(
        ["git", "show", f"{commit}:{relativo}"], cwd=root,
        capture_output=True, timeout=30, check=False)
    if processo.returncode != 0:
        raise ValueError(f"Arquivo ausente do commit: {relativo}")
    if hashlib.sha256(processo.stdout).hexdigest() != hash_esperado:
        raise ValueError(f"Arquivo difere do commit: {relativo}")


def publicar(identificador: str, exec_id: str, revisor: str,
             root: Path | None = None):
    root = Path(root or engine.ROOT).resolve()
    if not ID_RE.fullmatch(identificador) or not EXEC_RE.fullmatch(exec_id):
        raise ValueError("ID inválido")
    if not revisor.strip():
        raise ValueError("Revisor obrigatório")
    origem = root / "resultados_analises" / identificador / exec_id
    manifest = json.loads((origem / "execucao.json").read_text(encoding="utf-8"))
    evidencias = json.loads((origem / "evidencias.json").read_text(encoding="utf-8"))
    if manifest["analise_id"] != identificador or manifest["id"] != exec_id:
        raise ValueError("Identidade da execução divergente")
    if manifest["conclusao"] != evidencias["resultado"]["conclusao"]:
        raise ValueError("Conclusão divergente das evidências")
    if manifest["codigo"]["dirty"] or not manifest["codigo"]["commit"]:
        raise ValueError("Execução sem commit limpo identificado")

    protocolo_path = root / "analises" / identificador / "pergunta.yaml"
    script = root / "analises" / identificador / "analise.py"
    if sha256(protocolo_path) != manifest["protocolo_sha256"]:
        raise ValueError("Protocolo mudou desde a execução")
    if sha256(script) != manifest["codigo_analise_sha256"]:
        raise ValueError("Código mudou desde a execução")
    if manifest.get("evidencias_sha256") and sha256(origem / "evidencias.json") != manifest["evidencias_sha256"]:
        raise ValueError("Evidências foram alteradas")
    if manifest.get("cobertura_sha256") and sha256(origem / "cobertura.json") != manifest["cobertura_sha256"]:
        raise ValueError("Relatório de cobertura foi alterado")
    for evento in evidencias["eventos"]:
        if evento.get("tipo") == "consulta_sql":
            arquivo = origem / evento["arquivo_local"]
            if not arquivo.is_file() or sha256(arquivo) != evento["sha256_resultado"]:
                raise ValueError(f"Evidência SQL inválida: {evento['id']}")

    if (root / ".git").exists():
        commit = manifest["codigo"]["commit"]
        verificar_commit(root, commit, f"analises/{identificador}/pergunta.yaml",
                         manifest["protocolo_sha256"])
        verificar_commit(root, commit, f"analises/{identificador}/analise.py",
                         manifest["codigo_analise_sha256"])

    graficos_validos(origem, evidencias["resultado"])
    destino = root / "relatorios" / identificador / exec_id
    if destino.exists():
        raise FileExistsError("Execução já publicada")
    destino.mkdir(parents=True)
    try:
        # A versão pública registra a revisão e preserva o rascunho local.
        original = (origem / "relatorio.md").read_text(encoding="utf-8")
        revisado = original.replace(
            "**Status:** relatório gerado; publicação depende de revisão explícita",
            f"**Status:** publicado após revisão declarada por {revisor.strip()} em {agora()}",
        )
        (destino / "RELATORIO.md").write_text(revisado, encoding="utf-8")
        hashes_graficos = {}
        for item in evidencias["resultado"].get("graficos", []):
            relativo = Path(item["arquivo"])
            (destino / relativo.parent).mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem / relativo, destino / relativo)
            hashes_graficos[item["arquivo"]] = sha256(destino / relativo)
        protocolo = yaml.safe_load(protocolo_path.read_text(encoding="utf-8"))
        revisao = {
            "schema_version": 2, "analise": identificador,
            "titulo": protocolo["titulo"], "pergunta": protocolo["pergunta"],
            "execucao": exec_id, "revisor": revisor.strip(),
            "revisado_em": agora(), "conclusao": manifest["conclusao"],
            "snapshot_sha256": manifest["snapshot_sha256"],
            "commit": manifest["codigo"]["commit"],
            "protocolo_sha256": manifest["protocolo_sha256"],
            "codigo_analise_sha256": manifest["codigo_analise_sha256"],
            "relatorio_sha256": sha256(destino / "RELATORIO.md"),
            "evidencias_sha256": sha256(origem / "evidencias.json"),
            "cobertura_sha256": sha256(origem / "cobertura.json"),
            "consultas": [e for e in evidencias["eventos"] if e.get("tipo") == "consulta_sql"],
            "graficos_sha256": hashes_graficos,
        }
        salvar_json(destino / "reprodutibilidade.json", revisao)
        reporting.atualizar_indice(root)
    except Exception:
        shutil.rmtree(destino, ignore_errors=True)
        raise
    print("Relatório preparado no repositório:", destino)
    print("Revise o diff antes de usar git add / git push.")
    return destino
