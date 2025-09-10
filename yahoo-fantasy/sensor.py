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
                    "stats": {}
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
                                
                                # Store all stats by ID
                                if stat_id and value is not None:
                                    player_stats[str(player_id)]["stats"][stat_id] = value
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
                                    player_stats[str(player_id)]["stats"][stat_id] = value

        except Exception as e:
            _LOGGER.error(f"Error extracting player stats: {e}")
        
        return player_stats

    def _extract_roster_data(self, roster_data, player_stats=None):
        """Extract player information from roster data, including stats if provided."""
        if not roster_data:
            return []

        if player_stats is None:
            player_stats = {}

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
                    "stats": {}  # Individual stats
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
                    player["points_total"] = stats_info.get("points_total", 0.0)
                    player["stats"] = stats_info.get("stats", {})

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

            # Now extract roster data with stats included
            our_roster = []
            opponent_roster = []
            
            if our_roster_data:
                our_roster = self._extract_roster_data(our_roster_data, player_stats)
            
            if opp_roster_data:
                opponent_roster = self._extract_roster_data(opp_roster_data, player_stats)

            # Calculate team totals from player points (as backup/validation)
            our_calculated_score = sum(p.get("points_total", 0) for p in our_roster if p.get("is_starting"))
            opponent_calculated_score = sum(p.get("points_total", 0) for p in opponent_roster if p.get("is_starting")) if opponent_roster else 0

            # Determine matchup status and winner
            status = matchup_data.get("status", "unknown")
            is_tied = matchup_data.get("is_tied") == "1"
            winner_team_key = matchup_data.get("winner_team_key")
            
            # Set state based on our team's score (prefer official score, fall back to calculated)
            our_score = our_team.get("score")
            if our_score is None and our_calculated_score > 0:
                our_score = our_calculated_score
            
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
                "our_calculated_score": our_calculated_score,  # From individual player points
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
            })
            
            if opponent_roster:
                opp_starters = [p for p in opponent_roster if p.get("is_starting")]
                opp_bench = [p for p in opponent_roster if not p.get("is_starting")]
                
                self._attributes.update({
                    "opponent_starters_count": len(opp_starters),
                    "opponent_bench_count": len(opp_bench),
                    "opponent_starters_points": sum(p.get("points_total", 0) for p in opp_starters),
                    "opponent_bench_points": sum(p.get("points_total", 0) for p in opp_bench),
                })

            # Set entity picture to our team logo
            if our_team.get("logo"):
                self._attributes["entity_picture"] = our_team.get("logo")

            self._last_update = time.time()
            
            # Enhanced logging with player points info
            our_points_info = f"{our_score}"
            if our_calculated_score != our_score:
                our_points_info += f" (calculated: {our_calculated_score:.2f})"
                
            opp_points_info = "Unknown"
            if opponent_team:
                opp_points_info = f"{opponent_team.get('score', 'Unknown')}"
                if opponent_calculated_score != opponent_team.get('score'):
                    opp_points_info += f" (calculated: {opponent_calculated_score:.2f})"
            
            _LOGGER.debug(f"Updated matchup with player scoring: {our_team.get('name')} ({our_points_info}) vs {opponent_team.get('name') if opponent_team else 'Unknown'} ({opp_points_info})")

        except Exception as e:
            _LOGGER.error(f"Error updating Yahoo Fantasy matchup sensor: {e}")
            self._state = "error"
            self._attributes = {"error": str(e)}