# Automacao de Mapas no Railway

## Objetivo
Gerar mapas diarios automaticamente em 2 horarios (fuso Brasil) e manter disparo manual pelo Streamlit.

## Arquivos novos desta etapa
- `Procfile` (start do Streamlit no Railway)
- `scripts/run_daily_maps_job.py`
- `automation/timezone_utils.py`
- `automation/daily_maps.py`
- `automation/drive_uploader.py`
- `pages/6_Automacao_Mapas.py`

## Variaveis de ambiente
- `FEEGOW_ACCESS_TOKEN` (obrigatoria)
- `MAP_AUTOMATION_UNITS` (recomendado)  
  Exemplo: `CENTRO CAMBUI,OURO VERDE,SHOPPING CAMPINAS`
- `MAP_AUTOMATION_TIMEZONE` (opcional, padrao `America/Sao_Paulo`)
- `MAP_AUTOMATION_OUTPUT_DIR` (opcional, padrao `mapas_gerados/automacao`)
- `MAP_AUTOMATION_SAVE_LOCAL` (opcional, `true`/`false`, padrao `true`)
- `MAP_AUTOMATION_UPLOAD_DRIVE` (opcional, `true`/`false`, padrao `true`)
- `MAP_AUTOMATION_FAIL_ON_WARNING` (opcional, padrao `false`)

### Google Drive
- Autenticacao via OAuth2 com arquivos na raiz do projeto:
  - `credentials.json`
  - `token.json`
- Opcional para caminhos customizados:
  - `GOOGLE_OAUTH_CREDENTIALS_FILE`
  - `GOOGLE_OAUTH_TOKEN_FILE`
- Pastas raiz por tipo (padrao ja configurado em codigo):
  - Diario: `1YZ3WYpIsQtw_0vO0A6ugVTB7AZblFfbu`
  - Semanal: `1rHo2aJV-EsNrn3G-8uQUP6pAs6Sgoyu3`
  - Mensal: `1esY0pBwk9kvMujQCmguEh3kGBXih_RFg`
- Opcional para sobrescrever via env:
  - `GOOGLE_DRIVE_ROOT_DIARIO`
  - `GOOGLE_DRIVE_ROOT_SEMANAL`
  - `GOOGLE_DRIVE_ROOT_MENSAL`

### Estrutura de pastas no Drive
- Diario: `RAIZ_DIARIO/ANO/MES/DIA/ARQUIVO.pdf`
- Semanal (quando automatizar): `RAIZ_SEMANAL/ANO/MES/DIA/ARQUIVOS.pdf`
- Mensal (quando automatizar): `RAIZ_MENSAL/ANO/MES/ARQUIVOS.pdf`
- Nome de arquivo: `MAPA_<TIPO>_<UNIDADE>_<DD-MM-AAAA>.pdf`

As pastas sao criadas automaticamente quando nao existem.

## Comandos de cron (Railway)

O cron do Railway roda em UTC.

- 07:00 Brasil (UTC-3) => `10:00 UTC`  
  Cron: `0 10 * * *`
  Comando:
  `python scripts/run_daily_maps_job.py --when today --upload-drive true --save-local true`

- 17:00 Brasil (UTC-3) => `20:00 UTC`  
  Cron: `0 20 * * *`
  Comando:
  `python scripts/run_daily_maps_job.py --when tomorrow --upload-drive true --save-local true`

## Execucao manual
No Streamlit, use a pagina:
- `pages/6_Automacao_Mapas.py` (menu "Automacao de Mapas Diarios")

Nessa pagina e possivel:
- escolher data alvo (hoje, amanha ou data especifica)
- selecionar unidades
- salvar localmente
- enviar para Google Drive
