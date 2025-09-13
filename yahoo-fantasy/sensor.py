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

# Global cache for stat categories and league settings
_STAT_CATEGORIES_CACHE = {}
_LEAGUE_SETTINGS_CACHE = {}
_STAT_CACHE_LOCK = Lock()
_SETTINGS_CACHE_LOCK = Lock()

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

    def _get_league_settings(self, game_key, league_id):
        """Fetch and cache league settings including scoring configuration."""
        global _LEAGUE_SETTINGS_CACHE
        
        league_key = f"{game_key}.l.{league_id}"
        
        with _SETTINGS_CACHE_LOCK:
            # Check if we already have cached settings for this league
            if league_key in _LEAGUE_SETTINGS_CACHE:
                return _LEAGUE_SETTINGS_CACHE[league_key]
            
            try:
                settings_url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_key}/settings?format=json"
                settings_data = self._make_api_request(settings_url)
                
                if not settings_data:
                    _LOGGER.warning(f"No league settings data returned for league {league_key}")
                    return {}
                
                # Extract league settings from response
                league_settings = {
                    "scoring_type": None,
                    "roster_positions": [],
                    "stat_categories": {},
                    "stat_modifiers": {},
                    "league_info": {}
                }
                
                # Navigate through the response structure
                league_data = find_key(settings_data, "league")
                if not league_data:
                    _LOGGER.warning("No league data found in settings response")
                    return {}
                
                # Extract basic league info
                league_settings["league_info"] = {
                    "name": find_key(league_data, "name"),
                    "scoring_type": find_key(league_data, "scoring_type"),
                    "num_teams": find_key(league_data, "num_teams"),
                    "current_week": find_key(league_data, "current_week"),
                    "start_week": find_key(league_data, "start_week"),
                    "end_week": find_key(league_data, "end_week"),
                    "is_finished": find_key(league_data, "is_finished") == "1"
                }
                
                # Extract settings section
                settings_section = find_key(league_data, "settings")
                if not settings_section:
                    _LOGGER.warning("No settings section found in league data")
                    return league_settings
                
                # Extract roster positions
                roster_positions = find_key(settings_section, "roster_positions")
                if roster_positions:
                    positions_list = []
                    
                    # Handle different response formats
                    if isinstance(roster_positions, dict) and "roster_position" in roster_positions:
                        roster_pos_data = roster_positions["roster_position"]
                        if isinstance(roster_pos_data, list):
                            positions_list = roster_pos_data
                        elif isinstance(roster_pos_data, dict):
                            positions_list = [roster_pos_data]
                    
                    # Process each position
                    for pos_item in positions_list:
                        if isinstance(pos_item, dict):
                            position = pos_item.get("position")
                            count = pos_item.get("count")
                            if position and count:
                                try:
                                    league_settings["roster_positions"].append({
                                        "position": position,
                                        "count": int(count)
                                    })
                                except (ValueError, TypeError):
                                    pass
                
                # Extract stat categories (for reference)
                stat_categories = find_key(settings_section, "stat_categories")
                if stat_categories:
                    stats_data = find_key(stat_categories, "stats")
                    if stats_data:
                        # Handle different response formats
                        stat_items = []
                        if isinstance(stats_data, dict) and "stat" in stats_data:
                            stat_list = stats_data["stat"]
                            if isinstance(stat_list, list):
                                stat_items = stat_list
                            elif isinstance(stat_list, dict):
                                stat_items = [stat_list]
                        elif isinstance(stats_data, list):
                            stat_items = stats_data
                        
                        # Process each stat category
                        for stat_item in stat_items:
                            if isinstance(stat_item, dict):
                                stat_id = stat_item.get("stat_id")
                                name = stat_item.get("name")
                                display_name = stat_item.get("display_name")
                                enabled = stat_item.get("enabled") == "1"
                                
                                if stat_id and name:
                                    league_settings["stat_categories"][str(stat_id)] = {
                                        "name": name,
                                        "display_name": display_name,
                                        "enabled": enabled,
                                        "sort_order": stat_item.get("sort_order"),
                                        "position_type": stat_item.get("position_type"),
                                        "is_only_display_stat": stat_item.get("is_only_display_stat") == "1"
                                    }
                
                # Extract stat modifiers (scoring values)
                stat_modifiers = find_key(settings_section, "stat_modifiers")
                if stat_modifiers:
                    _LOGGER.debug(f"Found stat_modifiers section: {type(stat_modifiers)}")
                    stats_data = find_key(stat_modifiers, "stats")
                    if stats_data:
                        _LOGGER.debug(f"Found stats data in modifiers: {type(stats_data)}")
                        # Handle different response formats
                        stat_items = []
                        if isinstance(stats_data, list):
                            # stats_data is already the list of stat items
                            stat_items = stats_data
                        elif isinstance(stats_data, dict):
                            if "stat" in stats_data:
                                stat_list = stats_data["stat"]
                                if isinstance(stat_list, list):
                                    stat_items = stat_list
                                elif isinstance(stat_list, dict):
                                    stat_items = [stat_list]
                            else:
                                # Sometimes the stats are directly in the stats dict
                                stat_items = [v for k, v in stats_data.items() if k != "count" and isinstance(v, dict)]
                        
                        _LOGGER.debug(f"Processing {len(stat_items)} stat modifier items")
                        
                        # Process each stat modifier
                        for i, stat_item in enumerate(stat_items):
                            _LOGGER.debug(f"Stat modifier {i}: {stat_item}")
                            if isinstance(stat_item, dict):
                                # Handle nested structure - stat_id and value are inside 'stat' key
                                stat_info = stat_item.get("stat", stat_item)
                                
                                if isinstance(stat_info, dict):
                                    stat_id = stat_info.get("stat_id")
                                    value = stat_info.get("value")
                                    
                                    _LOGGER.debug(f"Stat modifier {i}: stat_id={stat_id}, value={value}, keys={list(stat_info.keys())}")
                                    
                                    if stat_id and value is not None:
                                        try:
                                            league_settings["stat_modifiers"][str(stat_id)] = float(value)
                                            _LOGGER.debug(f"Successfully added stat_id {stat_id} with value {value}")
                                        except (ValueError, TypeError) as e:
                                            _LOGGER.warning(f"Failed to convert value {value} for stat_id {stat_id}: {e}")
                                            league_settings["stat_modifiers"][str(stat_id)] = value
                                    else:
                                        _LOGGER.warning(f"Missing stat_id or value in item {i}: stat_id={stat_id}, value={value}")
                                else:
                                    _LOGGER.warning(f"stat_info is not a dict for item {i}: {type(stat_info)} - {stat_info}")
                            else:
                                _LOGGER.warning(f"Stat item {i} is not a dict: {type(stat_item)} - {stat_item}")
                
                # Cache the results
                _LEAGUE_SETTINGS_CACHE[league_key] = league_settings
                _LOGGER.info(f"Cached league settings for {league_key}: {len(league_settings['roster_positions'])} roster positions, {len(league_settings['stat_modifiers'])} scoring rules")
                
                return league_settings
                
            except Exception as e:
                _LOGGER.error(f"Error fetching league settings for {league_key}: {e}")
                return {}

    def _get_stat_categories(self, game_key):
        """Fetch and cache stat categories for a game."""
        global _STAT_CATEGORIES_CACHE
        
        with _STAT_CACHE_LOCK:
            # Check if we already have cached stat categories for this game
            if game_key in _STAT_CATEGORIES_CACHE:
                return _STAT_CATEGORIES_CACHE[game_key]
            
            try:
                stat_url = f"https://fantasysports.yahooapis.com/fantasy/v2/game/{game_key}/stat_categories?format=json"
                stat_data = self._make_api_request(stat_url)
                
                if not stat_data:
                    _LOGGER.warning(f"No stat categories data returned for game {game_key}")
                    return {}
                
                # Extract stat categories from response
                stat_categories = {}
                
                # Navigate through the response structure
                stats_data = find_key(stat_data, "stat_categories")
                if not stats_data:
                    _LOGGER.warning("No stat_categories found in response")
                    return {}
                
                # Handle different response formats
                stat_items = []
                if isinstance(stats_data, dict):
                    if "stats" in stats_data:
                        stats_list = stats_data["stats"]
                        if isinstance(stats_list, dict):
                            stat_items = [v for k, v in stats_list.items() if k != "count"]
                        elif isinstance(stats_list, list):
                            stat_items = stats_list
                    else:
                        # Sometimes the stats are directly in the stat_categories
                        stat_items = [v for k, v in stats_data.items() if k != "count"]
                elif isinstance(stats_data, list):
                    stat_items = stats_data
                
                # Process each stat category
                for stat_item in stat_items:
                    if isinstance(stat_item, dict):
                        stat_info = stat_item.get("stat", stat_item)
                        if isinstance(stat_info, dict):
                            stat_id = stat_info.get("stat_id")
                            name = stat_info.get("name") or stat_info.get("display_name")
                            abbr = stat_info.get("abbr")
                            
                            if stat_id and name:
                                stat_categories[str(stat_id)] = {
                                    "name": name,
                                    "abbr": abbr,
                                    "display_name": abbr if abbr else name
                                }
                
                # Cache the results
                _STAT_CATEGORIES_CACHE[game_key] = stat_categories
                _LOGGER.info(f"Cached {len(stat_categories)} stat categories for game {game_key}")
                
                return stat_categories
                
            except Exception as e:
                _LOGGER.error(f"Error fetching stat categories for game {game_key}: {e}")
                return {}

    def _calculate_projected_points(self, player_stats, stat_modifiers):
        """Calculate projected points for a player based on their stats and league scoring."""
        if not player_stats or not stat_modifiers:
            return 0.0
        
        projected_points = 0.0
        
        try:
            # Get the player's stats by ID
            stats_by_id = player_stats.get("stats_by_id", {})
            
            # Calculate points for each stat
            for stat_id, stat_value in stats_by_id.items():
                if stat_id in stat_modifiers:
                    modifier = stat_modifiers[stat_id]
                    try:
                        stat_val = float(stat_value)
                        mod_val = float(modifier)
                        points = stat_val * mod_val
                        projected_points += points
                    except (ValueError, TypeError):
                        continue
            
        except Exception as e:
            _LOGGER.debug(f"Error calculating projected points: {e}")
        
        return round(projected_points, 2)

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

    def _get_player_stats(self, player_ids, week):
        """Get player stats for multiple players in a single API call."""
        if not player_ids:
            return {}
        
        try:
            # Build the players query string for batch request
            # Yahoo API allows requesting multiple players in one call
            player_keys = [f"{self._game_key}.p.{pid}" for pid in player_ids]
            
            # Batch request for up to 25 players at a time (Yahoo API limit)
            all_stats = {}
            batch_size = 25
            
            for i in range(0, len(player_keys), batch_size):
                batch = player_keys[i:i + batch_size]
                players_query = ",".join(batch)
                
                # Request player stats for the specific week
                stats_url = f"https://fantasysports.yahooapis.com/fantasy/v2/players;player_keys={players_query}/stats;type=week;week={week}?format=json"
                
                try:
                    stats_data = self._make_api_request(stats_url)
                    if stats_data:
                        batch_stats = self._extract_player_stats(stats_data)
                        all_stats.update(batch_stats)
                except Exception as e:
                    _LOGGER.warning(f"Failed to fetch stats for batch starting at index {i}: {e}")
                    continue
                
                # Small delay between batch requests to be respectful
                if i + batch_size < len(player_keys):
                    time.sleep(0.5)
            
            return all_stats
            
        except Exception as e:
            _LOGGER.error(f"Error in _get_player_stats: {e}")
            return {}

    def _extract_player_stats(self, stats_data):
        """Extract player statistics from the API response."""
        player_stats = {}
        
        try:
            # Navigate through the response to find players
            players_data = find_key(stats_data, "players")
            
            if not players_data:
                return player_stats

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

                # Extract player ID
                player_id = find_key(player_info, "player_id")
                if not player_id:
                    continue

                # Extract stats
                stats = find_key(player_info, "player_stats")
                if not stats:
                    continue

                # Look for stats data
                stats_data_list = find_key(stats, "stats")
                if not stats_data_list:
                    continue

                # Initialize player stats
                player_stats[str(player_id)] = {
                    "points_total": 0.0,
                    "stats": {},
                    "stats_by_id": {}  # Keep original stat_id mapping as backup
                }

                # Process stats - can be in different formats
                if isinstance(stats_data_list, list):
                    for stat_item in stats_data_list:
                        if isinstance(stat_item, dict):
                            stat_info = stat_item.get("stat", stat_item)
                            if isinstance(stat_info, dict):
                                stat_id = stat_info.get("stat_id")
                                value = stat_info.get("value")
                                
                                # Yahoo often includes the total points as stat_id 0
                                if stat_id == "0" and value is not None:
                                    try:
                                        player_stats[str(player_id)]["points_total"] = float(value)
                                    except (ValueError, TypeError):
                                        pass
                                
                                # Store stats by ID (original format)
                                if stat_id and value is not None:
                                    player_stats[str(player_id)]["stats_by_id"][stat_id] = value
                elif isinstance(stats_data_list, dict):
                    # Sometimes stats come as a dict
                    for key, stat_item in stats_data_list.items():
                        if key != "count" and isinstance(stat_item, dict):
                            stat_info = stat_item.get("stat", stat_item)
                            if isinstance(stat_info, dict):
                                stat_id = stat_info.get("stat_id")
                                value = stat_info.get("value")
                                
                                if stat_id == "0" and value is not None:
                                    try:
                                        player_stats[str(player_id)]["points_total"] = float(value)
                                    except (ValueError, TypeError):
                                        pass
                                
                                if stat_id and value is not None:
                                    player_stats[str(player_id)]["stats_by_id"][stat_id] = value

        except Exception as e:
            _LOGGER.error(f"Error extracting player stats: {e}")
        
        return player_stats

    def _convert_stats_with_names(self, stats_by_id, stat_categories):
        """Convert stat IDs to human-readable names using stat categories."""
        named_stats = {}
        
        for stat_id, value in stats_by_id.items():
            if stat_id in stat_categories:
                stat_info = stat_categories[stat_id]
                # Use abbreviation if available, otherwise use full name
                display_name = stat_info.get("abbr") or stat_info.get("name")
                named_stats[display_name] = {
                    "value": value,
                    "stat_id": stat_id,
                    "full_name": stat_info.get("name")
                }
            else:
                # Fallback for unknown stat IDs
                named_stats[f"Stat_{stat_id}"] = {
                    "value": value,
                    "stat_id": stat_id,
                    "full_name": f"Unknown Stat {stat_id}"
                }
        
        return named_stats

    def _extract_roster_data(self, roster_data, player_stats=None, stat_categories=None, stat_modifiers=None):
        """Extract player information from roster data, including stats if provided."""
        if not roster_data:
            return []

        if player_stats is None:
            player_stats = {}
        
        if stat_categories is None:
            stat_categories = {}
            
        if stat_modifiers is None:
            stat_modifiers = {}

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
                    "uniform_number": find_key(player_info, "uniform_number"),
                    "points_total": 0.0,  # Default to 0
                    "calculated_points": 0.0,  # NEW: Points calculated from league scoring
                    "stats": {},  # Named stats (new format)
                    "stats_by_id": {}  # Original stat ID format (for compatibility)
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

                # Add player stats if available
                if player_id and str(player_id) in player_stats:
                    stats_info = player_stats[str(player_id)]
                    
                    # Calculate points using league scoring if available
                    if stat_modifiers and stats_info.get("stats_by_id"):
                        calculated_points = self._calculate_projected_points(stats_info, stat_modifiers)
                        player["points_total"] = calculated_points  # Use calculated points as primary
                        player["yahoo_points"] = stats_info.get("points_total", 0.0)  # Keep Yahoo's points as reference
                    else:
                        # Fallback to Yahoo's points if we can't calculate
                        player["points_total"] = stats_info.get("points_total", 0.0)
                        player["yahoo_points"] = stats_info.get("points_total", 0.0)
                    
                    player["stats_by_id"] = stats_info.get("stats_by_id", {})
                    
                    # Convert stats to named format if stat categories are available
                    if stat_categories and player["stats_by_id"]:
                        player["stats"] = self._convert_stats_with_names(
                            player["stats_by_id"], 
                            stat_categories
                        )
                    else:
                        # Fallback to numbered stats
                        player["stats"] = {f"Stat_{k}": {"value": v, "stat_id": k} 
                                        for k, v in player["stats_by_id"].items()}

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

            # Get league settings (includes scoring) - cached after first call
            league_settings = self._get_league_settings(self._game_key, self._league_id)
            stat_modifiers = league_settings.get("stat_modifiers", {})
            _LOGGER.debug(f"Loaded league settings with {len(stat_modifiers)} scoring rules")

            # Get stat categories for this game (cached after first call)
            stat_categories = self._get_stat_categories(self._game_key)
            _LOGGER.debug(f"Loaded {len(stat_categories)} stat categories for game {self._game_key}")

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

            # Get roster data for both teams (without stats first)
            our_roster_data = None
            opp_roster_data = None
            
            try:
                our_roster_data = self._get_team_roster(self._team_id, current_week)
            except Exception as e:
                _LOGGER.warning(f"Could not fetch our team roster: {e}")

            if opponent_team:
                try:
                    opp_roster_data = self._get_team_roster(opponent_team.get("team_id"), current_week)
                except Exception as e:
                    _LOGGER.warning(f"Could not fetch opponent roster: {e}")

            # Collect all player IDs for batch stats request
            all_player_ids = []
            
            if our_roster_data:
                our_roster_temp = self._extract_roster_data(our_roster_data)
                all_player_ids.extend([p["player_id"] for p in our_roster_temp if p.get("player_id")])
            
            if opp_roster_data:
                opp_roster_temp = self._extract_roster_data(opp_roster_data)
                all_player_ids.extend([p["player_id"] for p in opp_roster_temp if p.get("player_id")])

            # Get player stats for all players in batch
            player_stats = {}
            if all_player_ids:
                try:
                    player_stats = self._get_player_stats(all_player_ids, current_week)
                    _LOGGER.debug(f"Retrieved stats for {len(player_stats)} players")
                except Exception as e:
                    _LOGGER.warning(f"Could not fetch player stats: {e}")

            # Now extract roster data with stats, stat categories, and scoring included
            our_roster = []
            opponent_roster = []
            
            if our_roster_data:
                our_roster = self._extract_roster_data(our_roster_data, player_stats, stat_categories, stat_modifiers)
            
            if opp_roster_data:
                opponent_roster = self._extract_roster_data(opp_roster_data, player_stats, stat_categories, stat_modifiers)

            # Calculate team totals from player points (as backup/validation)
            our_calculated_score = sum(p.get("points_total", 0) for p in our_roster if p.get("is_starting"))
            opponent_calculated_score = sum(p.get("points_total", 0) for p in opponent_roster if p.get("is_starting")) if opponent_roster else 0

            # Calculate scores using league scoring rules
            our_scoring_calculated = sum(p.get("calculated_points", 0) for p in our_roster if p.get("is_starting"))
            opponent_scoring_calculated = sum(p.get("calculated_points", 0) for p in opponent_roster if p.get("is_starting")) if opponent_roster else 0

            # Determine matchup status and winner
            status = matchup_data.get("status", "unknown")
            is_tied = matchup_data.get("is_tied") == "1"
            winner_team_key = matchup_data.get("winner_team_key")
            
            # Set state based on our team's score (prefer official score, fall back to calculated)
            our_score = our_team.get("score")
            if our_score is None and our_calculated_score > 0:
                our_score = our_calculated_score
            
            self._state = our_score if our_score is not None else "unknown"

            # Build attributes with enhanced scoring information
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
                "our_calculated_score": our_calculated_score,  # From individual player points
                "our_scoring_calculated": our_scoring_calculated,  # NEW: Using league scoring rules
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
                    "opponent_calculated_score": opponent_calculated_score,  # From individual player points
                    "opponent_scoring_calculated": opponent_scoring_calculated,  # NEW: Using league scoring rules
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

            # Add some summary stats for easy access
            our_starters = [p for p in our_roster if p.get("is_starting")]
            our_bench = [p for p in our_roster if not p.get("is_starting")]
            
            self._attributes.update({
                "our_starters_count": len(our_starters),
                "our_bench_count": len(our_bench),
                "our_starters_points": sum(p.get("points_total", 0) for p in our_starters),
                "our_bench_points": sum(p.get("points_total", 0) for p in our_bench),
                "our_starters_scoring_points": sum(p.get("calculated_points", 0) for p in our_starters),  # NEW
                "our_bench_scoring_points": sum(p.get("calculated_points", 0) for p in our_bench),  # NEW
            })
            
            if opponent_roster:
                opp_starters = [p for p in opponent_roster if p.get("is_starting")]
                opp_bench = [p for p in opponent_roster if not p.get("is_starting")]
                
                self._attributes.update({
                    "opponent_starters_count": len(opp_starters),
                    "opponent_bench_count": len(opp_bench),
                    "opponent_starters_points": sum(p.get("points_total", 0) for p in opp_starters),
                    "opponent_bench_points": sum(p.get("points_total", 0) for p in opp_bench),
                    "opponent_starters_scoring_points": sum(p.get("calculated_points", 0) for p in opp_starters),  # NEW
                    "opponent_bench_scoring_points": sum(p.get("calculated_points", 0) for p in opp_bench),  # NEW
                })

            # Add league settings info to attributes for reference
            if league_settings:
                self._attributes["league_settings"] = {
                    "league_info": league_settings.get("league_info", {}),
                    "roster_positions": league_settings.get("roster_positions", []),
                    "scoring_rules": {
                        stat_id: {
                            "modifier": modifier,
                            "stat_name": league_settings.get("stat_categories", {}).get(stat_id, {}).get("name", f"Stat {stat_id}"),
                            "display_name": league_settings.get("stat_categories", {}).get(stat_id, {}).get("display_name", f"Stat {stat_id}")
                        }
                        for stat_id, modifier in stat_modifiers.items()
                    }
                }

            # Add stat categories info to attributes for reference
            if stat_categories:
                self._attributes["available_stat_categories"] = {
                    stat_id: {
                        "name": info["name"],
                        "abbr": info.get("abbr"),
                        "display_name": info.get("display_name")
                    }
                    for stat_id, info in stat_categories.items()
                }

            # Set entity picture to our team logo
            if our_team.get("logo"):
                self._attributes["entity_picture"] = our_team.get("logo")

            self._last_update = time.time()
            
            # Enhanced logging with scoring information
            our_points_info = f"{our_score}"
            if our_calculated_score != our_score:
                our_points_info += f" (calculated: {our_calculated_score:.2f})"
            if our_scoring_calculated != our_score:
                our_points_info += f" (league scoring: {our_scoring_calculated:.2f})"
                
            opp_points_info = "Unknown"
            if opponent_team:
                opp_points_info = f"{opponent_team.get('score', 'Unknown')}"
                if opponent_calculated_score != opponent_team.get('score'):
                    opp_points_info += f" (calculated: {opponent_calculated_score:.2f})"
                if opponent_scoring_calculated != opponent_team.get('score'):
                    opp_points_info += f" (league scoring: {opponent_scoring_calculated:.2f})"
            
            _LOGGER.info(f"Updated matchup with league scoring: {our_team.get('name')} ({our_points_info}) vs {opponent_team.get('name') if opponent_team else 'Unknown'} ({opp_points_info}). Scoring rules: {len(stat_modifiers)}")

        except Exception as e:
            _LOGGER.error(f"Error updating Yahoo Fantasy matchup sensor: {e}")
            self._state = "error"
            self._attributes = {"error": str(e)}