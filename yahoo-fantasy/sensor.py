import logging
import json
import os
import time
from threading import Lock, RLock

from yahoo_oauth import OAuth2
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

OAUTH_FILE = "/config/oauth.json"
_TOKEN_LOCK = RLock()
_GLOBAL_OAUTH = None
_LAST_TOKEN_REFRESH = 0
_LAST_SESSION_RESET = 0

def find_key(data, key):
    """Recursively find first occurrence of key in nested dict/list."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for v in data.values():
            result = find_key(v, key)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = find_key(item, key)
            if result is not None:
                return result
    return None

CONF_GAME_KEY = "game_key"
CONF_LEAGUE_ID = "league_id"
CONF_TEAM_ID = "team_id"
CONF_MIN_UPDATE_INTERVAL = "min_update_interval"

def get_global_oauth():
    """Get or create the global OAuth instance."""
    global _GLOBAL_OAUTH
    
    with _TOKEN_LOCK:
        if _GLOBAL_OAUTH is None:
            if not os.path.exists(OAUTH_FILE):
                raise FileNotFoundError(f"OAuth file not found: {OAUTH_FILE}")

            with open(OAUTH_FILE, "r") as f:
                creds = json.load(f)

            consumer_key = creds.get("consumer_key")
            consumer_secret = creds.get("consumer_secret")

            if not consumer_key or not consumer_secret:
                raise ValueError("consumer_key and consumer_secret must be in oauth.json")

            _GLOBAL_OAUTH = OAuth2(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                from_file=OAUTH_FILE,
            )
            
        return _GLOBAL_OAUTH

def reset_oauth_session():
    """Reset the OAuth session completely."""
    global _GLOBAL_OAUTH, _LAST_SESSION_RESET
    
    with _TOKEN_LOCK:
        current_time = time.time()
        
        # Prevent too frequent resets
        if current_time - _LAST_SESSION_RESET < 5:
            _LOGGER.debug("Skipping session reset - too recent")
            return
        
        if _GLOBAL_OAUTH:
            try:
                # Close existing session
                if hasattr(_GLOBAL_OAUTH, 'session') and _GLOBAL_OAUTH.session:
                    _GLOBAL_OAUTH.session.close()
                    
                # Clear the session
                _GLOBAL_OAUTH.session = None
                
                # Force new session creation on next request
                _LAST_SESSION_RESET = current_time
                
            except Exception as e:
                _LOGGER.error(f"Error resetting OAuth session: {e}")

def setup_platform(hass, config, add_entities, discovery_info=None):
    game_key = config.get(CONF_GAME_KEY)
    league_id = config.get(CONF_LEAGUE_ID)
    team_id = config.get(CONF_TEAM_ID)
    min_update_interval = config.get(CONF_MIN_UPDATE_INTERVAL, 300)  # Default 5 minutes

    try:
        oauth = get_global_oauth()
    except Exception as e:
        _LOGGER.error(f"Failed to initialize OAuth: {e}")
        raise

    # Create the matchup entity
    entities = [
        YahooFantasyMatchupSensor(oauth, game_key, league_id, team_id, min_update_interval)
    ]
    add_entities(entities, True)

class YahooFantasyMatchupSensor(Entity):
    """Sensor for Yahoo Fantasy matchup data from scoreboard."""
    
    def __init__(self, oauth, game_key, league_id, team_id, min_update_interval=300):
        self._oauth = oauth
        self._game_key = game_key
        self._league_id = league_id
        self._team_id = team_id
        self._state = None
        self._attributes = {}
        self._last_update = 0
        self._min_update_interval = min_update_interval
        self._consecutive_401_errors = 0

    @property
    def name(self):
        return "Yahoo Fantasy Matchup"
        
    @property
    def unique_id(self):
        return f"yahoo_fantasy_matchup_{self._league_id}_{self._team_id}"

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes

    def _should_update(self):
        """Check if enough time has passed to warrant an update."""
        current_time = time.time()
        if current_time - self._last_update < self._min_update_interval:
            _LOGGER.debug(f"Skipping update, last update was {current_time - self._last_update:.1f}s ago")
            return False
        return True

    def _refresh_oauth_if_needed(self, force_refresh=False, after_401=False):
        """Refresh OAuth token if needed or if forced."""
        global _LAST_TOKEN_REFRESH
        
        with _TOKEN_LOCK:
            current_time = time.time()
            
            # If this is after a 401 error, we should always try to refresh
            if after_401:
                force_refresh = True
                # Don't apply the time restriction for 401 errors
            elif force_refresh and (current_time - _LAST_TOKEN_REFRESH) < 30:
                _LOGGER.debug("Skipping token refresh - too recent")
                return True
            
            try:
                if force_refresh or not self._oauth.token_is_valid():
                    # For persistent 401 errors, reset the session
                    if after_401 and self._consecutive_401_errors > 1:
                        reset_oauth_session()
                    
                    self._oauth.refresh_access_token()
                    _LAST_TOKEN_REFRESH = current_time
                    
                    time.sleep(1)
                    
                    # Reset error counter on successful refresh
                    if after_401:
                        self._consecutive_401_errors = 0
                    
                return True
                
            except Exception as e:
                _LOGGER.error(f"Failed to refresh OAuth token: {e}")
                return False

    def _make_api_request(self, url, max_retries=3):
        """Make API request with automatic 401 handling and retries."""
        
        for attempt in range(max_retries):
            try:
                _LOGGER.debug(f"Making API request to: {url} (attempt {attempt + 1})")
                
                # Only do standard refresh on first attempt
                if attempt == 0:
                    if not self._refresh_oauth_if_needed():
                        raise Exception("Failed to ensure valid OAuth token")
                
                response = self._oauth.session.get(url, timeout=30)
                _LOGGER.debug(f"API response status: {response.status_code}")
                
                if response.status_code == 401:
                    self._consecutive_401_errors += 1
                    _LOGGER.warning(f"Got 401 error on attempt {attempt + 1} (consecutive: {self._consecutive_401_errors})")
                    
                    if attempt < max_retries - 1:
                        # Use special after_401 flag to bypass time restrictions
                        if self._refresh_oauth_if_needed(force_refresh=True, after_401=True):
                            # Wait a bit longer after 401 refresh
                            time.sleep(2)
                            continue
                        else:
                            raise Exception("Failed to refresh token after 401 error")
                    else:
                        # On final retry, try complete OAuth reset
                        _LOGGER.warning("Final attempt after 401 errors, attempting complete OAuth reset...")
                        reset_oauth_session()
                        # Recreate the OAuth instance
                        global _GLOBAL_OAUTH
                        _GLOBAL_OAUTH = None
                        self._oauth = get_global_oauth()
                        time.sleep(2)
                        
                        # One final attempt
                        response = self._oauth.session.get(url, timeout=30)
                        if response.status_code == 401:
                            raise Exception("Persistent 401 error - OAuth authorization may be invalid")
                
                # Reset consecutive error counter on success
                if response.status_code != 401:
                    self._consecutive_401_errors = 0
                
                response.raise_for_status()
                return response.json()
                
            except Exception as e:
                if attempt == max_retries - 1:
                    _LOGGER.error(f"API request failed for {url} after {max_retries} attempts: {e}")
                    raise
                else:
                    _LOGGER.warning(f"API request attempt {attempt + 1} failed, retrying: {e}")
                    time.sleep(2 ** attempt)

    def _get_current_week(self):
        """Fetch current week from league data."""
        try:
            league_url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{self._game_key}.l.{self._league_id}?format=json"
            league_data = self._make_api_request(league_url)
            return find_key(league_data, "current_week")
        except Exception as e:
            _LOGGER.error(f"Error fetching current week: {e}")
            return None

    def _get_scoreboard_data(self, week):
        """Get scoreboard data for the specified week."""
        try:
            scoreboard_url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{self._game_key}.l.{self._league_id}/scoreboard;week={week}?format=json"
            return self._make_api_request(scoreboard_url)
        except Exception as e:
            _LOGGER.error(f"Error fetching scoreboard data for week {week}: {e}")
            return None

    def _get_team_roster(self, team_id, week):
        """Get roster data for a specific team and week."""
        try:
            # Try multiple roster API endpoints to find one with lineup data
            urls_to_try = [
                f"https://fantasysports.yahooapis.com/fantasy/v2/team/{self._game_key}.l.{self._league_id}.t.{team_id}/roster;week={week}?format=json",
                f"https://fantasysports.yahooapis.com/fantasy/v2/team/{self._game_key}.l.{self._league_id}.t.{team_id}/roster;week={week}/players?format=json",
                f"https://fantasysports.yahooapis.com/fantasy/v2/team/{self._game_key}.l.{self._league_id}.t.{team_id}/roster/players?format=json"
            ]
            
            for url in urls_to_try:
                try:
                    roster_data = self._make_api_request(url)
                    if roster_data:
                        return roster_data
                except Exception:
                    continue
            
            return None
            
        except Exception as e:
            _LOGGER.error(f"Error in _get_team_roster for team {team_id}, week {week}: {e}")
            return None

    def _extract_roster_data(self, roster_data):
        """Extract player information from roster data."""
        if not roster_data:
            return []

        players = []
        try:
            # Navigate through the response structure to find players
            players_data = find_key(roster_data, "players")
            
            if not players_data:
                return []

            # Process players
            player_items = []
            if isinstance(players_data, dict):
                player_items = [v for k, v in players_data.items() if k != "count"]
            elif isinstance(players_data, list):
                player_items = players_data

            for player_item in player_items:
                player_info = None
                
                if isinstance(player_item, dict):
                    if "player" in player_item:
                        player_info = player_item["player"]
                    else:
                        player_info = player_item
                
                if not player_info:
                    continue

                # Extract basic info
                player_id = find_key(player_info, "player_id")
                
                # Extract name
                name_data = find_key(player_info, "name")
                player_name = "Unknown"
                if isinstance(name_data, dict):
                    player_name = name_data.get("full") or f"{name_data.get('first', '')} {name_data.get('last', '')}".strip()
                elif isinstance(name_data, str):
                    player_name = name_data

                # Extract all the standard fields
                player = {
                    "player_id": player_id,
                    "name": player_name,
                    "position": find_key(player_info, "display_position"),
                    "selected_position": None,
                    "team": find_key(player_info, "editorial_team_abbr"),
                    "is_starting": False,
                    "image_url": find_key(player_info, "image_url"),
                    "uniform_number": find_key(player_info, "uniform_number")
                }

                # Look for selected_position - handle the array structure properly
                selected_pos_raw = find_key(player_info, "selected_position")
                selected_position = None

                if isinstance(selected_pos_raw, list):
                    # Parse the array to find position
                    for item in selected_pos_raw:
                        if isinstance(item, dict) and "position" in item:
                            selected_position = item["position"]
                            break
                elif isinstance(selected_pos_raw, dict):
                    selected_position = selected_pos_raw.get("position")
                elif isinstance(selected_pos_raw, str):
                    selected_position = selected_pos_raw

                player["selected_position"] = selected_position

                # Determine starting status
                if selected_position:
                    bench_positions = ["BN", "BN*", "IR", "DL", "NA", "O"]
                    player["is_starting"] = selected_position not in bench_positions
                else:
                    player["is_starting"] = False

                # Only add if we have basic info
                if player["player_id"] and player["name"]:
                    players.append(player)

        except Exception as e:
            _LOGGER.error(f"Error in _extract_roster_data: {e}")
            
        return players

    def _extract_team_data(self, team_data):
        """Extract team information from team data."""
        if not team_data:
            return {}
            
        team_info = {
            "team_id": find_key(team_data, "team_id"),
            "name": find_key(team_data, "name"),
            "manager": find_key(team_data, "nickname"),
        }
        
        # Extract team logo
        team_logo = find_key(team_data, "team_logo")
        if isinstance(team_logo, dict):
            team_info["logo"] = team_logo.get("url")
        
        # Extract current score from team_points
        team_points = find_key(team_data, "team_points")
        if team_points and isinstance(team_points, dict):
            total = team_points.get("total")
            if total is not None:
                try:
                    team_info["score"] = float(total)
                except (ValueError, TypeError):
                    team_info["score"] = None
        
        # Extract projected score
        projected_points = find_key(team_data, "team_projected_points")
        if projected_points and isinstance(projected_points, dict):
            total = projected_points.get("total")
            if total is not None:
                try:
                    team_info["projected_score"] = float(total)
                except (ValueError, TypeError):
                    team_info["projected_score"] = None
        
        return team_info

    def _find_matchup_data(self, scoreboard_data):
        """Find the matchup containing our team."""
        try:
            # Navigate through the response structure to find matchups
            matchups = find_key(scoreboard_data, "matchups")
            
            if not matchups:
                scoreboard = find_key(scoreboard_data, "scoreboard")
                if scoreboard:
                    matchups = find_key(scoreboard, "matchups")
            
            if not matchups:
                fantasy_content = find_key(scoreboard_data, "fantasy_content")
                if fantasy_content:
                    league_data = find_key(fantasy_content, "league")
                    if league_data and isinstance(league_data, list):
                        for item in league_data:
                            if isinstance(item, dict) and "scoreboard" in item:
                                scoreboard = item["scoreboard"]
                                if isinstance(scoreboard, list):
                                    for sb_item in scoreboard:
                                        if isinstance(sb_item, dict) and "matchups" in sb_item:
                                            matchups = sb_item["matchups"]
                                            break

            if not matchups:
                _LOGGER.warning("No matchups found in scoreboard data")
                return None

            # Process matchups to find ours
            matchup_items = []
            if isinstance(matchups, dict):
                matchup_items = [v for k, v in matchups.items() if k != "count"]
            elif isinstance(matchups, list):
                matchup_items = matchups

            for matchup_item in matchup_items:
                matchup_info = None
                
                if isinstance(matchup_item, dict):
                    if "matchup" in matchup_item:
                        matchup_info = matchup_item["matchup"]
                    else:
                        matchup_info = matchup_item
                
                if not matchup_info:
                    continue

                # Get basic matchup info
                matchup_data = {
                    "week": find_key(matchup_info, "week"),
                    "status": find_key(matchup_info, "status"),
                    "is_tied": find_key(matchup_info, "is_tied"),
                    "winner_team_key": find_key(matchup_info, "winner_team_key")
                }

                teams_data = find_key(matchup_info, "teams")
                if not teams_data:
                    continue

                # Extract teams
                team_list = []
                if isinstance(teams_data, dict):
                    for key, team_data in teams_data.items():
                        if key != "count" and isinstance(team_data, dict):
                            if "team" in team_data:
                                team_list.append(team_data["team"])
                            elif "team_id" in team_data:
                                team_list.append(team_data)
                elif isinstance(teams_data, list):
                    for team_data in teams_data:
                        if isinstance(team_data, dict):
                            if "team" in team_data:
                                team_list.append(team_data["team"])
                            else:
                                team_list.append(team_data)

                if len(team_list) < 2:
                    continue

                # Check if our team is in this matchup
                our_team_found = False
                for team in team_list:
                    team_id = find_key(team, "team_id")
                    if str(team_id) == str(self._team_id):
                        our_team_found = True
                        break
                
                if our_team_found:
                    # Extract both teams' data
                    teams = []
                    for team in team_list:
                        team_info = self._extract_team_data(team)
                        if team_info.get("team_id"):
                            teams.append(team_info)
                    
                    matchup_data["teams"] = teams
                    return matchup_data

        except Exception as e:
            _LOGGER.error(f"Error finding matchup data: {e}")
            
        return None

    def update(self):
        """Fetch the latest matchup data."""
        try:
            if not self._should_update():
                return

            # Get current week
            current_week = self._get_current_week()
            if not current_week:
                self._state = "error"
                self._attributes = {"error": "Could not determine current week"}
                return

            # Get scoreboard data
            scoreboard_data = self._get_scoreboard_data(current_week)
            if not scoreboard_data:
                self._state = "error"
                self._attributes = {"error": "Could not fetch scoreboard data"}
                return

            # Find our matchup
            matchup_data = self._find_matchup_data(scoreboard_data)
            if not matchup_data:
                self._state = "no_matchup"
                self._attributes = {
                    "error": "No matchup found for current week",
                    "week": current_week,
                    "league_id": self._league_id
                }
                return

            # Find our team and opponent
            our_team = None
            opponent_team = None
            
            for team in matchup_data.get("teams", []):
                if str(team.get("team_id")) == str(self._team_id):
                    our_team = team
                else:
                    opponent_team = team

            if not our_team:
                self._state = "error"
                self._attributes = {"error": "Could not find our team in matchup data"}
                return

            # Get roster data for both teams
            our_roster = []
            opponent_roster = []
            
            try:
                our_roster_data = self._get_team_roster(self._team_id, current_week)
                if our_roster_data:
                    our_roster = self._extract_roster_data(our_roster_data)
            except Exception as e:
                _LOGGER.warning(f"Could not fetch our team roster: {e}")

            if opponent_team:
                try:
                    opp_roster_data = self._get_team_roster(opponent_team.get("team_id"), current_week)
                    if opp_roster_data:
                        opponent_roster = self._extract_roster_data(opp_roster_data)
                except Exception as e:
                    _LOGGER.warning(f"Could not fetch opponent roster: {e}")

            # Determine matchup status and winner
            status = matchup_data.get("status", "unknown")
            is_tied = matchup_data.get("is_tied") == "1"
            winner_team_key = matchup_data.get("winner_team_key")
            
            # Set state based on our team's score
            our_score = our_team.get("score")
            self._state = our_score if our_score is not None else "unknown"

            # Build attributes
            self._attributes = {
                "league_id": self._league_id,
                "week": matchup_data.get("week"),
                "status": status,
                "is_tied": is_tied,
                
                # Our team info
                "our_team_id": our_team.get("team_id"),
                "our_team_name": our_team.get("name"),
                "our_manager": our_team.get("manager"),
                "our_score": our_team.get("score"),
                "our_projected_score": our_team.get("projected_score"),
                "our_team_logo": our_team.get("logo"),
                "our_roster": our_roster,
            }
            
            # Add opponent info if available
            if opponent_team:
                self._attributes.update({
                    "opponent_team_id": opponent_team.get("team_id"),
                    "opponent_team_name": opponent_team.get("name"),
                    "opponent_manager": opponent_team.get("manager"),
                    "opponent_score": opponent_team.get("score"),
                    "opponent_projected_score": opponent_team.get("projected_score"),
                    "opponent_team_logo": opponent_team.get("logo"),
                    "opponent_roster": opponent_roster,
                })
                
                # Calculate score differential
                if our_score is not None and opponent_team.get("score") is not None:
                    self._attributes["score_differential"] = our_score - opponent_team.get("score")
            
            # Determine winner info
            if winner_team_key:
                our_team_key = f"{self._game_key}.l.{self._league_id}.t.{self._team_id}"
                if winner_team_key == our_team_key:
                    self._attributes["winner"] = "us"
                elif opponent_team and winner_team_key == f"{self._game_key}.l.{self._league_id}.t.{opponent_team.get('team_id')}":
                    self._attributes["winner"] = "opponent"
                else:
                    self._attributes["winner"] = "unknown"
            elif is_tied:
                self._attributes["winner"] = "tie"
            else:
                self._attributes["winner"] = "tbd"

            # Set entity picture to our team logo
            if our_team.get("logo"):
                self._attributes["entity_picture"] = our_team.get("logo")

            self._last_update = time.time()
            _LOGGER.debug(f"Updated matchup: {our_team.get('name')} ({our_score}) vs {opponent_team.get('name') if opponent_team else 'Unknown'} ({opponent_team.get('score') if opponent_team else 'Unknown'})")

        except Exception as e:
            _LOGGER.error(f"Error updating Yahoo Fantasy matchup sensor: {e}")
            self._state = "error"
            self._attributes = {"error": str(e)}