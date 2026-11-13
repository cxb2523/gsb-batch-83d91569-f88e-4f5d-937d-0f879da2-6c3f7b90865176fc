// Preload de las pruebas: apunta la base SQLite a una base temporal para que ningún test
// toque la base real de data/jobfilter.db. Si JOBFILTER_DB ya viene definida (por ejemplo
// para depurar con una ruta específica), se respeta.
import { resolve } from 'node:path';

process.env.JOBFILTER_DB ??= resolve('data/test-jobfilter.db');
