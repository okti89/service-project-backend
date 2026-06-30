import requests
from accounts.models import UserDevice


EXPO_URL = "https://exp.host/--/api/v2/push/send"


def _post_expo(messages):
    session = requests.Session()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }

    try:
        response = session.post(
            EXPO_URL,
            headers=headers,
            json=messages,
            timeout=12,
        )
    except requests.exceptions.RequestException as e:
        return {"status": "request_failed", "error": str(e)}

    # Expo bazen 200 + error payload döner
    try:
        return response.json()
    except Exception:
        return {
            "status": "invalid_response",
            "raw": response.text
        }


def _is_valid_token(token: str) -> bool:
    if not token:
        return False
    return "ExpoPushToken" in token or "ExponentPushToken" in token


def _chunk_list(data, size=100):
    for i in range(0, len(data), size):
        yield data[i:i + size]


def send_expo_push_notification(user, title, body, data=None, sound="default"):
    if not user:
        return {"status": "failed", "message": "User not provided"}

    tokens = UserDevice.objects.filter(user=user).values_list("expo_token", flat=True)

    valid_tokens = [t for t in tokens if _is_valid_token(t)]

    if not valid_tokens:
        return {"status": "failed", "message": "No valid tokens"}

    messages = [
        {
            "to": token,
            "title": title,
            "body": body,
            "sound": sound,
            "channelId": "default",
            "data": data or {},
        }
        for token in valid_tokens
    ]

    results = []

    for batch in _chunk_list(messages, 100):
        result = _post_expo(batch)
        results.append(result)

    return {"status": "success", "results": results}


def send_bulk_expo_push_notification(users, title, body, data=None, sound="default"):
    if not users:
        return {"status": "failed", "message": "Users empty"}

    tokens = UserDevice.objects.filter(
        user__in=users
    ).values_list("expo_token", flat=True)

    valid_tokens = [t for t in tokens if _is_valid_token(t)]

    if not valid_tokens:
        return {"status": "failed", "message": "No tokens found"}

    messages = [
        {
            "to": token,
            "title": title,
            "body": body,
            "sound": sound,
            "channelId": "default",
            "data": data or {},
        }
        for token in valid_tokens
    ]

    results = []

    for batch in _chunk_list(messages, 100):
        result = _post_expo(batch)
        results.append(result)

    return {
        "status": "processed",
        "batch_count": len(results),
        "results": results
    }