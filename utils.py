import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from database import get_user_tokens, save_token

load_dotenv()

# ============================================
# GOOGLE OAUTH CONFIGURATION
# ============================================

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
TOKEN_URL = "https://www.googleapis.com/oauth2/v4/token"


# ============================================
# TOKEN REFRESH FUNCTION
# ============================================

def refresh_access_token(user_id):
    """
    Refresh expired access token using refresh token
    """
    print("\n" + "="*60)
    print("🔄 TOKEN REFRESH STARTED")
    print("="*60)
    
    # Step 1: Database se current tokens lo
    token_data = get_user_tokens(user_id)
    
    if not token_data or not token_data['refresh_token']:
        print("❌ No refresh token found!")
        print("="*60 + "\n")
        return None
    
    refresh_token = token_data['refresh_token']
    print(f"✅ Refresh token found for user_id: {user_id}")
    
    # Step 2: Google ko request bhejo
    try:
        print("📤 Requesting new access token from Google...")
        
        response = requests.post(
            TOKEN_URL,
            data={
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
                'refresh_token': refresh_token,
                'grant_type': 'refresh_token'
            }
        )
        
        if response.status_code != 200:
            print(f"❌ Token refresh failed: {response.status_code}")
            print(f"Response: {response.text}")
            print("="*60 + "\n")
            return None
        
        # Step 3: New token data extract karo
        new_token_data = response.json()
        new_access_token = new_token_data.get('access_token')
        expires_in = new_token_data.get('expires_in', 3600)
        
        print("✅ New access token received!")
        print(f"⏰ Expires in: {expires_in} seconds")
        
        # Step 4: Database mein update karo
        save_token(
            user_id=user_id,
            access_token=new_access_token,
            refresh_token=refresh_token,
            expires_in=expires_in
        )
        
        print("💾 New token saved to database!")
        print("="*60 + "\n")
        
        return {
            'access_token': new_access_token,
            'refresh_token': refresh_token,
            'expires_in': expires_in
        }
        
    except Exception as e:
        print(f"❌ Exception during token refresh: {str(e)}")
        print("="*60 + "\n")
        return None


def get_valid_token(user_id):
    """
    Get valid token (auto-refresh if expired)
    """
    from database import is_token_expired
    
    if is_token_expired(user_id):
        print(f"⚠️ Token expired for user_id: {user_id}")
        print("🔄 Auto-refreshing token...")
        
        refreshed_token = refresh_access_token(user_id)
        
        if not refreshed_token:
            print("❌ Token refresh failed!")
            return None
        
        print("✅ Token refreshed successfully!")
        return refreshed_token
    
    # Token valid hai
    return get_user_tokens(user_id)