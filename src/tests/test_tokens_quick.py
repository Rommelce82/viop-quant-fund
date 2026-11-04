import json
import urllib.request
import urllib.error

def check_token(name, token):
    url = "https://evo.fintables.com/mcp"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req) as resp:
            print(f"[{name}] SUCCESS: {resp.status}")
            data = json.loads(resp.read().decode('utf-8'))
            tools = [t["name"] for t in data.get("result", {}).get("tools", [])]
            print(f"[{name}] Available tools: {tools}")
            return True, data
    except urllib.error.HTTPError as e:
        print(f"[{name}] HTTP Error: {e.code} -> {e.read().decode('utf-8', errors='ignore')}")
    except Exception as e:
        print(f"[{name}] Error: {e}")
    return False, None


if __name__ == "__main__":
    # Test 1: Fon token
    try:
        with open(r"C:\Users\alper\Desktop\Fon\fintables_token.json", "r", encoding="utf-8") as f:
            fon_token = json.load(f)["access_token"]
        check_token("Fon Token", fon_token)
    except Exception as e:
        print(f"Fon token error: {e}")

    # Test 2: Table token
    try:
        with open(r"C:\Users\alper\Desktop\table\mcp_token.json", "r", encoding="utf-8") as f:
            table_token = json.load(f)["access_token"]
        check_token("Table Token", table_token)
    except Exception as e:
        print(f"Table token error: {e}")

