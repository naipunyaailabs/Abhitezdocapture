import requests
import sys

def test_reconciliation(token):
    url = "http://localhost:5000/reconcile"
    headers = {"Authorization": f"Bearer {token}"}
    
    files = {
        "bank_statement": ("bank_statement_demo.txt", open("tests/demo_data/bank_statement_demo.txt", "rb"), "text/plain"),
        "ledger_file": ("internal_ledger_demo.txt", open("tests/demo_data/internal_ledger_demo.txt", "rb"), "text/plain")
    }
    
    print(f"Sending request to {url}...")
    try:
        response = requests.post(url, headers=headers, files=files)
        response.raise_for_status()
        result = response.json()
        
        if result.get("success"):
            data = result["data"]["result"]
            print("\nReconciliation Successful!")
            print(f"Matched Items: {data['summary']['matched_count']}")
            print(f"Discrepancies: {data['summary']['discrepancy_count']}")
            
            print("\nMatches found:")
            for m in data['matches']:
                bank = m['bank_transaction']
                ledger = m['ledger_entry']
                print(f" - ${bank['amount']} ({bank['date']}) Matched with Ledger Entry: {ledger['description']} (Score: {m['match_score']})")
        else:
            print("Error:", result.get("detail", "Unknown error"))
    except Exception as e:
        print("Failed to run test:", str(e))
    finally:
        for f in files.values():
            f[1].close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tests/test_reconciliation.py <YOUR_AUTH_TOKEN>")
    else:
        test_reconciliation(sys.argv[1])
