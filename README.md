# Eleições Lab

**Plataforma independente de coleta, preservação e análise de dados eleitorais brasileiros.**

## Sobre o projeto

O Eleições Lab é um projeto open-source desenvolvido em Python para coletar, organizar, validar e analisar dados oficiais das eleições presidenciais brasileiras de **2018, 2022 e 2026**, abrangendo o primeiro e o segundo turnos.

O projeto utiliza dados publicados pelo Tribunal Superior Eleitoral (TSE) e busca oferecer uma infraestrutura transparente, reproduzível e independente para investigações estatísticas e técnicas.

A proposta é permitir que qualquer pesquisador possa obter os dados diretamente das fontes oficiais, armazená-los localmente e executar suas próprias consultas, análises e verificações.

**O projeto não possui vinculação partidária ou compromisso com conclusões previamente estabelecidas.**

## Objetivos

- Coletar dados eleitorais diretamente das plataformas oficiais do TSE.
- Preservar os arquivos originais com identificação de origem e hashes criptográficos.
- Armazenar os dados estruturados em uma base SQLite para consultas offline.
- Analisar resultados presidenciais com granularidade de município, zona e seção eleitoral.
- Integrar boletins de urna, correspondências, logs e registros operacionais disponibilizados pelo TSE.
- Verificar a consistência matemática e estrutural dos dados.
- Comparar informações entre os três ciclos eleitorais.
- Documentar procedimentos, resultados, limitações e evidências para permitir reprodução independente.

## Escopo

| Eleição | Primeiro turno | Segundo turno |
|---|---|---|
| 2018 | Incluído | Incluído |
| 2022 | Incluído | Incluído |
| 2026 | Incluído | Incluído |

**Cargo analisado:** Presidente da República.

Os arquivos originais podem conter informações compartilhadas com outros cargos, especialmente registros técnicos das urnas. Nesses casos, os arquivos serão preservados integralmente e a seleção por cargo será aplicada durante o processamento.

## Fontes de dados

Fonte primária:

[Portal de Dados Abertos do TSE](https://dadosabertos.tse.jus.br/)

O projeto contempla diferentes categorias de informação, sujeitas à disponibilidade e à verificação de cobertura por eleição:

- Resultados eleitorais e votação por seção.
- Boletins de urna (BU).
- Arquivos transmitidos para totalização.
- Logs de funcionamento das urnas.
- Registros Digitais do Voto (RDV), quando publicados.
- Correspondências entre urnas e seções.
- Logs de preparação das urnas (GEDAI).
- Comparecimento, abstenções e dados complementares.

A existência de uma categoria no escopo não significa que todos os respectivos arquivos já tenham sido localizados ou importados.

## Arquitetura

O sistema possui quatro componentes principais:

**1. Descoberta e catalogação**

Consulta aos recursos disponibilizados pelo TSE, identificando datasets, arquivos, formatos, URLs e metadados.

**2. Download e preservação**

Download dos arquivos originais, com armazenamento local, manifesto de execução e cálculo de hashes SHA-256.

**3. Importação e armazenamento**

Leitura dos arquivos disponibilizados pelo TSE e transformação dos registros relevantes em estruturas consultáveis no SQLite.

**4. Auditoria e análise**

Verificações de integridade, consistência, cobertura, totalização e análises estatísticas, com rastreabilidade até os documentos de origem.

Os arquivos brutos permanecem separados da base de dados estruturada.

## Requisitos

- Python 3.11 ou superior.
- SQLite 3.
- Acesso à internet para obtenção dos dados.
- Espaço de armazenamento suficiente para os conjuntos selecionados.

A operação foi inicialmente desenvolvida para macOS, utilizando componentes Python multiplataforma.

## Instalação

Clone o repositório:

```bash
git clone https://github.com/SEU-USUARIO/eleicoes-lab.git
cd eleicoes-lab
```

Crie um ambiente virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Instale as dependências:

```bash
python -m pip install -r requirements.txt
```

## Utilização

### 1. Catalogar as fontes oficiais

```bash
python catalogo_tse.py
```

O script consulta o catálogo de dados abertos do TSE e registra os recursos identificados no banco `eleicoes.sqlite`.

### 2. Inspecionar o inventário

```bash
python inspecionar_catalogo.py
python auditar_catalogo.py
```

Os scripts produzem relatórios de inventário e classificação dos datasets.

### 3. Visualizar os arquivos disponíveis para download

```bash
python baixar_tse.py --ano 2026
```

### 4. Baixar os boletins de urna

```bash
python baixar_tse.py --ano 2018 --categoria boletins --executar
python baixar_tse.py --ano 2022 --categoria boletins --executar
python baixar_tse.py --ano 2026 --categoria boletins --executar
```

### 5. Importar os boletins para o SQLite

```bash
python importar_boletins.py --ano 2018
```

As rotinas estão em desenvolvimento. A importação deve ser acompanhada das verificações de integridade, cobertura e consistência descritas na metodologia.

## Armazenamento

Os arquivos produzidos localmente, incluindo banco SQLite, dados brutos, manifestos, relatórios e logs, não são versionados neste repositório.

A integridade e a procedência desses arquivos devem ser verificadas separadamente. O código publicado busca permitir sua reconstrução diretamente das fontes oficiais.

## Estado do desenvolvimento

**Projeto experimental — implementação e validação em andamento.**

Componentes implementados inicialmente:

- Descoberta de recursos do catálogo do TSE.
- Inventário e classificação de datasets.
- Download com tentativa de retomada e registro de hashes.
- Manifesto de arquivos baixados.
- Importação preliminar de boletins de urna presidenciais para SQLite.

Ainda não estão concluídos ou validados integralmente:

- Cobertura comprovada de todos os recursos exigidos por eleição.
- Verificação automatizada contra hashes oficiais.
- Importação de todos os formatos de arquivos de urna.
- Reconciliação independente dos totais por seção.
- Processamento completo dos logs operacionais.
- Testes automatizados abrangentes.
- Relatórios estatísticos e auditorias reproduzíveis de ponta a ponta.

O funcionamento parcial de uma rotina não deve ser interpretado como validação integral dos dados eleitorais.

## Metodologia científica

Os critérios de seleção, coleta, preservação, transformação, verificação e análise estão documentados em [METODOLOGIA.md](METODOLOGIA.md).

Esse documento será atualizado continuamente, com registro explícito de hipóteses, procedimentos, limitações e decisões metodológicas.

## Princípios

1. Neutralidade política e independência analítica.
2. Rastreabilidade das fontes e transformações.
3. Reprodutibilidade das análises.
4. Preservação dos dados originais.
5. Separação entre observações, hipóteses e conclusões.
6. Transparência sobre falhas, ausência de dados e limitações.
7. Nenhuma inferência de irregularidade baseada exclusivamente em anomalias estatísticas.

## Licença

A licença de código será definida antes da publicação oficial.

Os dados eleitorais permanecem sujeitos aos termos de uso e às condições estabelecidas pelos respectivos órgãos de origem.

## Aviso

Este é um projeto independente de pesquisa e desenvolvimento. Não é uma auditoria oficial do TSE e não representa qualquer órgão da Justiça Eleitoral.

Os resultados das análises deverão ser interpretados segundo os procedimentos, as evidências e as limitações metodológicas documentadas.

<!-- BEGIN:ESTADO_ATUAL_ELEICOES_LAB -->
## Estado atual do projeto — outubro de 2026

O Eleições Lab mantém uma **camada de dados local** (SQLite e arquivos oficiais preservados) e uma **camada independente de auditoria** (protocolos, execução, evidências e relatórios). A descrição abaixo distingue funcionalidades implementadas de verificações que ainda dependem de execução e validação nos dados reais.

| Componente | Estado e ressalvas |
|---|---|
| Descoberta e inventário do catálogo do TSE | Implementado; a completude depende de sincronizações e de conferência com os datasets oficiais. |
| Download com retomada, SHA-256 local e manifesto | Implementado; o hash local, isoladamente, não autentica o conteúdo perante o TSE. |
| Importação dos CSVs de boletins presidenciais | Implementada para os formatos já testados; a cobertura de cada seção e a interpretação dos casos excepcionais exigem validação específica. |
| Cobertura por eleição, turno e UF/exterior | Ferramenta implementada; **cobertura de arquivos** não implica cobertura de seções. |
| Snapshots SQLite | Implementados via API de backup, com `integrity_check`; podem capturar uma importação ainda incompleta. |
| Motor de análises | Protocolos YAML, executor, evidências, relatórios e publicação local sob revisão; nenhuma análise eleitoral deve ser descrita como concluída sem execução específica. |
| Sincronização segura do catálogo | Pacote de atualização disponível; deve ser testado localmente antes de ser considerado operacional no clone. |
| Comparação com hashes SHA-512 do TSE | Implementação e testes sintéticos disponibilizados; **pendente de instalação e verificação integral dos arquivos reais**. |
| Logs e formatos binários de urna | Ingestão e reconciliação completas ainda não comprovadas. |

### Comandos operacionais

Executar a partir da **raiz do repositório**, com o ambiente virtual ativado. O projeto utiliza a própria pasta como raiz dos artefatos locais.

```bash
# Coleta e importação (os argumentos disponíveis dependem da versão instalada)
python catalogo_tse.py
python baixar_tse.py --ano 2026 --categoria boletins
python baixar_tse.py --ano 2026 --categoria boletins --executar
python importar_boletins.py --ano 2026

# Infraestrutura de auditoria
python -m eleicoes_lab status
python -m eleicoes_lab listar
python -m eleicoes_lab snapshot
python -m eleicoes_lab cobertura --snapshot "$(ls -t snapshots/*.sqlite | head -1)"

# Após instalar o módulo específico de integridade:
python verificar_hashes_tse.py --ano 2026 --turno 2 --uf RR
python verificar_hashes_tse.py --registrar --estrito

# Testes automatizados
python -m unittest discover -s tests -v
```

Os comandos de sincronização do catálogo e de verificação SHA-512 devem ser executados somente após a instalação das respectivas atualizações. Não trate saída de teste sintético como verificação dos arquivos eleitorais reais.

### Política de relatórios públicos

- **Versionado no Git:** protocolos, scripts, testes, `METODOLOGIA.md` e relatórios revisados em `relatorios/`, com manifestos de reprodutibilidade.
- **Não versionado no Git:** arquivos em `raw/`, SQLite principal e snapshots, manifestos operacionais e resultados intermediários em `resultados_analises/`.
- Toda publicação deve identificar **pergunta, universo analisado, versão do protocolo, commit Git, hash do snapshot, critérios de decisão, resultados, limitações e responsável pela revisão**.
- A publicação em `relatorios/` é separada da execução. Um relatório provisório não deve ser promovido automaticamente a uma conclusão publicada.
- A conclusão de cada investigação responde **apenas à pergunta do protocolo**: `sim`, `não` ou `não foi possível concluir`. Resultados de consistência, isoladamente, não demonstram fraude nem sua ausência.

### Marcos ainda necessários para validação científica

1. Completar e confirmar o inventário dos seis turnos e dos recursos oficiais pertinentes.
2. Validar hashes oficiais, quando disponíveis, distinguindo integridade de autenticação da origem.
3. Confrontar seções importadas com seções oficialmente esperadas, considerando agregações e substituições de urnas.
4. Conciliar totalizações e boletins e documentar divergências sem descartar linhas silenciosamente.
5. Integrar arquivos operacionais e definir a semântica de cada timestamp antes de análises temporais.

Consulte [METODOLOGIA.md](METODOLOGIA.md) para os critérios de decisão, níveis de evidência e limitações.
<!-- END:ESTADO_ATUAL_ELEICOES_LAB -->
