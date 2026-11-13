<div class="top-controls">
  <div class="history-controls">
    <button type="button" class="history-day-btn" @click={{0}} aria-label="Previous day" title="Previous day">&#8249;</button>
    <button type="button" class="history-day-btn" @click={{1}} aria-label="Next day" title="Next day">&#8250;</button>
    <label for="history-date" class="history-label">Date</label>
    <input id="history-date" class="history-date-input" type="date" .value={{2}} @change={{3}} />
    <label for="history-time" class="history-label">Time</label>
    <input id="history-time" class="history-time-slider" type="range" min="0" max="1439" step="1" .value={{4}} @input={{5}} />
    <span class="history-time-value">{{6}}</span>
    <button type="button" class="history-now-btn" @click={{7}}>Now</button>
  </div>
  {{8}}
</div>
