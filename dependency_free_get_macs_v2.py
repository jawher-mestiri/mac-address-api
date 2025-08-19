import ssl, json, urllib.request, base64
from urllib.error import HTTPError, URLError
from html import escape
import webbrowser, os, getpass

# ----- INPUTS (show host & username while typing) -----
raw_host = getpass.getpass("Enter vCenter hostname or IP: ").strip()
# sanitize:
vcenter = raw_host.replace("https://", "").replace("http://", "").split("/")[0]
username = getpass.getpass("Enter username: ")
password = getpass.getpass("Enter password: ")

REPORT_FILE = os.path.abspath("vm_mac_report.html")

# ----- SSL (lab only: skip verification) -----
ctx = ssl._create_unverified_context()

def http_request(method, url, headers=None, data=None):
    if data is not None and not isinstance(data, bytes):
        data = data.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            body = resp.read()
            ctype = resp.getheader("Content-Type", "")
            if "application/json" in ctype:
                return resp.status, json.loads(body)
            return resp.status, body.decode(errors="replace")
    except HTTPError as e:
        # Return HTTP status + server body for clarity
        try:
            body = e.read().decode(errors="replace")
        except Exception:
            body = str(e)
        return e.code, body
    except URLError as e:
        return 0, f"URLError (network/SSL): {e.reason}"
    except Exception as e:
        return 0, f"Unexpected error: {e}"

# ----- 1) LOGIN -----
login_url = f"https://{vcenter}/rest/com/vmware/cis/session"
auth_b64 = base64.b64encode(f"{username}:{password}".encode()).decode()
login_headers = {"Authorization": f"Basic {auth_b64}"}

status, login_data = http_request("POST", login_url, headers=login_headers)
if status != 200:
    print("Login failed:", status, login_data)
    raise SystemExit(1)

session_id = (login_data or {}).get("value")
if not session_id:
    print("Login succeeded but no session token returned. Response:", login_data)
    raise SystemExit(1)

# ----- 2) LIST VMS -----
headers = {"vmware-api-session-id": session_id}
status, vms_data = http_request("GET", f"https://{vcenter}/rest/vcenter/vm", headers=headers)
if status != 200:
    print("Failed to fetch VMs:", status, vms_data)
    raise SystemExit(1)

# ----- 3) BUILD ROWS -----
vm_rows_html = ""
for vm in vms_data.get("value", []):
    vm_id = vm.get("vm", "")
    vm_name = vm.get("name", "")
    status, nics_data = http_request("GET", f"https://{vcenter}/rest/vcenter/vm/{vm_id}/hardware/ethernet", headers=headers)
    if status != 200:
        macs_html = f"<em>NIC query failed: {status}</em>"
    else:
        badges = []
        for nic in nics_data.get("value", []):
            nic_id = nic.get("nic")
            status, nic_detail = http_request("GET", f"https://{vcenter}/rest/vcenter/vm/{vm_id}/hardware/ethernet/{nic_id}", headers=headers)
            mac = (nic_detail.get("value", {}) if isinstance(nic_detail, dict) else {}).get("mac_address", "Unknown")
            badges.append(f'<span class="mac-badge">{escape(mac)}</span>')
        macs_html = " ".join(badges) if badges else "<em>No MAC addresses</em>"

    vm_rows_html += (
        f"<tr>"
        f"<td>{escape(vm_name)}</td>"
        f"<td>{escape(vm_id)}</td>"
        f"<td>{macs_html}</td>"
        f"</tr>"
    )

# ----- 4) TEMPLATE -----
# Put mac_addresses.html next to this script, or set an absolute path:
TEMPLATE_FILE = os.path.join(os.path.dirname(__file__), "mac_addresses.html")
with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
    html_template = f.read()

start_tag, end_tag = '{% for vm in vms %}', '{% endfor %}'
start_idx = html_template.find(start_tag)
end_idx = html_template.find(end_tag)
if start_idx == -1 or end_idx == -1:
    raise RuntimeError("Template markers not found. Ensure the file contains the Jinja-like loop.")
end_idx += len(end_tag)

rendered_html = html_template[:start_idx] + vm_rows_html + html_template[end_idx:]

# ----- 5) WRITE & OPEN -----
with open(REPORT_FILE, "w", encoding="utf-8") as f:
    f.write(rendered_html)

marker = os.path.join(os.path.dirname(REPORT_FILE), ".report_opened")
if not os.path.exists(marker):
    webbrowser.open(f"file://{REPORT_FILE}")
    with open(marker, "w") as m:
        m.write("opened")

print(f"Report updated: {REPORT_FILE} — refresh the tab to see changes.")
