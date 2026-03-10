import requests
import json

base_url = "http://localhost:8000/api/translate"

# Get a token for user "testuser"
headers = {"Authorization": "Bearer testuser"}

def test_quick():
    url = f"{base_url}/quick"
    payload = {
        "word": "obfuscate",
        "context": "The writer tried to obfuscate the real meaning of the poem by using obscure words."
    }
    print("Testing /quick...")
    response = requests.post(url, json=payload, headers=headers)
    print("Status code:", response.status_code)
    try:
        print("Response:", json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print("Raw response:", response.text)

def test_explain():
    url = f"{base_url}/explain"
    payload = {
        "word": "obfuscate",
        "context": "The writer tried to obfuscate the real meaning of the poem by using obscure words."
    }
    print("\nTesting /explain...")
    response = requests.post(url, json=payload, headers=headers)
    print("Status code:", response.status_code)
    try:
        print("Response:", json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print("Raw response:", response.text)

if __name__ == "__main__":
    test_quick()
    test_explain()
