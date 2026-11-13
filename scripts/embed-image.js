import { readFileSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const imagePath = resolve(__dirname, '..', 'dist', 'solar-panel-frame.png');
const outputPath = resolve(__dirname, '..', 'src', 'panel-image.ts');

const imageBuffer = readFileSync(imagePath);
const base64 = imageBuffer.toString('base64');
const dataUri = `data:image/png;base64,${base64}`;

writeFileSync(outputPath, `export const PANEL_IMAGE_DATA_URI = '${dataUri}';\n`);

console.log(`Embedded ${imagePath} (${imageBuffer.length} bytes) into ${outputPath}`);
