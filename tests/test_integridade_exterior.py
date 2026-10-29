"""Regressão: o TSE nomeia os recursos do exterior de 2018 como 'Exterior'."""
import hashlib
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from eleicoes_lab import integridade_tse


class TestExterior2018(unittest.TestCase):
    def test_exterior_dos_dois_turnos_eh_zz(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / "eleicoes.sqlite"
            base = "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2018/buweb/"
            with sqlite3.connect(db) as con:
                con.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, title TEXT)")
                con.execute("CREATE TABLE resources (id TEXT PRIMARY KEY, dataset_id TEXT, name TEXT, url TEXT)")
                con.execute("CREATE TABLE downloads (resource_id TEXT PRIMARY KEY, path TEXT, status TEXT, sha256 TEXT, url TEXT)")
                con.execute("INSERT INTO datasets VALUES (?, ?)", ("d2018", "Resultados - 2018 - Boletim de Urna"))
                for turno, ordinal in ((1, "Primeiro"), (2, "Segundo")):
                    zp = root / f"bweb_{turno}t_ZZ_teste.zip"
                    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
                        z.writestr("bweb.csv", "ANO_ELEICAO;QT_VOTOS\n2018;1\n")
                    hp = root / (zp.name + ".sha512")
                    hp.write_text(hashlib.sha512(zp.read_bytes()).hexdigest() + f"  {zp.name}\n", encoding="ascii")
                    for suffix, label, path in (("zip", "Boletim de urna", zp), ("hash", "Hash SHA2", hp)):
                        rid = f"{turno}-{suffix}"
                        url = base + path.name
                        con.execute("INSERT INTO resources VALUES (?,?,?,?)", (rid, "d2018", f"Exterior - {label} - {ordinal} turno - 2018", url))
                        con.execute("INSERT INTO downloads VALUES (?,?,?,?,?)", (rid, str(path), "downloaded", hashlib.sha256(path.read_bytes()).hexdigest(), url))

            for turno in (1, 2):
                with self.subTest(turno=turno):
                    results, unknown = integridade_tse.audit(db, year=2018, turn=turno, uf="ZZ")
                    self.assertEqual(unknown, [])
                    self.assertEqual(len(results), 1)
                    self.assertEqual(results[0]["status"], "confere")
                    self.assertEqual(results[0]["uf"], "ZZ")

    def test_alias_exterior_nao_confunde_uf_valida(self):
        match = integridade_tse.RESOURCE_RE.match("RR - Boletim de urna - Segundo turno - 2026")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "RR")


if __name__ == "__main__":
    unittest.main()
