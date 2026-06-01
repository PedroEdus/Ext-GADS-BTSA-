"""Gera o refresh_token OAuth para a Google Ads API.

Pré-requisito: client_secrets.json (OAuth desktop) na raiz do projeto.
Rode uma única vez. Cole o refresh_token gerado no google-ads.yaml.

    python etl/gerar_refresh_token.py
"""

from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_SECRETS = "client_secrets.json"
SCOPES = ["https://www.googleapis.com/auth/adwords"]


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, scopes=SCOPES)
    # Abre o navegador para login; usa servidor local para capturar o callback.
    creds = flow.run_local_server(port=0)
    print("\n=== COPIE O REFRESH TOKEN ABAIXO PARA google-ads.yaml ===\n")
    print(f"refresh_token: \"{creds.refresh_token}\"")
    print("\n=========================================================\n")


if __name__ == "__main__":
    main()
