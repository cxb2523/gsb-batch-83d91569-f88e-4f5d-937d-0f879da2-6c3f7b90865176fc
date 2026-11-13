// Main entry point for the Solar Panel Grid Card
export { SolarPanelGridCard } from './solar-panel-grid-card';
export { SolarPanelGridCardEditor } from './solar-panel-grid-card-editor';

// Register with Home Assistant's card picker
(window as any).customCards = (window as any).customCards || [];
(window as any).customCards.push({
  type: 'solar-panel-grid-card',
  name: 'Solar Panel Grid',
  description: 'Visualize individual solar panel production on a draggable grid layout.',
  preview: true,
  documentationURL: 'https://github.com/mutilator/homeassistant-solar-panel-preview',
});
