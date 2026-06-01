"""Descobre todas as contas-folha sob a(s) MCC(s) acessível(is).

Varre a árvore de contas a partir da MCC informada (default: a MCC -
BRASIL TERRENOS, login_customer_id do google-ads.yaml) e salva a lista
de contas-folha (que veiculam anúncios e têm métricas) em contas.json.

    python etl/descobrir_contas.py
    python etl/descobrir_contas.py --manager 6494622292
"""

import argparse
import json

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

ARQUIVO_SAIDA = "contas.json"
API_VERSION = "v20"

QUERY = """
    SELECT
        customer_client.id,
        customer_client.descriptive_name,
        customer_client.manager,
        customer_client.level,
        customer_client.status,
        customer_client.currency_code,
        customer_client.time_zone
    FROM customer_client
    WHERE customer_client.status = 'ENABLED'
"""


def _client() -> GoogleAdsClient:
    return GoogleAdsClient.load_from_storage("google-ads.yaml", version=API_VERSION)


def descobrir(client: GoogleAdsClient, manager_id: str) -> list[dict]:
    ga_service = client.get_service("GoogleAdsService")
    stream = ga_service.search_stream(customer_id=manager_id, query=QUERY)

    contas = []
    for batch in stream:
        for row in batch.results:
            cc = row.customer_client
            contas.append({
                "id":            str(cc.id),
                "nome":          cc.descriptive_name,
                "is_manager":    cc.manager,
                "level":         cc.level,
                "status":        cc.status.name,
                "currency":      cc.currency_code,
                "timezone":      cc.time_zone,
            })
    return contas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manager", help="ID da MCC de topo (sem traços). Default: login_customer_id do yaml.")
    args = parser.parse_args()

    client = _client()
    manager_id = args.manager or str(client.login_customer_id)

    try:
        todas = descobrir(client, manager_id)
    except GoogleAdsException as ex:
        print(f"[ERRO] GoogleAdsException (request_id={ex.request_id}):")
        for err in ex.failure.errors:
            print(f"   - {err.error_code}: {err.message}")
        raise

    folhas = [c for c in todas if not c["is_manager"]]
    managers = [c for c in todas if c["is_manager"]]

    with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(folhas, f, ensure_ascii=False, indent=2)

    print(f"[OK] MCC de topo: {manager_id}")
    print(f"[OK] {len(managers)} manager(s) e {len(folhas)} conta(s)-folha encontradas.\n")
    print("Contas-folha (com métricas):")
    for c in folhas:
        print(f"   {c['id']} | {c['nome']} | {c['currency']} | {c['timezone']}")
    print(f"\n-> Salvo em {ARQUIVO_SAIDA}")


if __name__ == "__main__":
    main()
