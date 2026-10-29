# A001 — Consistência aritmética dos boletins presidenciais

**Estado:** protocolo inicial, ainda não aprovado ou executado.

Esta investigação busca verificar a reconciliação aritmética dos boletins
presidenciais de 2018, 2022 e 2026, nos dois turnos, sem pressupor uma
conclusão positiva ou negativa.

## Fases previstas

1. **Reconhecimento dos leiautes:** inventariar códigos e categorias por pleito,
   tipos de urna, eventos especiais e seções agregadas.
2. **Verificação de importação:** confrontar contagens por arquivo da origem ZIP
   com a tabela `votos_bu`, impedindo truncamentos e duplicações silenciosas.
3. **Determinação das identidades:** definir e justificar as regras aplicáveis
   ao comparecimento, aptos, abstenções e categorias presidenciais.
4. **Cobertura por seção:** confrontar a base com fontes oficiais independentes.
5. **Execução confirmatória:** executar num snapshot identificado e registrar
   cada divergência com origem, chave de boletim, linhas e dados de suporte.
6. **Revisão e publicação:** conclusão ternária, limitações, relatório técnico
   versionado e manifesto de reprodução.

## Critérios para prosseguir

O protocolo em `pergunta.yaml` deve ser revisado, sobretudo quanto às
categorias especiais, à identificação de boletins únicos e à cobertura por
seção. Não alterar `status: rascunho` para `aprovado` sem essa revisão.

## Fontes institucionais iniciais

- Portal de Dados Abertos do TSE: https://dadosabertos.tse.jus.br/
- Resolução nº 23.669/2021, seção dos boletins de urna:
  https://sintse.tse.jus.br/documentos/2022/Mar/3/diario-da-justica-eletronico-tse/resolucao-no-23-669-de-14-de-dezembro-de-2021-dispoe-sobre-os-atos-gerais-do-processo-eleitoral-para-

**Nota:** a integridade dos ZIPs em relação aos arquivos de checksum não
atesta, isoladamente, a completude das seções ou a validade semântica das
linhas importadas.
