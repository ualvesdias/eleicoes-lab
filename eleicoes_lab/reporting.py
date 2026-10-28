"""Relatórios técnicos Markdown e índice público do repositório."""
from __future__ import annotations

import json
from pathlib import Path

DECISOES = {"sim": "SIM", "nao": "NÃO", "inconclusivo": "NÃO FOI POSSÍVEL CONCLUIR"}


def celula(valor) -> str:
    return str(valor if valor is not None else "—").replace("|", "\\|").replace("\n", " ")


def tabela(colunas, linhas) -> str:
    if not colunas:
        raise ValueError("Tabela sem colunas")
    if any(len(linha) != len(colunas) for linha in linhas):
        raise ValueError("Tabela com número de células incompatível")
    cabecalho = "| " + " | ".join(map(celula, colunas)) + " |"
    separador = "| " + " | ".join("---" for _ in colunas) + " |"
    corpo = ["| " + " | ".join(map(celula, linha)) + " |" for linha in linhas]
    return "\n".join([cabecalho, separador, *corpo])


def json_md(objeto) -> str:
    return "```json\n" + json.dumps(objeto, indent=2, ensure_ascii=False, default=str) + "\n```"


def construir(protocolo: dict, resultado: dict, manifesto: dict,
              cobertura: dict, evidencias: list) -> str:
    resumo = cobertura.get("resumo", [])
    cobertura_tabela = tabela(
        ["Eleição", "Turno", "UFs com ZIP importado", "Esperadas", "Estado"],
        [[r["ano"], r["turno"], r["ufs_com_arquivos_importados"],
          r["ufs_esperadas"], r["estado"]] for r in resumo]
    ) if resumo else "Auditoria de cobertura indisponível neste snapshot."

    tabelas = []
    for item in resultado.get("tabelas", []):
        tabelas.append(f"### {item['titulo']}\n\n" +
                       tabela(item["colunas"], item["linhas"]))
    graficos = []
    for grafico in resultado.get("graficos", []):
        # O runner verifica caminhos e existência antes de gerar o relatório.
        graficos.append(f"### {grafico['titulo']}\n\n![{celula(grafico['titulo'])}]"
                        f"({grafico['arquivo']})")
    incertezas = resultado.get("incertezas", [])
    metricas = json_md(incertezas) if incertezas else "Nenhuma métrica de incerteza fornecida."
    referencias = resultado.get("referencias", [])
    fontes = protocolo.get("fontes", [])
    links = [f"- {celula(x)}" for x in [*fontes, *referencias]]
    reg = [e for e in evidencias if e.get("tipo") == "consulta_sql"]
    referencias_consultas = tabela(
        ["Consulta", "Linhas", "SHA-256 do resultado"],
        [[e["id"], e["quantidade_linhas"], f"`{e['sha256_resultado']}`"] for e in reg]
    ) if reg else "Nenhuma consulta SQL registrada."
    limitacoes = resultado.get("limitacoes", [])

    return f"""# Relatório técnico — {protocolo['id']}

## 1. Identificação

- **Título:** {protocolo['titulo']}
- **Versão do protocolo:** {protocolo['versao']}
- **Execução:** `{manifesto['id']}`
- **Data UTC:** {manifesto['criado_em']}
- **Commit Git:** `{manifesto['codigo']['commit']}`
- **SHA-256 do snapshot:** `{manifesto['snapshot_sha256']}`
- **Status:** relatório gerado; publicação depende de revisão explícita

## 2. Pergunta central

{protocolo['pergunta']}

## 3. Hipóteses

{json_md(protocolo['hipoteses'])}

## 4. Fontes e cobertura

{cobertura_tabela}

**Limite:** cobertura de ZIPs não comprova cobertura de todas as seções,
reconciliação dos votos nem autenticidade dos arquivos de origem.

## 5. Metodologia e critérios de decisão

{json_md(protocolo['metodologia'])}

{json_md(protocolo['criterios_decisao'])}

## 6. Resultados

{json_md(resultado['resultados'])}

{chr(10).join(tabelas) or 'Nenhuma tabela adicional.'}

{chr(10).join(graficos) or 'Nenhum gráfico produzido.'}

## 7. Incertezas e sensibilidade

{metricas}

## 8. Evidências auditáveis

{referencias_consultas}

Os resultados completos das consultas são preservados localmente em JSONL.
Os hashes e as instruções SQL constam no manifesto de reprodução.

## 9. Discussão e limitações

{chr(10).join('- ' + str(v) for v in limitacoes) or '- Nenhuma limitação informada.'}

## 10. Conclusão

**Resposta: {DECISOES[resultado['conclusao']]}**

{resultado['justificativa']}

## 11. Reprodutibilidade

- **Protocolo SHA-256:** `{manifesto['protocolo_sha256']}`
- **Código da análise SHA-256:** `{manifesto['codigo_analise_sha256']}`
- **Python:** `{manifesto['ambiente']['python']}`
- **SQLite:** `{manifesto['ambiente']['sqlite']}`

A reprodução exige os dados oficiais correspondentes ao snapshot, além
 do código, parâmetros e protocolo identificados no manifesto.

## 12. Referências

{chr(10).join(links) or '- Não informadas.'}

## 13. Revisões

- Documento gerado automaticamente. Revisão registrada no manifesto público.
"""


def atualizar_indice(root: Path):
    raiz = root / "relatorios"
    raiz.mkdir(exist_ok=True)
    registros = []
    for arquivo in raiz.glob("A*/**/reprodutibilidade.json"):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        relatorio = arquivo.parent / "RELATORIO.md"
        if not relatorio.is_file():
            continue
        registros.append((dados.get("analise", ""), dados.get("execucao", ""),
                          dados.get("titulo", ""), dados.get("conclusao", ""),
                          relatorio.relative_to(raiz).as_posix()))
    registros.sort(key=lambda r: (r[0], r[1]), reverse=True)
    linhas = ["# Relatórios técnicos — Eleições Lab", "",
              "Índice das **execuções revisadas e publicadas**. A classificação da conclusão",
              "responde apenas à pergunta específica do relatório.", ""]
    if registros:
        linhas += [tabela(
            ["Análise", "Execução", "Título", "Conclusão", "Relatório"],
            [[a, e, t, c, f"[Abrir]({link})"] for a, e, t, c, link in registros]
        ), ""]
    else:
        linhas += ["Nenhum relatório publicado ainda.", ""]
    (raiz / "README.md").write_text("\n".join(linhas), encoding="utf-8")
