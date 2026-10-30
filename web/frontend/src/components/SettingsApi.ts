import {
  fetchEnvTools, startEnvInstall, fetchEnvJob, fetchModelChannels, runChannelSelftest,
  saveModelConfig, fetchLocalAgents, enableLocalAgent, fetchAvailableModels,
  fetchHarnessSettings, fetchHarnessModels, saveHarnessSettings,
} from '../lib/api';

/** Optional host port. The upstream application keeps its original defaults. */
export const defaultSettingsApi = {
  fetchEnvTools, startEnvInstall, fetchEnvJob, fetchModelChannels, runChannelSelftest,
  saveModelConfig, fetchLocalAgents, enableLocalAgent, fetchAvailableModels,
  fetchHarnessSettings, fetchHarnessModels, saveHarnessSettings,
};
export type SettingsApi = typeof defaultSettingsApi;
