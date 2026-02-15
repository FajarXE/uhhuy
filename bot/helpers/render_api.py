import aiohttp
from config import Config

RENDER_URL = "https://api.render.com/v1"

async def _request(method, endpoint, json=None):
    if not Config.RENDER_API_KEY:
        return None, "API Key belum diset di Config!"
    
    headers = {
        "Authorization": f"Bearer {Config.RENDER_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(method, f"{RENDER_URL}{endpoint}", headers=headers, json=json) as resp:
                if resp.status == 204:
                    return True, None
                
                try:
                    data = await resp.json()
                except:
                    data = await resp.text()
                
                if resp.status in [200, 201, 202]:
                    return data, None
                return None, f"Error {resp.status}: {data}"
        except Exception as e:
            return None, str(e)

# --- SERVICES ---
async def get_services(limit=50):
    return await _request("GET", f"/services?limit={limit}")

async def get_service(service_id):
    return await _request("GET", f"/services/{service_id}")

async def suspend_service(service_id):
    return await _request("POST", f"/services/{service_id}/suspend")

async def resume_service(service_id):
    return await _request("POST", f"/services/{service_id}/resume")

async def delete_service(service_id):
    return await _request("DELETE", f"/services/{service_id}")

# --- DEPLOYS ---
async def trigger_deploy(service_id):
    return await _request("POST", f"/services/{service_id}/deploys")

async def get_last_deploy(service_id):
    data, err = await _request("GET", f"/services/{service_id}/deploys?limit=1")
    if err: return None, err
    if not data: return None, "Belum ada history deploy."
    return data[0]['deploy'], None

async def cancel_deploy(service_id, deploy_id):
    return await _request("POST", f"/services/{service_id}/deploys/{deploy_id}/cancel")

# --- ENV VARS (BAGIAN YANG DIPERBAIKI) ---

async def get_env_vars(service_id):
    return await _request("GET", f"/services/{service_id}/env-vars")

async def update_env_var(service_id, key, value):
    # PERBAIKAN: Menggunakan endpoint spesifik per-Key agar tidak menghapus yang lain
    # Endpoint: PUT /services/{serviceId}/env-vars/{envVarKey}
    payload = {"value": value}
    return await _request("PUT", f"/services/{service_id}/env-vars/{key}", json=payload)

async def delete_env_var(service_id, key):
    # Endpoint: DELETE /services/{serviceId}/env-vars/{envVarKey}
    return await _request("DELETE", f"/services/{service_id}/env-vars/{key}")

async def update_full_env(service_id, env_list):
    # Hati-hati: Fungsi ini memang bertujuan me-replace SEMUA variabel (Bulk Update)
    return await _request("PUT", f"/services/{service_id}/env-vars", json=env_list)
