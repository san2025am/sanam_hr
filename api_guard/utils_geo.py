
import math

def parse_latlng(s: str):
    if not s:
        return None
    try:
        parts = [p.strip() for p in s.split(',')]
        if len(parts) != 2:
            return None
        return float(parts[0]), float(parts[1])
    except Exception:
        return None

def haversine_distance_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c
