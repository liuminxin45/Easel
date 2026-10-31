import React from 'react';
import {createRoot} from 'react-dom/client';
import NativeHost from './host';
import {retireLegacyWorker} from './retireLegacyWorker';
void retireLegacyWorker();
createRoot(document.getElementById('root')!).render(<NativeHost auth/>);
