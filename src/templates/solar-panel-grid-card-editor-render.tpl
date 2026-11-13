<div class="card-config">
  <h2>Grid Settings</h2>
  <ha-form
    .hass={{0}}
    .data={{1}}
    .schema={{2}}
    .computeLabel={{3}}
    @value-changed={{4}}
  ></ha-form>

  <h2>Panel Entities</h2>
  <div class="panels-config">
    <p>Configure sensor entities for each panel:</p>
    {{5}}
  </div>

  <h2>Add Panel</h2>
  <div class="panels-config">
    <ha-button @click={{6}}>Add Panel</ha-button>
  </div>

  <h2>Panel Positions</h2>
  <div class="panels-info">
    <p>Drag panels in the card preview - positions update automatically!</p>
    <div class="panels-list">
      {{7}}
    </div>
    <p class="yaml-note">Positions sync automatically as you drag in the preview!</p>
  </div>
</div>
