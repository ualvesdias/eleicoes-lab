"""Verificação offline dos ZIPs de boletins contra checksums oficiais baixados.

Nunca modifica arquivos brutos, downloads ou votos.  A gravação dos resultados
na tabela verificacoes_hash_bu é explícita (--registrar na CLI).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'eleicoes.sqlite'
HEX_LENGTH = {'sha512': 128, 'sha256': 64}
RESOURCE_RE = re.compile(
    r'^\s*([A-Z]{2}|Exterior)\s*-\s*(Boletim\s+de\s+Urna|Hash\s+SHA2)\s*-\s*'
    r'(Primeiro|Segundo)\s+turno\b', re.IGNORECASE
)
YEAR_RE = re.compile(r'(?<!\d)(2018|2022|2026)(?!\d)')


def now():
    return datetime.now(timezone.utc).isoformat()


def basename(url: str) -> str:
    return Path(unquote(urlsplit(url or '').path)).name


def origem_oficial(url: str) -> bool:
    parsed = urlsplit(url or '')
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and (host == 'tse.jus.br' or host.endswith('.tse.jus.br'))


def hash_file(path: Path, algorithms=('sha512', 'sha256')) -> dict:
    hashers = {name: hashlib.new(name) for name in algorithms}
    with path.open('rb') as src:
        for chunk in iter(lambda: src.read(8 * 1024 * 1024), b''):
            for hasher in hashers.values():
                hasher.update(chunk)
    return {name: h.hexdigest() for name, h in hashers.items()}


def read_checksum(path: Path) -> list[dict]:
    """Parses checksum lines: GNU, BSD, bare hex, and colon-separated forms.

    Deliberately refuses unexpected/binary or large checksum payloads.
    """
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Arquivo de checksum excessivamente grande (>1 MiB)')
    raw = path.read_bytes()
    if raw.startswith(b'\x1f\x8b'):
        with gzip.open(path, 'rb') as f:
            raw = f.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Checksum gzip excessivamente grande')
    if b'\x00' in raw:
        raise ValueError('Checksum contém bytes nulos')
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        content = raw.decode('latin-1')

    entries = []
    for index, line in enumerate(content.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([0-9a-fA-F]{64}|[0-9a-fA-F]{128})', line)
        if match:
            entries.append({'digest': match.group(1).lower(), 'filename': None, 'line': index})
            continue
        match = re.fullmatch(
            r'(?:SHA(?:2-)?(?:256|512))\s*\((.+?)\)\s*=\s*([a-fA-F0-9]{64}|[a-fA-F0-9]{128})',
            line, re.IGNORECASE
        )
        if match:
            entries.append({'digest': match.group(2).lower(), 'filename': match.group(1).strip(), 'line': index})
            continue
        match = re.fullmatch(r'([0-9a-fA-F]{64}|[0-9a-fA-F]{128})\s+\*?(.+)', line)
        if match:
            entries.append({'digest': match.group(1).lower(), 'filename': match.group(2).strip(), 'line': index})
            continue
        match = re.fullmatch(r'(.+?)\s*:\s*([0-9a-fA-F]{64}|[0-9a-fA-F]{128})', line)
        if match:
            entries.append({'digest': match.group(2).lower(), 'filename': match.group(1).strip(), 'line': index})
            continue
        raise ValueError(f'Formato desconhecido na linha {index}: {line[:100]!r}')
    if not entries:
        raise ValueError('Arquivo de checksum vazio ou sem digests')
    return entries


def select_checksum(entries: list[dict], zip_name: str, algo: str) -> str:
    eligible = [e for e in entries if len(e['digest']) == HEX_LENGTH[algo]]
    if not eligible:
        raise ValueError(f'Nenhum checksum {algo.upper()} encontrado')
    # If an entry specifies a filename, require an exact basename match.
    # Never silently trust an unrelated named digest.
    named = [e for e in eligible if e['filename'] is not None]
    if named:
        matches = [e for e in named if Path(e['filename'].replace('\\', '/')).name == zip_name]
        if not matches:
            raise ValueError(f'Checksum não corresponde ao nome do ZIP: {zip_name}')
    else:
        matches = eligible
    values = {e['digest'] for e in matches}
    if len(values) != 1:
        raise ValueError('Checksum ambíguo: múltiplos hashes diferentes')
    return next(iter(values))


def load_catalog(conn: sqlite3.Connection) -> dict:
    rows = conn.execute('''
        SELECT d.title, r.id, r.name, r.url,
               dl.path, dl.status, dl.sha256, dl.url
        FROM resources r
        JOIN datasets d ON d.id=r.dataset_id
        LEFT JOIN downloads dl ON dl.resource_id=r.id
        WHERE lower(d.title) LIKE '%boletim de urna%'
        ORDER BY d.title, r.name
    ''').fetchall()
    groups = defaultdict(lambda: {'zip': [], 'hash': []})
    unclassified = []
    for title, rid, name, url, path, status, sha256, download_url in rows:
        year_match = YEAR_RE.search(title or '')
        match = RESOURCE_RE.match(name or '')
        if not year_match or not match:
            unclassified.append({'dataset': title, 'resource': name, 'id': rid})
            continue
        uf = match.group(1).upper()
        if uf == 'EXTERIOR':
            uf = 'ZZ'
        year, turn = int(year_match.group(1)), (1 if match.group(3).lower() == 'primeiro' else 2)
        kind = 'zip' if match.group(2).lower().startswith('boletim') else 'hash'
        groups[(year, turn, uf)][kind].append({
            'id': rid, 'name': name, 'url': url or '',
            'path': path, 'status': status, 'sha256': sha256,
            'download_url': download_url or ''
        })
    return {'groups': groups, 'unclassified': unclassified}


def verify_one(key, pair) -> dict:
    year, turn, uf = key
    result = {
        'ano': year, 'turno': turn, 'uf': uf, 'status': None,
        'detalhe': '', 'zip_resource_id': None, 'hash_resource_id': None,
        'zip_url': None, 'hash_url': None, 'zip_path': None,
        'hash_path': None, 'algoritmo': None,
        'hash_esperado': None, 'hash_calculado': None,
        'zip_sha256': None, 'sha256_manifesto': None,
        'hash_arquivo_sha256': None, 'tamanho_zip': None,
        'verificado_em': now()
    }

    if len(pair['zip']) != 1 or len(pair['hash']) != 1:
        result['status'] = 'recursos_incompletos'
        result['detalhe'] = f"ZIPs={len(pair['zip'])}; hashes={len(pair['hash'])} (esperado: 1 de cada)"
        return result

    z, h = pair['zip'][0], pair['hash'][0]
    result.update(zip_resource_id=z['id'], hash_resource_id=h['id'],
                  zip_url=z['url'], hash_url=h['url'],
                  zip_path=z['path'], hash_path=h['path'],
                  sha256_manifesto=z['sha256'])
    if not origem_oficial(z['url']) or not origem_oficial(h['url']):
        result.update(status='metadados_incompativeis', detalhe='URL sem HTTPS ou fora do domínio oficial tse.jus.br')
        return result
    zip_name, check_name = basename(z['url']), basename(h['url'])
    if not zip_name.lower().endswith('.zip'):
        result.update(status='metadados_incompativeis', detalhe=f'URL do ZIP termina em {zip_name!r}, esperado .zip')
        return result
    if not (check_name.lower().endswith('.sha512') or check_name.lower().endswith('.sha256')):
        result.update(status='metadados_incompativeis', detalhe=f'URL de checksum termina em {check_name!r}')
        return result
    algorithm = 'sha512' if check_name.lower().endswith('.sha512') else 'sha256'
    result['algoritmo'] = algorithm
    if not check_name.lower().startswith(zip_name.lower() + '.'):
        result.update(status='metadados_incompativeis', detalhe='URL do hash não corresponde ao nome do ZIP oficial')
        return result
    if z['status'] != 'downloaded' or h['status'] != 'downloaded':
        result.update(status='download_pendente', detalhe=f"ZIP={z['status']!r}; hash={h['status']!r}")
        return result
    zip_path = Path(z['path']) if z['path'] else None
    hash_path = Path(h['path']) if h['path'] else None
    if not zip_path or not zip_path.is_file() or not hash_path or not hash_path.is_file():
        result.update(status='arquivo_ausente', detalhe='ZIP ou checksum não encontrado no disco')
        return result
    if zip_path.suffix.lower() != '.zip' or hash_path.suffix.lower() not in ('.sha512', '.sha256'):
        result.update(status='metadados_incompativeis', detalhe='Extensões dos arquivos locais incompatíveis')
        return result
    # A redirected resource may have changed URL between catalog and download.
    if z['download_url'] and basename(z['download_url']) != zip_name:
        result.update(status='metadados_incompativeis', detalhe='URL usada no download diverge do ZIP atualmente catalogado')
        return result
    if h['download_url'] and basename(h['download_url']) != check_name:
        result.update(status='metadados_incompativeis', detalhe='URL usada no download diverge do checksum atualmente catalogado')
        return result

    try:
        result['tamanho_zip'] = zip_path.stat().st_size
        if not zipfile.is_zipfile(zip_path):
            result.update(status='arquivo_invalido', detalhe='Arquivo supostamente ZIP não possui estrutura ZIP válida')
            return result
        result['hash_arquivo_sha256'] = hash_file(hash_path, ('sha256',))['sha256']
        expected = select_checksum(read_checksum(hash_path), zip_name, algorithm)
        result['hash_esperado'] = expected
        computed = hash_file(zip_path, (algorithm, 'sha256'))
        result['hash_calculado'] = computed[algorithm]
        result['zip_sha256'] = computed['sha256']
        if computed[algorithm] != expected:
            result.update(status='divergente', detalhe=f'Checksum oficial {algorithm.upper()} difere dos bytes do ZIP')
        elif z['sha256'] and z['sha256'].lower() != computed['sha256']:
            result.update(status='manifesto_local_divergente', detalhe='Checksum oficial confere, mas SHA-256 do manifesto local diverge')
        elif h['sha256'] and h['sha256'].lower() != result['hash_arquivo_sha256']:
            result.update(status='manifesto_local_divergente', detalhe='Checksum oficial confere, mas SHA-256 local do arquivo de hash diverge do manifesto')
        else:
            result.update(status='confere', detalhe=f'{algorithm.upper()} do ZIP coincide com checksum oficial baixado')
    except (OSError, ValueError, UnicodeError, zipfile.BadZipFile, EOFError) as exc:
        result.update(status='checksum_invalido', detalhe=str(exc)[:500])
    return result


SQL = '''
CREATE TABLE IF NOT EXISTS verificacoes_hash_bu (
    ano INTEGER NOT NULL, turno INTEGER NOT NULL, uf TEXT NOT NULL,
    zip_resource_id TEXT, hash_resource_id TEXT, status TEXT NOT NULL,
    algoritmo TEXT, hash_esperado TEXT, hash_calculado TEXT,
    zip_sha256 TEXT, sha256_manifesto TEXT, hash_arquivo_sha256 TEXT,
    tamanho_zip INTEGER, detalhe TEXT, verificado_em TEXT NOT NULL,
    PRIMARY KEY(ano, turno, uf)
);
'''


def persist(db: Path, results: list[dict]):
    with sqlite3.connect(db, timeout=120) as con:
        con.execute('PRAGMA busy_timeout=120000')
        con.execute(SQL)
        con.executemany('''
            INSERT INTO verificacoes_hash_bu
                (ano, turno, uf, zip_resource_id, hash_resource_id,
                 status, algoritmo, hash_esperado, hash_calculado,
                 zip_sha256, sha256_manifesto, hash_arquivo_sha256,
                 tamanho_zip, detalhe, verificado_em)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ano,turno,uf) DO UPDATE SET
                zip_resource_id=excluded.zip_resource_id,
                hash_resource_id=excluded.hash_resource_id,
                status=excluded.status,
                algoritmo=excluded.algoritmo,
                hash_esperado=excluded.hash_esperado,
                hash_calculado=excluded.hash_calculado,
                zip_sha256=excluded.zip_sha256,
                sha256_manifesto=excluded.sha256_manifesto,
                hash_arquivo_sha256=excluded.hash_arquivo_sha256,
                tamanho_zip=excluded.tamanho_zip,
                detalhe=excluded.detalhe,
                verificado_em=excluded.verificado_em
        ''', [tuple(r.get(k) for k in (
            'ano', 'turno', 'uf', 'zip_resource_id', 'hash_resource_id',
            'status', 'algoritmo', 'hash_esperado', 'hash_calculado',
            'zip_sha256', 'sha256_manifesto', 'hash_arquivo_sha256',
            'tamanho_zip', 'detalhe', 'verificado_em'
        )) for r in results])
        con.commit()


def audit(db: Path, year=None, turn=None, uf=None, limit=None):
    if not db.is_file():
        raise FileNotFoundError(db)
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=60) as con:
        catalog = load_catalog(con)
    groups = catalog['groups']
    # For a selected year, cover ALL 28 UFs even if a pair is missing entirely.
    ufs = ['AC','AL','AM','AP','BA','CE','DF','ES','GO','MA','MG','MS','MT','PA','PB','PE','PI','PR','RJ','RN','RO','RR','RS','SC','SE','SP','TO','ZZ']
    years = [year] if year else [2018, 2022, 2026]
    turns = [turn] if turn else [1, 2]
    keys = [(y, t, x) for y in years for t in turns for x in ([uf] if uf else ufs)]
    if limit is not None:
        keys = keys[:limit]
    results = []
    for i, key in enumerate(keys, 1):
        r = verify_one(key, groups.get(key, {'zip': [], 'hash': []}))
        results.append(r)
        print(f"[{i}/{len(keys)}] {key[0]} T{key[1]} {key[2]}: {r['status']}", flush=True)
        if r['status'] != 'confere':
            print(f"    {r['detalhe']}", flush=True)
    return results, catalog['unclassified']


def main(argv=None):
    parser = argparse.ArgumentParser(description='Confronta hashes oficiais baixados do TSE com ZIPs locais dos boletins')
    parser.add_argument('--ano', type=int, choices=(2018, 2022, 2026))
    parser.add_argument('--turno', type=int, choices=(1, 2))
    parser.add_argument('--uf', type=str)
    parser.add_argument('--limite', type=int)
    parser.add_argument('--db', type=Path, default=DB)
    parser.add_argument('--registrar', action='store_true', help='Grava verificações em tabela própria, nunca nos dados eleitorais')
    parser.add_argument('--estrito', action='store_true', help='Código de saída 2 se algo não conferir')
    args = parser.parse_args(argv)
    if args.uf:
        args.uf = args.uf.upper()
        if args.uf not in {'AC','AL','AM','AP','BA','CE','DF','ES','GO','MA','MG','MS','MT','PA','PB','PE','PI','PR','RJ','RN','RO','RR','RS','SC','SE','SP','TO','ZZ'}:
            parser.error('UF inválida (use ZZ para exterior)')
    if args.limite is not None and args.limite <= 0:
        parser.error('--limite deve ser positivo')
    try:
        results, unclassified = audit(args.db.resolve(), args.ano, args.turno, args.uf, args.limite)
        counts = Counter(x['status'] for x in results)
        print('\nRESUMO DA INTEGRIDADE DOS BOLETINS')
        for label, count in sorted(counts.items()):
            print(f'  {label:<28} {count}')
        print(f'  recursos não classificados:    {len(unclassified)}')
        report = {
            'versao_esquema': 1, 'gerado_em': now(), 'banco': str(args.db.resolve()),
            'filtros': {'ano': args.ano, 'turno': args.turno, 'uf': args.uf, 'limite': args.limite},
            'resultados': results, 'recursos_nao_classificados': unclassified
        }
        target_dir = args.db.resolve().parent / 'manifests'
        target_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        target = target_dir / f'verificacao_hash_bu_{stamp}.json'
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print('Manifesto:', target)
        if args.registrar:
            persist(args.db.resolve(), results)
            print('Registro SQLite: verificacoes_hash_bu')
        if args.estrito and (counts.get('confere', 0) != len(results) or unclassified):
            return 2
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f'ERRO: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
