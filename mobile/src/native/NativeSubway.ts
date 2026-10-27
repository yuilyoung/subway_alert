import type {TurboModule} from 'react-native';
import {TurboModuleRegistry} from 'react-native';

export interface Spec extends TurboModule {
  getState(): Promise<string>;
  saveFavorites(json: string): Promise<boolean>;
  configure(baseUrl: string, demo: boolean): Promise<boolean>;
  identity(): Promise<string>;
  setActiveSession(id: string): Promise<boolean>;
  clearActiveSession(id: string): Promise<boolean>;
  syncGeofences(): Promise<boolean>;
  capabilities(): Promise<string>;
  location(): Promise<string>;
  demoNotification(): Promise<boolean>;
  openSettings(): void;
}
export default TurboModuleRegistry.getEnforcing<Spec>('Subway');
