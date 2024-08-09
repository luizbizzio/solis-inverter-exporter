from prometheus_client import start_http_server, Gauge, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.exposition import start_wsgi_server
from wsgiref.simple_server import make_server
import requests
from bs4 import BeautifulSoup
import re

# Exporter Port
PORT = 8686

# Device Configuration
IP = "INVERTER_IP"
USERNAME = "INVERTER_USERNAME"
PASSWORD = "INVERTER_PASSWORD"

SOLIS_ADDRESS = f"http://{IP}/status.html"

registry = CollectorRegistry()
inverter_power = Gauge('inverter_power', 'Power output of the inverter', registry=registry)
inverter_energy_today = Gauge('inverter_energy_today', 'Energy produced today by the inverter', registry=registry)
inverter_energy_total = Gauge('inverter_energy_total', 'Total energy produced by the inverter', registry=registry)

def fetch_data():
    while True:
        try:
            response = requests.get(SOLIS_ADDRESS, auth=(USERNAME, PASSWORD), timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                script = soup.find_all('script')[1].string
                def extract_value(name):
                    match = re.search(f'var {name} = "(.*?)";', script)
                    return float(match.group(1).strip()) if match else 0

                inverter_power.set(extract_value('webdata_now_p'))
                inverter_energy_today.set(extract_value('webdata_today_e'))
                inverter_energy_total.set(extract_value('webdata_total_e'))
                break
            else:
                print(f"Failed to fetch data. Status code: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Network error: {e}, retrying...")
        except Exception as e:
            print(f"Unexpected error: {e}")
            break

    print("Data fetched successfully.")
def metrics_app(environ, start_response):
    if environ['PATH_INFO'] == '/metrics':
        fetch_data()
        data = generate_latest(registry)
        status = '200 OK'
        headers = [('Content-type', CONTENT_TYPE_LATEST)]
    else:
        status = '404 Not Found'
        headers = [('Content-type', 'text/plain')]
        data = b'Not Found'
    start_response(status, headers)
    return [data]

if __name__ == '__main__':
    server = make_server('', PORT, metrics_app)
    print(f"Serving metrics on port {PORT}")
    server.serve_forever()
