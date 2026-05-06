# ============================================================
# Indie-Go — Configuration & Artist Ledger
# ============================================================

# ============================================================
# DEVELOPER ACCESS
# Full access to all artist profiles for testing purposes.
# ============================================================
DEVELOPER_USER_IDS = {
    "95cm1z9hpxncv9a6sytt8oi5c",  # Jeremy (developer)
}

# Artist profiles — keyed by Spotify ARTIST PAGE ID
ARTIST_PROFILES = {
    "02t7FwVp7Bgif8teVSqYDn": {
        "name": "George Paul",
        "persona": "visualist",       # High-fashion, aesthetic tone
        "artist_id": "02t7FwVp7Bgif8teVSqYDn",
    },
    "3tujXdkggqf5yCp80Yc6PH": {
        "name": "Ashbel Peter",
        "persona": "storyteller",     # Story-driven, deep tone
        "artist_id": "3tujXdkggqf5yCp80Yc6PH",
    },
    "3rWPiyV2dFS6IwTF40zsDR": {
        "name": "Tushar Mathur",
        "persona": "statistician",    # Aggressive, momentum-driven tone
        "artist_id": "3rWPiyV2dFS6IwTF40zsDR",
    },
}

# ============================================================
# VERIFICATION MAPPING
# Maps Spotify USER ACCOUNT IDs → Artist Page IDs
#
# HOW TO POPULATE THIS:
# 1. Run the app: run.bat
# 2. Have each artist log in with their personal Spotify account
# 3. If their ID is not in this ledger, the app shows their
#    User ID on screen — copy it and add the mapping below
# 4. Format: "their_spotify_user_id": "artist_page_id"
#
# Example:
#   "31xvpz2n7wkjqpsdlcf4xyz": "02t7FwVp7Bgif8teVSqYDn",
# ============================================================
AUTHORIZED_USER_IDS = {
    # Jeremy mapped to George Paul for UAT testing
    "95cm1z9hpxncv9a6sytt8oi5c": "02t7FwVp7Bgif8teVSqYDn",

    # Ashbel Peter — add after first login
    # "ASHBEL_USER_ID_HERE": "3tujXdkggqf5yCp80Yc6PH",

    # Tushar Mathur — add after first login
    # "TUSHAR_USER_ID_HERE": "3rWPiyV2dFS6IwTF40zsDR",
}

# OAuth Configuration
SCOPES = "user-read-private user-read-email"

import os as _os
REDIRECT_URI = _os.getenv("REDIRECT_URI", "http://127.0.0.1:8080")
