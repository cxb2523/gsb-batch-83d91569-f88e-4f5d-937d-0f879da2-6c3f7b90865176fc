import type { PlatformAdapter } from './types';
import { computrabajo } from './computrabajo';
import { elempleo } from './elempleo';
import { getonbrd } from './getonbrd';
import { hireline } from './hireline';
import { linkedin } from './linkedin';
import { magneto } from './magneto';
import { peaku } from './peaku';
import { talently } from './talently';

// Una entrada por plataforma integrada. Cómo agregar una: docs/plataformas.md
export const adapters: PlatformAdapter[] = [getonbrd, computrabajo, linkedin, elempleo, peaku, hireline, magneto, talently];
