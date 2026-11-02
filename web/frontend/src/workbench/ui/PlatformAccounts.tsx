import AccountsPage from '../../components/AccountsPage';
import {useWorkbench} from './hooks';
import {useCallback} from 'react';

/** Native account UI and login lifecycle have one implementation. */
export function Accounts(){const vm=useWorkbench(),entry=vm.navigation.entryKey,ready=useCallback(()=>vm.navigation.contentReady?.({entryId:entry}),[vm.navigation.contentReady,entry]);return <AccountsPage registerLayer={vm.navigation.registerLayer} onContentReady={ready}/>}
