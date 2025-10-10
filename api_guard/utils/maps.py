from django.utils import timezone
"""
Map/geo utilities (geofencing, bounds, etc.).

Auto-added: module-level documentation and gentle guidance.
This block is safe to remove if you prefer.
"""
# django_project/api_guard/utils/maps.py
import re
from urllib.parse import urlparse, parse_qs, unquote

class LatLngNotFound(ValueError):
    pass

def parse_google_maps_latlng(url_or_text: str) -> dict:
    s = unquote((url_or_text or "").strip())
    if not s:
        raise LatLngNotFound("نص فارغ")
    num = r"-?\d+(?:\.\d+)?"

    def _valid(lat, lng):
        try:
            lat, lng = float(lat), float(lng)
        except Exception:
            return None
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return {"lat": round(lat, 5), "lng": round(lng, 5)}
        return None

    # query params: q, query, ll, center, destination
    try:
        parsed = urlparse(s)
        qs = parse_qs(parsed.query)
        for key in ("q", "query", "ll", "center", "destination"):
            if key in qs and qs[key]:
                cand = qs[key][0]
                m = re.search(rf"({num})\s*,\s*({num})", cand)
                if m:
                    res = _valid(m.group(1), m.group(2))
                    if res: return res
    except Exception:
        pass

    # /place/lat,lng
    m = re.search(rf"/place/({num})\s*,\s*({num})", s)
    if m:
        res = _valid(m.group(1), m.group(2))
        if res: return res

    # @lat,lng,zoom
    m = re.search(rf"@\s*({num})\s*,\s*({num})\s*,", s)
    if m:
        res = _valid(m.group(1), m.group(2))
        if res: return res

    # !3dLAT!4dLNG  أو !2dLNG!3dLAT
    m = re.search(rf"!3d({num})!4d({num})", s)
    if m:
        res = _valid(m.group(1), m.group(2))
        if res: return res
    m = re.search(rf"!2d({num})!3d({num})", s)
    if m:
        res = _valid(m.group(2), m.group(1))
        if res: return res

    # fallback: أول "lat,lng" في النص
    m = re.search(rf"({num})\s*,\s*({num})", s)
    if m:
        res = _valid(m.group(1), m.group(2))
        if res: return res

    raise LatLngNotFound("لم أستطع استخراج الإحداثيات من النص/الرابط.")


def get_current_shift_window(user):
    """
    Best-effort: Return (start_dt, end_dt, unrestricted, pre_buf_min, post_buf_min).
    Tries to inspect user-related models to find current shift assignment.
    Falls back to (None, None, False, 0, 0) safely.
    """
    try:
        guard = getattr(user, 'guard', None) or getattr(user, 'profile', None)
        if not guard:
            return None, None, False, 0, 0
        assignment = getattr(guard, 'current_assignment', None) or getattr(guard, 'shift_assignment', None)
        if not assignment:
            return None, None, False, 0, 0
        shift = getattr(assignment, 'shift', None) or assignment
        start = getattr(assignment, 'start_time', None) or getattr(shift, 'start_time', None)
        end = getattr(assignment, 'end_time', None) or getattr(shift, 'end_time', None)
        unrestricted = bool(getattr(assignment, 'unrestricted', False) or getattr(shift, 'unrestricted', False))
        pre_buf = int(getattr(shift, 'pre_shift_buffer_minutes', 0) or 0)
        post_buf = int(getattr(shift, 'post_shift_buffer_minutes', 0) or 0)
        # Normalize to aware UTC datetimes if naive
        try:
            if start and timezone.is_naive(start):
                start = timezone.make_aware(start, timezone.get_current_timezone())
            if end and timezone.is_naive(end):
                end = timezone.make_aware(end, timezone.get_current_timezone())
            start = start.astimezone(timezone.utc) if start else None
            end = end.astimezone(timezone.utc) if end else None
        except Exception:
            pass
        return start, end, unrestricted, pre_buf, post_buf
    except Exception:
        return None, None, False, 0, 0


def is_location_allowed_for_user(user, lat: float, lng: float):
    """
    Best-effort: Validate (lat,lng) vs user's assigned location.
    Return (allowed: bool, reason: str|None, location_id: str|None).
    Fallback to allowing with None reason if no data.
    """
    try:
        guard = getattr(user, 'guard', None) or getattr(user, 'profile', None)
        if not guard:
            return True, None, None
        location = getattr(guard, 'location', None) or getattr(guard, 'site', None) or getattr(guard, 'post', None)
        radius_m = float(getattr(location, 'radius_m', 150)) if location else 150.0
        lat0 = getattr(location, 'lat', None) or getattr(location, 'latitude', None)
        lng0 = getattr(location, 'lng', None) or getattr(location, 'longitude', None)
        if lat0 is None or lng0 is None:
            return True, None, getattr(location, 'id', None) if location else None
        from .geo import haversine_distance_m
        d = haversine_distance_m(float(lat0), float(lng0), float(lat), float(lng))
        if d <= radius_m:
            return True, None, str(getattr(location, 'id', None)) if location else None
        return False, f"خارج النطاق ({int(d)}م > {int(radius_m)}م)", str(getattr(location, 'id', None)) if location else None
    except Exception:
        return True, None, None
