class YahooFantasyMatchupCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('You need to define an entity');
    }
    this.config = config;
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  getPositionOrder(position) {
    const order = {
      'QB': 1, 'RB': 2, 'RB1': 2, 'RB2': 2,
      'WR': 3, 'WR1': 3, 'WR2': 3, 'WR3': 3,
      'TE': 4, 'FLEX': 5, 'W/R/T': 5, 'W/R': 5, 'R/W/T': 5,
      'K': 6, 'DEF': 7, 'D/ST': 7
    };
    return order[position] || 999;
  }

  renderPlayer(player, isOur = true) {
    const playerImg = player.image_url && !player.image_url.includes('blank_player') 
      ? `<img src="${player.image_url}" alt="${player.name}" loading="lazy">` 
      : '<div class="player-placeholder">👤</div>';
    
    return `
      <div class="player ${isOur ? 'our-player' : 'opp-player'}">
        <div class="player-image">
          ${playerImg}
        </div>
        <div class="player-info">
          <div class="player-name">${player.name || 'Unknown'}</div>
          <div class="player-details">
            <span class="player-team">${player.team || ''}</span>
            ${player.uniform_number ? `<span class="player-number">#${player.uniform_number}</span>` : ''}
          </div>
        </div>
      </div>
    `;
  }

  render() {
    if (!this._hass || !this.config.entity) return;

    const entity = this._hass.states[this.config.entity];
    if (!entity) {
      this.shadowRoot.innerHTML = `
        <div style="padding: 16px; color: red;">
          Entity ${this.config.entity} not found
        </div>
      `;
      return;
    }

    const attrs = entity.attributes;
    const ourScore = attrs.our_score || 0;
    const oppScore = attrs.opponent_score || 0;
    const ourProjected = attrs.our_projected_score || 0;
    const oppProjected = attrs.opponent_projected_score || 0;
    const week = attrs.week || '?';
    const status = attrs.status || 'unknown';
    const winner = attrs.winner || 'tbd';

    // Filter starting lineups from roster data
    const ourRoster = attrs.our_roster || [];
    const oppRoster = attrs.opponent_roster || [];
    
    const ourStarters = ourRoster
      .filter(player => player.is_starting)
      .sort((a, b) => this.getPositionOrder(a.selected_position) - this.getPositionOrder(b.selected_position));
    
    const oppStarters = oppRoster
      .filter(player => player.is_starting)
      .sort((a, b) => this.getPositionOrder(a.selected_position) - this.getPositionOrder(b.selected_position));

    // Determine colors based on winner
    let ourTeamClass = 'team-neutral';
    let oppTeamClass = 'team-neutral';
    
    if (winner === 'us') {
      ourTeamClass = 'team-winner';
      oppTeamClass = 'team-loser';
    } else if (winner === 'opponent') {
      ourTeamClass = 'team-loser';
      oppTeamClass = 'team-winner';
    } else if (winner === 'tie') {
      ourTeamClass = 'team-tie';
      oppTeamClass = 'team-tie';
    }

    // Get team logos
    const ourLogo = attrs.our_team_logo || '';
    const oppLogo = attrs.opponent_team_logo || '';

    // Build lineup comparison
    const maxPlayers = Math.max(ourStarters.length, oppStarters.length);
    let lineupRows = '';
    
    for (let i = 0; i < maxPlayers; i++) {
      const ourPlayer = ourStarters[i];
      const oppPlayer = oppStarters[i];
      
      lineupRows += `
        <div class="lineup-row">
          <div class="position-cell">
            ${ourPlayer ? ourPlayer.selected_position || ourPlayer.position : ''}
          </div>
          <div class="player-cell our-side">
            ${ourPlayer ? this.renderPlayer(ourPlayer, true) : '<div class="empty-slot">-</div>'}
          </div>
          <div class="vs-divider">vs</div>
          <div class="player-cell opp-side">
            ${oppPlayer ? this.renderPlayer(oppPlayer, false) : '<div class="empty-slot">-</div>'}
          </div>
          <div class="position-cell">
            ${oppPlayer ? oppPlayer.selected_position || oppPlayer.position : ''}
          </div>
        </div>
      `;
    }

    this.shadowRoot.innerHTML = `
      <style>
        .card {
          background: var(--card-background-color, white);
          border-radius: var(--card-border-radius, 12px);
          box-shadow: var(--card-box-shadow, 0 2px 8px rgba(0,0,0,0.1));
          padding: 16px;
          font-family: var(--primary-font-family, -apple-system, BlinkMacSystemFont, sans-serif);
        }
        .header {
          text-align: center;
          margin-bottom: 16px;
        }
        .week {
          font-size: 14px;
          color: var(--secondary-text-color, #666);
          font-weight: 500;
        }
        .status {
          font-size: 12px;
          color: var(--secondary-text-color, #666);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .matchup-summary {
          display: grid;
          grid-template-columns: 1fr 40px 1fr;
          align-items: center;
          gap: 16px;
          margin: 20px 0;
          padding: 16px;
          border-radius: 8px;
          background: var(--secondary-background-color, #f8f9fa);
        }
        .team-summary {
          text-align: center;
          padding: 12px;
          border-radius: 6px;
          transition: all 0.3s ease;
          width: 100%;
          background: transparent;
          border: none;
        }
        .team-winner {
          background: transparent;
          border: none;
        }
        .team-loser {
          background: transparent;
          border: none;
        }
        .team-tie {
          background: transparent;
          border: none;
        }
        .team-neutral {
          background: transparent;
          border: none;
        }
        .team-logo {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          margin: 0 auto 8px;
          background: var(--divider-color, #e0e0e0);
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
        }
        .team-logo img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
        .team-logo-placeholder {
          font-size: 16px;
          font-weight: bold;
          color: var(--secondary-text-color, #666);
        }
        .team-name {
          font-size: 12px;
          font-weight: 600;
          color: var(--primary-text-color, #333);
          margin-bottom: 4px;
        }
        .manager-name {
          font-size: 10px;
          color: var(--secondary-text-color, #666);
          margin-bottom: 6px;
        }
        .score {
          font-size: 20px;
          font-weight: bold;
          color: var(--primary-text-color, #333);
          margin: 4px 0;
        }
        .projected {
          font-size: 10px;
          color: var(--secondary-text-color, #666);
        }
        .vs {
          font-size: 16px;
          font-weight: bold;
          color: var(--secondary-text-color, #666);
          text-align: center;
          width: 100%;
        }
        .lineup-section {
          margin-top: 20px;
        }
        .lineup-title {
          text-align: center;
          font-size: 16px;
          font-weight: 600;
          margin-bottom: 12px;
          color: var(--primary-text-color, #333);
        }
        .lineup-row {
          display: grid;
          grid-template-columns: 50px 1fr 40px 1fr 50px;
          align-items: center;
          gap: 8px;
          margin-bottom: 8px;
          padding: 8px 4px;
          border-radius: 6px;
        }
        .position-cell {
          font-size: 10px;
          font-weight: 600;
          text-align: center;
          color: var(--secondary-text-color, #666);
          padding: 4px 2px;
          border-radius: 4px;
          width: 100%;
        }
        .player-cell {
          min-height: 50px;
          display: flex;
          align-items: center;
          width: 100%;
          padding: 0 4px;
        }
        .our-side {
          justify-content: flex-end;
        }
        .opp-side {
          justify-content: flex-start;
        }
        .vs-divider {
          font-size: 10px;
          font-weight: 600;
          text-align: center;
          color: var(--secondary-text-color, #666);
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 50px;
        }
        .player {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 0;
          border-radius: 0;
          background: transparent;
          border: none;
          max-width: 200px;
          width: 100%;
          overflow: hidden;
        }
        .our-player {
          flex-direction: row;
          justify-content: flex-end;
        }
        .opp-player {
          flex-direction: row-reverse;
          justify-content: flex-start;
        }
        .player-image {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          overflow: hidden;
          background: var(--divider-color, #e0e0e0);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .player-image img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
        .player-placeholder {
          font-size: 14px;
          color: var(--secondary-text-color, #666);
        }
        .player-info {
          flex: 1;
          min-width: 0;
          overflow: hidden;
          max-width: calc(100% - 40px);
        }
        .our-player .player-info {
          text-align: right;
          padding-right: 4px;
        }
        .opp-player .player-info {
          text-align: left;
          padding-left: 4px;
        }
        .player-name {
          font-size: 11px;
          font-weight: 600;
          color: var(--primary-text-color, #333);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          line-height: 1.2;
          margin-bottom: 2px;
        }
        .player-details {
          font-size: 9px;
          color: var(--secondary-text-color, #666);
        }
        .player-team {
          font-weight: 500;
        }
        .player-number {
          margin-left: 4px;
        }
        .opp-player .player-number {
          margin-left: 0;
          margin-right: 4px;
        }
        .empty-slot {
          font-size: 12px;
          color: var(--secondary-text-color, #666);
          font-style: italic;
          text-align: center;
          width: 100%;
        }
        .winner-badge {
          position: absolute;
          top: -6px;
          right: -6px;
          background: #4CAF50;
          color: white;
          border-radius: 50%;
          width: 16px;
          height: 16px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 10px;
          font-weight: bold;
        }
        .team-container {
          position: relative;
        }
        .score-diff {
          text-align: center;
          margin: 12px 0;
          padding: 6px;
          border-radius: 4px;
          font-size: 12px;
          font-weight: 500;
        }
        .score-diff.positive {
          background: rgba(76, 175, 80, 0.1);
          color: #4CAF50;
        }
        .score-diff.negative {
          background: rgba(244, 67, 54, 0.1);
          color: #f44336;
        }
        .score-diff.zero {
          background: rgba(158, 158, 158, 0.1);
          color: #9e9e9e;
        }
        @media (max-width: 600px) {
          .matchup-summary {
            grid-template-columns: 1fr auto 1fr;
            gap: 8px;
            padding: 12px;
          }
          .team-summary {
            max-width: 140px;
            min-width: 0;
            padding: 8px;
          }
          .team-name {
            font-size: 11px;
            line-height: 1.2;
          }
          .vs {
            padding: 0 8px;
            font-size: 12px;
          }
          .lineup-row {
            grid-template-columns: 35px minmax(0, 1fr) auto minmax(0, 1fr) 35px;
            gap: 4px;
            padding: 6px 2px;
          }
          .player {
            max-width: 120px;
          }
          .player-name {
            font-size: 10px;
          }
          .player-details {
            font-size: 8px;
          }
          .position-cell {
            font-size: 9px;
            padding: 2px 1px;
          }
          .vs-divider {
            font-size: 9px;
          }
          .player-cell {
            padding: 0 2px;
          }
        }
      </style>
      
      <div class="card">
        <div class="header">
          <div class="week">Week ${week}</div>
          <div class="status">${status}</div>
        </div>
        
        <div class="matchup-summary">
          <div class="team-container">
            <div class="team-summary ${ourTeamClass}">
              <div class="team-logo">
                ${ourLogo ? `<img src="${ourLogo}" alt="Team Logo">` : '<div class="team-logo-placeholder">🏈</div>'}
              </div>
              <div class="team-name">${attrs.our_team_name || 'My Team'}</div>
              <div class="manager-name">${attrs.our_manager || 'Me'}</div>
              <div class="score">${ourScore.toFixed(2)}</div>
              <div class="projected">Proj: ${ourProjected.toFixed(2)}</div>
            </div>
            ${winner === 'us' ? '<div class="winner-badge">👑</div>' : ''}
          </div>
          
          <div class="vs">VS</div>
          
          <div class="team-container">
            <div class="team-summary ${oppTeamClass}">
              <div class="team-logo">
                ${oppLogo ? `<img src="${oppLogo}" alt="Team Logo">` : '<div class="team-logo-placeholder">🏈</div>'}
              </div>
              <div class="team-name">${attrs.opponent_team_name || 'Opponent'}</div>
              <div class="manager-name">${attrs.opponent_manager || 'Unknown'}</div>
              <div class="score">${oppScore.toFixed(2)}</div>
              <div class="projected">Proj: ${oppProjected.toFixed(2)}</div>
            </div>
            ${winner === 'opponent' ? '<div class="winner-badge">👑</div>' : ''}
          </div>
        </div>
        
        ${attrs.score_differential !== undefined ? `
          <div class="score-diff ${attrs.score_differential > 0 ? 'positive' : attrs.score_differential < 0 ? 'negative' : 'zero'}">
            ${attrs.score_differential > 0 ? '+' : ''}${attrs.score_differential.toFixed(2)} points
          </div>
        ` : ''}
        
        ${ourStarters.length > 0 || oppStarters.length > 0 ? `
          <div class="lineup-section">
            <div class="lineup-title">Starting Lineups</div>
            ${lineupRows}
          </div>
        ` : ''}
      </div>
    `;
  }

  getCardSize() {
    return 5;
  }
}

customElements.define('yahoo-fantasy-matchup-card', YahooFantasyMatchupCard);

// Add card to custom card registry
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'yahoo-fantasy-matchup-card',
  name: 'Yahoo Fantasy Matchup Card',
  description: 'A card to display Yahoo Fantasy Football matchup information with starting lineups',
});

console.info(
  '%c  YAHOO-FANTASY-MATCHUP-CARD  \n%c  Version 2.1.1                ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);