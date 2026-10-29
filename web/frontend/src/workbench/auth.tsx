import React from 'react';
import {createRoot} from 'react-dom/client';
import NativeHost from './host';
createRoot(document.getElementById('root')!).render(<NativeHost auth/>);
