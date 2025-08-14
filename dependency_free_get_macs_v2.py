import ssl
import json
import urllib.request
import base64
from html import escape
import webbrowser
import os
import getpass  

# ===== CONFIG =====
vcenter = getpass.getpass("Enter vCenter hostname or IP: ")
username = getpass.getpass("Enter username: ")
password = getpass.getpass("Enter password: ")  

# Where the HTML report will be saved
REPORT_FILE = os.path.abspath("vm_mac_report.html")

# ===== SSL context (disable verification for lab use) =====
ctx = ssl._create_unverified_context()

def http_request(method, url, headers=None, data=None):
    if data is not None and not isinstance(data, bytes):
        data = data.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, context=ctx) as resp:
        body = resp.read()
        if resp.getheader("Content-Type", "").startswith("application/json"):
            return resp.status, json.loads(body)
        return resp.status, body.decode()

# ===== 1. Login to vCenter =====
login_url = f"https://{vcenter}/rest/com/vmware/cis/session"
auth_b64 = base64.b64encode(f"{username}:{password}".encode()).decode()
login_headers = {"Authorization": f"Basic {auth_b64}"}

status, login_data = http_request("POST", login_url, headers=login_headers)
if status != 200:
    print(f"Login failed: {status} {login_data}")
    exit()
session_id = login_data.get("value")

# ===== 2. Get VM list =====
headers = {"vmware-api-session-id": session_id}
status, vms_data = http_request("GET", f"https://{vcenter}/rest/vcenter/vm", headers=headers)
if status != 200:
    print(f"Failed to fetch VMs: {status} {vms_data}")
    exit()

# ===== 3. Collect VM details =====
vm_rows_html = ""
for vm in vms_data.get("value", []):
    vm_id = vm.get("vm")
    vm_name = vm.get("name")
    status, nics_data = http_request("GET", f"https://{vcenter}/rest/vcenter/vm/{vm_id}/hardware/ethernet", headers=headers)

    macs_html = ""
    for nic in nics_data.get("value", []):
        nic_id = nic.get("nic")
        status, nic_detail_data = http_request("GET", f"https://{vcenter}/rest/vcenter/vm/{vm_id}/hardware/ethernet/{nic_id}", headers=headers)
        mac = nic_detail_data.get("value", {}).get("mac_address", "Unknown")
        macs_html += f'<span class="mac-badge">{escape(mac)}</span> '

    if not macs_html:
        macs_html = "<em>No MAC addresses</em>"

    vm_rows_html += f"""
    <tr>
        <td>{escape(vm_name)}</td>
        <td>{escape(vm_id)}</td>
        <td>{macs_html}</td>
    </tr>
    """

# ===== 4. Read your HTML template =====
with open("mac_addresses.html", "r", encoding="utf-8") as f:
    html_template = f.read()

# Replace the Jinja-like loop with generated rows
start_tag = '{% for vm in vms %}'
end_tag = '{% endfor %}'
start_idx = html_template.find(start_tag)
end_idx = html_template.find(end_tag) + len(end_tag)
rendered_html = html_template[:start_idx] + vm_rows_html + html_template[end_idx:]

# ===== 5. Save to fixed file =====
with open(REPORT_FILE, "w", encoding="utf-8") as f:
    f.write(rendered_html)

# ===== 6. Open in browser first time only =====
if not os.path.exists(".report_opened"):
    webbrowser.open(f"file://{REPORT_FILE}")
    with open(".report_opened", "w") as marker:
        marker.write("opened")

print(f"Report updated: {REPORT_FILE}\nRefresh your browser to see new data.")
