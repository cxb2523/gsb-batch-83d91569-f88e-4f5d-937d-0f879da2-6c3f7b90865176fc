// Nombre y color (tono HSL) de cada plataforma. El badge arma el fondo y el texto a partir
// del tono, así cada plataforma se distingue en claro y oscuro con el mismo contraste.
export const PLATFORMS: Record<string, { name: string; hue: number }> = {
	getonbrd: { name: 'GetOnBoard', hue: 262 },
	linkedin: { name: 'LinkedIn', hue: 212 },
	computrabajo: { name: 'Computrabajo', hue: 25 },
	elempleo: { name: 'elempleo', hue: 145 },
	peaku: { name: 'PeakU', hue: 185 },
	hireline: { name: 'Hireline', hue: 48 },
	magneto: { name: 'Magneto365', hue: 305 },
	talently: { name: 'Talently', hue: 350 }
};

export function platform(id: string) {
	return PLATFORMS[id] ?? { name: id, hue: 0 };
}
