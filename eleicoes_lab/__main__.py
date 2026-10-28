
import argparse
import sys

from . import engine


def main():
    parser = argparse.ArgumentParser(
        prog="eleicoes_lab",
        description="Motor de análises do Eleições Lab"
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True
    )

    commands.add_parser(
        "status",
        help="Exibe estado do projeto e banco"
    )

    commands.add_parser(
        "listar",
        help="Lista análises cadastradas"
    )

    new = commands.add_parser(
        "nova",
        help="Cria uma estrutura de análise"
    )
    new.add_argument("id")

    validate = commands.add_parser(
        "validar",
        help="Valida o protocolo de uma análise"
    )
    validate.add_argument("id")

    commands.add_parser(
        "snapshot",
        help="Cria uma cópia consistente do SQLite"
    )

    args = parser.parse_args()

    try:
        if args.command == "status":
            engine.status()

        elif args.command == "listar":
            engine.list_analyses()

        elif args.command == "nova":
            engine.create_analysis(args.id)

        elif args.command == "validar":
            valid = engine.validate_analysis(args.id)
            if not valid:
                return 2

        elif args.command == "snapshot":
            engine.create_snapshot()

    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

