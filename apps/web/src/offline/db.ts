import Dexie, { type Table } from 'dexie';

/** Mensajes escritos sin señal: se guardan en el navegador y se envían al volver la red. */
export type Pendiente = {
  id?: number;
  creadoAt: string;
  texto: string;
  idioma: 'es' | 'en';
  parcelId: string | null;
  conversationId: string | null;
  viaVoz: boolean;
  consentimientoUso: boolean;
};

class MilpaDB extends Dexie {
  outbox!: Table<Pendiente, number>;
  constructor() {
    super('milpa-v2');
    this.version(1).stores({ outbox: '++id, creadoAt' });
  }
}

export const db = new MilpaDB();
