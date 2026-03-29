import requests
ACCESS_TOKEN = "EAANec5rGMCABRLcyIIOmlv2EciPJbNSLcvhggSTZAmBkSbZCAzG7097U4x0UyVuvDKOBaRZA6LdPGy1pkyPniC5cowwUtm40zZB00yarZCWRe4Jo8btLtJXIhzQV4AVATEgRuuFdNBDrYiS9N6newVnzeObSBsOL2arRtHqRQkmIZAvw63bAtUqZBuxhrNp9ej4RZAjg92PYJKajWdwoaOAA26Xt2o3iFVfzQy0IZBZChFD2yjZCPKXiZANpUtkUcIrxKB1gYXDMGLZCtoO74xt6rZBzTmXXEk4NYPNmgZD"
PHONE_ID = "919410367932677"
RECIPIENT = "+33785557054"

url = f"https://graph.facebook.com/v17.0/{PHONE_ID}/messages"
headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
data = {"messaging_product": "whatsapp", "to": RECIPIENT, "type": "text", "text": {"body": "Diagnostic SnackFlow : OK"}}

response = requests.post(url, json=data, headers=headers)
print(f"STATUS: {response.status_code}")
print(f"RESPONSE: {response.text}")