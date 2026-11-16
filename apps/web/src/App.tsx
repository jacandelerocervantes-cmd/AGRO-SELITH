import Chat from './Chat';
import ExpertoCola from './ExpertoCola';
import Landing from './Landing';
import MapaParcela from './MapaParcela';
import Reportes from './Reportes';
import { useSession } from './store';

export default function App() {
  const { pantalla, rol } = useSession();
  if (pantalla === 'landing' || !rol) return <Landing />;
  if (rol !== 'agricultor') return <ExpertoCola />;
  if (pantalla === 'mapa') return <MapaParcela />;
  if (pantalla === 'reportes') return <Reportes />;
  return <Chat />;
}
