"""Interface de linha de comando do Eleições Lab."""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from . import coverage, engine, runner


def auditar_cobertura(snapshot: Path, saida: Path | None, profundo: bool = False):
    snapshot = snapshot.resolve()
    if not snapshot.is_file():
        raise FileNotFoundError(snapshot)
    uri = snapshot.as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True, timeout=120)) as con:
        auditoria = coverage.auditar(con, profundo=profundo)
    print("COBERTURA DOCUMENTAL DOS BOLETINS (NÃO é cobertura de seções)")
    if auditoria["estado"] != "avaliada":
        print("Não disponível:", auditoria.get("tabelas_ausentes", []))
    else:
        for linha in auditoria["resumo"]:
            print(f"{linha['ano']} | T{linha['turno']} | "
                  f"{linha['ufs_com_arquivos_importados']}/{linha['ufs_esperadas']} UFs "
                  f"| {linha['estado']}")
        print("Recursos não classificados:", len(auditoria["nao_classificados"]))
    destino = saida or (
        engine.ROOT / "resultados_analises" / "coberturas" / f"{snapshot.stem}.json"
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(auditoria, ensure_ascii=False,
                                  indent=2) + "\n", encoding="utf-8")
    print("Manifesto local:", destino)


def main():
    parser = argparse.ArgumentParser(
        prog="eleicoes_lab", description="Motor de análises do Eleições Lab")
    cmds = parser.add_subparsers(dest="command", required=True)
    for nome in ("status", "listar", "snapshot"):
        cmds.add_parser(nome)

    nova = cmds.add_parser("nova")
    nova.add_argument("id")
    validar = cmds.add_parser("validar")
    validar.add_argument("id")
    executar = cmds.add_parser("executar")
    executar.add_argument("id")
    executar.add_argument("--snapshot", type=Path, required=True)
    publicar = cmds.add_parser("publicar")
    publicar.add_argument("id")
    publicar.add_argument("execucao")
    publicar.add_argument("--revisor", required=True)
    cov = cmds.add_parser("cobertura", help="Inventaria a cobertura de arquivos em um snapshot")
    cov.add_argument("--snapshot", type=Path, required=True)
    cov.add_argument("--saida", type=Path)
    cov.add_argument("--profundo", action="store_true", help="Conta seções observadas; pode demorar")

    args = parser.parse_args()
    try:
        if args.command == "status":
            engine.status()
        elif args.command == "listar":
            engine.list_analyses()
        elif args.command == "snapshot":
            engine.create_snapshot()
        elif args.command == "nova":
            engine.create_analysis(args.id)
        elif args.command == "validar":
            if not engine.validate_analysis(args.id):
                return 2
        elif args.command == "executar":
            runner.executar(args.id.upper(), args.snapshot)
        elif args.command == "publicar":
            runner.publicar(args.id.upper(), args.execucao, args.revisor)
        elif args.command == "cobertura":
            auditar_cobertura(args.snapshot, args.saida, args.profundo)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError,
            sqlite3.Error) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
