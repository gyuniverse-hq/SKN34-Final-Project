import { useRecentSearchStore } from '@/store/recentSearchStore';

beforeEach(() => useRecentSearchStore.getState().clear());

it('keeps recent nonempty searches unique and allows removing them', () => {
  const { add, remove } = useRecentSearchStore.getState();
  add('  Lip  ');
  add('cream');
  add('lip');
  add('  ');
  expect(useRecentSearchStore.getState().searches).toEqual(['lip', 'cream']);
  remove('lip');
  expect(useRecentSearchStore.getState().searches).toEqual(['cream']);
});
