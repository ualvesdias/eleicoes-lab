import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from eleicoes_lab import catalogo

DATASET_ID = 'dataset-teste'
ZIP_ID = 'zip-id'
HASH_ID = 'hash-id'
ZIP = 'https://cdn.tse.jus.br/estatistica/bweb_2t_RR_261020260742.zip'
HASH = ZIP + '.sha512'


def resource(rid=ZIP_ID, url=ZIP, name='RR - Boletim de Urna - Segundo turno - 26.10.2026'):
    return {'id': rid, 'package_id': DATASET_ID, 'name': name, 'format': 'ZIP', 'url': url}


class TestCatalogo(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'eleicoes.sqlite'
        with sqlite3.connect(self.db) as con:
            con.executescript('''
                CREATE TABLE datasets (
                    id TEXT PRIMARY KEY, title TEXT, metadata_json TEXT NOT NULL,
                    discovered_at TEXT NOT NULL
                );
                CREATE TABLE resources (
                    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL,
                    name TEXT, format TEXT, url TEXT,
                    metadata_json TEXT NOT NULL,
                    download_status TEXT DEFAULT 'pending', local_path TEXT, sha256 TEXT
                );
                CREATE TABLE downloads (
                    resource_id TEXT PRIMARY KEY, dataset_id TEXT,
                    year INTEGER, category TEXT, url TEXT, path TEXT,
                    status TEXT, sha256 TEXT
                );
                CREATE TABLE votos_bu (dummy INTEGER);
            ''')
            con.execute('INSERT INTO datasets VALUES (?,?,?,?)',
                (DATASET_ID, 'Resultados - 2026 - Boletim de Urna',
                 json.dumps({'id': DATASET_ID, 'name': 'resultados-2026-boletim-de-urna'}), '2026'))

    def tearDown(self):
        self.temp.cleanup()

    def pkg(self, resources):
        return {'id': DATASET_ID, 'name': 'resultados-2026-boletim-de-urna',
                'title': 'Resultados - 2026 - Boletim de Urna', 'resources': resources}

    def fake_api(self, s, action, params):
        rid = params['id']
        if action == 'resource_show':
            for r in self.resources:
                if r['id'] == rid:
                    return r
        if action == 'package_show':
            return self.pkg(self.resources)
        raise AssertionError((action, params))

    def test_bootstrap_novo_clone(self):
        self.db.unlink()
        self.resources = [resource()]
        with patch.object(catalogo, 'descobrir', return_value=[
            (DATASET_ID, 'Resultados - 2026 - Boletim de Urna',
             {'id': DATASET_ID, 'name': 'resultados-2026-boletim-de-urna'})
        ]), patch.object(catalogo, 'api', self.fake_api), \
                patch.object(catalogo, 'verificar_conteudo', return_value=4):
            rc = catalogo.cli(['--ano', '2026', '--categoria', 'boletins',
                               '--descobrir', '--aplicar'], root=self.root, client=object())
            self.assertEqual(rc, 0)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM resources').fetchone()[0], 1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM datasets').fetchone()[0], 1)

    def test_probe_remoto_exige_assinatura_zip(self):
        class FakeResponse:
            status_code = 206
            url = ZIP
            headers = {'Content-Range': 'bytes 0-3/10000'}
            def __init__(self, data):
                self.data = data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def raise_for_status(self):
                return None
            def iter_content(self, chunk_size=256):
                yield self.data

        class FakeSession:
            def __init__(self, data):
                self.data = data
            def get(self, *args, **kwargs):
                return FakeResponse(self.data)

        self.assertEqual(catalogo.verificar_conteudo(
            FakeSession(b'PK\x03\x04'), ZIP, 'boletim'), 4)
        with self.assertRaisesRegex(ValueError, 'assinatura ZIP'):
            catalogo.verificar_conteudo(FakeSession(b'<html>erro</html>'), ZIP, 'boletim')

    def test_probe_remoto_exige_digest(self):
        class Response:
            status_code = 200
            url = HASH
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def raise_for_status(self): pass
            def iter_content(self, chunk_size=256):
                yield b'arquivo indisponivel'
        class Session:
            def get(self, *args, **kwargs): return Response()
        with self.assertRaisesRegex(ValueError, 'checksum|digest SHA'):
            catalogo.verificar_conteudo(Session(), HASH, 'hash')

    def test_url_zip_nao_pode_ser_checksum(self):
        erros = catalogo.validar_metadados(resource(url=HASH), True)
        self.assertTrue(any('Boletim' in x for x in erros))

    def test_hash_requer_checksum(self):
        erros = catalogo.validar_metadados(resource(HASH_ID, ZIP, 'RR - Hash SHA2 - Segundo turno - 26.10.2026'), True)
        self.assertTrue(any('Hash' in x for x in erros))

    def test_url_oficial_anti_spoof(self):
        self.assertFalse(catalogo.url_oficial('https://cdn.tse.jus.br.evil.com/file.zip'))
        self.assertFalse(catalogo.url_oficial('http://cdn.tse.jus.br/file.zip'))
        self.assertTrue(catalogo.url_oficial(ZIP))

    def test_insert_nao_toca_nas_tabelas_de_votacao(self):
        self.resources = [resource()]
        with sqlite3.connect(self.db) as con, patch.object(catalogo, 'api', self.fake_api), patch.object(catalogo, 'verificar_conteudo', return_value=4):
            plan, problems = catalogo.plano_atualizacao(con, [self.pkg(self.resources)], object(), {}, True)
            self.assertEqual(problems, [])
            self.assertEqual(len(plan), 1)
            catalogo.aplicar(con, [self.pkg(self.resources)], plan)
            catalogo.aplicar(con, [self.pkg(self.resources)], [])
            self.assertEqual(con.execute('SELECT COUNT(*) FROM resources').fetchone()[0], 1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM votos_bu').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM catalogo_historico').fetchone()[0], 1)

    def test_idempotencia(self):
        self.resources = [resource()]
        with sqlite3.connect(self.db) as con, patch.object(catalogo, 'api', self.fake_api):
            catalogo.aplicar(con, [self.pkg(self.resources)], [{
                'acao': 'inserir', 'dataset_id': DATASET_ID,
                'resource_id': ZIP_ID, 'nome': self.resources[0]['name'],
                'url_antiga': None, 'url_nova': ZIP,
                'metadados': self.resources[0], 'oficial': self.resources[0], 'override': None}])
            plan, errors = catalogo.plano_atualizacao(con, [self.pkg(self.resources)], object(), {}, True)
            self.assertEqual((plan, errors), ([], []))

    def test_nao_substitui_recurso_baixado(self):
        self.resources = [resource(url=ZIP.replace('.zip', '_novo.zip'))]
        old = resource()
        with sqlite3.connect(self.db) as con, patch.object(catalogo, 'api', self.fake_api), patch.object(catalogo, 'verificar_conteudo', return_value=4):
            con.execute('INSERT INTO resources (id,dataset_id,name,format,url,metadata_json) VALUES (?,?,?,?,?,?)',
                        (ZIP_ID, DATASET_ID, old['name'], old['format'], ZIP, json.dumps(old)))
            con.execute('INSERT INTO downloads (resource_id,url,status) VALUES (?,?,?)', (ZIP_ID, ZIP, 'downloaded'))
            con.commit()
            plan, problems = catalogo.plano_atualizacao(con, [self.pkg(self.resources)], object(), {}, True)
            self.assertFalse(plan)
            self.assertTrue(any('já foi baixado' in x['erro'] for x in problems))
            self.assertEqual(con.execute('SELECT url FROM resources').fetchone()[0], ZIP)

    def test_erro_da_api_nao_sobrescreve_url_corrigida(self):
        self.resources = [resource(url=HASH)]
        with sqlite3.connect(self.db) as con:
            old = resource()
            con.execute('INSERT INTO resources (id,dataset_id,name,format,url,metadata_json) VALUES (?,?,?,?,?,?)',
                        (ZIP_ID, DATASET_ID, old['name'], 'ZIP', ZIP, json.dumps(old)))
            con.commit()
            plan, problems = catalogo.plano_atualizacao(con, [self.pkg(self.resources)], object(), {}, False)
            self.assertEqual(plan, [])
            self.assertTrue(problems)
            self.assertEqual(con.execute('SELECT url FROM resources').fetchone()[0], ZIP)

    def test_override_exige_procedencia(self):
        file = self.root / 'overrides.json'
        file.write_text(json.dumps({ZIP_ID: {'url': ZIP}}))
        with self.assertRaises(ValueError):
            catalogo.carregar_overrides(file)

    def test_auditoria_detecta_inconsistencia_existente(self):
        with sqlite3.connect(self.db) as con:
            bad = resource(url=HASH)
            con.execute('INSERT INTO resources (id,dataset_id,name,format,url,metadata_json) VALUES (?,?,?,?,?,?)',
                        (ZIP_ID, DATASET_ID, bad['name'], 'ZIP', HASH, json.dumps(bad)))
            con.commit()
            issues = catalogo.auditar_local(con, [2026], 'boletins')
            self.assertTrue(issues)

    def test_dry_run_cli_nao_muda_db(self):
        self.resources = [resource()]
        with patch.object(catalogo, 'api', self.fake_api):
            rc = catalogo.cli(['--ano', '2026', '--categoria', 'boletins'], root=self.root, client=object())
            self.assertEqual(rc, 0)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM resources').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
