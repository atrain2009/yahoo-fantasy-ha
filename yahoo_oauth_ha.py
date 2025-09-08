from yahoo_oauth import OAuth2
import os
import json
import shutil

# Replace these with your app's credentials
CONSUMER_KEY = "YOUR_YAHOO_APP_CONSUMER_KEY"
CONSUMER_SECRET = "YOUR_YAHOO_APP_CONSUMER_SECRET"

# Where you want the oauth.json file to be saved
OAUTH_FILE = r"YOUR_PATH_TO_OAUTH_FILE_LOCATION"

print("Setting up Yahoo OAuth for Fantasy Sports...")
print("IMPORTANT: Make sure your Yahoo app is set to 'Installed Application' with EMPTY redirect URI!")

# Clean up any existing files
for file_path in [OAUTH_FILE]:
    if os.path.exists(file_path):
        os.remove(file_path)
        print(f"Removed existing file: {file_path}")

# Create initial oauth.json file with credentials
initial_oauth_data = {
    "consumer_key": CONSUMER_KEY,
    "consumer_secret": CONSUMER_SECRET
}

try:
    with open(OAUTH_FILE, 'w') as f:
        json.dump(initial_oauth_data, f, indent=2)
    print(f"Created initial oauth.json at: {OAUTH_FILE}")
    
    # Verify file was created
    if os.path.exists(OAUTH_FILE):
        print("✅ File creation confirmed")
    else:
        print("❌ File creation failed!")
        exit(1)
        
except Exception as e:
    print(f"❌ Error creating oauth.json: {e}")
    exit(1)

# Initialize OAuth2 - now the file exists
try:
    oauth = OAuth2(
        consumer_key=CONSUMER_KEY,
        consumer_secret=CONSUMER_SECRET,
        from_file=OAUTH_FILE
    )
    print("✅ OAuth2 object created successfully")
except Exception as e:
    print(f"❌ Error creating OAuth2 object: {e}")
    print(f"File exists: {os.path.exists(OAUTH_FILE)}")
    if os.path.exists(OAUTH_FILE):
        with open(OAUTH_FILE, 'r') as f:
            print(f"File contents: {f.read()}")
    exit(1)
print("\nStarting OAuth authorization flow...")
print("1. Click 'Agree' to authorize your app")
print("2. You'll see a verification code or be redirected")
print("3. Copy the code/URL when prompted")

# Force the authorization flow
try:
    # This will handle the full OAuth flow
    if not oauth.token_is_valid():
        oauth.refresh_access_token()
    
    print("\n✅ OAuth authorization successful!")
    
except Exception as e:
    print(f"\n❌ OAuth authorization failed: {e}")
    print("Make sure:")
    print("1. Your Yahoo app is 'Installed Application' type")
    print("2. Redirect URI is EMPTY")
    print("3. Fantasy Sports permission is enabled")
    exit(1)

# Now ensure the file has the correct format with credentials
try:
    # Read the current file (might be oauth.json or secrets.json)
    oauth_data = {}
    
    # Check for secrets.json first (common yahoo_oauth behavior)
    secrets_file = r"C:\Users\skorp\Downloads\secrets.json"
    source_file = None
    
    if os.path.exists(secrets_file):
        source_file = secrets_file
    elif os.path.exists(OAUTH_FILE):
        source_file = OAUTH_FILE
    
    if source_file:
        with open(source_file, 'r') as f:
            oauth_data = json.load(f)
        print(f"Read OAuth data from: {source_file}")
    
    # Ensure credentials are included
    final_data = {
        "consumer_key": CONSUMER_KEY,
        "consumer_secret": CONSUMER_SECRET
    }
    
    # Add all other fields (tokens, etc.)
    for key, value in oauth_data.items():
        if key not in ["consumer_key", "consumer_secret"]:
            final_data[key] = value
    
    # Write to oauth.json with proper format
    with open(OAUTH_FILE, 'w') as f:
        json.dump(final_data, f, indent=2)
    
    # Clean up secrets.json if it exists
    if source_file == secrets_file:
        os.remove(secrets_file)
        print("Renamed secrets.json to oauth.json")
    
    print(f"✅ Created properly formatted oauth.json")
    
except Exception as e:
    print(f"❌ Error formatting oauth.json: {e}")
    exit(1)

# Test the token by making a simple API call
try:
    print("\nTesting API access...")
    response = oauth.session.get('https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games?format=json')
    print(f"API Response Status: {response.status_code}")
    
    if response.status_code == 200:
        print("✅ API test successful!")
        
        # Show available games
        games_data = response.json()
        print(f"Response data keys: {list(games_data.keys())}")
        
        print("\nAvailable fantasy games:")
        if 'fantasy_content' in games_data:
            users = games_data['fantasy_content'].get('users', {})
            if '0' in users and 'user' in users['0']:
                user_games = users['0']['user'][1].get('games', {})
                if 'count' in user_games:
                    game_count = int(user_games['count'])
                    print(f"Found {game_count} games:")
                    for i in range(game_count):
                        game_data = user_games.get(str(i), {})
                        if 'game' in game_data:
                            game = game_data['game']
                            if isinstance(game, list) and len(game) >= 1:
                                game_info = game[0]
                                print(f"  - {game_info.get('name', 'Unknown')} (Key: {game_info.get('game_key', 'N/A')})")
                            elif isinstance(game, dict):
                                print(f"  - {game.get('name', 'Unknown')} (Key: {game.get('game_key', 'N/A')})")
                        else:
                            print(f"  - Game {i}: No game data found")
                else:
                    print("  No games found or no count field")
                    print(f"  User games structure: {user_games}")
            else:
                print("  User data structure not as expected")
                print(f"  Users keys: {list(users.keys()) if users else 'No users'}")
        else:
            print("  No fantasy_content in response")
            print(f"  Full response: {games_data}")
    else:
        print(f"❌ API test failed with status: {response.status_code}")
        print(f"Response: {response.text}")
        print("This indicates your OAuth setup is incorrect.")
        exit(1)
        
except Exception as e:
    print(f"❌ API test failed: {e}")
    print("This indicates your OAuth setup is incorrect.")
    exit(1)

# Show final file contents (masked for security)
if os.path.exists(OAUTH_FILE):
    print(f"\nFinal oauth.json structure:")
    with open(OAUTH_FILE, 'r') as f:
        data = json.load(f)
        # Show structure but hide sensitive values
        display_data = {}
        for key, value in data.items():
            if key in ["consumer_key", "consumer_secret", "access_token", "refresh_token"]:
                display_data[key] = f"***{str(value)[-4:]}" if value else "⚠ MISSING!"
            else:
                display_data[key] = value
        print(json.dumps(display_data, indent=2))
    
    # Verify all required fields are present
    required_fields = ["consumer_key", "consumer_secret", "access_token", "refresh_token"]
    missing_fields = []
    
    with open(OAUTH_FILE, 'r') as f:
        final_data = json.load(f)
        for field in required_fields:
            if field not in final_data or not final_data.get(field):
                missing_fields.append(field)
    
    if missing_fields:
        print(f"\n⚠ CRITICAL: Missing required fields: {missing_fields}")
        print("OAuth setup is incomplete!")
        exit(1)
    else:
        print(f"\n✅ All required fields present in oauth.json")

print(f"\n🎉 Setup complete!")
print(f"📁 Copy this file to your Home Assistant: {OAUTH_FILE}")
print("\n⚠️  IMPORTANT: Restart Home Assistant after copying the file!")