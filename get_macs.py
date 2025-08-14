import requests
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Replace with your vCenter IP or hostname
vcenter = "https://<vcenter-server>/rest"
username = "administrator@vsphere.local"
password = "Password"

# Login and get session token
session = requests.post(
    f"https://{vcenter}/rest/com/vmware/cis/session",
    auth=(username, password),
    verify=False
)

if session.status_code != 200:
    print("Login failed:", session.text)
    exit()

print(" Login Response:", session.status_code)

# Set headers with session token
headers = {
    "vmware-api-session-id": session.json()['value']
}

# Get list of VMs
vms_response = requests.get(
    f"https://{vcenter}/rest/vcenter/vm",
    headers=headers,
    verify=False
)

if vms_response.status_code != 200:
    print("Failed to fetch VMs:", vms_response.text)
    exit()

vms = vms_response.json()
print(" VMs Response:", vms_response.status_code)

# Loop through each VM and fetch NIC details
for vm in vms['value']:
    vm_id = vm['vm']
    vm_name = vm['name']
    print(f"\n=== VM: {vm_name} ({vm_id}) ===")

    # Get NICs (IDs only)
    nics_response = requests.get(
        f"https://{vcenter}/rest/vcenter/vm/{vm_id}/hardware/ethernet",
        headers=headers,
        verify=False
    )
    nics = nics_response.json()

    # Loop through each NIC ID and fetch details
    if 'value' in nics and nics['value']:
        for nic in nics['value']:
            nic_id = nic['nic']

            nic_detail_response = requests.get(
                f"https://{vcenter}/rest/vcenter/vm/{vm_id}/hardware/ethernet/{nic_id}",
                headers=headers,
                verify=False
            )
            nic_detail = nic_detail_response.json()

            mac = nic_detail.get('value', {}).get('mac_address', 'Unknown')
            print(f"NIC {nic_id}: MAC Address = {mac}")
    else:
        print("No NICs found for this VM")
