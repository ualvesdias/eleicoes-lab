
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from eleicoes_lab import runner


class TestAnalysisRunner(unittest.TestCase):

    def test_formato_id_execucao(self):
        pasta = runner.executar(
            "A999", self.snapshot, self.root
        )

        import re

        self.assertRegex(
            pasta.name,
            r"^\d{8}T\d{6}_\d{6}Z_[0-9a-f]{8}$"
        )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.analysis = self.root / "analises" / "A999"
        self.analysis.mkdir(parents=True)

        self.snapshot = self.root / "teste.sqlite"

        with sqlite3.connect(self.snapshot) as con:
            con.execute("""
                CREATE TABLE dados_teste (
                    id INTEGER PRIMARY KEY,
                    valor INTEGER NOT NULL
                )
            """)
            con.executemany(
                "INSERT INTO dados_teste(valor) VALUES (?)",
                [(10,), (20,), (30,)]
            )

        self.protocol = {
            "id": "A999",
            "titulo": "Teste sintético do motor",
            "versao": "0.1",
            "status": "aprovado",
            "pergunta": "O conjunto sintético possui três registros?",
            "hipoteses": {
                "h0": "O conjunto possui três registros.",
                "h1": "O conjunto não possui três registros."
            },
            "fontes": ["Dados sintéticos gerados no teste"],
            "metodologia": {
                "populacao": "Três registros sintéticos",
                "variaveis": ["valor"],
                "procedimento": "Contagem SQL"
            },
            "criterios_decisao": {
                "sim": "Contagem igual a três",
                "nao": "Contagem diferente de três",
                "inconclusivo": "Consulta indisponível"
            }
        }

        self.protocol_path = self.analysis / "pergunta.yaml"
        self.protocol_path.write_text(
            yaml.safe_dump(
                self.protocol,
                allow_unicode=True,
                sort_keys=False
            ),
            encoding="utf-8"
        )

        self.code_path = self.analysis / "analise.py"
        self.code_path.write_text(
            """
def executar(contexto):
    linhas = contexto.consulta(
        "SELECT COUNT(*) AS n FROM dados_teste"
    )
    n = linhas[0]["n"]

    contexto.evidencia(
        "quantidade_registros",
        n,
        "snapshot sintético",
        "SELECT COUNT(*)"
    )

    return {
        "conclusao": "sim" if n == 3 else "nao",
        "justificativa": "Resultado da contagem sintética.",
        "resultados": {"contagem": n},
        "limitacoes": ["Teste sem dados eleitorais reais."]
    }
""",
            encoding="utf-8"
        )

        self.git_patch = patch.object(
            runner,
            "git_info",
            return_value={
                "commit": "a" * 40,
                "dirty": False
            }
        )
        self.git_patch.start()

    def tearDown(self):
        self.git_patch.stop()
        self.tmp.cleanup()

    def test_protocolo_aprovado(self):
        protocolo = runner.carregar_protocolo(
            self.root, "A999"
        )
        self.assertEqual(protocolo["id"], "A999")

    def test_protocolo_rascunho_bloqueado(self):
        self.protocol["status"] = "rascunho"
        self.protocol_path.write_text(
            yaml.safe_dump(self.protocol, allow_unicode=True),
            encoding="utf-8"
        )

        with self.assertRaises(ValueError):
            runner.carregar_protocolo(self.root, "A999")

    def test_execucao_com_evidencias(self):
        pasta = runner.executar(
            "A999", self.snapshot, self.root
        )

        self.assertTrue((pasta / "execucao.json").is_file())
        self.assertTrue((pasta / "evidencias.json").is_file())
        self.assertTrue((pasta / "relatorio.md").is_file())

        evidencias = json.loads(
            (pasta / "evidencias.json").read_text()
        )

        self.assertEqual(
            evidencias["resultado"]["resultados"]["contagem"],
            3
        )
        self.assertEqual(
            evidencias["resultado"]["conclusao"],
            "sim"
        )
        self.assertEqual(len(evidencias["eventos"]), 2)

    def test_publicacao_revisada(self):
        pasta = runner.executar(
            "A999", self.snapshot, self.root
        )

        destino = runner.publicar(
            "A999", pasta.name, "Revisor de teste",
            self.root
        )

        self.assertTrue((destino / "RELATORIO.md").exists())
        self.assertTrue(
            (destino / "reprodutibilidade.json").exists()
        )

        revisao = json.loads(
            (destino / "reprodutibilidade.json").read_text()
        )
        self.assertEqual(
            revisao["revisor"], "Revisor de teste"
        )

        with self.assertRaises(FileExistsError):
            runner.publicar(
                "A999", pasta.name, "Outro revisor",
                self.root
            )

    def test_conclusao_invalida(self):
        with self.assertRaises(ValueError):
            runner.validar_resultado({
                "conclusao": "talvez",
                "justificativa": "Teste",
                "resultados": {},
                "limitacoes": []
            })

    def test_snapshot_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            runner.executar(
                "A999",
                self.root / "nao_existe.sqlite",
                self.root
            )


if __name__ == "__main__":
    unittest.main()

