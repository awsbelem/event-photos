"""Face search, deployed as the faces stack's Lambda (`index.py`; stdlib + boto3 only).

POST /search  {"consent": true, "image": "<base64 JPEG>"} → {"photos": [external ids], "note"?, "message"?}

The selfie lives only in this call's memory: it is never written anywhere, and nothing here logs a
request body. Rate limits are kept in DynamoDB under a salted hash of the caller's IP.
Messages are user-facing, so they are in Portuguese. Overview: README, "Face search".
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import os
import time

COLLECTION = os.environ.get("COLLECTION_ID", "")
THRESHOLD = float(os.environ.get("THRESHOLD", "95"))
RATE_TABLE = os.environ.get("RATE_TABLE", "")
IP_SALT = os.environ.get("IP_SALT", "")
ENABLED = os.environ.get("ENABLED", "1") != "0"  # `face-search disable` turns answers off
MAX_BODY = 1_400_000  # bytes of request body (~1 MB image after base64)
MAX_IMAGE = 1_000_000
LIMITS = ((60, 5), (3600, 30))  # (window seconds, searches allowed) per caller
GLOBAL_LIMIT = int(os.environ.get("GLOBAL_LIMIT", "2000"))  # searches an hour for everyone: caps the Rekognition bill

NO_CONSENT = "Marque a autorização para fazer a busca."
NOT_JPEG = "Envie a selfie em JPEG."
TOO_BIG = "A selfie ficou grande demais. Tente de novo."
NO_FACE = "Não encontramos um rosto. Tente com mais luz, de frente para a câmera."
MANY_FACES = "Usamos o maior rosto da selfie."
NO_MATCH = "Ainda não achamos fotos suas. Novas fotos entram ao longo do dia; tente mais tarde ou veja por momento."
TOO_MANY = "Muitas buscas em pouco tempo. Tente de novo em um minuto."
CLOSED = "A busca por rosto deste evento foi encerrada."
BUSY = "Busca indisponível agora. Tente de novo em instantes."
DISABLED = "A busca por rosto está desligada no momento."

_clients: dict = {}


def _client(name: str):
    if name not in _clients:
        import boto3  # in the Lambda runtime; not a dependency of this package's runtime path
        _clients[name] = boto3.client(name)
    return _clients[name]


def _code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    if http.get("method") != "POST" or event.get("rawPath") != "/search":
        return _reply(404, {"error": "Endereço não encontrado."})
    if not ENABLED:
        return _reply(410, {"error": DISABLED})
    try:
        return _search(event, http.get("sourceIp", ""))
    except Exception as exc:  # log the kind of failure only: never the event, which holds the selfie
        print(json.dumps({"error": type(exc).__name__, "code": _code(exc),
                          "request": getattr(context, "aws_request_id", "")}))
        return _reply(503, {"error": BUSY})


def _search(event: dict, ip: str) -> dict:
    body = event.get("body") or ""
    if len(body) > MAX_BODY:
        return _reply(400, {"error": TOO_BIG})
    try:
        raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
        request = json.loads(raw)
    except (ValueError, binascii.Error):
        return _reply(400, {"error": NOT_JPEG})
    if request.get("consent") is not True:
        return _reply(400, {"error": NO_CONSENT})
    try:
        image = base64.b64decode(request.get("image", ""), validate=True)
    except (ValueError, binascii.Error):
        return _reply(400, {"error": NOT_JPEG})
    del request, raw, body
    if not image.startswith(b"\xff\xd8\xff"):
        return _reply(400, {"error": NOT_JPEG})
    if len(image) > MAX_IMAGE:
        return _reply(400, {"error": TOO_BIG})
    if not _allowed(ip):
        return _reply(429, {"error": TOO_MANY})

    rekognition = _client("rekognition")
    faces = rekognition.detect_faces(Image={"Bytes": image}).get("FaceDetails", [])
    if not faces:
        return _reply(400, {"error": NO_FACE})
    try:
        matches = _with_retry(lambda: rekognition.search_faces_by_image(
            CollectionId=COLLECTION, Image={"Bytes": image}, FaceMatchThreshold=THRESHOLD,
            MaxFaces=100, QualityFilter="AUTO"))
    except Exception as exc:
        code = _code(exc)
        if code == "ResourceNotFoundException":
            return _reply(410, {"error": CLOSED})
        if code == "InvalidParameterException":  # Rekognition found no usable face
            return _reply(400, {"error": NO_FACE})
        if code in ("ThrottlingException", "ProvisionedThroughputExceededException"):
            return _reply(503, {"error": BUSY})
        raise
    finally:
        del image
    photos = list(dict.fromkeys(m["Face"]["ExternalImageId"] for m in matches.get("FaceMatches", [])
                                if m.get("Face", {}).get("ExternalImageId")))
    result: dict = {"photos": photos}
    if len(faces) > 1:
        result["note"] = MANY_FACES
    if not photos:
        result["message"] = NO_MATCH
    return _reply(200, result)


def _with_retry(call):
    try:
        return call()
    except Exception as exc:
        if _code(exc) not in ("ThrottlingException", "ProvisionedThroughputExceededException"):
            raise
        time.sleep(0.3)
        return call()


def _caller(ip: str) -> str:
    """One IPv6 /64 is one caller: a single connection gets a whole /64 to rotate through."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if address.version == 6 else ip


def _allowed(ip: str, now: float | None = None) -> bool:
    """At most 5 searches a minute and 30 an hour per caller, and GLOBAL_LIMIT an hour in all;
    counters expire on their own."""
    now = time.time() if now is None else now
    who = hashlib.sha256(f"{IP_SALT}:{_caller(ip)}".encode()).hexdigest()[:32]
    table = _client("dynamodb")
    for who_key, window, limit in [(who, w, n) for w, n in LIMITS] + [("global", 3600, GLOBAL_LIMIT)]:
        slot = int(now // window)
        response = table.update_item(
            TableName=RATE_TABLE, Key={"k": {"S": f"{who_key}#{window}#{slot}"}},
            UpdateExpression="ADD n :one SET #exp = if_not_exists(#exp, :exp)",
            ExpressionAttributeNames={"#exp": "exp"},
            ExpressionAttributeValues={":one": {"N": "1"}, ":exp": {"N": str((slot + 1) * window + 60)}},
            ReturnValues="UPDATED_NEW")
        if int(response["Attributes"]["n"]["N"]) > limit:
            return False
    return True


def _reply(status: int, body: dict) -> dict:
    return {"statusCode": status, "body": json.dumps(body, ensure_ascii=False),
            "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store",
                        "x-robots-tag": "noindex, nofollow", "referrer-policy": "no-referrer",
                        "x-frame-options": "DENY", "content-security-policy": "frame-ancestors 'none'"}}
