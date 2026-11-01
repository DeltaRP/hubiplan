// Einstieg: erst den Sprachkatalog laden (nur bei Englisch), dann den Rest der Oberfläche.
// So stimmen auch Texte, die Module schon beim Laden erzeugen (z. B. Listen von Beschriftungen).
import { loadCatalog } from './i18n/index.ts'

void loadCatalog().then(() => import('./boot.tsx'))
