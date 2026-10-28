
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "eleicoes.sqlite"

ANALYSES = ROOT / "analises"
REGISTRY = ANALYSES / "registro.json"
TEMPLATES = ROOT / "templates"
SNAPSHOTS = ROOT / "snapshots"

ID_PATTERN = re.compile(r"^A[0-9]{3,}$")

REQUIRED_FIELDS = {
    "id", "titulo", "pergunta", "versao",
    "status", "hipoteses", "fontes",
    "metodologia", "criterios_decisao"
}

DECISIONS = {"sim", "nao", "inconclusivo"}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def initialize():
    for directory in (ANALYSES, TEMPLATES, SNAPSHOTS):
        directory.mkdir(parents=True, exist_ok=True)

    if not REGISTRY.exists():
        REGISTRY.write_text(
            json.dumps(
                {"schema_version": 1, "analises": []},
                ensure_ascii=False,
                indent=2
            ) + "\n",
            encoding="utf-8"
        )


def read_registry():
    initialize()
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))

    if not isinstance(data.get("analises"), list):
        raise ValueError("Registro inválido: analises deve ser lista")

    return data


def write_registry(data):
    temp = REGISTRY.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    temp.replace(REGISTRY)


def status():
    initialize()

    print("ELEIÇÕES LAB — MOTOR DE ANÁLISES")
    print("=" * 48)
    print("Projeto:", ROOT)
    print("Banco encontrado:", DB.is_file())

    if DB.is_file():
        # Consulta somente leitura; não interfere nas importações.
        uri = DB.as_uri() + "?mode=ro"

        try:
            with sqlite3.connect(
                uri, uri=True, timeout=10
            ) as con:
                tables = [
                    row[0]
                    for row in con.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' ORDER BY name"
                    )
                ]
                print("Tabelas encontradas:", len(tables))
                for table in tables:
                    print("  -", table)
        except sqlite3.Error as exc:
            print("Banco indisponível:", exc)

    registry = read_registry()
    print("Análises cadastradas:", len(registry["analises"]))
    print("Execuções realizadas pelo motor: nenhuma")


def list_analyses():
    registry = read_registry()
    analyses = registry["analises"]

    if not analyses:
        print("Nenhuma análise cadastrada.")
        return

    for entry in analyses:
        print(
            f"{entry['id']} | "
            f"{entry['status']} | "
            f"{entry['titulo']}"
        )


def create_analysis(analysis_id):
    analysis_id = analysis_id.upper()

    if not ID_PATTERN.fullmatch(analysis_id):
        raise ValueError(
            "ID inválido. Use A001, A002, A003..."
        )

    registry = read_registry()

    if any(
        entry["id"] == analysis_id
        for entry in registry["analises"]
    ):
        raise ValueError(f"{analysis_id} já existe no registro")

    folder = ANALYSES / analysis_id

    if folder.exists():
        raise FileExistsError(
            f"Diretório já existente: {folder}"
        )

    folder.mkdir(parents=True)

    protocol = {
        "id": analysis_id,
        "titulo": "A DEFINIR",
        "versao": "0.1",
        "status": "rascunho",
        "pergunta": "A DEFINIR",
        "hipoteses": {
            "h0": "A DEFINIR",
            "h1": "A DEFINIR"
        },
        "fontes": [],
        "metodologia": {
            "populacao": "A DEFINIR",
            "variaveis": [],
            "procedimento": "A DEFINIR"
        },
        "criterios_decisao": {
            "sim": "A DEFINIR",
            "nao": "A DEFINIR",
            "inconclusivo": "A DEFINIR"
        }
    }

    (folder / "pergunta.yaml").write_text(
        yaml.safe_dump(
            protocol,
            allow_unicode=True,
            sort_keys=False
        ),
        encoding="utf-8"
    )

    (folder / "README.md").write_text(
        f"# {analysis_id}\n\n"
        "Análise ainda não definida.\n\n"
        "Nenhuma execução foi realizada.\n",
        encoding="utf-8"
    )

    registry["analises"].append({
        "id": analysis_id,
        "titulo": "A DEFINIR",
        "status": "rascunho",
        "criado_em": timestamp()
    })

    write_registry(registry)
    print(f"Estrutura criada: {folder}")


def validate_analysis(analysis_id):
    analysis_id = analysis_id.upper()
    path = ANALYSES / analysis_id / "pergunta.yaml"

    if not path.exists():
        raise FileNotFoundError(path)

    protocol = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(protocol, dict):
        raise ValueError("O protocolo deve ser um objeto YAML")

    missing = REQUIRED_FIELDS - set(protocol)
    if missing:
        raise ValueError(
            f"Campos obrigatórios ausentes: {sorted(missing)}"
        )

    if protocol["id"] != analysis_id:
        raise ValueError("ID do protocolo não corresponde ao diretório")

    hypotheses = protocol["hipoteses"]
    if not isinstance(hypotheses, dict) or not {
        "h0", "h1"
    }.issubset(hypotheses):
        raise ValueError("Hipóteses H0 e H1 obrigatórias")

    criteria = protocol["criterios_decisao"]
    if not isinstance(criteria, dict) or not DECISIONS.issubset(
        criteria
    ):
        raise ValueError("Critérios de decisão incompletos")

    placeholders = []

    def inspect(obj, prefix=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                inspect(value, f"{prefix}.{key}" if prefix else key)
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                inspect(value, f"{prefix}[{i}]")
        elif isinstance(obj, str) and obj.strip() == "A DEFINIR":
            placeholders.append(prefix)

    inspect(protocol)

    print(f"Protocolo {analysis_id}: estrutura válida")

    if placeholders:
        print("Pendências:")
        for field in placeholders:
            print("  -", field)
        print("Situação: RASCUNHO — não aprovado para execução")
        return False

    if protocol["status"] != "aprovado":
        print("Situação: protocolo ainda não aprovado")
        return False

    print("Validação estrutural concluída.")
    print("Aprovação científica exige revisão metodológica.")
    return True


def create_snapshot():
    initialize()

    if not DB.is_file():
        raise FileNotFoundError(DB)

    name = datetime.now(timezone.utc).strftime(
        "eleicoes_%Y%m%dT%H%M%S_%fZ.sqlite"
    )
    target = SNAPSHOTS / name

    # A API backup() fornece uma cópia transacionalmente
    # consistente, inclusive com WAL habilitado.
    source_uri = DB.as_uri() + "?mode=ro"

    try:
        with sqlite3.connect(
            source_uri, uri=True, timeout=120
        ) as source:
            with sqlite3.connect(
                target, timeout=120
            ) as destination:
                source.backup(destination, pages=1000, sleep=0.25)

                result = destination.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]

                if result != "ok":
                    raise RuntimeError(
                        f"Snapshot inválido: {result}"
                    )

        print("Snapshot criado:", target)
        print("Integridade SQLite:", result)

    except Exception:
        target.unlink(missing_ok=True)
        raise

