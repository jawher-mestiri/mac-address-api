from flask import Flask, jsonify,render_template
import requests
import urllib3

app = Flask(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# vCenter info – update if needed
VCENTER = "https://<vcenter-server>/rest"
USERNAME = "administrator@vsphere.local"
PASSWORD = "password"

def get_vcenter_session():
    response = requests.post(
        f"https://{VCENTER}/rest/com/vmware/cis/session",
        auth=(USERNAME, PASSWORD),
        verify=False
    )
    if response.status_code != 200:
        return None
    return response.json()["value"]

@app.route('/mac-addresses', methods=['GET'])
def get_mac_addresses():
    session_id = get_vcenter_session()
    if not session_id:
        return jsonify({"error": "Failed to authenticate with vCenter"}), 500

    headers = {
        "vmware-api-session-id": session_id
    }

    vms_resp = requests.get(
        f"https://{VCENTER}/rest/vcenter/vm",
        headers=headers,
        verify=False
    )

    if vms_resp.status_code != 200:
        return jsonify({"error": "Failed to retrieve VMs"}), 500

    vms = vms_resp.json().get("value", [])
    results = []

    for vm in vms:
        vm_id = vm["vm"]
        vm_name = vm["name"]

        nics_resp = requests.get(
            f"https://{VCENTER}/rest/vcenter/vm/{vm_id}/hardware/ethernet",
            headers=headers,
            verify=False
        )

        nic_list = nics_resp.json().get("value", [])
        macs = []

        for nic in nic_list:
            nic_id = nic["nic"]
            nic_detail_resp = requests.get(
                f"https://{VCENTER}/rest/vcenter/vm/{vm_id}/hardware/ethernet/{nic_id}",
                headers=headers,
                verify=False
            )
            nic_data = nic_detail_resp.json()
            mac = nic_data.get("value", {}).get("mac_address")
            if mac:
                macs.append(mac)

        results.append({
            "vm_name": vm_name,
            "vm_id": vm_id,
            "mac_addresses": macs or ["No MACs found"]
        })

    return render_template('mac_addresses.html', results)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
