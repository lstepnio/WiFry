import { describe, expect, it } from 'vitest';
import {
  DEFAULT_NAV_STATE,
  getVisibleSelection,
  getVisibleSystemSubTabs,
  getVisibleTabs,
  normalizeNavState,
} from './config';

describe('dashboard config', () => {
  it('maps the legacy sharing tab to system remote access', () => {
    expect(normalizeNavState({ tab: 'sharing' })).toEqual({
      ...DEFAULT_NAV_STATE,
      tab: 'system',
      sysSubTab: 'remote',
    });
  });

  it('falls back invalid selections to defaults', () => {
    expect(
      normalizeNavState({
        tab: 'system',
        impSubTab: 'invalid' as never,
        sysSubTab: 'invalid' as never,
        analyzingCaptureId: 42 as never,
      }),
    ).toEqual({
      ...DEFAULT_NAV_STATE,
      tab: 'system',
      analyzingCaptureId: null,
      selectedStreamId: null,
    });
  });

  it('hides feature-gated tabs from the visible list', () => {
    const visibleTabs = getVisibleTabs((flagName) => !['sessions', 'captures'].includes(flagName));

    expect(visibleTabs.map((tab) => tab.id)).not.toContain('sessions');
    expect(visibleTabs.map((tab) => tab.id)).not.toContain('captures');
    expect(visibleTabs.map((tab) => tab.id)).toContain('system');
  });

  it('falls back to the first visible system tab when remote access is hidden', () => {
    const visibleTabs = getVisibleSystemSubTabs(false);

    expect(getVisibleSelection('remote', visibleTabs, DEFAULT_NAV_STATE.sysSubTab)).toBe('overview');
  });
});
