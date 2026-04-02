"""
Server-side token verification for Google, Facebook, and Apple Sign-In.

Each verify function validates the provider token and returns a unified dict:
    { id, name, email, picture, provider }
or raises SocialAuthError on failure.
"""

import os
import json
import time
import jwt          # PyJWT
import requests
from dotenv import load_dotenv
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

load_dotenv()


class SocialAuthError(Exception):
    """Raised when social token verification fails."""
    pass


# ══════════════════════════════════════════════
#  Config from environment
# ══════════════════════════════════════════════

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "")
APPLE_CLIENT_ID = os.environ.get("APPLE_CLIENT_ID", "")  # Service ID e.g. com.chatgenius.web
APPLE_TEAM_ID = os.environ.get("APPLE_TEAM_ID", "")
APPLE_KEY_ID = os.environ.get("APPLE_KEY_ID", "")
APPLE_PRIVATE_KEY_PATH = os.environ.get("APPLE_PRIVATE_KEY_PATH", "")


# ══════════════════════════════════════════════
#  Google — verify ID token or access token
# ══════════════════════════════════════════════

def verify_google(token):
    """
    Verify a Google token. Supports two flows:
    1. ID token (JWT from Google Sign-In) — verified via google-auth library
    2. Access token (from oauth2 token client) — verified via Google userinfo endpoint
    """
    if not GOOGLE_CLIENT_ID:
        raise SocialAuthError("Google Sign-In is not configured (missing GOOGLE_CLIENT_ID).")

    # Try ID token verification first (more secure)
    try:
        idinfo = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), GOOGLE_CLIENT_ID
        )
        # Check issuer
        if idinfo["iss"] not in ("accounts.google.com", "https://accounts.google.com"):
            raise SocialAuthError("Invalid Google token issuer.")

        return {
            "id": idinfo["sub"],
            "name": idinfo.get("name", ""),
            "email": idinfo.get("email", ""),
            "picture": idinfo.get("picture", ""),
            "provider": "google",
        }
    except ValueError:
        # Not a valid ID token — try as access token
        pass

    # Fallback: treat as access token, fetch userinfo
    try:
        resp = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code != 200:
            raise SocialAuthError(f"Google token rejected (HTTP {resp.status_code}).")

        profile = resp.json()
        if "error" in profile:
            raise SocialAuthError(f"Google API error: {profile['error'].get('message', 'unknown')}")

        # Verify the token belongs to our app by checking tokeninfo
        tokeninfo_resp = requests.get(
            f"https://oauth2.googleapis.com/tokeninfo?access_token={token}",
            timeout=10,
        )
        if tokeninfo_resp.status_code == 200:
            tokeninfo = tokeninfo_resp.json()
            aud = tokeninfo.get("aud", "")
            if aud and aud != GOOGLE_CLIENT_ID:
                raise SocialAuthError("Google token was not issued for this application.")

        return {
            "id": profile.get("sub", ""),
            "name": profile.get("name", ""),
            "email": profile.get("email", ""),
            "picture": profile.get("picture", ""),
            "provider": "google",
        }
    except requests.RequestException as e:
        raise SocialAuthError(f"Failed to verify Google token: {e}")


# ══════════════════════════════════════════════
#  Facebook — verify access token via Graph API
# ══════════════════════════════════════════════

def verify_facebook(token):
    """
    Verify a Facebook access token server-side:
    1. Debug the token with Facebook's /debug_token endpoint to confirm it's valid
       and was issued for our app.
    2. Fetch user profile from /me endpoint.
    """
    if not FACEBOOK_APP_ID or not FACEBOOK_APP_SECRET:
        raise SocialAuthError("Facebook Login is not configured (missing FACEBOOK_APP_ID or FACEBOOK_APP_SECRET).")

    app_token = f"{FACEBOOK_APP_ID}|{FACEBOOK_APP_SECRET}"

    # Step 1: Debug/verify the user token
    try:
        debug_resp = requests.get(
            "https://graph.facebook.com/debug_token",
            params={"input_token": token, "access_token": app_token},
            timeout=10,
        )
        if debug_resp.status_code != 200:
            raise SocialAuthError(f"Facebook token debug failed (HTTP {debug_resp.status_code}).")

        debug_data = debug_resp.json().get("data", {})

        if not debug_data.get("is_valid"):
            error_msg = debug_data.get("error", {}).get("message", "Token is invalid or expired.")
            raise SocialAuthError(f"Facebook token invalid: {error_msg}")

        if str(debug_data.get("app_id")) != str(FACEBOOK_APP_ID):
            raise SocialAuthError("Facebook token was not issued for this application.")

        if debug_data.get("expires_at", 0) and debug_data["expires_at"] < time.time():
            raise SocialAuthError("Facebook token has expired.")

        fb_user_id = debug_data.get("user_id", "")

    except requests.RequestException as e:
        raise SocialAuthError(f"Failed to verify Facebook token: {e}")

    # Step 2: Fetch user profile
    try:
        profile_resp = requests.get(
            "https://graph.facebook.com/v19.0/me",
            params={
                "fields": "id,name,email,picture.width(200)",
                "access_token": token,
            },
            timeout=10,
        )
        if profile_resp.status_code != 200:
            raise SocialAuthError(f"Facebook profile fetch failed (HTTP {profile_resp.status_code}).")

        profile = profile_resp.json()
        if "error" in profile:
            raise SocialAuthError(f"Facebook API error: {profile['error'].get('message', 'unknown')}")

        picture_url = ""
        if "picture" in profile and "data" in profile["picture"]:
            picture_url = profile["picture"]["data"].get("url", "")

        return {
            "id": profile.get("id", fb_user_id),
            "name": profile.get("name", ""),
            "email": profile.get("email", ""),
            "picture": picture_url,
            "provider": "facebook",
        }
    except requests.RequestException as e:
        raise SocialAuthError(f"Failed to fetch Facebook profile: {e}")


# ══════════════════════════════════════════════
#  Apple — verify identity token (JWT)
# ══════════════════════════════════════════════

# Cache Apple's public keys
_apple_keys_cache = {"keys": None, "fetched_at": 0}


def _get_apple_public_keys():
    """Fetch Apple's public keys from their JWKS endpoint. Cached for 24h."""
    now = time.time()
    if _apple_keys_cache["keys"] and (now - _apple_keys_cache["fetched_at"]) < 86400:
        return _apple_keys_cache["keys"]

    try:
        resp = requests.get("https://appleid.apple.com/auth/keys", timeout=10)
        resp.raise_for_status()
        keys = resp.json()["keys"]
        _apple_keys_cache["keys"] = keys
        _apple_keys_cache["fetched_at"] = now
        return keys
    except requests.RequestException as e:
        raise SocialAuthError(f"Failed to fetch Apple public keys: {e}")


def verify_apple(token, client_provided_name="", client_provided_email=""):
    """
    Verify an Apple identity token (JWT):
    1. Fetch Apple's public JWKS keys
    2. Decode and verify the JWT signature, issuer, audience, expiry
    3. Extract user info from the verified claims

    Apple only sends the user's name on the FIRST login, so we accept
    client_provided_name as a fallback.
    """
    if not APPLE_CLIENT_ID:
        raise SocialAuthError("Apple Sign-In is not configured (missing APPLE_CLIENT_ID).")

    # Get Apple's public keys
    apple_keys = _get_apple_public_keys()

    # Decode the JWT header to find the key ID
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.DecodeError:
        raise SocialAuthError("Invalid Apple token format.")

    kid = unverified_header.get("kid")
    if not kid:
        raise SocialAuthError("Apple token missing key ID (kid).")

    # Find the matching public key
    matching_key = None
    for key_data in apple_keys:
        if key_data["kid"] == kid:
            matching_key = key_data
            break

    if not matching_key:
        # Keys might have rotated — clear cache and retry once
        _apple_keys_cache["keys"] = None
        apple_keys = _get_apple_public_keys()
        for key_data in apple_keys:
            if key_data["kid"] == kid:
                matching_key = key_data
                break

    if not matching_key:
        raise SocialAuthError("Apple token signed with unknown key.")

    # Build the public key from JWK
    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(matching_key))

    # Verify and decode the JWT
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=APPLE_CLIENT_ID,
            issuer="https://appleid.apple.com",
        )
    except jwt.ExpiredSignatureError:
        raise SocialAuthError("Apple token has expired.")
    except jwt.InvalidAudienceError:
        raise SocialAuthError("Apple token was not issued for this application.")
    except jwt.InvalidIssuerError:
        raise SocialAuthError("Apple token has invalid issuer.")
    except jwt.InvalidTokenError as e:
        raise SocialAuthError(f"Invalid Apple token: {e}")

    email = claims.get("email", client_provided_email)
    # Apple doesn't include name in the JWT — use client-provided name
    name = client_provided_name if client_provided_name else (email.split("@")[0] if email else "Apple User")

    return {
        "id": claims["sub"],
        "name": name,
        "email": email,
        "picture": "",  # Apple doesn't provide profile pictures
        "provider": "apple",
    }


# ══════════════════════════════════════════════
#  Unified verify function
# ══════════════════════════════════════════════

def verify_social_token(provider, token, client_name="", client_email=""):
    """
    Verify a social login token and return unified user info.

    Returns: { id, name, email, picture, provider }
    Raises: SocialAuthError on any failure
    """
    if provider == "google":
        return verify_google(token)
    elif provider == "facebook":
        return verify_facebook(token)
    elif provider == "apple":
        return verify_apple(token, client_provided_name=client_name, client_provided_email=client_email)
    else:
        raise SocialAuthError(f"Unknown provider: {provider}")


def is_provider_configured(provider):
    """Check if a social provider has the required env vars configured."""
    if provider == "google":
        return bool(GOOGLE_CLIENT_ID)
    elif provider == "facebook":
        return bool(FACEBOOK_APP_ID and FACEBOOK_APP_SECRET)
    elif provider == "apple":
        return bool(APPLE_CLIENT_ID)
    return False
