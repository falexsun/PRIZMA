import time, httpx
login = httpx.post("http://localhost:8000/auth/login", json={"login": "admin", "password": "-Zsdb7fa9nPIKtOP"})
token = login.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

start = time.time()
resp = httpx.get("http://localhost:8000/messages/29", headers=h, timeout=120)
elapsed = time.time() - start
d = resp.json()
print(f"Status: {resp.status_code}")
print(f"Time: {elapsed:.1f}s")
print(f"Links: {len(d.get('links', []))}")
print(f"links_with_metrics: {d.get('links_with_metrics')}")
print(f"links_pending: {d.get('links_pending')}")
