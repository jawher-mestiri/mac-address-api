import ssl
import json
import urllib.request
import base64
from urllib.error import HTTPError, URLError
from html import escape
import webbrowser
import os
import getpass
import re

# ===== Prompt & sanitize host =====
raw_host = getpass.getpass("Enter vCenter hostname or IP (no scheme needed): ").strip()
username = getpass.getpass("Enter username: ").strip()
password = getpass.getpass("Enter password: ")

# strip scheme + path if user pasted a full URL
vcenter = re.sub(r'^https?://', '', raw_host).split('/')[0]

TEMPLATE_FILE = os.path.join(os.path.dirname(__file__), "mac_addresses.html")
REPORT_FILE = os.path.abspath("vm_mac_report.html")

# ===== SSL context: lab vs prod =====
# LAB (self-signed): disable verification
ctx = ssl._create_unverified_context()
# PROD: use your CA instead
# ctx = ssl.create_default_context(cafile="/path/to/vcenter-ca.pem")

# ===== HTTP helper that returns (status, data, headers) =====
def http_request(method, url, headers=None, data=None):
    if data is not None and not isinstance(data, bytes):
        data = data.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            body = resp.read()
            ctype = resp.getheader("Content-Type", "") or ""
            headers_out = {k.lower(): v for k, v in resp.headers.items()}
            if "application/json" in ctype:
                return resp.status, json.loads(body), headers_out
            return resp.status, body.decode(errors="replace"), headers_out
    except HTTPError as e:
        try:
            body = e.read().decode(errors="replace")
        except Exception:
            body = str(e)
        return e.code, f"HTTPError: {e.reason} | {body}", {k.lower(): v for k, v in getattr(e, "headers", {}).items()}
    except URLError as e:
        return 0, f"URLError: {e.reason}", {}
    except Exception as e:
        return 0, f"Unexpected error: {str(e)}", {}

# ===== Login that tries both endpoints =====
def login_and_get_session_id():
    auth_b64 = base64.b64encode(f"{username}:{password}".encode()).decode()
    auth_hdr = {"Authorization": f"Basic {auth_b64}"}

    # Try REST endpoint first
    status, data, hdrs = http_request("POST", f"https://{vcenter}/rest/com/vmware/cis/session", headers=auth_hdr)
    if status in (200, 201):
        if isinstance(data, dict) and data.get("value"):
            return data["value"], "rest"
        # Some proxies strip bodies; keep trying below

    # Try newer /api endpoint
    status2, data2, hdrs2 = http_request("POST", f"https://{vcenter}/api/session", headers=auth_hdr)
    if status2 in (200, 201):
        # Session id might be in JSON, header, or Set-Cookie
        if isinstance(data2, dict) and data2.get("value"):
            return data2["value"], "api"
        sid = hdrs2.get("vmware-api-session-id")
        if not sid:
            # Parse Set-Cookie if present
            sc = hdrs2.get("set-cookie", "")
            m = re.search(r"vmware-api-session-id=([^;]+)", sc, re.I)
            if m:
                sid = m.group(1)
        if sid:
            return sid, "api"

    # If we got here, both attempts failed; show diagnostic
    raise SystemExit(
        "Login failed.\n"
        f"REST /cis/session → {status}: {data}\n"
        f"API  /api/session → {status2}: {data2}\n"
        "Tips: ensure host is vCenter (not ESXi), creds are correct, and proxy/SSL allow HTTPS 443."
    )

session_id, api_flavor = login_and_get_session_id()
print(f"Session established via {api_flavor.upper()} endpoint.")

# Common auth headers for subsequent calls (header + cookie for compatibility)
common_headers = {
    "vmware-api-session-id": session_id,
    "Cookie": f"vmware-api-session-id={session_id}"
}

# ===== Helpers to try /rest then /api for each resource =====
def get_json_any(path_rest, path_api):
    # try /rest
    status, data, _ = http_request("GET", f"https://{vcenter}{path_rest}", headers=common_headers)
    if status == 200:
        return ("rest", data)
    # fallback to /api
    status2, data2, _ = http_request("GET", f"https://{vcenter}{path_api}", headers=common_headers)
    if status2 == 200:
        return ("api", data2)
    raise SystemExit(f"Fetch failed.\nREST {path_rest} → {status}: {data}\nAPI  {path_api} → {status2}: {data2}")

# Shape-normalizers (REST usually wraps in {'value': [...]}, API may return a list)
def unwrap_list(payload):
    if isinstance(payload, dict) and "value" in payload and isinstance(payload["value"], list):
        return payload["value"]
    if isinstance(payload, list):
        return payload
    # Some rare cases return dicts keyed by id; convert to list
    if isinstance(payload, dict):
        return list(payload.values())
    return []

def unwrap_obj(payload):
    if isinstance(payload, dict) and "value" in payload and isinstance(payload["value"], dict):
        return payload["value"]
    if isinstance(payload, dict):
        return payload
    return {}

# ===== 1) VMs =====
_, vms_payload = get_json_any("/rest/vcenter/vm", "/api/vcenter/vm")
vms = unwrap_list(vms_payload)

# ===== 2) Build table rows (adapters + MACs in separate cols) =====
vm_rows_html = ""
for vm in vms:
    vm_id = vm.get("vm") or vm.get("vm_id") or vm.get("id") or ""
    vm_name = vm.get("name") or vm.get("vm_name") or ""

    # NICs list for this VM
    _, nics_payload = get_json_any(
        f"/rest/vcenter/vm/{vm_id}/hardware/ethernet",
        f"/api/vcenter/vm/{vm_id}/hardware/ethernet"
    )
    nics = unwrap_list(nics_payload)

    adapters = []
    macs = []

    for nic in nics:
        nic_id = nic.get("nic") or nic.get("nic_id") or nic.get("pci_slot_number") or ""
        nic_label = nic.get("label") or (f"NIC {nic_id}" if nic_id else "NIC")

        # NIC detail (for adapter type + MAC)
        status, nic_detail_payload, _ = http_request(
            "GET",
            f"https://{vcenter}/rest/vcenter/vm/{vm_id}/hardware/ethernet/{nic_id}",
            headers=common_headers
        )
        if status != 200:
            status, nic_detail_payload, _ = http_request(
                "GET",
                f"https://{vcenter}/api/vcenter/vm/{vm_id}/hardware/ethernet/{nic_id}",
                headers=common_headers
            )

        nic_detail = unwrap_obj(nic_detail_payload)
        adapter_type = nic_detail.get("adapter_type", "Unknown")
        mac = nic_detail.get("mac_address", "Unknown")

        adapters.append(f"{nic_label} ({adapter_type})")
        macs.append(mac)

    # Compose HTML
    adapter_html = " ".join(f'<span class="adapter-badge">{escape(a)}</span>' for a in adapters) or "<em>No Adapters</em>"
    macs_html = " ".join(f'<span class="mac-badge">{escape(m)}</span>' for m in macs) or "<em>No MAC addresses</em>"

    vm_rows_html += f"""
    <tr>
        <td>{escape(vm_name)}</td>
        <td>{escape(vm_id)}</td>
        <td>{adapter_html}</td>
        <td>{macs_html}</td>
    </tr>
    """

# ===== Inject rows into your template =====
with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
    template = f.read()

start_tag = '{% for vm in vms %}'
end_tag = '{% endfor %}'
start_idx = template.find(start_tag)
end_idx = template.find(end_tag)
if start_idx == -1 or end_idx == -1:
    raise SystemExit("Template markers not found. Ensure mac_addresses.html has the {% for vm in vms %}...{% endfor %} block.")
end_idx += len(end_tag)

rendered = template[:start_idx] + vm_rows_html + template[end_idx:]

with open(REPORT_FILE, "w", encoding="utf-8") as f:
    f.write(rendered)

marker = os.path.join(os.path.dirname(REPORT_FILE), ".report_opened")
if not os.path.exists(marker):
    webbrowser.open(f"file://{REPORT_FILE}")
    with open(marker, "w") as m:
        m.write("opened")

print(f" Report generated: {REPORT_FILE}\n Refresh the tab to see updates.")
