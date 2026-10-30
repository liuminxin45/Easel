import type {Page} from '../../components/Sidebar';

/** The single mapping from native Easel pages to host URLs. */
export const nativePageRoutes:Record<Page,string>={
 dashboard:'/toolbox',chat:'/chat?fresh=1',trends:'/news',ideas:'/toolbox?section=research&pane=topics',
 calendar:'/toolbox?section=calendar',publish:'/toolbox?section=publications',breakdown:'/toolbox?section=research&pane=breakdown',
 outputs:'/works',accounts:'/toolbox?section=distribution&pane=connections',skills:'/toolbox?section=skills',profile:'/toolbox?section=profiles',
};
