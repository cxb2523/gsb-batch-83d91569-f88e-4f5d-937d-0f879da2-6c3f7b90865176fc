<div class="panel-content">
  <div class="config-row">
    <label>Name:</label>
    <ha-textfield
      .value={{0}}
      data-config-value="name"
      data-index={{1}}
      @input={{2}}
    ></ha-textfield>
  </div>
  <div class="config-row">
    <label for={{3}}>Power Entity:</label>
    <select
      id={{3}}
      .value={{4}}
      data-config-value="entity"
      data-index={{1}}
      @change={{5}}
      class="entity-select"
    >
      <option value="">Select a power sensor...</option>
      {{6}}
    </select>
  </div>
  <div class="config-row">
    <label for={{7}}>Energy Entity:</label>
    <select
      id={{7}}
      .value={{8}}
      data-config-value="entity_energy"
      data-index={{1}}
      @change={{5}}
      class="entity-select"
    >
      <option value="">Select an energy sensor...</option>
      {{9}}
    </select>
  </div>
  <div class="config-row">
    <label>Rotation (°):</label>
    <div class="slider-row">
      <input
        type="range"
        min="-180"
        max="180"
        step="5"
        .value={{10}}
        data-config-value="rotation"
        data-index={{1}}
        @input={{2}}
        class="rotation-slider"
      />
      <span class="slider-value">{{11}}°</span>
    </div>
  </div>
  <div class="config-row">
    <label>Max Production (W):</label>
    <ha-textfield
      type="number"
      .value={{12}}
      data-config-value="max_production"
      data-index={{1}}
      @input={{2}}
    ></ha-textfield>
  </div>
  <div class="config-row">
    <label>Max Daily Production (kWh):</label>
    <ha-textfield
      type="number"
      .value={{13}}
      data-config-value="max_daily_production"
      data-index={{1}}
      @input={{2}}
    ></ha-textfield>
  </div>
  <div class="config-row">
    <ha-button @click={{14}} class="delete-btn">
      Delete Panel
    </ha-button>
  </div>
</div>
