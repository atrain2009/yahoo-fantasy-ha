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

  formatPlayerName(fullName) {
    if (!fullName) return 'Unknown';
    
    const parts = fullName.trim().split(' ');
    if (parts.length < 2) return fullName;
    
    const firstName = parts[0];
    const suffixes = ['Jr.', 'Jr', 'Sr.', 'Sr', 'II', 'III', 'IV', 'V'];
    
    const lastPart = parts[parts.length - 1];
    if (suffixes.includes(lastPart) && parts.length >= 3) {
      const lastName = parts[parts.length - 2];
      return `${firstName.charAt(0)}. ${lastName} ${lastPart}`;
    } else {
      const lastName = parts[parts.length - 1];
      return `${firstName.charAt(0)}. ${lastName}`;
    }
  }

  showPlayerPopup(playerId, playerName, position, team, uniformNumber, points, imageUrl, stats) {
    this.closePlayerPopup();
    
    const popup = document.createElement('div');
    popup.className = 'player-popup-overlay';
    popup.innerHTML = `
      <div class="player-popup">
        <div class="player-popup-header">
          <div class="player-popup-image">
            ${imageUrl && !imageUrl.includes('blank_player') ? 
              `<img src="${imageUrl}" alt="${playerName}" loading="lazy">` : 
              '<div class="player-placeholder">👤</div>'
            }
          </div>
          <div class="player-popup-info">
            <h3 class="player-popup-name">${playerName}</h3>
            <div class="player-popup-details">
              <span class="player-popup-position">${position}</span>
              <span class="player-popup-team">${team}</span>
              ${uniformNumber ? `<span class="player-popup-number">#${uniformNumber}</span>` : ''}
            </div>
            <div class="player-popup-points">
              <strong>${points} points</strong>
            </div>
          </div>
          <button class="player-popup-close">×</button>
        </div>
        <div class="player-popup-stats">
          <h4>Player Stats</h4>
          <div class="stats-grid">
            ${this.renderPlayerStats(stats)}
          </div>
        </div>
      </div>
    `;
    
    const popupStyles = document.createElement('style');
    popupStyles.textContent = `
      .player-popup-overlay {
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background: rgba(0, 0, 0, 0.5);
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 20px;
        box-sizing: border-box;
      }
      .player-popup {
        background: var(--card-background-color, white);
        color: var(--primary-text-color, #333);
        border-radius: var(--card-border-radius, 12px);
        box-shadow: var(--card-box-shadow, 0 8px 32px rgba(0,0,0,0.3));
        max-width: 500px;
        width: 100%;
        max-height: 80vh;
        overflow-y: auto;
        animation: popupSlideIn 0.3s ease-out;
      }
      @keyframes popupSlideIn {
        from {
          opacity: 0;
          transform: scale(0.8) translateY(20px);
        }
        to {
          opacity: 1;
          transform: scale(1) translateY(0);
        }
      }
      .player-popup-header {
        display: flex;
        align-items: flex-start;
        gap: 16px;
        padding: 20px 20px 16px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        position: relative;
      }
      .player-popup-image {
        width: 80px;
        height: 80px;
        border-radius: 50%;
        overflow: hidden;
        background: var(--divider-color, #e0e0e0);
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      .player-popup-image img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .player-popup-image .player-placeholder {
        font-size: 32px;
        color: var(--secondary-text-color, #666);
      }
      .player-popup-info {
        flex: 1;
        min-width: 0;
      }
      .player-popup-name {
        font-size: 24px;
        font-weight: bold;
        color: var(--primary-text-color, #333);
        margin: 0 0 8px 0;
        line-height: 1.2;
      }
      .player-popup-details {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 12px;
        flex-wrap: wrap;
      }
      .player-popup-position {
        background: var(--accent-color, #2196F3);
        color: var(--text-accent-color, white);
        padding: 4px 8px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: bold;
      }
      .player-popup-team {
        font-size: 14px;
        font-weight: 600;
        color: var(--primary-text-color, #333);
      }
      .player-popup-number {
        font-size: 12px;
        color: var(--secondary-text-color, #666);
        background: var(--secondary-background-color, #f0f0f0);
        padding: 2px 6px;
        border-radius: 8px;
      }
      .player-popup-points {
        font-size: 18px;
        color: var(--accent-color, #2196F3);
        font-family: 'Courier New', 'Monaco', 'Menlo', 'Consolas', monospace;
      }
      .player-popup-close {
        position: absolute;
        top: 16px;
        right: 16px;
        background: none;
        border: none;
        font-size: 24px;
        width: 32px;
        height: 32px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        color: var(--secondary-text-color, #666);
        transition: all 0.2s ease;
      }
      .player-popup-close:hover {
        background: var(--secondary-background-color, #f0f0f0);
        color: var(--primary-text-color, #333);
      }
      .player-popup-stats {
        padding: 20px;
      }
      .player-popup-stats h4 {
        font-size: 18px;
        font-weight: 600;
        color: var(--primary-text-color, #333);
        margin: 0 0 16px 0;
      }
      .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 12px;
      }
      .stat-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 12px;
        background: var(--secondary-background-color, #f8f9fa);
        border-radius: 6px;
      }
      .stat-label {
        font-size: 12px;
        color: var(--secondary-text-color, #666);
        font-weight: 500;
      }
      .stat-value {
        font-size: 14px;
        font-weight: bold;
        color: var(--primary-text-color, #333);
        font-family: 'Courier New', 'Monaco', 'Menlo', 'Consolas', monospace;
      }
      .no-stats {
        text-align: center;
        color: var(--secondary-text-color, #666);
        font-style: italic;
        grid-column: 1 / -1;
        padding: 20px;
      }
      @media (max-width: 600px) {
        .player-popup {
          max-width: 95vw;
          margin: 10px;
        }
        .player-popup-header {
          padding: 16px;
          flex-direction: column;
          text-align: center;
          gap: 12px;
        }
        .player-popup-image {
          width: 60px;
          height: 60px;
          align-self: center;
        }
        .player-popup-name {
          font-size: 20px;
        }
        .player-popup-details {
          justify-content: center;
        }
        .player-popup-stats {
          padding: 16px;
        }
        .stats-grid {
          grid-template-columns: 1fr;
          gap: 8px;
        }
      }
    `;
    
    this._currentPopup = popup;
    this._currentPopupStyles = popupStyles;
    
    document.head.appendChild(popupStyles);
    document.body.appendChild(popup);
    
    const closeButton = popup.querySelector('.player-popup-close');
    closeButton.addEventListener('click', () => this.closePlayerPopup());
    
    popup.addEventListener('click', (e) => {
      if (e.target === popup) {
        this.closePlayerPopup();
      }
    });
    
    this._escapeHandler = (e) => {
      if (e.key === 'Escape') {
        this.closePlayerPopup();
      }
    };
    document.addEventListener('keydown', this._escapeHandler);
  }
  
  closePlayerPopup() {
    if (this._currentPopup && this._currentPopup.parentNode) {
      this._currentPopup.parentNode.removeChild(this._currentPopup);
    }
    
    if (this._currentPopupStyles && this._currentPopupStyles.parentNode) {
      this._currentPopupStyles.parentNode.removeChild(this._currentPopupStyles);
    }
    
    this._currentPopup = null;
    this._currentPopupStyles = null;
    
    if (this._escapeHandler) {
      document.removeEventListener('keydown', this._escapeHandler);
      this._escapeHandler = null;
    }
  }
  
  disconnectedCallback() {
    this.closePlayerPopup();
  }
  
  renderPlayerStats(stats) {
    if (!stats || typeof stats !== 'object' || Object.keys(stats).length === 0) {
      return '<div class="no-stats">No stats available</div>';
    }
    
    let statsHtml = '';
    for (const [key, value] of Object.entries(stats)) {
      const formattedKey = key.replace(/([A-Z])/g, ' $1').replace(/^./, str => str.toUpperCase());
      
      let displayValue;
      if (typeof value === 'object' && value !== null) {
        displayValue = value.display || value.value || 'N/A';
      } else {
        displayValue = value;
      }
      
      statsHtml += `
        <div class="stat-item">
          <span class="stat-label">${formattedKey}:</span>
          <span class="stat-value">${displayValue}</span>
        </div>
      `;
    }
    
    return statsHtml;
  }

  renderPlayer(player, isOur = true, isBench = false) {
    const playerImg = player.image_url && !player.image_url.includes('blank_player') 
      ? `<img src="${player.image_url}" alt="${player.name}" loading="lazy">` 
      : '<div class="player-placeholder">👤</div>';
    
    const points = player.points_total || 0;
    const pointsDisplay = typeof points === 'number' ? points.toFixed(2) : '0.0';
    const formattedName = this.formatPlayerName(player.name);
    
    const benchClass = isBench ? ' bench-player' : '';
    
    return {
      image: `
        <div class="player-image" onclick="this.getRootNode().host.showPlayerPopup('${player.player_id || ''}', '${player.name?.replace(/'/g, "\\'")}', '${player.position}', '${player.team}', '${player.uniform_number || ''}', '${pointsDisplay}', '${player.image_url || ''}', ${JSON.stringify(player.stats || {}).replace(/"/g, '&quot;')})">
          ${playerImg}
        </div>
      `,
      info: `
        <div class="player-info ${isOur ? 'our-side' : 'opp-side'}${benchClass}" onclick="this.getRootNode().host.showPlayerPopup('${player.player_id || ''}', '${player.name?.replace(/'/g, "\\'")}', '${player.position}', '${player.team}', '${player.uniform_number || ''}', '${pointsDisplay}', '${player.image_url || ''}', ${JSON.stringify(player.stats || {}).replace(/"/g, '&quot;')})">
          <div class="player-name">${formattedName}</div>
          <div class="player-details">
            <span class="player-team">${player.team || ''} — ${player.position}</span>
            ${player.uniform_number ? `<span class="player-number">#${player.uniform_number}</span>` : ''}
          </div>
        </div>
      `,
      points: pointsDisplay
    };
  }

  renderCombinedBenchSection(ourRoster, oppRoster) {
    const ourBench = ourRoster.filter(player => !player.is_starting);
    const oppBench = oppRoster.filter(player => !player.is_starting);
    const maxBench = Math.max(ourBench.length, oppBench.length);
    
    let benchRows = '';
    for (let i = 0; i < maxBench; i++) {
      const ourPlayer = ourBench[i];
      const oppPlayer = oppBench[i];
      
      const ourPlayerData = ourPlayer ? this.renderPlayer(ourPlayer, true, true) : null;
      const oppPlayerData = oppPlayer ? this.renderPlayer(oppPlayer, false, true) : null;
      
      benchRows += `
        <div class="lineup-row">
          <div class="player-image-cell">
            ${ourPlayerData ? ourPlayerData.image : '<div class="empty-slot">-</div>'}
          </div>
          <div class="player-info-cell our-side">
            ${ourPlayerData ? ourPlayerData.info : '<div class="empty-slot">-</div>'}
          </div>
          <div class="player-points-cell">
            ${ourPlayerData ? ourPlayerData.points : '-'}
          </div>
          <div class="position-cell">BN</div>
          <div class="player-points-cell">
            ${oppPlayerData ? oppPlayerData.points : '-'}
          </div>
          <div class="player-info-cell opp-side">
            ${oppPlayerData ? oppPlayerData.info : '<div class="empty-slot">-</div>'}
          </div>
          <div class="player-image-cell">
            ${oppPlayerData ? oppPlayerData.image : '<div class="empty-slot">-</div>'}
          </div>
        </div>
      `;
    }
    
    return benchRows;
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
    const showBench = this.config.show_bench || false;

    const ourRoster = attrs.our_roster || [];
    const oppRoster = attrs.opponent_roster || [];
    
    const ourStarters = ourRoster
      .filter(player => player.is_starting)
      .sort((a, b) => this.getPositionOrder(a.selected_position) - this.getPositionOrder(b.selected_position));
    
    const oppStarters = oppRoster
      .filter(player => player.is_starting)
      .sort((a, b) => this.getPositionOrder(a.selected_position) - this.getPositionOrder(b.selected_position));

    const ourLogo = attrs.our_team_logo || '';
    const oppLogo = attrs.opponent_team_logo || '';

    const maxPlayers = Math.max(ourStarters.length, oppStarters.length);
    let lineupRows = '';
    
    for (let i = 0; i < maxPlayers; i++) {
      const ourPlayer = ourStarters[i];
      const oppPlayer = oppStarters[i];
      
      const position = (ourPlayer && (ourPlayer.selected_position || ourPlayer.position)) || 
                      (oppPlayer && (oppPlayer.selected_position || oppPlayer.position)) || '';
      
      const ourPlayerData = ourPlayer ? this.renderPlayer(ourPlayer, true) : null;
      const oppPlayerData = oppPlayer ? this.renderPlayer(oppPlayer, false) : null;
      
      lineupRows += `
        <div class="lineup-row">
          <div class="player-image-cell">
            ${ourPlayerData ? ourPlayerData.image : '<div class="empty-slot">-</div>'}
          </div>
          <div class="player-info-cell our-side">
            ${ourPlayerData ? ourPlayerData.info : '<div class="empty-slot">-</div>'}
          </div>
          <div class="player-points-cell">
            ${ourPlayerData ? ourPlayerData.points : '-'}
          </div>
          <div class="position-cell">
            ${position}
          </div>
          <div class="player-points-cell">
            ${oppPlayerData ? oppPlayerData.points : '-'}
          </div>
          <div class="player-info-cell opp-side">
            ${oppPlayerData ? oppPlayerData.info : '<div class="empty-slot">-</div>'}
          </div>
          <div class="player-image-cell">
            ${oppPlayerData ? oppPlayerData.image : '<div class="empty-slot">-</div>'}
          </div>
        </div>
      `;
    }

    const benchSections = showBench ? `
      <div class="bench-container">
        <div class="bench-title-main">Bench Players</div>
        <div class="bench-header">
          <div></div>
          <div>Your Bench</div>
          <div>Pts</div>
          <div>POS</div>
          <div>Pts</div>
          <div>Opponent Bench</div>
          <div></div>
        </div>
        ${this.renderCombinedBenchSection(ourRoster, oppRoster)}
      </div>
    ` : '';

    this.shadowRoot.innerHTML = `
      <style>
        .card {
          background: var(--card-background-color, white);
          border-radius: var(--card-border-radius, 12px);
          box-shadow: var(--card-box-shadow, 0 2px 8px rgba(0,0,0,0.1));
          padding: 12px 0px 0px 0px;
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
          grid-template-columns: 1fr auto 1fr;
          text-align: center;
          gap: 4px 16px;
        }
        .matchup-row {
          display: contents;
        }
        .team-logo {
          width: 40px;
          height: 40px;
          margin: 0 auto;
          border-radius: 50%;
          overflow: hidden;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .team-logo img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
        .team-name {
          font-weight: 600;
          font-size: 12px;
          word-break: break-word;
        }
        .manager-name {
          font-size: 10px;
          color: var(--secondary-text-color, #666);
        }
        .score {
          font-size: 20px;
          font-family: monospace;
          font-weight: bold;
        }
        .projected {
          font-size: 10px;
          font-family: monospace;
          color: var(--secondary-text-color, #666);
        }
        .vs {
          align-self: center;
        }
        .lineup-section {
          margin-top: 20px;
          padding: 0 8px;
        }
        .lineup-title {
          text-align: center;
          font-size: 16px;
          font-weight: 600;
          margin-bottom: 12px;
          color: var(--primary-text-color, #333);
        }
        .lineup-header {
          display: grid;
          grid-template-columns: 32px 1fr 40px 60px 40px 1fr 32px;
          align-items: center;
          gap: 8px;
          margin-bottom: 8px;
          padding: 8px 4px;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          font-size: 11px;
          font-weight: 600;
          color: var(--secondary-text-color, #666);
          text-align: center;
        }
        .lineup-row {
          display: grid;
          grid-template-columns: 32px 1fr 40px 60px 40px 1fr 32px;
          align-items: center;
          gap: 8px;
          margin-bottom: 8px;
          padding: 8px 4px;
          border-radius: 6px;
          transition: background-color 0.2s ease;
        }
        .lineup-row:hover {
          background: var(--secondary-background-color, #f8f9fa);
        }
        .position-cell {
          font-size: 11px;
          font-weight: 700;
          text-align: center;
          color: var(--primary-text-color, #333);
          padding: 6px 4px;
        }
        .player-image-cell {
          display: flex;
          justify-content: center;
          align-items: center;
        }
        .player-info-cell {
          min-height: 50px;
          display: flex;
          align-items: center;
          overflow: hidden;
          padding: 0 4px;
        }
        .player-info-cell.our-side {
          justify-content: flex-start;
        }
        .player-info-cell.opp-side {
          justify-content: flex-end;
        }
        .player-points-cell {
          display: flex;
          justify-content: center;
          align-items: center;
          font-size: 12px;
          font-weight: bold;
          color: var(--primary-text-color, #333);
          font-family: 'Courier New', 'Monaco', 'Menlo', 'Consolas', monospace;
        }
        .player {
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .player:hover, .player-image:hover, .player-info:hover {
          background: var(--secondary-background-color, #f0f0f0);
          transform: scale(1.02);
          border-radius: 4px;
        }
        .bench-player {
          opacity: 0.8;
        }
        .bench-player:hover {
          opacity: 1;
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
          cursor: pointer;
          transition: all 0.2s ease;
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
          min-width: 0;
          overflow: hidden;
          cursor: pointer;
          padding: 4px;
          border-radius: 4px;
          transition: all 0.2s ease;
          max-width: 100%;
        }
        .player-info.our-side {
          text-align: left;
        }
        .player-info.opp-side {
          text-align: right;
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
        .player-info.opp-side .player-number {
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
        .score-diff {
          text-align: center;
          margin: 12px 0;
          padding: 6px;
          border-radius: 4px;
          font-size: 12px;
          font-weight: 500;
          font-family: 'Courier New', 'Monaco', 'Menlo', 'Consolas', monospace;
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
        
        .bench-container {
          margin-top: 24px;
          border-top: 2px solid var(--divider-color, #e0e0e0);
          padding: 16px 8px 0;
        }
        .bench-title-main {
          text-align: center;
          font-size: 16px;
          font-weight: 600;
          margin-bottom: 16px;
          color: var(--primary-text-color, #333);
        }
        .bench-header {
          display: grid;
          grid-template-columns: 32px 1fr 40px 60px 40px 1fr 32px;
          align-items: center;
          gap: 8px;
          margin-bottom: 8px;
          padding: 8px 4px;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          font-size: 11px;
          font-weight: 600;
          color: var(--secondary-text-color, #666);
          text-align: center;
        }
        @media (max-width: 600px) {
          .matchup-summary {
            grid-template-columns: 1fr auto 1fr;
            gap: 8px;
            padding: 12px;
          }
          .team-name {
            font-size: 11px;
            line-height: 1.2;
          }
          .vs {
            padding: 0 8px;
            font-size: 12px;
          }
          .lineup-row, .lineup-header, .bench-header {
            grid-template-columns: 28px 1fr 35px 36px 35px 1fr 28px;
            gap: 4px;
            padding: 6px 2px;
          }
          .position-cell {
            font-size: 8px;
            font-weight: 700;
            padding: 3px 2px;
            line-height: 1.1;
          }
          .player-name {
            font-size: 10px;
          }
          .player-details {
            font-size: 8px;
          }
          .player-points-cell {
            font-size: 10px;
            min-width: 30px;
          }
          .player-image {
            width: 28px;
            height: 28px;
          }
          .player-info {
            padding-left: 2px;
          }
          .bench-title-main {
            font-size: 14px;
          }
        }
      </style>
      
      <div class="card">
        <div class="header">
          <div class="week">Week ${week}</div>
          <div class="status">${status}</div>
        </div>
        
        <div class="matchup-summary">
          <div class="matchup-row">
            <div class="team-logo">${ourLogo ? `<img src="${ourLogo}">` : '🏈'}</div>
            <div></div>
            <div class="team-logo">${oppLogo ? `<img src="${oppLogo}">` : '🏈'}</div>
          </div>

          <div class="matchup-row">
            <div class="team-name">${attrs.our_team_name}</div>
            <div class="vs">VS</div>
            <div class="team-name">${attrs.opponent_team_name}</div>
          </div>

          <div class="matchup-row">
            <div class="manager-name">${attrs.our_manager}</div>
            <div></div>
            <div class="manager-name">${attrs.opponent_manager}</div>
          </div>

          <div class="matchup-row">
            <div class="score">${ourScore.toFixed(2)}</div>
            <div></div>
            <div class="score">${oppScore.toFixed(2)}</div>
          </div>

          <div class="matchup-row">
            <div class="projected">Proj: ${ourProjected.toFixed(2)}</div>
            <div></div>
            <div class="projected">Proj: ${oppProjected.toFixed(2)}</div>
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
            <div class="lineup-header">
              <div></div>
              <div>Your Team</div>
              <div>Pts</div>
              <div>POS</div>
              <div>Pts</div>
              <div>Opponent</div>
              <div></div>
            </div>
            ${lineupRows}
          </div>
        ` : ''}
        
        ${benchSections}
      </div>
    `;
  }

  getCardSize() {
    return this.config.show_bench ? 8 : 6;
  }
}

customElements.define('yahoo-fantasy-matchup-card', YahooFantasyMatchupCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'yahoo-fantasy-matchup-card',
  name: 'Yahoo Fantasy Matchup Card',
  description: 'A card to display Yahoo Fantasy Football matchup information with starting lineups and player points. Configure with show_bench: true to display bench players.',
});

console.info(
  '%c  YAHOO-FANTASY-MATCHUP-CARD  \n%c  Version 2.3.0                ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);