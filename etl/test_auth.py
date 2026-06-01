"""[P0] Teste de autenticação na Google Ads API.

Valida que as credenciais (developer_token + OAuth refresh_token + customer_id)
conseguem autenticar e extrair dados. Lista as contas acessíveis e roda uma
query GAQL simples na conta cliente.

    python etl/test_auth.py
"""

import os

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

load_dotenv()

CUSTOMER_ID = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "").replace("-", "")


def _client() -> GoogleAdsClient:
    # Carrega de google-ads.yaml na raiz do projeto.
    return GoogleAdsClient.load_from_storage("google-ads.yaml", version="v18")


def listar_contas_acessiveis(client: GoogleAdsClient) -> None:
    customer_service = client.get_service("CustomerService")
    recursos = customer_service.list_accessible_customers().resource_names
    print(f"[OK] {len(recursos)} conta(s) acessível(is):")
    for rn in recursos:
        print(f"   - {rn}")


def testar_query(client: GoogleAdsClient, customer_id: str) -> None:
    ga_service = client.get_service("GoogleAdsService")
    query = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.status
        FROM campaign
        ORDER BY campaign.id
        LIMIT 10
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    print(f"\n[OK] Campanhas da conta {customer_id}:")
    n = 0
    for batch in stream:
        for row in batch.results:
            n += 1
            print(f"   {row.campaign.id} | {row.campaign.name} | {row.campaign.status.name}")
    if n == 0:
        print("   (nenhuma campanha encontrada — credencial OK, conta vazia)")


def main() -> None:
    try:
        client = _client()
        print("[OK] Cliente Google Ads carregado de google-ads.yaml\n")
        listar_contas_acessiveis(client)
        if CUSTOMER_ID:
            testar_query(client, CUSTOMER_ID)
        else:
            print("\n[AVISO] GOOGLE_ADS_CUSTOMER_ID não definido no .env — pulei a query de teste.")
        print("\n✅ Autenticação validada com sucesso.")
    except GoogleAdsException as ex:
        print(f"\n❌ GoogleAdsException (request_id={ex.request_id}):")
        for err in ex.failure.errors:
            print(f"   - {err.error_code}: {err.message}")
        raise
    except Exception as ex:
        print(f"\n❌ Erro: {ex}")
        raise


if __name__ == "__main__":
    main()
