# Ext Google Ads — Buriti

Pipeline de extração do Google Ads → BigQuery + dashboard Streamlit.

## Stack
Python + Google Ads API (lib `google-ads`, GAQL) + BigQuery (`buriti-marketing-analytics`) + Streamlit + GitHub Actions.

## Fluxo
```
Google Ads API → etl/load_google_ads.py → BigQuery (RAW) → data.py (dedup) → app.py (Streamlit)
                          ↑
                  GitHub Actions (cron diário, D-1)
```

## Setup local

1. `pip install -r requirements.txt`
2. Gere o refresh token OAuth (uma vez):
   ```
   python etl/gerar_refresh_token.py
   ```
3. Copie `google-ads.yaml.example` → `google-ads.yaml` e preencha:
   - `developer_token` (Google Ads API Center)
   - `client_secret` (do `client_secrets.json`)
   - `refresh_token` (passo 2)
   - `login_customer_id` (MCC, sem traços)
4. Preencha o `.env` (customer_id da conta a extrair + caminho da SA do BigQuery).
5. **Teste a autenticação (P0):**
   ```
   python etl/test_auth.py
   ```

## Cargas

```bash
# Histórica (2025 → hoje):
python etl/load_google_ads.py --inicio 2025-01-01 --fim 2026-06-01

# Incremental D-1 (o que o Action roda):
python etl/load_google_ads.py
```

## Dashboard
```bash
streamlit run app.py
```

## NUNCA commitar
- `google-ads.yaml`, `client_secrets.json`, `.env`, `keys/`, `token.pkl`

## Secrets do GitHub Actions
- `GCP_SA_KEY` = `base64 -w0 keys/sa.json`
- `GOOGLE_ADS_YAML` = `base64 -w0 google-ads.yaml`
- `GOOGLE_ADS_CUSTOMER_ID` = ID da conta cliente (sem traços)
