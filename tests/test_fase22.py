import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from eleicoes_lab import coverage, runner, reporting


class TestFase22(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.analise = self.root / 'analises' / 'A999'
        self.analise.mkdir(parents=True)
        self.snapshot = self.root / 'teste.sqlite'
        with sqlite3.connect(self.snapshot) as con:
            con.execute('CREATE TABLE dados_teste(id INTEGER PRIMARY KEY, valor INTEGER)')
            con.executemany('INSERT INTO dados_teste(valor) VALUES (?)', [(10,), (20,), (30,)])
            con.executescript('''
              CREATE TABLE datasets(id TEXT, title TEXT);
              CREATE TABLE resources(id TEXT, dataset_id TEXT, name TEXT, format TEXT, url TEXT);
              CREATE TABLE downloads(resource_id TEXT, status TEXT, sha256 TEXT);
              CREATE TABLE importacoes_bu(resource_id TEXT, sha256 TEXT, linhas_presidente INTEGER);
            ''')
            con.execute("INSERT INTO datasets VALUES ('D1','Resultados - 2018 - Boletim de Urna')")
            con.execute("INSERT INTO resources VALUES ('R1','D1','AC - Boletim de urna - Primeiro turno','ZIP','https://tse/AC.zip')")
            con.execute("INSERT INTO downloads VALUES ('R1','downloaded','abc')")
            con.execute("INSERT INTO importacoes_bu VALUES ('R1','abc',100)")
        self.protocol = {
            'id':'A999','titulo':'Teste sintético','versao':'0.1','status':'aprovado',
            'pergunta':'O conjunto sintético possui três registros?',
            'hipoteses': {'h0':'Possui', 'h1':'Não possui'},
            'fontes':['Dados sintéticos'],
            'metodologia': {'populacao':'dados sintéticos','variaveis':['valor'],'procedimento':'COUNT'},
            'criterios_decisao': {'sim':'3', 'nao':'diferente', 'inconclusivo':'não acessível'}
        }
        self.protocol_path = self.analise/'pergunta.yaml'
        self.protocol_path.write_text(yaml.safe_dump(self.protocol,allow_unicode=True), encoding='utf-8')
        self.analise.joinpath('analise.py').write_text('''
def executar(contexto):
    rows = contexto.consulta("SELECT COUNT(*) AS n FROM dados_teste")
    contexto.evidencia('contagem',rows[0]['n'],'snapshot sintético','COUNT')
    return {'conclusao':'sim','justificativa':'Três registros.',
            'resultados': {'n':rows[0]['n']}, 'limitacoes':['Sintéticos'],
            'tabelas':[{'titulo':'Contagem','colunas':['Métrica','Valor'],
                        'linhas':[['Linhas', rows[0]['n']]]}],
            'incertezas':[{'metodo':'Contagem exata','aplicavel':False}]}
''', encoding='utf-8')
        self.gitpatch=patch.object(runner,'git_info',return_value={'commit':'a'*40,'dirty':False})
        self.gitpatch.start()

    def tearDown(self):
        self.gitpatch.stop()
        self.tmp.cleanup()

    def test_cobertura_nao_e_completeza_eleitoral(self):
        with sqlite3.connect(self.snapshot) as con:
            cov=coverage.auditar(con)
        ac=next(s for s in cov['segmentos'] if s['ano']==2018 and s['turno']==1 and s['uf']=='AC')
        self.assertEqual(ac['estado'],'ok')
        r=next(s for s in cov['resumo'] if s['ano']==2018 and s['turno']==1)
        self.assertEqual(r['estado'],'parcial')
        self.assertEqual(r['ufs_com_arquivos_importados'],1)
        ok,pend = coverage.verificar_escopo(cov,{'anos':[2018],'turnos':[1],'ufs':['AC']})
        self.assertTrue(ok)

    def test_integracao(self):
        pasta=runner.executar('A999',self.snapshot,self.root)
        eventos=json.loads((pasta/'evidencias.json').read_text())['eventos']
        self.assertEqual(len(eventos),2)
        self.assertTrue((pasta/'consultas'/'consulta_0001.jsonl').exists())
        md=(pasta/'relatorio.md').read_text()
        self.assertIn('Contagem',md)
        self.assertIn('Incertezas',md)
        rel=runner.publicar('A999',pasta.name,'Revisão sintética',self.root)
        self.assertTrue((rel/'RELATORIO.md').exists())
        self.assertTrue((self.root/'relatorios'/'README.md').exists())
        man=json.loads((rel/'reprodutibilidade.json').read_text())
        self.assertEqual(len(man['consultas']),1)

    def test_bloqueio_cobertura(self):
        self.protocol['exigir_cobertura_arquivos']=True
        self.protocol['escopo']={'anos':[2018],'turnos':[1,2],'ufs':['AC']}
        self.protocol_path.write_text(yaml.safe_dump(self.protocol,allow_unicode=True),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Cobertura'):
            runner.executar('A999',self.snapshot,self.root)

    def test_resultado_excessivo_bloqueia(self):
        with sqlite3.connect(self.snapshot) as con:
            con.execute('PRAGMA query_only=ON')
            from eleicoes_lab.evidence import gravar_consulta
            with self.assertRaisesRegex(ValueError,'limite'):
                gravar_consulta(con,'SELECT * FROM dados_teste',(),self.root/'queries',[],max_linhas=2)
        self.assertFalse((self.root/'queries'/'consulta_0001.jsonl').exists())

    def test_integridade_evidencia_impede_publicar(self):
        pasta=runner.executar('A999',self.snapshot,self.root)
        with (pasta/'consultas'/'consulta_0001.jsonl').open('ab') as f:
            f.write(b'alterado')
        with self.assertRaisesRegex(ValueError,'Evidência SQL inválida'):
            runner.publicar('A999',pasta.name,'Revisor',self.root)


if __name__=='__main__':
    unittest.main()
