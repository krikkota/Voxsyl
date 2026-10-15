import React from 'react';
import { createRoot } from 'react-dom/client';
import './i18n';
import App from './App';
import Overlay from './Overlay';
import './styles.css';
const overlay = location.pathname.endsWith('/overlay.html');
document.body.dataset.surface = overlay ? 'overlay' : 'main';
createRoot(document.getElementById('root')!).render(<React.StrictMode>{overlay ? <Overlay /> : <App />}</React.StrictMode>);
