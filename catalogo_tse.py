#!/usr/bin/env python3
"""Entrada permanente do catálogo oficial TSE.

Sem --aplicar, apenas consulta e gera prévia. Não importa ou baixa votos.
Exemplos:
    python catalogo_tse.py --auditar-local --ano 2026 --categoria boletins
    python catalogo_tse.py --ano 2026 --categoria boletins
    python catalogo_tse.py --ano 2026 --categoria boletins --aplicar
    python catalogo_tse.py --ano 2026 --descobrir --aplicar
"""
from eleicoes_lab.catalogo import cli

if __name__ == "__main__":
    raise SystemExit(cli())
