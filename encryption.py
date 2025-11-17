import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print("\n" + "=" * 60)
    print("⚠️  ENCRYPTION KEY GENERATED!")
    print("=" * 60)
    print("Add this line to your .env file:")
    print(f"\nENCRYPTION_KEY={ENCRYPTION_KEY}\n")
    print("=" * 60 + "\n")

cipher = Fernet(ENCRYPTION_KEY.encode())
def encrypt_token(token_string):
    if not token_string:
        return None
    return cipher.encrypt(token_string.encode())
def decrypt_token(encrypted_token):
    if not encrypted_token:
        return None
    return cipher.decrypt(encrypted_token).decode()