import requests

def reverse_geocode(lat, lng):
    """
    Koordinatları adrese çevirir (Nominatim OpenStreetMap kullanır).
    """
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}&zoom=18&addressdetails=1"
        headers = {
            'User-Agent': 'ServiceManagementApp/1.0'
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('display_name', f"{lat}, {lng}")
    except Exception as e:
        print(f"Geocoding hatası: {e}")
    
    return f"{lat}, {lng}"
