
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import engine


CONCLUSOES = {"sim", "nao", "inconclusivo"}
ID_RE = re.compile(r"^A[0-9]{3,}$")


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def salvar_json(path: Path, dados: dict):
    path.write_text(
        json.dumps(
            dados, ensure_ascii=False, indent=2,
            sort_keys=True, default=str
        ) + "\n",
        encoding="utf-8"
    )


def git_info(root: Path) -> dict:
    def git(*args):
        p = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False
        )
        return p.stdout.strip() if p.returncode == 0 else None

    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
    }


@dataclass
class Contexto:
    conexao: sqlite3.Connection
    snapshot: Path
    protocolo: dict
    evidencias: list[dict]

    def consulta(self, sql: str, parametros=()) -> list[dict]:
        # Esta conexão é somente leitura. Consultas não confiáveis
        # não devem ser fornecidas por usuários externos.
        cursor = self.conexao.execute(sql, parametros)

        if cursor.description is None:
            raise ValueError("A consulta deve retornar dados")

        nomes = [col[0] for col in cursor.description]
        linhas = [dict(zip(nomes, row)) for row in cursor.fetchall()]

        self.evidencias.append({
            "tipo": "consulta_sql",
            "sql": sql,
            "parametros": list(parametros),
            "quantidade_linhas": len(linhas),
        })
        return linhas

    def evidencia(
        self,
        nome: str,
        valor: Any,
        fonte: str,
        procedimento: str
    ):
        if not all([nome, fonte, procedimento]):
            raise ValueError("Evidência sem identificação completa")

        self.evidencias.append({
            "tipo": "evidencia",
            "nome": nome,
            "valor": valor,
            "fonte": fonte,
            "procedimento": procedimento,
        })


def carregar_protocolo(root: Path, identificador: str) -> dict:
    if not ID_RE.fullmatch(identificador):
        raise ValueError("ID inválido")

    arquivo = root / "analises" / identificador / "pergunta.yaml"
    if not arquivo.is_file():
        raise FileNotFoundError(arquivo)

    protocolo = yaml.safe_load(arquivo.read_text(encoding="utf-8"))

    if not isinstance(protocolo, dict):
        raise ValueError("Protocolo YAML inválido")

    if protocolo.get("id") != identificador:
        raise ValueError("ID divergente no protocolo")

    if protocolo.get("status") != "aprovado":
        raise ValueError("Protocolo não aprovado")

    obrigatorios = (
        "titulo", "pergunta", "versao",
        "hipoteses", "fontes", "metodologia",
        "criterios_decisao"
    )
    for campo in obrigatorios:
        if campo not in protocolo:
            raise ValueError(f"Campo ausente: {campo}")

    if not isinstance(protocolo["fontes"], list):
        raise ValueError("Fontes deve ser uma lista")

    hipoteses = protocolo["hipoteses"]
    criterios = protocolo["criterios_decisao"]

    if not isinstance(hipoteses, dict) or not {"h0", "h1"} <= hipoteses.keys():
        raise ValueError("Hipóteses incompletas")

    if not isinstance(criterios, dict) or not CONCLUSOES <= criterios.keys():
        raise ValueError("Critérios de decisão incompletos")

    def possui_pendencia(obj):
        if isinstance(obj, dict):
            return any(possui_pendencia(v) for v in obj.values())
        if isinstance(obj, list):
            return any(possui_pendencia(v) for v in obj)
        return isinstance(obj, str) and obj.strip() == "A DEFINIR"

    if possui_pendencia(protocolo):
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
        raise ValueError("Módulo deve definir executar(contexto)")

    return modulo


def validar_resultado(resultado):
    if not isinstance(resultado, dict):
        raise ValueError("A análise deve retornar um dicionário")

    campos = ("conclusao", "justificativa", "resultados", "limitacoes")
    for campo in campos:
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


def formatar_relatorio(protocolo, resultado, execucao) -> str:
    def bloco(obj):
        return "```json\n" + json.dumps(
            obj, ensure_ascii=False, indent=2, default=str
        ) + "\n```"

    conclusao = {
        "sim": "SIM",
        "nao": "NÃO",
        "inconclusivo": "NÃO FOI POSSÍVEL CONCLUIR"
    }[resultado["conclusao"]]

    return f"""# Relatório técnico — {protocolo['id']}

## 1. Identificação

- **Título:** {protocolo['titulo']}
- **Versão do protocolo:** {protocolo['versao']}
- **Execução:** `{execucao['id']}`
- **Data UTC:** {execucao['criado_em']}
- **Commit Git:** `{execucao['codigo']['commit']}`
- **SHA-256 do snapshot:** `{execucao['snapshot_sha256']}`
- **Status de publicação:** provisório até revisão

## 2. Pergunta central

{protocolo['pergunta']}

## 3. Hipóteses

{bloco(protocolo['hipoteses'])}

## 4. Fontes e cobertura

{bloco(protocolo['fontes'])}

A cobertura deve ser confirmada pela análise específica.
A integridade SQLite não comprova cobertura eleitoral completa.

## 5. Metodologia

{bloco(protocolo['metodologia'])}

## 6. Critérios de decisão

{bloco(protocolo['criterios_decisao'])}

## 7. Resultados

{bloco(resultado['resultados'])}

## 8. Discussão e limitações

{chr(10).join('- ' + str(x) for x in resultado['limitacoes']) or '- Nenhuma informada.'}

## 9. Conclusão

**Resposta: {conclusao}**

{resultado['justificativa']}

## 10. Reprodutibilidade

- ID da execução: `{execucao['id']}`
- Versão Python: `{execucao['ambiente']['python']}`
- Sistema: `{execucao['ambiente']['sistema']}`
- Hash do protocolo: `{execucao['protocolo_sha256']}`
- Hash do código da análise: `{execucao['codigo_analise_sha256']}`

O manifesto da execução e as evidências estruturadas devem
ser preservados para reprodução e revisão.

## 11. Referências

Consultar as fontes identificadas no protocolo.

## 12. Histórico de revisões

- Relatório gerado automaticamente na execução inicial.
"""


def executar(
    identificador: str,
    snapshot: Path,
    root: Path | None = None
) -> Path:
    root = Path(root or engine.ROOT).resolve()
    snapshot = Path(snapshot).resolve()
    protocolo = carregar_protocolo(root, identificador)

    if not snapshot.is_file():
        raise FileNotFoundError(snapshot)

    arquivo_analise = root / "analises" / identificador / "analise.py"
    if not arquivo_analise.is_file():
        raise FileNotFoundError(arquivo_analise)

    # Nenhum acesso de escrita ao banco.
    uri = snapshot.as_uri() + "?mode=ro&immutable=1"

    with sqlite3.connect(uri, uri=True, timeout=120) as con:
        con.execute("PRAGMA query_only=ON")

        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Snapshot não passou na integridade SQLite")

        contexto = Contexto(con, snapshot, protocolo, [])
        modulo = carregar_modulo(arquivo_analise)
        resultado = modulo.executar(contexto)
        validar_resultado(resultado)

    exec_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        + "_" + uuid.uuid4().hex[:8]
    )

    pasta_base = root / "resultados_analises" / identificador
    pasta_base.mkdir(parents=True, exist_ok=True)
    pasta = pasta_base / exec_id
    pasta.mkdir()

    arquivo_protocolo = (
        root / "analises" / identificador / "pergunta.yaml"
    )

    manifest = {
        "schema_version": 1,
        "id": exec_id,
        "analise_id": identificador,
        "criado_em": agora(),
        "conclusao": resultado["conclusao"],
        "snapshot_sha256": sha256(snapshot),
        "protocolo_sha256": sha256(arquivo_protocolo),
        "codigo_analise_sha256": sha256(arquivo_analise),
        "codigo": git_info(root),
        "ambiente": {
            "python": sys.version.split()[0],
            "sistema": platform.platform(),
            "sqlite": sqlite3.sqlite_version,
            "pyyaml": yaml.__version__
        }
    }

    salvar_json(pasta / "execucao.json", manifest)
    salvar_json(pasta / "evidencias.json", {
        "eventos": contexto.evidencias,
        "resultado": resultado
    })
    (pasta / "relatorio.md").write_text(
        formatar_relatorio(protocolo, resultado, manifest),
        encoding="utf-8"
    )

    print("Execução concluída:", exec_id)
    print("Conclusão declarada:", resultado["conclusao"])
    print("Relatório provisório:", pasta / "relatorio.md")
    return pasta


def publicar(
    identificador: str,
    exec_id: str,
    revisor: str,
    root: Path | None = None
) -> Path:
    root = Path(root or engine.ROOT).resolve()

    if not ID_RE.fullmatch(identificador):
        raise ValueError("ID inválido")
    if not re.fullmatch(r"\d{8}T\d{6}_\d{6}Z_[0-9a-f]{8}", exec_id):
        raise ValueError("ID de execução inválido")
    if not revisor.strip():
        raise ValueError("Informe o responsável pela revisão")

    origem = root / "resultados_analises" / identificador / exec_id
    manifest = json.loads(
        (origem / "execucao.json").read_text(encoding="utf-8")
    )
    evidencias = json.loads(
        (origem / "evidencias.json").read_text(encoding="utf-8")
    )

    if manifest["analise_id"] != identificador or manifest["id"] != exec_id:
        raise ValueError("Identidade da execução divergente")
    if manifest["conclusao"] != evidencias["resultado"]["conclusao"]:
        raise ValueError("Conclusão divergente das evidências")
    if manifest["codigo"]["dirty"]:
        raise ValueError("Execução com alterações Git não commitadas")
    if not manifest["codigo"]["commit"]:
        raise ValueError("Execução sem commit Git identificado")

    protocolo = root / "analises" / identificador / "pergunta.yaml"
    codigo = root / "analises" / identificador / "analise.py"

    if sha256(protocolo) != manifest["protocolo_sha256"]:
        raise ValueError("Protocolo mudou desde a execução")
    if sha256(codigo) != manifest["codigo_analise_sha256"]:
        raise ValueError("Código mudou desde a execução")

    destino = root / "relatorios" / identificador / exec_id
    if destino.exists():
        raise FileExistsError("Esta execução já foi publicada")

    destino.mkdir(parents=True)

    revisao = {
        "analise": identificador,
        "execucao": exec_id,
        "revisor": revisor.strip(),
        "revisado_em": agora(),
        "conclusao": manifest["conclusao"],
        "snapshot_sha256": manifest["snapshot_sha256"],
        "commit": manifest["codigo"]["commit"],
        "protocolo_sha256": manifest["protocolo_sha256"],
        "codigo_analise_sha256": manifest["codigo_analise_sha256"],
        "relatorio_sha256": sha256(origem / "relatorio.md"),
        "evidencias_sha256": sha256(origem / "evidencias.json")
    }

    shutil.copy2(origem / "relatorio.md", destino / "RELATORIO.md")
    salvar_json(destino / "reprodutibilidade.json", revisao)

    print("Publicado localmente:", destino)
    print("Revise o diff antes de enviar ao GitHub.")
    return destino

