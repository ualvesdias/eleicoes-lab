# Metodologia de Pesquisa e Auditoria Eleitoral

**Projeto:** Eleições Lab  
**Versão:** 0.1 — Estrutura inicial  
**Última atualização:** 28 de outubro de 2026  
**Situação:** Em elaboração conjunta

## 1. Objetivo

Estabelecer um procedimento técnico, transparente e reproduzível para coletar, preservar, processar e analisar dados oficiais das eleições presidenciais brasileiras de 2018, 2022 e 2026.

A metodologia deverá permitir que terceiros reproduzam as etapas de processamento e verifiquem os resultados das análises utilizando as mesmas fontes e critérios.

## 2. Princípios metodológicos

### 2.1 Neutralidade

As análises não deverão pressupor a existência ou a inexistência de irregularidades.

As hipóteses serão formuladas de maneira verificável e avaliadas conforme as evidências disponíveis.

### 2.2 Reprodutibilidade

Cada análise deverá documentar:

- Fontes e versões dos dados utilizados.
- Critérios de inclusão e exclusão.
- Procedimentos de tratamento e transformação.
- Código e parâmetros empregados.
- Resultados obtidos.
- Limitações e eventuais divergências.

### 2.3 Integridade e rastreabilidade

Os arquivos originais serão preservados sem alterações intencionais.

Cada recurso coletado deverá manter informações de procedência, localização, data de obtenção e hash criptográfico.

Quando o TSE disponibilizar referências de integridade, os hashes locais deverão ser comparados aos valores oficiais.

### 2.4 Distinção entre evidência e interpretação

Toda investigação deverá distinguir explicitamente:

- **Dados observados:** registros extraídos das fontes.
- **Resultados derivados:** valores calculados pelo projeto.
- **Hipóteses:** afirmações propostas para verificação.
- **Conclusões:** interpretações sustentadas pelas evidências.

## 3. Universo da pesquisa

### 3.1 Eleições

- Eleição presidencial de 2018, primeiro e segundo turnos.
- Eleição presidencial de 2022, primeiro e segundo turnos.
- Eleição presidencial de 2026, primeiro e segundo turnos.

### 3.2 Unidade de análise

As unidades de análise poderão incluir:

- Eleição e turno.
- Unidade da Federação e exterior.
- Município.
- Zona eleitoral.
- Seção eleitoral.
- Urna eletrônica.
- Registro de votação agregada.
- Evento registrado em log.
- Arquivo transmitido ou divulgado.

A correspondência entre essas unidades deverá ser estabelecida por identificadores oficiais sempre que possível.

### 3.3 Critérios de inclusão

Serão incluídos os registros pertinentes ao cargo de Presidente da República, bem como documentos técnicos necessários à interpretação e à verificação desses registros.

Os logs operacionais compartilhados entre cargos poderão ser preservados integralmente.

### 3.4 Critérios de exclusão

Dados exclusivamente relacionados a outros cargos serão excluídos da camada analítica presidencial, salvo quando necessários à validação, à identificação de urnas, ao contexto operacional ou à interpretação dos registros.

Nenhum arquivo de origem será modificado para realizar essa exclusão.

## 4. Fontes de dados

A fonte primária será o Portal de Dados Abertos do Tribunal Superior Eleitoral:

https://dadosabertos.tse.jus.br/

As fontes serão catalogadas por eleição, turno, tipo de recurso e unidade geográfica.

A disponibilidade dos conjuntos deverá ser documentada independentemente de sua presença no inventário automatizado.

## 5. Procedimentos de coleta

**Estado: implementação inicial.**

A coleta será realizada por scripts Python, utilizando metadados e URLs oficiais dos recursos.

Os procedimentos deverão contemplar:

1. Descoberta dos datasets.
2. Identificação e classificação dos recursos.
3. Seleção conforme o escopo.
4. Download e preservação dos arquivos originais.
5. Registro dos hashes e metadados.
6. Validação de integridade.
7. Verificação da cobertura da coleta.

Downloads incompletos, indisponíveis ou inválidos deverão ser registrados explicitamente.

## 6. Preparação e armazenamento

**Estado: implementação inicial.**

Os arquivos brutos serão mantidos separadamente dos registros estruturados.

O SQLite será utilizado para consultas locais, com referência aos recursos e às linhas de origem.

Os procedimentos de normalização deverão preservar identificadores oficiais, categorias de voto, datas, horários e demais informações relevantes.

Transformações destrutivas, deduplicações e agregações deverão ter justificativa documentada.

## 7. Validação dos dados

**Estado: planejado.**

As verificações deverão incluir:

- Integridade dos arquivos.
- Cobertura de eleições, turnos, localidades e seções.
- Consistência entre comparecimento, abstenções e eleitores aptos.
- Reconciliação entre categorias de votação e totais.
- Comparação de totais calculados e divulgados.
- Correspondência entre boletins, urnas e registros operacionais.
- Identificação de duplicidades e divergências.
- Tratamento de seções agregadas, contingências e casos excepcionais.

Qualquer divergência deverá ser investigada considerando os significados oficiais dos campos e as particularidades de cada eleição.

## 8. Investigação de eventos temporais

**Estado: planejado.**

O projeto poderá examinar horários de abertura e encerramento, eventos operacionais, transmissão de arquivos e etapas de totalização.

Os diferentes tipos de timestamp deverão ser tratados separadamente.

O encerramento da votação em uma seção não equivale necessariamente ao horário de transmissão ou de contabilização de seu boletim.

A metodologia não presumirá que os horários de votos individuais possam ser reconstruídos a partir de registros agregados.

## 9. Análise estatística

**Estado: a desenvolver.**

Cada análise estatística deverá possuir:

- Pergunta de pesquisa.
- Hipótese nula e hipótese alternativa, quando aplicáveis.
- Unidade amostral e população.
- Variáveis e critérios de seleção.
- Método estatístico.
- Pressupostos e possíveis fatores de confusão.
- Resultados e medidas de incerteza.
- Interpretação e limitações.

Anomalias estatísticas não serão tratadas, isoladamente, como evidência conclusiva de fraude ou irregularidade.

## 10. Limitações conhecidas

A disponibilidade e a estrutura dos arquivos variam entre os ciclos eleitorais.

No catálogo inicial, ainda não foram identificados conjuntos equivalentes de arquivos transmitidos e logs GEDAI para todos os anos.

A ausência de um recurso no catálogo local não comprova sua inexistência na infraestrutura oficial.

Os arquivos transmitidos classificados como totalizados também podem não representar todos os eventos operacionais de uma urna.

## 11. Registro de revisões

| Versão | Data | Alteração |
|---|---|---|
| 0.1 | 28/10/2026 | Criação da estrutura metodológica inicial |

## 12. Questões metodológicas pendentes

- Definir um protocolo formal de comprovação da completude da coleta.
- Estabelecer a chave de identificação de urnas e seções entre diferentes conjuntos.
- Definir o tratamento de seções agregadas e substituições de urnas.
- Validar as diferenças de layout entre 2018, 2022 e 2026.
- Definir os procedimentos de comparação com resultados oficiais.
- Estabelecer regras para timestamps e diferenças entre eventos.
- Definir os critérios de publicação de análises e evidências.

**Este documento será desenvolvido progressivamente. Nenhuma etapa será descrita como validada antes de sua execução e verificação.**
