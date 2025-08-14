import json
import urllib.request
import urllib.error
import ssl

# ===== personal credentials =====
vcenter = "<vcenter-server>"  # hostname or IP only, no https://
username = "administrator@vsphere.local"
password = "Password"

# ===== SSL context (disable verification ONLY for testing) =====
ctx = ssl._create_unverified_context()

# ===== Helper function =====
def http_request(method, url, headers=None, data=None):
    if data is not None and not isinstance(data, bytes):
        data = data.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            body = resp.read()
            if resp.getheader("Content-Type", "").startswith("application/json"):
                return resp.status, json.loads(body)
            return resp.status, body.decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

# ===== 1. Login to vCenter =====
login_url = f"https://{vcenter}/rest/com/vmware/cis/session"
login_headers = {
    "Authorization": f"Basic {username}:{password}"
}

import base64
auth_string = f"{username}:{password}"
auth_b64 = base64.b64encode(auth_string.encode()).decode()
login_headers["Authorization"] = f"Basic {auth_b64}"

status, login_data = http_request("POST", login_url, headers=login_headers)
if status != 200:
    print(f"Login failed: {status} {login_data}")
    exit()

print(f"Login Response: {status}")
session_id = login_data.get("value")

# ===== 2. Get list of VMs =====
headers = {"vmware-api-session-id": session_id}
vms_url = f"https://{vcenter}/rest/vcenter/vm"
status, vms_data = http_request("GET", vms_url, headers=headers)

if status != 200:
    print(f"Failed to fetch VMs: {status} {vms_data}")
    exit()

print(f"VMs Response: {status}")

# ===== 3. Loop through VMs and fetch NIC MACs =====
for vm in vms_data.get("value", []):
    vm_id = vm.get("vm")
    vm_name = vm.get("name")
    print(f"\n=== VM: {vm_name} ({vm_id}) ===")

    nics_url = f"https://{vcenter}/rest/vcenter/vm/{vm_id}/hardware/ethernet"
    status, nics_data = http_request("GET", nics_url, headers=headers)

    for nic in nics_data.get("value", []):
        nic_id = nic.get("nic")
        nic_detail_url = f"https://{vcenter}/rest/vcenter/vm/{vm_id}/hardware/ethernet/{nic_id}"
        status, nic_detail_data = http_request("GET", nic_detail_url, headers=headers)
        mac = nic_detail_data.get("value", {}).get("mac_address", "Unknown")
        print(f"NIC {nic_id}: MAC Address = {mac}")
