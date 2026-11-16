import { create } from 'zustand';

export type Rol = 'agricultor' | 'extensionista' | 'admin';
export type Pantalla = 'landing' | 'mapa' | 'chat' | 'reportes' | 'experto';

const KEY = 'milpa.sesion';
type Guardado = { login: string; rol: Rol; areas: string[]; parcelaId: string | null } | null;

const leer = (): Guardado => {
  try {
    const s = localStorage.getItem(KEY);
    return s ? (JSON.parse(s) as Guardado) : null;
  } catch {
    return null;
  }
};
const escribir = (g: Guardado) => {
  try {
    if (g) localStorage.setItem(KEY, JSON.stringify(g));
    else localStorage.removeItem(KEY);
  } catch {
    /* sin almacenamiento: la sesión vive en memoria */
  }
};

const g0 = leer();

type Estado = {
  login: string | null;
  rol: Rol | null;
  areas: string[];
  pantalla: Pantalla;
  parcelaId: string | null;
  conversationId: string | null;
  entrar: (login: string, rol: Rol, areas: string[]) => void;
  salir: () => void;
  ir: (p: Pantalla) => void;
  setParcela: (id: string | null) => void;
  setConversacion: (id: string | null) => void;
};

export const useSession = create<Estado>((set, get) => ({
  login: g0?.login ?? null,
  rol: g0?.rol ?? null,
  areas: g0?.areas ?? [],
  pantalla: g0 ? (g0.rol === 'agricultor' ? (g0.parcelaId ? 'chat' : 'mapa') : 'experto') : 'landing',
  parcelaId: g0?.parcelaId ?? null,
  conversationId: null,
  entrar: (login, rol, areas) => {
    escribir({ login, rol, areas, parcelaId: null });
    set({ login, rol, areas, parcelaId: null, conversationId: null, pantalla: rol === 'agricultor' ? 'mapa' : 'experto' });
  },
  salir: () => {
    escribir(null);
    set({ login: null, rol: null, areas: [], parcelaId: null, conversationId: null, pantalla: 'landing' });
  },
  ir: (pantalla) => set({ pantalla }),
  setParcela: (parcelaId) => {
    const { login, rol, areas } = get();
    if (login && rol) escribir({ login, rol, areas, parcelaId });
    set({ parcelaId });
  },
  setConversacion: (conversationId) => set({ conversationId }),
}));
