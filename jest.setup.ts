jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock')
);
jest.mock('@expo/ui/community/masked-view', () => ({ MaskedView: 'MaskedView' }));
