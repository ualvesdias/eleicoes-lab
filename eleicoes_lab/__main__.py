
import argparse
import sys
from pathlib import Path

from . import engine, runner


def main():
    parser = argparse.ArgumentParser(
        prog="eleicoes_lab",
        description="Motor de análises do Eleições Lab"
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True
    )

    commands.add_parser("status")
    commands.add_parser("listar")
    commands.add_parser("snapshot")

    new = commands.add_parser("nova")
    new.add_argument("id")

    validate = commands.add_parser("validar")
    validate.add_argument("id")

    execute = commands.add_parser("executar")
    execute.add_argument("id")
    execute.add_argument(
        "--snapshot",
        type=Path,
        required=True,
        help="Caminho do snapshot SQLite"
    )

    publish = commands.add_parser("publicar")
    publish.add_argument("id")
    publish.add_argument("execucao")
    publish.add_argument(
        "--revisor",
        required=True,
        help="Responsável pela revisão técnica"
    )

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
            runner.publicar(
                args.id.upper(),
                args.execucao,
                args.revisor
            )

    except (OSError, ValueError, RuntimeError,
            KeyError, TypeError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

