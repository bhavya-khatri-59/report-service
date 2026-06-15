import os
import requests
import msal
from dotenv import load_dotenv

load_dotenv()

def test_live_dax():
    print("1. Requesting Access Token from Azure Entra ID...")
    authority = f"https://login.microsoftonline.com/{os.environ.get('AZURE_DIR_ID')}"
    app = msal.ConfidentialClientApplication(
        os.environ.get("AZURE_APP_ID"),
        authority=authority,
        client_credential=os.environ.get("POWER_BI_CLIENT_SECRET")
    )
    
    scopes = ["https://analysis.windows.net/powerbi/api/.default"]
    result = app.acquire_token_for_client(scopes=scopes)
    
    if "access_token" not in result:
        print(f"❌ Auth Failed: {result.get('error_description')}")
        return

    token = result["access_token"]
    print("✅ Token acquired successfully!\n")

    print("2. Firing DAX Query at live Power BI Semantic Model...")
    dataset_id = os.environ.get("POWER_BI_DATASET_ID")
    workspace_id = os.environ.get("POWER_BI_WORKSPACE_ID")
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{dataset_id}/executeQueries"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # We use a simple query from your Slide 1 template to verify the data pipe
    payload = {
        "queries": [{"query": "EVALUATE ROW(\"Total_AUM\", [AUM])"}],
        "serializerSettings": {"includeNulls": True}
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 200:
        print("✅ SUCCESS! Live data retrieved:")
        rows = response.json().get('results', [{}])[0].get('tables', [{}])[0].get('rows', [])
        print(rows)
    else:
        print(f"❌ API Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    test_live_dax()